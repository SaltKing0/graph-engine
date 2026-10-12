"""Hybrid retrieval: dense (cosine) + BM25, fused via Reciprocal Rank Fusion.

Roadmap V2#1: "first hybrid dense+BM25 with tuned fusion (highest ROI)".
BM25 is pure text statistics — no dependency, no model. The RRF fusion
combines both rankings robustly (independent of their scale) before a
cross-encoder reranking of the top-K is added later.
"""

from __future__ import annotations

import math
import time
from contextlib import contextmanager
from typing import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from .brain_engine import BrainEngine
from .brain import Brain
from .search_index import SearchIndex, corpus_stamp, embedder_stamp
from .feedback import LearningProfile, learning_profile
from .tiers import order_by_tier
from .graph_retrieval import GraphOptions, GraphTrace, eligible_edges, expand


@contextmanager
def _stage(engine: BrainEngine, name: str) -> Iterator[None]:
    """Optional caller-owned timings in milliseconds, never persisted."""
    timings = getattr(engine, "retrieval_timings", None)
    start = time.perf_counter() if timings is not None else 0.0
    try:
        yield
    finally:
        if timings is not None:
            timings[name] = timings.get(name, 0.0) + (time.perf_counter() - start) * 1000


def tokenize(text: str) -> list[str]:
    return text.lower().split()


class BM25:
    """BM25 scorer. The index (df, doc_len, per-doc tf) is built ONCE in the
    constructor — `scores()` only looks it up (Audit #10: the old version
    re-tokenized the entire corpus twice per query, 0.225 s/query @2k docs)."""

    def __init__(self, corpus: list[str], k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.N = len(corpus)
        self.doc_len: list[int] = []
        self.avgdl = sum(self.doc_len) / self.N if self.N else 0.0
        self.df: dict[str, int] = {}
        self._tf: list[dict[str, int]] = []
        for doc in corpus:
            tf: dict[str, int] = {}
            for t in tokenize(doc):
                tf[t] = tf.get(t, 0) + 1
            self._tf.append(tf)
            self.doc_len.append(sum(tf.values()))
            for term in tf:
                self.df[term] = self.df.get(term, 0) + 1
        self.avgdl = sum(self.doc_len) / self.N if self.N else 0.0

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))

    def scores(self, query_tokens: list[str]) -> list[float]:
        """BM25 score per document (same order as corpus)."""
        if self.N == 0:
            return []
        out: list[float] = []
        for tf, dl in zip(self._tf, self.doc_len):
            s = 0.0
            for t in query_tokens:
                f = tf.get(t, 0)
                if f == 0:
                    continue
                denom = f + self.k1 * (1.0 - self.b + self.b * dl / self.avgdl)
                s += self.idf(t) * (f * (self.k1 + 1.0)) / denom
            out.append(s)
        return out


def rrf_fuse(ranked_lists: list[list[tuple[str, float]]], k: int = 60,
             weights: list[float] | None = None) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: merges multiple (id, score) rankings into one.

    Each ranking is sorted by score descending; each rank contributes
    1/(k + rank). k=60 is the usual RRF standard.
    """
    fused: dict[str, float] = {}
    weights = weights if weights is not None else [1.0] * len(ranked_lists)
    if len(weights) != len(ranked_lists) or any(not math.isfinite(w) or w < 0 for w in weights):
        raise ValueError("one finite non-negative weight is required per ranking")
    for rl, weight in zip(ranked_lists, weights):
        ordered = sorted(rl, key=lambda x: x[1], reverse=True)
        for rank, (nid, _) in enumerate(ordered):
            fused[nid] = fused.get(nid, 0.0) + weight / (k + rank + 1)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


@dataclass
class _RetrievalTrace:
    node_ids: list[str]
    text_by_id: dict[str, str]
    candidates: list[tuple[str, float]] = field(default_factory=list)
    dense_scores: dict[str, float] = field(default_factory=dict)
    bm25_scores: dict[str, float] = field(default_factory=dict)
    dense_ranks: dict[str, int] = field(default_factory=dict)
    bm25_ranks: dict[str, int] = field(default_factory=dict)
    fused: list[tuple[str, float]] = field(default_factory=list)
    reranker_scores: dict[str, float] = field(default_factory=dict)
    tiers: dict[str, str] = field(default_factory=dict)
    learning: LearningProfile | None = None
    feedback_adjustments: dict[str, float] = field(default_factory=dict)
    graph: GraphTrace = field(default_factory=GraphTrace)


def _limit_hits(hits: list[tuple[str, float]], k: int,
                tiers: dict[str, str] | None = None) -> list[tuple[str, float]]:
    """Preserve ranking while applying either a global or per-tier quota."""
    if tiers is None:
        return hits[:k]
    counts: dict[str, int] = {}
    result = []
    for hit in hits:
        tier = tiers[hit[0]]
        if counts.get(tier, 0) < k:
            result.append(hit)
            counts[tier] = counts.get(tier, 0) + 1
    return result


def _retrieve_trace(engine: BrainEngine, query: str, rerank_k: int,
                    persist: bool, *, learn: bool = True,
                    per_tier: bool = False, graph: GraphOptions | None = None) -> _RetrievalTrace:
    """One scoring path for normal retrieval and its explanation."""
    # Protected/custom stores always use fresh authorized reads. Never retain
    # a principal's corpus or reuse it after revocation or across graphs.
    cacheable = type(engine.brain) is Brain and getattr(engine, "search_cache_enabled", True)
    if type(engine.brain) is not Brain:
        engine.__dict__.pop("_search_index", None)
    with _stage(engine, "freshness_scan"):
        key = ((corpus_stamp(engine.brain.path), embedder_stamp(engine.embedder), persist, per_tier)
               if cacheable else None)
    index = getattr(engine, "_search_index", None) if cacheable else None
    if not isinstance(index, SearchIndex) or index.key != key or not index.valid():
        index = None
    with _stage(engine, "filesystem_parsing"):
        nodes = index.nodes if index is not None else engine.brain.read_nodes()
    # Audit #7: tombstones are "forgotten" — they must not come back as
    # search answers (consolidate/_find_duplicate already exclude them).
    nodes = [n for n in nodes if n.status != "tombstone"
             and (not per_tier or n.text.strip())]
    trace = _RetrievalTrace([n.id for n in nodes], {n.id: n.text for n in nodes})
    trace.tiers = {n.id: n.storage_tier for n in nodes}
    trace.learning = learning_profile(engine.brain, query, nodes) if learn else LearningProfile(query)
    query = trace.learning.expanded_query
    if not nodes:
        trace.graph = expand(engine.brain, set(), [], graph)
        return trace
    node_ids = [n.id for n in nodes]
    with _stage(engine, "query_embedding"):
        qvec = engine.embedder.embed(query)

    if index is not None and index.dimension != len(qvec):
        index = None
    with _stage(engine, "vector_loading_embedding"):
        vecs = ({} if index is not None else engine.brain.vectors_for(
            set(node_ids), lambda t: engine.embedder.embed(t), persist=persist,
            **({"embedder_key": embedder_stamp(engine.embedder)} if type(engine.brain) is Brain else {})))
    # Audit #8 (follow-up fix): vectors with a foreign dimension are not
    # comparable with the query (different embedder in the same brain, e.g.
    # demo seed with precomputed ST vectors + HashEmbedder engine). Instead of
    # silently truncating (old cosine bug) they are skipped — the dense stage
    # degrades, BM25 stays fully effective.
    # Audit #60: the dense stage runs as a numpy matmul over L2-normalized
    # vectors instead of a pure-Python cosine loop (0.150 s/query @2k×384-dim →
    # sub-2 ms). Foreign-dimension/empty vectors remain excluded.
    with _stage(engine, "dense_index_construction"):
        if index is not None:
            dense_ids, M = index.dense_ids, index.matrix
        else:
            dense_ids = [nid for nid in node_ids
                         if nid in vecs and vecs[nid] and len(vecs[nid]) == len(qvec)]
            M = (np.array([vecs[nid] for nid in dense_ids], dtype=np.float64)
                 .reshape((-1, len(qvec))) if qvec else np.empty((0, 0)))
            if dense_ids:
                M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-12)
    with _stage(engine, "dense_scoring"):
        if dense_ids:
            q = np.asarray(qvec, dtype=np.float64)
            q = q / (np.linalg.norm(q) + 1e-12)
            sims = M @ q
            dense = [(nid, float(s)) for nid, s in zip(dense_ids, sims)]
        else:
            dense = []
    with _stage(engine, "lexical_index_construction"):
        bm = index.bm25 if index is not None else BM25([n.text for n in nodes])
    if cacheable and index is None:
        # Never label an old matrix with a new vector stamp. A writer's first
        # vector fill also skips publication; its next stable query can cache.
        with _stage(engine, "freshness_scan"):
            after = (corpus_stamp(engine.brain.path), embedder_stamp(engine.embedder), persist, per_tier)
        if after == key:
            M.setflags(write=False)
            engine._search_index = SearchIndex(after, nodes, dense_ids, M, bm, len(qvec))
    with _stage(engine, "lexical_scoring"):
        bm_scores = bm.scores(tokenize(query))
    bm_rank = [(nid, s) for nid, s in zip(node_ids, bm_scores) if s > 0.0]
    trace.dense_scores = dict(dense)
    trace.bm25_scores = dict(zip(node_ids, bm_scores))

    # Audit #37: a nonsense query otherwise returned 5 "results" with
    # RRF scores ≈ 0.033 — both ranks meaningless, but presented as a
    # ranking. Nodes without any overlap (dense 0.0 AND BM25 0.0)
    # are dropped before the fusion.
    dense_ids = {nid for nid, s in dense if s > 0.0}
    bm_ids = {nid for nid, s in bm_rank}
    overlap = dense_ids | bm_ids
    dense = [(nid, s) for nid, s in dense if nid in overlap]
    bm_rank = [(nid, s) for nid, s in bm_rank if nid in overlap]

    trace.dense_ranks = {nid: rank for rank, (nid, _) in enumerate(
        sorted(dense, key=lambda hit: hit[1], reverse=True), start=1)}
    trace.bm25_ranks = {nid: rank for rank, (nid, _) in enumerate(
        sorted(bm_rank, key=lambda hit: hit[1], reverse=True), start=1)}
    trace.fused = rrf_fuse([dense, bm_rank], k=60,
                           weights=[trace.learning.dense_weight, trace.learning.bm25_weight])
    # Graph relevance is added to base RRF before feedback and tier ordering.
    # Seed selection honors feedback, before persisted tier priority. Apply
    # feedback to the combined candidate score only once below.
    seeds = sorted([(nid, max(0.0, score + trace.learning.adjustments.get(nid, 0.0)))
                    for nid, score in trace.fused], key=lambda hit: hit[1], reverse=True)
    trace.graph = expand(engine.brain, set(node_ids), seeds, graph)
    combined = dict(trace.fused)
    for nid, contribution in trace.graph.contributions.items():
        combined[nid] = combined.get(nid, 0.0) + contribution
    trace.fused = list(combined.items())
    trace.feedback_adjustments = {
        nid: max(-score, trace.learning.adjustments.get(nid, 0.0))
        for nid, score in trace.fused}
    trace.fused = sorted([(nid, score + trace.feedback_adjustments[nid])
                          for nid, score in trace.fused], key=lambda hit: hit[1], reverse=True)
    trace.fused = order_by_tier(trace.fused, trace.tiers)
    trace.candidates = _limit_hits(trace.fused, rerank_k,
                                   trace.tiers if per_tier else None)
    return trace


def retrieve_candidates(engine: BrainEngine, query: str, rerank_k: int = 30,
                        persist: bool = True, *, graph: GraphOptions | None = None) -> tuple[list[str], dict[str, str], list[tuple[str, float]]]:
    """Shared candidate retrieval for the retrieve()/rerank path."""
    trace = _retrieve_trace(engine, query, rerank_k, persist, graph=graph)
    return trace.node_ids, trace.text_by_id, trace.candidates


def explain(engine: BrainEngine, node_id: str, query: str, *, k: int = 5,
            rerank_k: int = 30, graph: GraphOptions | None = None) -> dict:
    """Explain a fresh query against the current brain, without writing anything.

    Graph expansion is explicit and bounded; paths never assert entailment.
    This is a recomputation, not a historical search log.
    """
    if not query.strip():
        raise ValueError("query must be non-empty")
    if k < 1 or rerank_k < 1:
        raise ValueError("k and rerank_k must be positive")
    node = engine.brain.read_node(node_id)
    if node is None:
        raise ValueError(f"No node with id {node_id!r}.")
    if node.status == "tombstone":
        raise ValueError(f"Node {node_id!r} is tombstoned and excluded from retrieval.")

    trace = _retrieve_trace(engine, query, rerank_k, persist=False, graph=graph)
    reranked = getattr(engine, "reranker", None) is not None
    hits = (_rerank(engine, query, k, trace.text_by_id, trace.candidates,
                    reranker_scores=trace.reranker_scores, tiers=trace.tiers)
            if reranked and trace.candidates else trace.candidates[:k])
    final_ranks = {nid: rank for rank, (nid, _) in enumerate(hits, start=1)}
    fused_ranks = {nid: rank for rank, (nid, _) in enumerate(trace.fused, start=1)}

    def channel(scores: dict[str, float], ranks: dict[str, int], weight: float) -> dict:
        rank = ranks.get(node_id)
        return {"score": scores.get(node_id), "rank": rank,
                "rrf_contribution": weight / (60 + rank) if rank is not None else 0.0}

    dense = channel(trace.dense_scores, trace.dense_ranks, trace.learning.dense_weight)
    bm25 = channel(trace.bm25_scores, trace.bm25_ranks, trace.learning.bm25_weight)
    candidate = any(nid == node_id for nid, _ in trace.candidates)
    retrieved = node_id in final_ranks
    retrieval_score = dict(hits).get(node_id)
    has_model_scores = bool(trace.reranker_scores)
    reranker_score = trace.reranker_scores.get(node_id)
    reason = ("returned" if retrieved else "outside_top_k" if candidate else
              "outside_candidate_limit" if node_id in fused_ranks else "no_overlap")
    # Only accepted, live connections to other returned hits are evidence.
    hit_ids = set(final_ranks) - {node_id}
    edges = [edge for edge in eligible_edges(engine.brain, set(trace.node_ids),
                                            datetime.now(timezone.utc))
             if ((edge.source == node_id and edge.target in hit_ids)
                  or (edge.target == node_id and edge.source in hit_ids))]
    return {
        "query": query, "node_id": node_id, "retrieved": retrieved,
        "storage_tier": trace.tiers.get(node_id),
        "tier_priority": ["main", "recall", "archival"],
        "learning": {"expanded_query": trace.learning.expanded_query,
                     "expansion_terms": trace.learning.expansion_terms,
                     "dense_weight": trace.learning.dense_weight,
                     "bm25_weight": trace.learning.bm25_weight,
                     "feedback_adjustment": trace.feedback_adjustments.get(node_id, 0.0)},
        "reason": reason, "rank": final_ranks.get(node_id),
        "k": k, "rerank_k": rerank_k, "candidate": candidate,
        "dense": dense, "bm25": bm25,
        "rrf": {"k": 60, "rank": fused_ranks.get(node_id),
                "score": dict(trace.fused).get(node_id, 0.0)},
        "retrieval_score": retrieval_score,
        "reranker_score": reranker_score,
        "final_score": (reranker_score if has_model_scores else retrieval_score)
                       if retrieved else None,
        "final_score_kind": ("reranker" if has_model_scores else
                             "rrf_graph" if trace.graph.contributions else "rrf"),
        "matched_terms": sorted(set(tokenize(query)) & set(tokenize(node.text))),
        "graph_used_for_ranking": bool(trace.graph.contributions),
        "graph": {**trace.graph.summary(),
                  "contribution": trace.graph.contributions.get(node_id, 0.0),
                  "paths": trace.graph.paths.get(node_id, [])},
        "graph_context": [edge.to_dict() for edge in sorted(edges, key=lambda e: e.id)],
    }


def retrieve(engine: BrainEngine, query: str, k: int = 5, rerank_k: int = 30,
             persist: bool = True, track: bool = False, *,
             per_tier: bool = False, graph: GraphOptions | None = None) -> list[tuple[str, float]]:
    """Hybrid retrieval over the brain. Returns top-k (node_id, rrf_score).

    Dense: cosine of the query embedding against the cached node vectors.
    BM25: lexical overlap against the node texts.
    GraphOptions explicitly adds bounded graph relevance before candidate limits.
    Fusion: RRF over the two rankings with optional learned weights and
    explicit feedback adjustments. Matching tiers precede relevance: main,
    recall, archival, including after reranking.
    Rerank (V2#1, optional): hybrid yields top-`rerank_k` candidates; a
    `reranker` set on the engine (cross-encoder or stub) re-sorts them to
    top-`k`. Without a reranker (default) the behavior is identical.
    With per_tier=True, both limits apply independently to each persisted
    tier, and empty bodies are excluded. This bounds context candidates
    without letting a populated higher tier crowd out the lower tiers.
    track (recall tracking): append the returned ids to the local recall ledger
    (`recall.record`). Off by default so read-only surfaces (MCP) stay
    read-only; CLI/HTTP pass True. The ledger write is an append to a
    gitignored file — it never dirties the brain repo.
    """
    trace = _retrieve_trace(engine, query, rerank_k, persist, per_tier=per_tier, graph=graph)
    return _finish_retrieval(engine, query, k, trace, track=track, per_tier=per_tier)


def retrieve_with_evidence(engine: BrainEngine, query: str, k: int = 5,
                           rerank_k: int = 30, *, persist: bool = False,
                           track: bool = False, graph: GraphOptions | None = None) -> dict:
    """One scoring pass with paths/evidence for returned candidates, read-only by default."""
    trace = _retrieve_trace(engine, query, rerank_k, persist, graph=graph)
    hits = _finish_retrieval(engine, query, k, trace, track=track)
    return {"hits": hits, "graph": trace.graph.summary(),
            "evidence": {nid: trace.graph.paths.get(nid, []) for nid, _ in hits}}


def _finish_retrieval(engine: BrainEngine, query: str, k: int, trace: _RetrievalTrace,
                      *, track: bool = False, per_tier: bool = False) -> list[tuple[str, float]]:
    text_by_id, candidates = trace.text_by_id, trace.candidates
    if not candidates:
        return []

    reranker = getattr(engine, "reranker", None)
    if reranker is None:
        result = _limit_hits(candidates, k, trace.tiers if per_tier else None)
    else:
        with _stage(engine, "reranking"):
            result = _rerank(engine, query, k, text_by_id, candidates,
                             tiers=trace.tiers, per_tier=per_tier)
    if track:
        from .recall import record, tracking_enabled
        if tracking_enabled():
            record(engine.brain, query, [nid for nid, _ in result])
    return result


def _rerank(engine: BrainEngine, query: str, k: int, text_by_id: dict[str, str],
            candidates: list[tuple[str, float]], *,
            reranker_scores: dict[str, float] | None = None,
            tiers: dict[str, str] | None = None,
            per_tier: bool = False) -> list[tuple[str, float]]:
    with_text = [(nid, text_by_id[nid], score) for nid, score in candidates]
    with_scores = getattr(engine.reranker, "rerank_with_scores", None)
    if with_scores is None:
        reranked = engine.reranker.rerank(query, with_text, len(with_text))
    else:
        reranked, scores = with_scores(query, with_text, len(with_text))
        if reranker_scores is not None:
            reranker_scores.update(scores)
    hits = order_by_tier([(nid, score) for nid, _, score in reranked], tiers or {})
    return _limit_hits(hits, k, tiers if per_tier else None)

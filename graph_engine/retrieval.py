"""Hybrid retrieval: dense (cosine) + BM25, fused via Reciprocal Rank Fusion.

Roadmap V2#1: "first hybrid dense+BM25 with tuned fusion (highest ROI)".
BM25 is pure text statistics — no dependency, no model. The RRF fusion
combines both rankings robustly (independent of their scale) before a
cross-encoder reranking of the top-K is added later.
"""

from __future__ import annotations

import math

import numpy as np

from .brain_engine import BrainEngine
from .similarity import cosine


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


def rrf_fuse(ranked_lists: list[list[tuple[str, float]]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: merges multiple (id, score) rankings into one.

    Each ranking is sorted by score descending; each rank contributes
    1/(k + rank). k=60 is the usual RRF standard.
    """
    fused: dict[str, float] = {}
    for rl in ranked_lists:
        ordered = sorted(rl, key=lambda x: x[1], reverse=True)
        for rank, (nid, _) in enumerate(ordered):
            fused[nid] = fused.get(nid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def retrieve_candidates(engine: BrainEngine, query: str, rerank_k: int = 30,
                        persist: bool = True) -> tuple[list[str], dict[str, str], list[tuple[str, float]]]:
    """Shared candidate retrieval for the retrieve()/rerank path."""
    nodes = engine.brain.read_nodes()
    # Audit #7: tombstones are "forgotten" — they must not come back as
    # search answers (consolidate/_find_duplicate already exclude them).
    nodes = [n for n in nodes if n.status != "tombstone"]
    if not nodes:
        return [], {}, []
    node_ids = [n.id for n in nodes]
    qvec = engine.embedder.embed(query)

    vecs = engine.brain.vectors_for(set(node_ids), lambda t: engine.embedder.embed(t),
                                    persist=persist)
    # Audit #8 (follow-up fix): vectors with a foreign dimension are not
    # comparable with the query (different embedder in the same brain, e.g.
    # demo seed with precomputed ST vectors + HashEmbedder engine). Instead of
    # silently truncating (old cosine bug) they are skipped — the dense stage
    # degrades, BM25 stays fully effective.
    # Audit #60: the dense stage runs as a numpy matmul over L2-normalized
    # vectors instead of a pure-Python cosine loop (0.150 s/query @2k×384-dim →
    # sub-2 ms). Foreign-dimension/empty vectors remain excluded.
    dense_ids = [nid for nid in node_ids
                 if nid in vecs and vecs[nid] and len(vecs[nid]) == len(qvec)]
    if dense_ids:
        M = np.array([vecs[nid] for nid in dense_ids], dtype=np.float64)
        M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-12)
        q = np.asarray(qvec, dtype=np.float64)
        q = q / (np.linalg.norm(q) + 1e-12)
        sims = M @ q
        dense = [(nid, float(s)) for nid, s in zip(dense_ids, sims)]
    else:
        dense = []

    bm = BM25([n.text for n in nodes])
    bm_scores = bm.scores(tokenize(query))
    bm_rank = [(nid, s) for nid, s in zip(node_ids, bm_scores) if s > 0.0]

    # Audit #37: a nonsense query otherwise returned 5 "results" with
    # RRF scores ≈ 0.033 — both ranks meaningless, but presented as a
    # ranking. Nodes without any overlap (dense 0.0 AND BM25 0.0)
    # are dropped before the fusion.
    dense_ids = {nid for nid, s in dense if s > 0.0}
    bm_ids = {nid for nid, s in bm_rank}
    overlap = dense_ids | bm_ids
    dense = [(nid, s) for nid, s in dense if nid in overlap]
    bm_rank = [(nid, s) for nid, s in bm_rank if nid in overlap]
    if not dense and not bm_rank:
        return node_ids, {n.id: n.text for n in nodes}, []

    candidates = rrf_fuse([dense, bm_rank], k=60)[:rerank_k]
    return node_ids, {n.id: n.text for n in nodes}, candidates


def retrieve(engine: BrainEngine, query: str, k: int = 5, rerank_k: int = 30,
             persist: bool = True, track: bool = False) -> list[tuple[str, float]]:
    """Hybrid retrieval over the brain. Returns top-k (node_id, rrf_score).

    Dense: cosine of the query embedding against the cached node vectors.
    BM25: lexical overlap against the node texts.
    Fusion: RRF over the two rankings.
    Rerank (V2#1, optional): hybrid yields top-`rerank_k` candidates; a
    `reranker` set on the engine (cross-encoder or stub) re-sorts them to
    top-`k`. Without a reranker (default) the behavior is identical.
    track (recall tracking): append the returned ids to the local recall ledger
    (`recall.record`). Off by default so read-only surfaces (MCP) stay
    read-only; CLI/HTTP pass True. The ledger write is an append to a
    gitignored file — it never dirties the brain repo.
    """
    node_ids, text_by_id, candidates = retrieve_candidates(engine, query, rerank_k,
                                                           persist=persist)
    if not candidates:
        return []

    reranker = getattr(engine, "reranker", None)
    result = candidates[:k] if reranker is None else _rerank(engine, query, k,
                                                             text_by_id, candidates)
    if track:
        from .recall import record, tracking_enabled
        if tracking_enabled():
            record(engine.brain, query, [nid for nid, _ in result])
    return result


def _rerank(engine: BrainEngine, query: str, k: int, text_by_id: dict[str, str],
            candidates: list[tuple[str, float]]) -> list[tuple[str, float]]:
    with_text = [(nid, text_by_id[nid], score) for nid, score in candidates]
    reranked = engine.reranker.rerank(query, with_text, k)
    return [(nid, score) for nid, _, score in reranked]

"""Growth loop on brain basis: ingest → embed → suggest → commit.

Every ingest is a git commit in the private repo — the graph grows as a
visible commit history.
"""

from __future__ import annotations

import os
import sys
import threading

from .brain import Brain, Node, Edge
from .embedder import get_embedder
from .similarity import cosine
from .suggester import suggest, is_auto_accept
from .intent import detect_intent
from .reranker import get_reranker
from .review import intent_auto_accept_max

DEDUPE_THRESHOLD = 0.92
# Intent edges may only fire for pairs that are genuinely topically
# related (same threshold as "extends"). Without this guard, a marker
# word in the new text ("ersetzt", "supersedes") would subordinate a node
# to EVERY existing node as intent — in a topically homogeneous brain
# (shared domain vocabulary) even to almost all of them.
INTENT_SIM_THRESHOLD = 0.45
AUTO_ACCEPT_ENV = "IDEAGRAPH_AUTO_ACCEPT"  # "1"/"true" → edges accepted without HITL
# "1"/"true" -> intent edges (supersedes/continues/contradicts) stay
# pending (HITL review) instead of auto-accepted. Lets the user decide
# whether automatically detected intents go straight into the graph.
INTENT_PENDING_ENV = "IDEAGRAPH_INTENT_PENDING"

# Serializes all brain write operations per process. The store is a series
# of whole-file rewrites (read-all → mutate → write-all); without a lock,
# parallel ingests/resolves interleave and last-writer-wins swallows the
# other's writes (Audit #1/#15). One lock suffices because all mutations
# run through the same process (server, CLI, pipeline tools).
BRAIN_LOCK = threading.RLock()


def auto_accept_from_env() -> bool:
    return os.environ.get(AUTO_ACCEPT_ENV, "").lower() in ("1", "true", "yes")


def intent_pending_from_env() -> bool:
    return os.environ.get(INTENT_PENDING_ENV, "").lower() in ("1", "true", "yes")


def _normalize(text: str) -> str:
    """For the duplicate comparison: lowercase, whitespace flattened."""
    return " ".join(text.lower().split())


class BrainEngine:
    def __init__(self, brain: Brain, embedder=None, dedupe_threshold: float = DEDUPE_THRESHOLD,
                 reranker=None):
        self.brain = brain
        self.embedder = embedder if embedder is not None else get_embedder()
        self.dedupe_threshold = dedupe_threshold
        # V2#1: optional cross-encoder rerank pass; None/default → no rerank.
        self.reranker = reranker if reranker is not None else get_reranker()

    def _find_duplicate(self, vec: list[float], exclude_id: str | None = None) -> Node | None:
        """Closest node above the dedupe threshold — or None. Uses the vector cache."""
        node_ids = {n.id for n in self.brain.read_nodes() if n.id != exclude_id}
        vectors = self.brain.vectors_for(
            node_ids,
            lambda t: self.embedder.embed(_normalize(t)),
            batch_fn=lambda ts: self.embedder.embed_batch([_normalize(t) for t in ts]),
        )
        best: tuple[float, str] | None = None
        for nid, v in vectors.items():
            if len(v) != len(vec):
                continue  # Audit #8: foreign dimension = not comparable, skip
            sim = cosine(vec, v)
            if sim >= self.dedupe_threshold and (best is None or sim > best[0]):
                best = (sim, nid)
        if best is None:
            return None
        return next((n for n in self.brain.read_nodes() if n.id == best[1]), None)

    def consolidate(self, admit_required: bool = False) -> dict:
        """Dedup-based consolidation (V2#2): dual-buffer promotion.

        Checks all probation nodes AGAINST EACH OTHER and against active
        (closes the streaming blind spot: nodes ingested in the same commit
        were never compared before). Near-duplicates are MERGED (dedupe,
        never summarize) and the redundant probation node is tombstoned;
        all others are promoted to active.

        `admit_required` (V2#3 admit rule, opt-in): when True, a node only
        enters the active graph if it has relations (active edges) —
        otherwise it stays in probation. Default False = existing behavior
        (promote all).
        """
        with BRAIN_LOCK:
            promoted, merged = 0, 0
            for pn in self.brain.read_nodes():
                if pn.status != "probation":
                    continue
                pvec = self.brain.vectors_for(
                    {pn.id}, lambda t: self.embedder.embed(_normalize(t))
                ).get(pn.id)
                dup = self._find_duplicate(pvec, exclude_id=pn.id) if pvec else None
                if dup is not None and dup.status != "tombstone":
                    self.brain.merge_node(dup, source=pn.source)
                    self.brain.tombstone_node(pn.id)
                    merged += 1
                    continue
                # V2#3 admit rule (opt-in): without relations (active edges) the
                # node does not enter the active graph — it stays in probation.
                if admit_required and not self._has_relation(pn.id):
                    continue
                self.brain.promote_node(pn.id)
                promoted += 1
            if promoted or merged:
                self.brain.rebuild_index()
            return {"promoted": promoted, "merged": merged}

    def _has_relation(self, node_id: str) -> bool:
        """V2#3 admit rule: does the node have an active edge (in/out)?"""
        return any(e.source == node_id or e.target == node_id
                   for e in self.brain.read_edges() if e.valid_to is None)

    def demote_forgotten(self, level_fn) -> int:
        """Graceful degradation (V2#2): active nodes whose level_fn=='tombstone'
        are tombstoned (never hard-deleted). level_fn(node)->str returns the
        decay level (e.g. from decay.decay_level with retrieval counters)."""
        with BRAIN_LOCK:
            count = 0
            for n in self.brain.read_nodes():
                if n.status == "active" and level_fn(n) == "tombstone":
                    self.brain.tombstone_node(n.id)
                    count += 1
            if count:
                self.brain.rebuild_index()
            return count

    def ingest(self, text: str, source: str = "human", tags: list[str] | None = None,
               allow_duplicates: bool = False, ntype: str = "semantic",
               auto_accept: bool | None = None,
               relations: list[tuple[str, str]] | None = None,
               edge_origin: str = "manual",
               env: dict[str, str] | None = None) -> tuple[Node, list[Edge], bool]:
        """Ingest with dedupe. Returns: (node, edges, is_duplicate).

        On a near-duplicate (cosine >= threshold against the normalized text)
        no new node is created; the existing one is merged instead: the
        source is logged on the node, the commit message says "dup".
        auto_accept (default: env IDEAGRAPH_AUTO_ACCEPT) accepts
        Auto-accept edge suggestions instead of leaving them pending.
        env (Tier-3): per-call env overrides for eval cases. The confidence floor
        (IG_EDGE_CONF_FLOOR, default 0.0 = no filter) drops weak
        Auto-edge suggestions — ROADMAP_CASE `roadmap-confidence-floor`.
        """
        if auto_accept is None:
            auto_accept = auto_accept_from_env()
        intent_pending = intent_pending_from_env()
        # Intent fan-out dam (ROADMAP_CASE `roadmap-intent-fanout-cap`): the
        # marker heuristic auto-accepted every intent edge it produced, so one
        # marker word could write dozens of false `contradicts` into the graph
        # (live: 39 % of all intent edges ever created were invalidated again).
        # At most `intent_auto_accept_max()` intent edges per source are
        # auto-accepted; the rest are born PENDING (kept, reviewable, not
        # dropped) — see graph_engine/review.py for the policy and its bounds.
        intent_auto_left = intent_auto_accept_max(env)
        text = text.strip()
        if not text:
            raise ValueError("Empty text cannot be ingested.")
        # The complete RMW chain (dedupe → node → embed → edges → vectors →
        # evolve → index → commit) runs under ONE lock: parallel ingests
        # must not duplicate each other's nodes/edges or lose
        # vector-cache writes (Audit #1/#15).
        with BRAIN_LOCK:
            self.brain.ensure_ready()  # onboarding: creates a missing brain repo
            self.brain.pull()
            vec = self.embedder.embed(_normalize(text))
            if not allow_duplicates:
                dup = self._find_duplicate(vec)
                if dup is not None:
                    self.brain.merge_node(dup, source=source)
                    self.brain.rebuild_index()
                    # Audit #31: a failing commit must not look like data loss —
                    # catch, heal the derived index, re-raise with guidance.
                    try:
                        self.brain.commit_and_push(
                            f"ingest dup of {dup.id[:8]}: {_normalize(text)[:50]}…")
                    except Exception:
                        self._heal_after_failed_commit()
                        raise
                    return dup, [], True
            node = Node(text=text, source=source, tags=tags, ntype=ntype)
            self.brain.write_node(node)
            # Embedding cache: only new nodes get embedded, the rest comes from vectors.jsonl
            others = {n.id for n in self.brain.read_nodes() if n.id != node.id}
            candidates = self.brain.vectors_for(
                others,
                lambda t: self.embedder.embed(_normalize(t)),
                batch_fn=lambda ts: self.embedder.embed_batch([_normalize(t) for t in ts]),
            )
            # V2#3 intent edges + admit rule: the new node enters with its relations.
            # Intent edges are pending=False (auto-accepted), so they must
            # additionally prove real topical relatedness (ST cosine
            # >= INTENT_SIM_THRESHOLD), otherwise a single marker word spams all nodes.
            intent_edges: list[Edge] = []
            # Sorted by target id: which edges fall inside the cap must not
            # depend on the filesystem's node read order (determinism).
            for ex in sorted(self.brain.read_nodes(), key=lambda n: n.id):
                if ex.id == node.id:
                    continue
                intent = detect_intent(node.text, ex.text)
                if not intent:
                    continue
                ex_vec = candidates.get(ex.id)
                if ex_vec is None or cosine(vec, ex_vec) < INTENT_SIM_THRESHOLD:
                    continue
                if intent_pending:
                    pending = True
                elif intent_auto_left > 0:
                    pending = False
                    intent_auto_left -= 1
                else:
                    pending = True
                intent_edges.append(Edge(source=node.id, target=ex.id, kind=intent, pending=pending,
                                         origin="intent"))
            # Admit rule: explicitly declared relations (target_text|id, kind).
            if relations:
                for ref, kind in relations:
                    target = next((n for n in self.brain.read_nodes()
                                   if n.id == ref or n.text.strip().lower() == ref.strip().lower()), None)
                    if target is not None and target.id != node.id:
                        intent_edges.append(Edge(source=node.id, target=target.id, kind=kind, pending=False,
                                             origin=edge_origin))
            # Similarity edges (V2#3): pending unless either the confidence band (>=0.95)
            # or the env override (IDEAGRAPH_AUTO_ACCEPT) auto-accepts the edge.
            # Tier-3 confidence floor (roadmap-confidence-floor): suggestions below the
            # floor (per-call env IG_EDGE_CONF_FLOOR, default 0.0 = no filter) are
            # dropped instead of landing pending — protects autonomous cycles from
            # a flood of low-confidence edges.
            # Tier-3 confidence floor: non-numeric values get an
            # understandable error instead of a bare float() ValueError
            # (Audit #20: "unexplained 500s").
            _floor_raw = (env or {}).get("IG_EDGE_CONF_FLOOR",
                                         os.environ.get("IG_EDGE_CONF_FLOOR", "0.0"))
            try:
                floor = float(_floor_raw)
            except (TypeError, ValueError):
                raise ValueError(
                    f"IG_EDGE_CONF_FLOOR must be a number, got: {_floor_raw!r}")
            sim_edges = [Edge(source=s.source, target=s.target, kind=s.kind,
                              pending=not (is_auto_accept(s.confidence) or auto_accept),
                              confidence=s.confidence, origin="suggester")
                         for s in suggest(node.id, vec, candidates)
                         if s.confidence >= floor]
            # Intent/admit-rule edges take precedence; similarity must not duplicate the same pair.
            claimed = {(e.source, e.target) for e in intent_edges}
            combined = list(intent_edges)
            for e in sim_edges:
                if (e.source, e.target) in claimed:
                    continue
                claimed.add((e.source, e.target))
                combined.append(e)
            existing_pairs = {(e.source, e.target) for e in self.brain.read_edges()}
            new_edges = [e for e in combined if (e.source, e.target) not in existing_pairs]
            for e in new_edges:
                self.brain.add_edge(e)
            # Cache the new node's vector
            cached = self.brain.read_vectors()
            cached[node.id] = vec
            self.brain.write_vectors(cached)
            # Memory evolution (A-Mem lesson): strong new connection (similar,
            # auto-accepted via confidence band OR env) → enrich related old
            # nodes with a cross-reference.
            # Audit #22: the rewrite must preserve the target node's status (and
            # created) — previously it lost status → active fell back to
            # probation (status erosion, verified live).
            # Audit #19: the annotation grows unboundedly and drifts the node's
            # own embedding → hard cap; further references go into the
            # edges (which exist anyway), not into the text.
            EVOLVED_ANNOTATION_CAP = 5
            evolved = 0
            for e in new_edges:
                if not e.pending and e.kind == "similar":
                        target_node = next((n for n in self.brain.read_nodes()
                                            if n.id == e.target), None)
                        if target_node is None or target_node.status == "tombstone":
                            continue
                        existing = target_node.text.count("[evolved ")
                        if existing >= EVOLVED_ANNOTATION_CAP:
                            continue
                        ref = f"[evolved {self._now_short()}: connected to {node.id[:8]} “{_normalize(text)[:40]}…”]"
                        if "evolved" not in target_node.text or node.id[:8] not in target_node.text:
                            self.brain.write_node(Node(
                                text=target_node.text + "\n\n" + ref,
                                id=target_node.id, created=target_node.created,
                                source=target_node.source, tags=target_node.tags,
                                sources=getattr(target_node, 'sources', []),
                                ntype=target_node.ntype,
                                status=target_node.status,
                                # Recall stats must survive a text rewrite:
                                # they are the input for promotion/decay.
                                recall_count=getattr(target_node, "recall_count", 0),
                                recall_queries=list(getattr(target_node, "recall_queries", [])),
                                last_recalled=getattr(target_node, "last_recalled", None)))
                            evolved += 1
            self.brain.rebuild_index()
            suffix = f", {evolved} nodes evolved" if evolved else ""
            try:
                self.brain.commit_and_push(
                    f"ingest: {text[:50]}{'…' if len(text) > 50 else ''} (+{len(new_edges)} suggestions{suffix})")
            except Exception:
                # Audit #31: the mutation landed on disk but the commit/push
                # failed. Heal the derived index and raise an actionable error
                # instead of a bare CalledProcessError (no fake rollback — the
                # next successful ingest commits whatever landed).
                self._heal_after_failed_commit()
                raise
            return node, new_edges, False

    def _heal_after_failed_commit(self) -> None:
        """Audit #31: after a failed commit, restore the derived state to a
        consistent, rebuildable condition and tell the operator what happened."""
        try:
            self.brain.rebuild_index()
        except Exception:
            pass  # index rebuild is best-effort; nodes/edges/vectors are the truth
        print("WARNING: brain mutated but commit/push failed — changes are on disk "
              "UNCOMMITTED. Recovery: `git -C <brain> add -A && git commit`, or "
              "retry the ingest (its commit will include these changes).", file=sys.stderr)

    @staticmethod
    def _now_short() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def resolve(self, edge_id: str, accept: bool) -> Edge | None:
        with BRAIN_LOCK:
            self.brain.ensure_ready()
            self.brain.pull()
            edge = self.brain.resolve_edge(edge_id, accept)
            if edge is not None:
                action = "accept" if accept else "reject"
                self.brain.commit_and_push(f"edge {action}: {edge_id[:8]} [{edge.kind}]")
            return edge

    def undo(self, edge_id: str) -> Edge | None:
        with BRAIN_LOCK:
            self.brain.ensure_ready()
            self.brain.pull()
            edge = self.brain.restore_edge(edge_id)
            if edge is not None:
                self.brain.commit_and_push(f"edge undo: {edge_id[:8]} [{edge.kind}]")
            return edge

    def link(self, source_id: str, target_id: str,
             kind: str = "same_as") -> Edge:
        """Create a manual edge (e.g. same_as for translation/alias pairs)."""
        with BRAIN_LOCK:
            self.brain.ensure_ready()
            self.brain.pull()
            ids = {n.id for n in self.brain.read_nodes()}
            missing = [nid for nid in (source_id, target_id) if nid not in ids]
            if missing:
                raise ValueError(f"Node(s) not found: {', '.join(missing)}")
            # Audit #23: the pair set was direction-less and kind-blind — a
            # legitimate same_as AND similar between the same pair could not
            # coexist, and A→B also blocked B→A. Dedupe is now
            # kind-aware and direction-sensitive; only exact duplicates block.
            existing = [(e.source, e.target, e.kind) for e in self.brain.read_edges()
                        if e.valid_to is None and not e.rejected]
            if (source_id, target_id, kind) in existing:
                raise ValueError("This edge already exists.")
            edge = Edge(source=source_id, target=target_id, kind=kind, pending=False,
                        origin="manual")
            self.brain.add_edge(edge)
            self.brain.commit_and_push(f"edge link: {source_id[:8]} --[{kind}]--> {target_id[:8]}")
            return edge

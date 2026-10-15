"""Growth loop on brain basis: ingest → embed → suggest → commit.

Every ingest is a git commit in the private repo — the graph grows as a
visible commit history.
"""

from __future__ import annotations

import os
import sys
import math
from contextlib import contextmanager
from collections.abc import Iterator
from .write_guard import THREAD_LOCK
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .consolidation import ConsolidationConfig

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
# parallel ingests/resolves interleave and lose updates (Audit #1/#15).
# Kept as a compatibility alias; brain.write_guard() also locks other processes.
BRAIN_LOCK = THREAD_LOCK  # compatibility alias; use brain.write_guard() for writes

CONSOLIDATE_THRESHOLD_ENV = "IG_CONSOLIDATE_THRESHOLD"
CONSOLIDATE_MIN_AGE_DAYS_ENV = "IG_CONSOLIDATE_MIN_AGE_DAYS"
CONSOLIDATE_MIN_COUNT_ENV = "IG_CONSOLIDATE_MIN_COUNT"
CONSOLIDATE_LIMIT_ENV = "IG_CONSOLIDATE_LIMIT"
CONSOLIDATE_LLM_CMD_ENV = "IG_CONSOLIDATE_LLM_CMD"
CONSOLIDATE_STRUCTURED_CMD_ENV = "IG_CONSOLIDATE_STRUCTURED_CMD"


def consolidation_structured_command_from_env() -> str:
    """Separate opt-in JSON adapter; never fall back to the legacy command."""
    return os.environ.get(CONSOLIDATE_STRUCTURED_CMD_ENV, "").strip()


GRAPH_HOME_ENV = "IG_GRAPH_HOME"
GRAPH_ENV = "IG_GRAPH"
ACCESS_POLICY_ENV = "IG_ACCESS_POLICY"
PRINCIPAL_ENV = "IG_PRINCIPAL"


def graph_access_config_from_env() -> dict[str, str]:
    """Trusted local process configuration for namespaces and access control."""
    return {key: os.environ.get(key, "") for key in
            (GRAPH_HOME_ENV, GRAPH_ENV, ACCESS_POLICY_ENV, PRINCIPAL_ENV)}


def consolidation_config_from_env(overrides: dict | None = None) -> "ConsolidationConfig":
    """Read gates at call time; explicit CLI/API values override environment."""
    from .consolidation import ConsolidationConfig
    overrides = overrides or {}
    values = {}
    for key, env_name, cast, default in (
        ("threshold", CONSOLIDATE_THRESHOLD_ENV, int, 1),
        ("min_age_days", CONSOLIDATE_MIN_AGE_DAYS_ENV, float, 1.0),
        ("min_count", CONSOLIDATE_MIN_COUNT_ENV, int, 1),
        ("limit", CONSOLIDATE_LIMIT_ENV, int, 50),
    ):
        raw = overrides.get(key)
        if raw is None:
            raw = os.environ.get(env_name, default)
        try:
            values[key] = cast(raw)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"{env_name}: invalid {key}: {raw!r}") from exc
    return ConsolidationConfig(**values)


WRITE_LOCK_TIMEOUT = 30.0
WRITE_LOCK_TIMEOUT_ENV = "IG_WRITE_LOCK_TIMEOUT"


def write_lock_timeout_from_env() -> float:
    """Maximum local writer wait (seconds); invalid values fail explicitly."""
    raw = os.environ.get(WRITE_LOCK_TIMEOUT_ENV, str(WRITE_LOCK_TIMEOUT))
    try:
        value = float(raw)
    except (ValueError, TypeError):
        raise ValueError(f"{WRITE_LOCK_TIMEOUT_ENV} must be a number between 0 and 3600") from None
    if not math.isfinite(value) or not 0 <= value <= 3600:
        raise ValueError(f"{WRITE_LOCK_TIMEOUT_ENV} must be finite and between 0 and 3600")
    return value


EDGE_CONF_FLOOR_ENV = "IG_EDGE_CONF_FLOOR"
EDGE_CONF_FLOOR = 0.0


def edge_conf_floor_from_env(env: dict[str, str] | None = None) -> float:
    """Per-call override > process environment; confidence is finite in [0, 1]."""
    raw = (env or {}).get(EDGE_CONF_FLOOR_ENV,
                          os.environ.get(EDGE_CONF_FLOOR_ENV, str(EDGE_CONF_FLOOR)))
    try:
        value = float(raw)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"{EDGE_CONF_FLOOR_ENV} must be a finite number between 0 and 1") from None
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{EDGE_CONF_FLOOR_ENV} must be a finite number between 0 and 1")
    return value


class IngestPartialError(RuntimeError):
    """Ingest failed after saving a note; never represent this as rejection."""

    def __init__(self, node_id: str, source_node_id: str | None, duplicate: bool,
                 cause: Exception, *, retryable: bool = False):
        self.node_id = node_id
        self.source_node_id = source_node_id
        self.duplicate = duplicate
        self.retryable = retryable
        super().__init__(f"Note {node_id} was saved, but ingest did not finish: {cause}")

    def to_dict(self) -> dict:
        # Do not expose backend exceptions (which may contain private paths/text).
        return dict(error="ingest_incomplete", captured=True, node_id=self.node_id,
                    source_node_id=self.source_node_id, duplicate=self.duplicate,
                    retryable=self.retryable,
                    message="Note saved; ingest incomplete. Inspect local state and Git sync. "
                            + ("Retry identical input to resume extraction." if self.retryable else
                               "Manual recovery is required before retrying extraction."))


def auto_accept_from_env() -> bool:
    return os.environ.get(AUTO_ACCEPT_ENV, "").lower() in ("1", "true", "yes")


def intent_pending_from_env() -> bool:
    return os.environ.get(INTENT_PENDING_ENV, "").lower() in ("1", "true", "yes")


def _normalize(text: str) -> str:
    """For the duplicate comparison: lowercase, whitespace flattened."""
    return " ".join(text.lower().split())


class BrainEngine:
    def __init__(self, brain: Brain, embedder=None, dedupe_threshold: float = DEDUPE_THRESHOLD,
                 reranker=None, *, search_cache_enabled: bool = True):
        self.brain = brain
        self.embedder = embedder if embedder is not None else get_embedder()
        self.dedupe_threshold = dedupe_threshold
        self.search_cache_enabled = search_cache_enabled
        # V2#1: optional cross-encoder rerank pass; None/default → no rerank.
        self.reranker = reranker if reranker is not None else get_reranker()

    def clear_search_cache(self) -> None:
        """Discard this engine's disposable parsed/lexical/dense snapshot."""
        self.__dict__.pop("_search_index", None)

    def _find_duplicate(self, vec: list[float], exclude_id: str | None = None) -> Node | None:
        """Closest node above the dedupe threshold — or None. Uses the vector cache."""
        node_ids = {n.id for n in self.brain.read_nodes()
                    if n.id != exclude_id and n.ntype != "entity" and n.status != "tombstone"
                    and "consolidation-proposal" not in n.tags
                    and not (n.capture and n.capture["duplicate"])
                    and self.brain.can_access("write", n.id)}
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
        with self.brain.write_guard():
            promoted, merged = 0, 0
            nodes = self.brain.read_nodes()
            # Receipts and their survivors own exact evidence and retry state.
            # Promote them normally, but never cosine-merge away their IDs.
            protected = {nid for n in nodes if n.capture and n.status != "tombstone"
                         for nid in (n.id, n.capture["node_id"])}
            for pn in nodes:
                if (pn.status != "probation" or pn.ntype == "entity"
                        or "consolidation-proposal" in pn.tags):
                    continue
                pvec = self.brain.vectors_for(
                    {pn.id}, lambda t: self.embedder.embed(_normalize(t))
                ).get(pn.id)
                dup = self._find_duplicate(pvec, exclude_id=pn.id) if pvec and pn.id not in protected else None
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
                   for e in self.brain.read_edges() if e.is_current)

    def demote_forgotten(self, level_fn) -> int:
        """Graceful degradation (V2#2): active nodes whose level_fn=='tombstone'
        are tombstoned (never hard-deleted). level_fn(node)->str returns the
        decay level (e.g. from decay.decay_level with retrieval counters)."""
        with self.brain.write_guard():
            count = 0
            for n in self.brain.read_nodes():
                if n.status == "active" and level_fn(n) == "tombstone":
                    self.brain.tombstone_node(n.id)
                    count += 1
            if count:
                self.brain.rebuild_index()
            return count

    def _prepare_ingest(self, text: str, source: str = "human", tags: list[str] | None = None,
                        allow_duplicates: bool = False, ntype: str = "semantic",
                        auto_accept: bool | None = None,
                        relations: list[tuple[str, str]] | None = None,
                        edge_origin: str = "manual", env: dict[str, str] | None = None,
                        _capture_input: str | None = None, _document: dict | None = None,
                        _node_id: str | None = None) -> tuple[Node, float, int]:
        """Validate and serialize before init, pull, dedupe or vector cache writes.

        Capture retries use the same preflight, even when they skip ingest.
        Storage-dependent target authorization still runs under the writer guard.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Empty text cannot be ingested.")
        if not isinstance(source, str):
            raise ValueError("source must be a string")
        if tags is not None and (not isinstance(tags, list)
                                 or any(not isinstance(t, str) for t in tags)):
            raise ValueError("tags must be a list of strings")
        if ntype not in ("semantic", "episodic", "procedural", "entity"):
            raise ValueError("Unknown ingest memory type")
        if not isinstance(allow_duplicates, bool):
            raise ValueError("allow_duplicates must be a boolean")
        if auto_accept is not None and not isinstance(auto_accept, bool):
            raise ValueError("auto_accept must be a boolean")
        if not isinstance(edge_origin, str):
            raise ValueError("edge_origin must be a string")
        if relations is not None and (not isinstance(relations, list) or any(
                not isinstance(pair, (tuple, list)) or len(pair) != 2
                or any(not isinstance(v, str) or not v.strip() for v in pair)
                for pair in relations)):
            raise ValueError("relations must be a list of (target, kind) string pairs")
        if env is not None and (not isinstance(env, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in env.items())):
            raise ValueError("env must be a dictionary of strings")
        floor = edge_conf_floor_from_env(env)
        intent_cap = intent_auto_accept_max(env)
        # Thresholds above 1 remain supported to disable cosine deduplication.
        if (not isinstance(self.dedupe_threshold, (int, float))
                or not math.isfinite(self.dedupe_threshold)):
            raise ValueError("dedupe_threshold must be finite")
        if _node_id is not None and not isinstance(_node_id, str):
            raise ValueError("node ID must be a string")
        if _node_id is not None:
            self.brain.node_path(_node_id)
        node = Node(text=text.strip(), source=source, tags=tags, ntype=ntype,
                    id=_node_id, document=_document)
        if _capture_input is not None:
            if not isinstance(_capture_input, str):
                raise ValueError("capture input must be a string")
            node.capture = dict(input=_capture_input, node_id=node.id,
                                duplicate=False, source=source, ingest_incomplete=True)
        node.to_markdown().encode("utf-8")  # Validate metadata and on-disk encoding.
        return node, floor, intent_cap

    def _complete_capture_ingest(self, receipt: Node | None) -> None:
        """Only a fully written ingest may be skipped by an extraction retry."""
        if receipt is None:
            return
        incomplete = receipt.capture
        receipt.capture = {k: v for k, v in incomplete.items() if k != "ingest_incomplete"}
        try:
            self.brain.write_node(receipt)
        except Exception:
            receipt.capture = incomplete
            raise

    @contextmanager
    def _after_capture(self, node: Node, receipt: Node | None = None,
                       duplicate: bool = False) -> Iterator[None]:
        """Convert post-save failures into a safe, machine-readable partial result."""
        try:
            yield
        except Exception as exc:
            self._heal_after_failed_commit()
            receipt_id = (receipt.id if receipt is not None
                          and self.brain.node_path(receipt.id).is_file() else None)
            raise IngestPartialError(node.id, receipt_id,
                                     duplicate, exc, retryable=receipt_id is not None
                                     and not receipt.capture.get("ingest_incomplete", False)) from exc

    def ingest(self, text: str, source: str = "human", tags: list[str] | None = None,
               allow_duplicates: bool = False, ntype: str = "semantic",
               auto_accept: bool | None = None,
               relations: list[tuple[str, str]] | None = None,
               edge_origin: str = "manual",
               env: dict[str, str] | None = None,
               _capture_input: str | None = None,
               _document: dict | None = None,
               _node_id: str | None = None) -> tuple[Node, list[Edge], bool]:
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
        node, floor, intent_auto_left = self._prepare_ingest(
            text, source, tags, allow_duplicates, ntype, auto_accept, relations,
            edge_origin, env, _capture_input, _document, _node_id)
        text = node.text
        if auto_accept is None:
            auto_accept = auto_accept_from_env()
        intent_pending = intent_pending_from_env()
        # The complete RMW chain (dedupe → node → embed → edges → vectors →
        # evolve → index → commit) runs under ONE lock: parallel ingests
        # must not duplicate each other's nodes/edges or lose
        # vector-cache writes (Audit #1/#15).
        with self.brain.write_guard():
            self.brain.ensure_ready()  # onboarding: creates a missing brain repo
            self.brain.pull()
            if _node_id is not None:
                self.brain.authorize("write", _node_id)
                capture_path = self.brain.node_path(_node_id)
                if capture_path.exists() or capture_path.is_symlink():
                    raise ValueError("Capture ID already exists; refusing to overwrite")
            if relations:
                for ref, _kind in relations:
                    target = next((n for n in self.brain.read_nodes()
                                   if n.id == ref or n.text.strip().lower() == ref.strip().lower()), None)
                    if target is not None:
                        self.brain.authorize("write", target.id)
            vec = self.embedder.embed(_normalize(text))
            if not allow_duplicates:
                dup = self._find_duplicate(vec)
                if dup is not None:
                    receipt = None
                    if _capture_input is not None:
                        # Prepare exact evidence before touching the survivor.
                        node.capture.update(node_id=dup.id, duplicate=True)
                        receipt = node
                    self.brain.merge_node(dup, source=source)
                    with self._after_capture(dup, receipt, duplicate=True):
                        if receipt is not None:
                            self.brain.write_node(receipt)
                        self.brain.rebuild_index()
                        self._complete_capture_ingest(receipt)
                        self.brain.commit_and_push(
                            f"ingest dup of {dup.id[:8]}: {_normalize(text)[:50]}…")
                        return dup, [], True
            self.brain.write_node(node)
            with self._after_capture(node, node if node.capture else None):
                # Embedding cache: only new nodes get embedded, the rest comes from vectors.jsonl
                others = {n.id for n in self.brain.read_nodes()
                          if n.id != node.id and n.ntype != "entity"
                          and self.brain.can_access("write", n.id)}
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
                    if (ex.id == node.id or ex.ntype == "entity"
                            or not self.brain.can_access("write", ex.id)):
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
                # Apply the confidence floor resolved before any storage mutation.
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
                            if (target_node is None or target_node.status == "tombstone"
                                    or target_node.ntype == "entity"
                                    or "consolidation-proposal" in target_node.tags):
                                # Proposal text is the claim's reuse/decision key.
                                # Keep automatic cross-references in edges only.
                                continue
                            existing = target_node.text.count("[evolved ")
                            if existing >= EVOLVED_ANNOTATION_CAP:
                                continue
                            ref = f"[evolved {self._now_short()}: connected to {node.id[:8]} “{_normalize(text)[:40]}…”]"
                            if "evolved" not in target_node.text or node.id[:8] not in target_node.text:
                                # Enrich the existing object: reconstructing a Node
                                # resets newer metadata (including pinned tiers).
                                target_node.text += "\n\n" + ref
                                self.brain.write_node(target_node)
                                evolved += 1
                self.brain.rebuild_index()
                self._complete_capture_ingest(node if node.capture else None)
                suffix = f", {evolved} nodes evolved" if evolved else ""
                self.brain.commit_and_push(
                    f"ingest: {text[:50]}{'…' if len(text) > 50 else ''} (+{len(new_edges)} suggestions{suffix})")
                return node, new_edges, False

    def capture(self, text: str, source: str = "human", tags: list[str] | None = None,
                allow_duplicates: bool = False, *, extraction: str | None = None,
                accept_facts: bool = False, **kwargs) -> tuple[Node, list[Edge], bool, dict | None]:
        """Shared opt-in ingestion: capture commit, then extraction commit.

        Default calls retain ingest behavior. Extraction calls persist an exact
        input receipt; identical input/source/type retries reuse that receipt
        and skip ingest, including when allow_duplicates is true. Failures
        after capture return an explicit failed summary, with safe error codes.
        """
        from .entities import command_extractor, extract_entities

        if extraction not in (None, "rules", "model"):
            raise ValueError("extraction must be rules or model")
        if not isinstance(accept_facts, bool):
            raise ValueError("accept_facts must be a boolean")
        if accept_facts and extraction is None:
            raise ValueError("accept_facts requires extraction")
        if extraction is None:
            node, edges, duplicate = self.ingest(text, source, tags, allow_duplicates, **kwargs)
            return node, edges, duplicate, None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Empty text cannot be ingested.")
        if kwargs.get("ntype", "semantic") not in ("semantic", "episodic", "procedural"):
            raise ValueError("capture requires a semantic, episodic or procedural note")
        self._prepare_ingest(text, source, tags, allow_duplicates, **kwargs)
        # Reject missing model configuration before capture, but execute the
        # adapter only after the original input is durably stored.
        extractor = command_extractor() if extraction == "model" else None
        with self.brain.write_guard():
            self.brain.ensure_ready()
            self.brain.pull()
            evidence = next((n for n in self.brain.read_nodes()
                if n.status != "tombstone" and n.capture
                and n.capture["input"] == text and n.capture["source"] == source
                and n.ntype == kwargs.get("ntype", "semantic")
                and self.brain.can_access("write", n.id)), None)
            retried = evidence is not None
            if evidence is None:
                node, edges, duplicate = self.ingest(text, source, tags, allow_duplicates,
                                                     _capture_input=text, **kwargs)
                evidence = next(n for n in self.brain.read_nodes()
                    if n.capture and n.capture["input"] == text
                    and n.capture["source"] == source and n.capture["node_id"] == node.id
                    and n.ntype == kwargs.get("ntype", "semantic") and n.status != "tombstone")
            else:
                node = self.brain.read_node(evidence.capture["node_id"])
                if node is None or node.status == "tombstone":
                    raise ValueError("Captured note is no longer live; retry cannot revive it")
                self.brain.authorize("write", node.id)
                if evidence.capture.get("ingest_incomplete", False):
                    raise IngestPartialError(node.id, evidence.id, evidence.capture["duplicate"],
                        RuntimeError("Capture ingest requires manual recovery"))
                edges, duplicate = [], evidence.capture["duplicate"]
            summary = dict(mode=extraction, source_node_id=evidence.id,
                           captured=True, retried=retried)
            try:
                if retried:
                    # Also finish a capture whose commit/sync previously failed.
                    self.brain.commit_and_push(f"capture retry: {evidence.id}", sync_pending=True)
                result = extract_entities(self.brain, node_id=evidence.id,
                    extractor=extractor, accept_facts=accept_facts, commit=False)
                # Even a no-op retry commits prior writes left by a failed sync.
                self.brain.commit_and_push(f"capture entities: {evidence.id}", sync_pending=True)
            except Exception as exc:
                code = ("access_denied" if isinstance(exc, PermissionError) else
                        "invalid_extraction" if isinstance(exc, ValueError) else "extraction_failed")
                summary.update(status="failed", error=code, retryable=True,
                    created_entities=None, reused_entities=None, created_facts=None,
                    reused_facts=None, pending_facts=None)
            else:
                facts = {f["id"]: f for f in result["facts"]}.values()
                summary.update(status="complete", created_entities=result["created_entities"],
                    reused_entities=len(result["entities"]) - result["created_entities"],
                    created_facts=result["created_facts"],
                    reused_facts=len(facts) - result["created_facts"],
                    pending_facts=sum(f["pending"] and not f.get("rejected") and not f.get("invalidated_at")
                                      for f in facts),
                    proposals=result["proposals"])
            return node, edges, duplicate, summary

    def entities(self, text: str | None = None, **kwargs) -> dict:
        """Extract typed entities/facts and link them to an evidence node."""
        from .entities import extract_entities
        return extract_entities(self.brain, text, **kwargs)

    def observe(self, text: str, source: str = "human", tags: list[str] | None = None,
                observed_at: str | None = None, context: str | None = None,
                allow_duplicates: bool = False) -> tuple[Node, bool]:
        """Store a raw episodic event (Phase 1: episodic layer).

        Episodic nodes are NOT deduplicated — every observation is a distinct
        event, even if it describes the same fact. They carry `observed_at`
        (when the event happened) and `context` (where/how it was observed).
        Returns (node, is_duplicate) — is_duplicate is always False unless
        allow_duplicates=False and an identical text already exists.
        """
        with self.brain.write_guard():
            self.brain.ensure_ready()
            self.brain.pull()
            text = text.strip()
            if not text:
                raise ValueError("Empty text cannot be observed.")
            if not allow_duplicates:
                # Exact-text dedupe for episodic (not cosine — events are unique)
                existing = next(
                    (n for n in self.brain.read_nodes()
                     if n.ntype == "episodic" and n.text.strip() == text),
                    None)
                if existing is not None:
                    return existing, True
            node = Node(text=text, source=source, tags=tags, ntype="episodic",
                        status="active", observed_at=observed_at, context=context)
            self.brain.write_node(node)
            self.brain.rebuild_index()
            self.brain.commit_and_push(
                f"observe: {text[:50]}{'…' if len(text) > 50 else ''}")
            return node, False

    def extract(self, node_id: str, text: str | None = None,
                source: str = "human", tags: list[str] | None = None) -> Node:
        """Extract a semantic fact from an episodic node (Phase 1).

        Creates a new semantic node linked to the episodic source via an
        `extends` edge. The original episodic node is NOT modified — the
        extraction is a new, derived memory. If `text` is None, the episodic
        node's text is used as the basis (the caller is expected to have
        already refined it, e.g. via an LLM).
        """
        with self.brain.write_guard():
            self.brain.ensure_ready()
            self.brain.pull()
            episodic = self.brain.read_node(node_id)
            if episodic is None:
                raise ValueError(f"No node with id {node_id!r}.")
            if episodic.ntype != "episodic":
                raise ValueError(
                    f"Node {node_id!r} is not episodic (type={episodic.ntype!r}).")
            semantic_text = (text or episodic.text).strip()
            if not semantic_text:
                raise ValueError("Empty text cannot be extracted.")
            node = Node(text=semantic_text, source=source, tags=tags,
                        ntype="semantic", status="probation", derived_from=[episodic.id])
            self.brain.write_node(node)
            edge = Edge(source=node.id, target=episodic.id, kind="extends",
                        pending=False, origin="consolidator")
            self.brain.add_edge(edge)
            self.brain.rebuild_index()
            self.brain.commit_and_push(
                f"extract: {node.id[:8]} from episodic {episodic.id[:8]}")
            return node

    def timeline(self, *, since: str | None = None, until: str | None = None,
                 limit: int = 50) -> list[Node]:
        """Query episodic nodes by time range (Phase 1: temporal reasoning).

        Returns episodic nodes sorted by `observed_at` (newest first).
        `since`/`until` are ISO-8601 date strings. Without arguments,
        returns the most recent `limit` episodic nodes.
        """
        nodes = [n for n in self.brain.read_nodes()
                 if n.ntype == "episodic" and n.status != "tombstone"]
        if since:
            nodes = [n for n in nodes
                     if (n.observed_at or n.created) >= since]
        if until:
            nodes = [n for n in nodes
                     if (n.observed_at or n.created) <= until]
        nodes.sort(key=lambda n: n.observed_at or n.created, reverse=True)
        return nodes[:limit]

    def valid_at(self, timestamp: str) -> dict:
        """Current records filtered by creation and fact-validity time.

        Returns {nodes: [...], edges: [...]} — only nodes and edges that were
        live at the given timestamp. Read-only.
        """
        from .temporal import valid_at
        return valid_at(self.brain, timestamp)

    def history(self, node_id: str) -> list[dict]:
        """How a node's edges evolved over time (Phase 2: temporal reasoning).

        Returns a chronological list of edge events (creation, invalidation)
        involving this node. Read-only.
        """
        from .temporal import history
        return history(self.brain, node_id)

    def when(self, query: str, at: str, k: int = 5) -> list[tuple[str, float]]:
        """Retrieve current text, restricted by node creation time.

        Runs the normal hybrid retrieval, then filters the results to only
        include nodes that existed at the given timestamp. Read-only.
        """
        from .temporal import when
        return when(self, query, at, k=k)

    def snapshot(self, revision: str, *, fact_valid_at: str | None = None) -> dict:
        """Read Git snapshot state with current authorization, without sync."""
        from .snapshots import snapshot
        return snapshot(self.brain, revision, fact_valid_at=fact_valid_at)

    def snapshot_query(self, revision: str, query: str, *, k: int = 5,
                       fact_valid_at: str | None = None) -> dict:
        """Search historical committed text without recall/cache writes."""
        from .snapshots import snapshot_query
        return snapshot_query(self, revision, query, k=k, fact_valid_at=fact_valid_at)

    def build_context(self, query: str, budget: int = 4000, **kwargs) -> dict:
        """Assemble a context window for a query (Phase 3: context management).

        Returns {context, tokens, nodes, budget, truncated}. Read-only.
        """
        from .context import build_context
        return build_context(self, query, budget, **kwargs)

    def context_for_prompt(self, query: str, max_tokens: int = 2000) -> str:
        """Build a context string ready for a prompt (Phase 3). Read-only."""
        from .context import context_for_prompt
        return context_for_prompt(self, query, max_tokens=max_tokens)

    def context_stats(self, query: str, budget: int = 4000) -> dict:
        """Statistics about a context build (Phase 3). Read-only."""
        from .context import context_stats
        return context_stats(self, query, budget)

    def _heal_after_failed_commit(self) -> None:
        """Audit #31: after a failed commit, restore the derived state to a
        consistent, rebuildable condition and tell the operator what happened."""
        try:
            self.brain.rebuild_index()
        except Exception:
            pass  # index rebuild is best-effort; nodes/edges/vectors are the truth
        print("WARNING: brain mutated but ingest did not finish — changes remain local "
              "and may already be committed. Inspect `git -C <brain> status` and "
              "`git -C <brain> log` before retrying sync.", file=sys.stderr)

    @staticmethod
    def _now_short() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def resolve(self, edge_id: str, accept: bool) -> Edge | None:
        with self.brain.write_guard():
            self.brain.ensure_ready()
            self.brain.pull()
            edge = self.brain.resolve_edge(edge_id, accept)
            if edge is not None:
                action = "accept" if accept else "reject"
                self.brain.commit_and_push(f"edge {action}: {edge_id[:8]} [{edge.kind}]")
            return edge

    def undo(self, edge_id: str) -> Edge | None:
        with self.brain.write_guard():
            self.brain.ensure_ready()
            self.brain.pull()
            edge = self.brain.restore_edge(edge_id)
            if edge is not None:
                self.brain.commit_and_push(f"edge undo: {edge_id[:8]} [{edge.kind}]")
            return edge

    def link(self, source_id: str, target_id: str,
             kind: str = "same_as") -> Edge:
        """Create a manual edge (e.g. same_as for translation/alias pairs)."""
        with self.brain.write_guard():
            self.brain.ensure_ready()
            self.brain.pull()
            ids = {n.id for n in self.brain.read_nodes() if n.status != "tombstone"}
            missing = [nid for nid in (source_id, target_id) if nid not in ids]
            if missing:
                raise ValueError(f"Node(s) not found: {', '.join(missing)}")
            # Audit #23: the pair set was direction-less and kind-blind — a
            # legitimate same_as AND similar between the same pair could not
            # coexist, and A→B also blocked B→A. Dedupe is now
            # kind-aware and direction-sensitive; only exact duplicates block.
            existing = [(e.source, e.target, e.kind) for e in self.brain.read_edges()
                        if e.is_current and not e.rejected]
            if (source_id, target_id, kind) in existing:
                raise ValueError("This edge already exists.")
            edge = Edge(source=source_id, target=target_id, kind=kind, pending=False,
                        origin="manual")
            self.brain.add_edge(edge)
            self.brain.commit_and_push(f"edge link: {source_id[:8]} --[{kind}]--> {target_id[:8]}")
            return edge

"""Eval layer for the engine (Roadmap V2#4).

End-state verification instead of transcripts: each eval task describes an
ingest sequence + an ORACLE over the final brain state (does the node exist,
are the edges set, was the duplicate merged?). Deterministic checkers run
against the actual brain state — no peeking at intermediate steps.

Two tiers (tiered gates):
  - GOLDEN_SET: regression on every engine change. These cases MUST be green
    on the current state — they freeze the as-is behavior as a baseline.
  - ROADMAP_CASES: document desired future behavior from the roadmap
    (confidence bands, intent edges, contradictions). They are registered as
    a specification and turn green once the feature is implemented — making
    progress measurable without breaking the baseline.

pass^k: run_eval(... k=...) runs the same task k times against a fresh
brain and requires ALL runs to pass (protection against flakiness).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .brain import Brain, Node
from .brain_engine import BrainEngine
from .intent import INTENT_KINDS
from .recall import aggregate as aggregate_recalls
from .retrieval import explain, retrieve
from .reranker import ReverseReranker


# ---------------------------------------------------------------------------
# Oracle / tasks
# ---------------------------------------------------------------------------

@dataclass
class EdgeExpectation:
    """An expected edge, text-based (source/target NODE CONTENT).

    kind="*" means: any active edge between the two nodes suffices
    (robust against exact kind names when only "being connected" matters).
    pending/min_confidence are optional and check the confidence band (V2#3).
    """
    source: str
    target: str
    kind: str
    pending: bool | None = None          # if set: edge must have this pending value
    min_confidence: float | None = None  # if set: Edge.confidence >= this value
    # Who created the edge (`roadmap-edge-origin`): "suggester" (cosine kNN),
    # "intent" (marker heuristic), "manual" (ig link / declared relations),
    # "consolidator" (dream pass). Maintenance passes may rewrite heuristic
    # edges; manual ones are user-authored and must be left alone.
    origin: str | None = None


@dataclass
class RetrievalExpectation:
    """A retrieval expectation (hybrid dense+BM25): query must return matching nodes."""
    query: str
    top: int = 5
    includes: list[str] = field(default_factory=list)   # node texts that must appear in the top-`top`
    excludes: list[str] = field(default_factory=list)   # node texts that must NOT appear


@dataclass
class ExplanationExpectation:
    """Explain a result with reconstructible scores and contextual edges."""
    query: str
    node_text: str
    retrieved: bool = True
    related_texts: list[str] = field(default_factory=list)


@dataclass
class CommunityExpectation:
    """Structural expectation over the community partition of the FINAL graph.

    Topology evals (report #3): `together` texts must share ONE community,
    `apart` pairs must sit in DIFFERENT communities, `gap` pairs must appear
    together in a reported structural gap. All three are asserted — each one
    alone is trivially green (everything-in-one / everything-singleton /
    report-every-pair). min_size mirrors the CLI default's role: communities
    smaller than this are not gap candidates.
    """
    together: list[list[str]] = field(default_factory=list)
    apart: list[tuple[str, str]] = field(default_factory=list)
    gap: list[tuple[str, str]] = field(default_factory=list)
    min_size: int = 2


@dataclass
class NeighborhoodExpectation:
    """Graph-traversal expectation (report #1): the node with `node_text`
    must have each of `expected_neighbor_texts` within `hops` undirected
    live-edge hops. `absent_neighbor_texts` must NOT be reachable within
    `hops` — an expectation family alone is trivially green, so both run
    together (same rule as CommunityExpectation).
    """
    node_text: str
    expected_neighbor_texts: list[str] = field(default_factory=list)
    absent_neighbor_texts: list[str] = field(default_factory=list)
    hops: int = 1


@dataclass
class EvalOracle:
    """Desired brain state after the ingest sequence."""
    node_count: int | None = None
    nodes_present: list[str] = field(default_factory=list)
    node_absent: list[str] = field(default_factory=list)
    # (text, required sources): the node with this text must have all these sources.
    duplicate_merged: list[tuple[str, list[str]]] = field(default_factory=list)
    edges: list[EdgeExpectation] = field(default_factory=list)
    no_edge: list[EdgeExpectation] = field(default_factory=list)
    retrieval: list[RetrievalExpectation] = field(default_factory=list)
    explanations: list[ExplanationExpectation] = field(default_factory=list)
    # text -> expected node status (V2#2 memory hygiene)
    node_status: dict[str, str] = field(default_factory=dict)
    # topology expectations (report #3): partition-level assertions
    communities: list[CommunityExpectation] = field(default_factory=list)
    # rendered-output expectations (report #7): strings that must appear in /
    # must not appear in the generated BRAIN_REPORT digest
    report_contains: list[str] = field(default_factory=list)
    report_absent: list[str] = field(default_factory=list)
    # graph-traversal expectations (report #1): neighborhood reachability
    neighborhoods: list[NeighborhoodExpectation] = field(default_factory=list)
    # Intent fan-out dam (`roadmap-intent-fanout-cap`): no source node may hold
    # more than this many AUTO-ACCEPTED (pending=False) intent edges. Intent
    # edges carry no confidence, so the confidence bands cannot judge them and
    # the marker heuristic is the only producer — the cap is the structural
    # bound on that stream.
    max_auto_intent_per_source: int | None = None
    # Recall tracking (`roadmap-recall-tracking`): text -> expected
    # `recall_count` after the recall ledger was aggregated. This is the input
    # signal for promotion/decay — a memory that does not know what it is asked
    # for cannot decide what to keep.
    node_recalls: dict[str, int] = field(default_factory=dict)
    # Edge-provenance floors (`roadmap-dream-distill`): origin -> minimum number
    # of LIVE edges carrying that origin. A pass that writes `consolidator` edges
    # is only observable through counts — the texts it generates are not
    # knowable up front. Pending/rejected/invalidated edges do not count.
    min_edges_by_origin: dict[str, int] = field(default_factory=dict)


@dataclass
class EvalTask:
    id: str
    name: str
    ingests: list[tuple[str, dict]]  # (text, kwargs) — order is part of the scenario
    oracle: EvalOracle
    # Optional actions AFTER the ingests (e.g. manual same_as links,
    # consolidation, demotion). Return values are ignored.
    actions: list[Callable[[BrainEngine], object]] = field(default_factory=list)
    # Optional reranker (V2#1): set after engine construction so retrieval
    # evals can measure the cross-encoder rerank pass with a deterministic
    # stand-in. None = engine default (no rerank).
    reranker: object | None = None


@dataclass
class EvalResult:
    task_id: str
    name: str
    passed: bool
    failures: list[str]
    runs: int


# ---------------------------------------------------------------------------
# End-State-Checker
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def find_node_by_text(brain: Brain, text: str) -> Node | None:
    """Resolve an oracle text to a node: exact normalized match wins.

    Prefix fallback exists because memory evolution appends an auto-accepted
    "[evolved …]" cross-reference to the text — the original text stays a
    prefix and must still resolve. Audit #27: when one oracle text is a
    prefix of another, first-hit-wins prefix matching resolved to the wrong
    node — an exact match now always beats a prefix match, and prefix
    matching prefers the SHORTEST prefix (the original, pre-evolution text).
    """
    target = _norm(text)
    nodes = brain.read_nodes()
    for n in nodes:
        if _norm(n.text) == target:
            return n
    best: Node | None = None
    for n in nodes:
        if _norm(n.text).startswith(target):
            if best is None or len(_norm(n.text)) < len(_norm(best.text)):
                best = n
    return best


def verify_end_state(brain: Brain, oracle: EvalOracle) -> list[str]:
    """Check the final brain state against the oracle. Returns all failures ([] = green)."""
    failures: list[str] = []
    nodes = brain.read_nodes()
    edges = brain.read_edges()

    if oracle.node_count is not None and len(nodes) != oracle.node_count:
        failures.append(f"node_count: expected {oracle.node_count}, got {len(nodes)}")

    for text in oracle.nodes_present:
        if find_node_by_text(brain, text) is None:
            failures.append(f"node missing: {text!r}")

    for text in oracle.node_absent:
        if find_node_by_text(brain, text) is not None:
            failures.append(f"node should be absent: {text!r}")

    for text, req_sources in oracle.duplicate_merged:
        n = find_node_by_text(brain, text)
        if n is None:
            failures.append(f"dup node missing: {text!r}")
        else:
            for s in req_sources:
                if s not in n.sources:
                    failures.append(f"node {text!r} missing source {s!r} (got {n.sources})")

    for text, expected_status in oracle.node_status.items():
        n = find_node_by_text(brain, text)
        if n is None:
            failures.append(f"status node missing: {text!r}")
        elif n.status != expected_status:
            failures.append(f"node {text!r}: expected status {expected_status!r}, got {n.status!r}")

    for eexp in oracle.edges:
        s = find_node_by_text(brain, eexp.source)
        t = find_node_by_text(brain, eexp.target)
        if s is None or t is None:
            failures.append(f"edge endpoint missing: {eexp.source!r}->{eexp.target!r}")
            continue
        # Direction-agnostic: auto edges point from the newer to the older node,
        # so direction doesn't matter for "being connected".
        active = [
            e for e in edges
            if e.valid_to is None
            and ((e.source == s.id and e.target == t.id) or (e.source == t.id and e.target == s.id))
        ]
        if eexp.kind != "*":
            kind_match = [e for e in active if e.kind == eexp.kind]
        else:
            kind_match = active
        if not kind_match:
            failures.append(f"edge missing: {eexp.source!r} --[{eexp.kind}]--> {eexp.target!r}")
            continue
        if eexp.pending is not None and not any(e.pending == eexp.pending for e in kind_match):
            failures.append(
                f"edge {eexp.source!r}->{eexp.target!r}: expected pending={eexp.pending}, "
                f"got {[e.pending for e in kind_match]}"
            )
        if eexp.min_confidence is not None and not any(
            (e.confidence or 0.0) >= eexp.min_confidence for e in kind_match
        ):
            failures.append(
                f"edge {eexp.source!r}->{eexp.target!r}: expected confidence>={eexp.min_confidence}, "
                f"got {[e.confidence for e in kind_match]}"
            )
        # Edge provenance (`roadmap-edge-origin`): who CREATED the edge. A
        # maintenance pass may rewrite heuristic edges but never manual ones,
        # so the origin has to be asserted, not inferred from the text.
        if eexp.origin is not None and not any(
            getattr(e, "origin", None) == eexp.origin for e in kind_match
        ):
            failures.append(
                f"edge {eexp.source!r}->{eexp.target!r}: expected origin "
                f"{eexp.origin!r}, got {[getattr(e, 'origin', None) for e in kind_match]}"
            )

    for eexp in oracle.no_edge:
        s = find_node_by_text(brain, eexp.source)
        t = find_node_by_text(brain, eexp.target)
        if s is None or t is None:
            continue
        # Audit #27: mirror the positive path — only ACTIVE edges count, and
        # kind="*" means any kind; a specific kind must match exactly. An
        # invalidated edge or a different-kind edge is NOT a violation.
        violating = [
            e for e in edges
            if e.valid_to is None
            and ((e.source == s.id and e.target == t.id) or (e.source == t.id and e.target == s.id))
            and (eexp.kind == "*" or e.kind == eexp.kind)
        ]
        if violating:
            failures.append(f"unexpected edge: {eexp.source!r} --[{eexp.kind}]--> {eexp.target!r}")

    if oracle.report_contains or oracle.report_absent:
        from .report import render_report
        rendered = render_report(brain)
        for needle in oracle.report_contains:
            if needle not in rendered:
                failures.append(f"report missing: {needle!r}")
        for needle in oracle.report_absent:
            if needle in rendered:
                failures.append(f"report should not contain: {needle!r}")

    if oracle.node_recalls:
        for text, expected in oracle.node_recalls.items():
            n = find_node_by_text(brain, text)
            if n is None:
                failures.append(f"recall node missing: {text!r}")
            elif getattr(n, "recall_count", 0) != expected:
                failures.append(
                    f"node {text!r}: expected recall_count {expected}, "
                    f"got {getattr(n, 'recall_count', 0)}")

    if oracle.max_auto_intent_per_source is not None:
        per_source: dict[str, int] = {}
        for e in edges:
            if (e.kind in INTENT_KINDS and not e.pending and not e.rejected
                    and e.valid_to is None):
                per_source[e.source] = per_source.get(e.source, 0) + 1
        over = {s: n for s, n in per_source.items()
                if n > oracle.max_auto_intent_per_source}
        if over:
            worst_source, worst_n = max(over.items(), key=lambda kv: kv[1])
            failures.append(
                f"intent fan-out: source {worst_source} has {worst_n} auto-accepted "
                f"intent edges (max {oracle.max_auto_intent_per_source}); "
                f"{len(over)} source(s) over the cap")

    for origin, minimum in oracle.min_edges_by_origin.items():
        found = sum(1 for e in edges
                    if getattr(e, "origin", None) == origin
                    and not e.pending and not e.rejected and e.valid_to is None)
        if found < minimum:
            failures.append(
                f"edges with origin {origin!r}: expected >= {minimum} live, got {found}")

    return failures


def verify_retrieval(engine: BrainEngine, expectations: list[RetrievalExpectation]) -> list[str]:
    """Check hybrid retrieval: query must return expected nodes in the top-k (or exclude them)."""
    failures: list[str] = []
    id2node = {n.id: n for n in engine.brain.read_nodes()}
    for exp in expectations:
        hits = retrieve(engine, exp.query, k=exp.top)
        hit_texts = [_norm(id2node[nid].text) for nid, _ in hits if nid in id2node]
        for want in exp.includes:
            if not any(_norm(want) in t or t.startswith(_norm(want)) for t in hit_texts):
                failures.append(f"retrieval '{exp.query}' should hit {want!r} in top-{exp.top}")
        for avoid in exp.excludes:
            if any(_norm(avoid) in t or t.startswith(_norm(avoid)) for t in hit_texts):
                failures.append(f"retrieval '{exp.query}' should NOT hit {avoid!r} in top-{exp.top}")
    return failures


def verify_explanations(engine: BrainEngine,
                        expectations: list[ExplanationExpectation]) -> list[str]:
    """Require score fidelity and expected graph context in the final brain."""
    import math

    failures: list[str] = []
    for exp in expectations:
        node = find_node_by_text(engine.brain, exp.node_text)
        if node is None:
            failures.append(f"explanation node missing: {exp.node_text!r}")
            continue
        result = explain(engine, node.id, exp.query)
        hits = dict(retrieve(engine, exp.query, persist=False))
        rank = next((i for i, nid in enumerate(hits, start=1) if nid == node.id), None)
        expected_final = (result["reranker_score"] if result["final_score_kind"] == "reranker"
                          else hits.get(node.id)) if rank is not None else None
        if (result["retrieved"] != exp.retrieved or result["rank"] != rank
                or result["retrieval_score"] != hits.get(node.id)
                or result["final_score"] != expected_final):
            failures.append(f"explanation disagrees with retrieval: {exp.node_text!r}")
        contributions = sum(result[channel]["rrf_contribution"] for channel in ("bm25", "dense"))
        if not math.isclose(result["rrf"]["score"], contributions):
            failures.append(f"explanation RRF contributions do not sum: {exp.node_text!r}")
        connected = {edge[side] for edge in result["graph_context"]
                     for side in ("source", "target")} - {node.id}
        for text in exp.related_texts:
            related = find_node_by_text(engine.brain, text)
            if related is None or related.id not in connected:
                failures.append(f"explanation missing connection: {text!r}")
    return failures


def verify_neighborhood(brain: Brain, expectations: list) -> list[str]:
    """Check neighborhood reachability against NeighborhoodExpectation entries.

    Degrades gracefully when graph_engine.graph does not exist: the gate test
    must fail for the RIGHT reason (expectation violation), never crash the
    harness with an ImportError (same trap as a missing no-op kwarg stub).
    """
    try:
        from .graph import neighbors
    except ImportError:
        return ["graph traversal not implemented (graph_engine/graph.py missing)"]
    failures: list[str] = []
    if not expectations:
        return failures
    for exp in expectations:
        node = find_node_by_text(brain, exp.node_text)
        if node is None:
            continue  # missing nodes already reported by verify_end_state
        # expected + absent in ONE call set: include_pending=True because the
        # harness verifies what the graph CONTAINS, not the review gate state.
        found = neighbors(brain, node.id, hops=exp.hops, include_pending=True,
                          limit=None)
        found_ids = {n.id for n in found}
        for want in exp.expected_neighbor_texts:
            w = find_node_by_text(brain, want)
            if w is None or w.id not in found_ids:
                failures.append(
                    f"neighborhood '{exp.node_text[:40]}': {want!r} not within "
                    f"{exp.hops} hops")
        for avoid in exp.absent_neighbor_texts:
            w = find_node_by_text(brain, avoid)
            if w is not None and w.id in found_ids:
                failures.append(
                    f"neighborhood '{exp.node_text[:40]}': {avoid!r} must NOT be "
                    f"within {exp.hops} hops")
    return failures


def verify_communities(brain: Brain, expectations: list) -> list[str]:
    """Check the final partition against CommunityExpectation entries.

    All three assertion families run together on purpose: `together` alone
    is trivially green if everything lands in one community, `apart` alone
    if every node is its own community, and `gap` alone if the analyzer
    reported every pair. Requires all three to hold.
    """
    from .communities import analyze_communities

    failures: list[str] = []
    if not expectations:
        return failures
    # One analysis per expectation list, min_size = the strictest requested.
    min_size = min(exp.min_size for exp in expectations)
    # top is generous on purpose: the verifier needs the COMPLETE gap list
    # (truncating to the CLI default could hide a pair the oracle asserts).
    rep = analyze_communities(brain, min_size=min_size, top=10_000,
                              include_pending=True, with_members=True)
    # Community membership lookup: id -> canonical community index.
    id2com: dict[str, int] = {}
    for c in rep.communities:
        for nid in c.members:
            id2com[nid] = c.id
    gap_pairs: set[tuple[int, int]] = {(g.a, g.b) for g in rep.gaps}

    def _resolve(text: str):
        node = find_node_by_text(brain, text)
        return node.id if node else None

    for exp in expectations:
        for group in exp.together:
            ids = [_resolve(t) for t in group]
            if any(i is None for i in ids):
                continue  # missing nodes already reported by verify_end_state
            coms = {id2com[i] for i in ids}
            if len(coms) != 1:
                failures.append(
                    f"together violated: {group!r} spans communities {sorted(coms)}")
        for a, b in exp.apart:
            ia, ib = _resolve(a), _resolve(b)
            if ia is None or ib is None:
                continue
            if id2com.get(ia) == id2com.get(ib):
                failures.append(
                    f"apart violated: {a!r} and {b!r} share community {id2com.get(ia)}")
        for a, b in exp.gap:
            ia, ib = _resolve(a), _resolve(b)
            if ia is None or ib is None:
                continue
            pair = (min(id2com.get(ia, -1), id2com.get(ib, -1)),
                    max(id2com.get(ia, -1), id2com.get(ib, -1)))
            if pair not in gap_pairs:
                failures.append(
                    f"gap not reported: {a!r} <-> {b!r} (communities {pair[0]}/{pair[1]})")
    return failures


# ---------------------------------------------------------------------------
# Runner (pass^k)
# ---------------------------------------------------------------------------

EngineFactory = Callable[[], BrainEngine]


def run_eval(task: EvalTask, engine_factory: EngineFactory, k: int = 1) -> EvalResult:
    """Run the task k times against a fresh brain; all runs must be green."""
    for run in range(1, k + 1):
        engine = engine_factory()
        if task.reranker is not None:
            engine.reranker = task.reranker
        for text, kwargs in task.ingests:
            engine.ingest(text, **kwargs)
        for action in task.actions:
            action(engine)
        failures = verify_end_state(engine.brain, task.oracle)
        failures += verify_retrieval(engine, task.oracle.retrieval)
        failures += verify_explanations(engine, task.oracle.explanations)
        failures += verify_communities(engine.brain, task.oracle.communities)
        failures += verify_neighborhood(engine.brain, task.oracle.neighborhoods)
        if failures:
            return EvalResult(task.id, task.name, False, failures, run)
    return EvalResult(task.id, task.name, True, [], k)


def run_tasks(tasks: list[EvalTask], engine_factory: EngineFactory, k: int = 1) -> list[EvalResult]:
    return [run_eval(t, engine_factory, k) for t in tasks]


def report(results: list[EvalResult]) -> tuple[int, list[EvalResult]]:
    """Returns (number green, all) — useful for CLI/logging."""
    failed = [r for r in results if not r.passed]
    return len(results) - len(failed), failed


# ---------------------------------------------------------------------------
# Golden set — regression on every engine change (MUST be green)
# ---------------------------------------------------------------------------

def _seed_episodic_consolidation(engine: BrainEngine) -> None:
    for _ in range(2):
        engine.observe("User requested brief replies", allow_duplicates=True,
                       observed_at="2000-01-01T00:00:00Z")
    engine.observe("A button was clicked", observed_at="2000-01-01T00:00:00Z")


def _consolidate_episodic(engine: BrainEngine) -> None:
    from .consolidation import ConsolidationConfig, consolidate
    consolidate(engine.brain, config=ConsolidationConfig(),
                extractor=lambda evidence: "User prefers concise answers")


def _dream_lifecycle() -> Callable[[BrainEngine], None]:
    """Test action: the lifecycle pass under the case's gates."""
    def action(engine: BrainEngine) -> None:
        from .dream import lifecycle
        lifecycle(engine.brain, min_recall=1, min_degree=2, stale_days=0,
                  max_degree=2)
    return action


def _record_recall(query: str, texts: list[str]) -> Callable[[BrainEngine], None]:
    """Test action: record a recall of the given nodes (the promotion signal)."""
    def action(engine: BrainEngine) -> None:
        from .recall import record
        ids = [n.id for n in engine.brain.read_nodes()
               if n.text.strip() in {t.strip() for t in texts}]
        record(engine.brain, query, ids)
    return action


def _agent_remember(text: str, relation_target: str | None = None) -> Callable[[BrainEngine], None]:
    """Test action: an agent writes a note (Welle C write path)."""
    def action(engine: BrainEngine) -> None:
        from .agent_memory import remember
        relations = [(relation_target, "extends")] if relation_target else None
        remember(engine, text, relations=relations)
    return action


def _agent_forget(text: str, reason: str) -> Callable[[BrainEngine], None]:
    """Test action: an agent forgets a node — tombstoned, never deleted."""
    def action(engine: BrainEngine) -> None:
        from .agent_memory import forget
        node = find_node_by_text(engine.brain, text)
        if node is not None:
            forget(engine.brain, node.id, reason=reason)
    return action


def _link_same_as(source_text: str, target_text: str) -> Callable[[BrainEngine], None]:
    def action(engine: BrainEngine) -> None:
        s = find_node_by_text(engine.brain, source_text)
        t = find_node_by_text(engine.brain, target_text)
        if s and t:
            engine.link(s.id, t.id, "same_as")
    return action


def _force_kind(source_text: str, target_text: str, kind: str) -> Callable[[BrainEngine], None]:
    """Test action: rewrite the kind of an existing similarity edge.

    Simulates drift/legacy data (an edge whose kind no longer matches the band
    rule its cosine implies) so `dream.refresh()` has something to re-derive.
    """
    def action(engine: BrainEngine) -> None:
        s = find_node_by_text(engine.brain, source_text)
        t = find_node_by_text(engine.brain, target_text)
        if not s or not t:
            return
        edges = engine.brain.read_edges(include_rejected=True)
        for edge in edges:
            if ({edge.source, edge.target} == {s.id, t.id}
                    and edge.kind in ("extends", "similar")):
                edge.kind = kind
        engine.brain.write_edges(edges)
    return action


def _dream_distill(engine: BrainEngine) -> None:
    from .dream import distill
    distill(engine.brain, min_size=2, limit=5, members_per_summary=3)


def _dream_refresh(engine: BrainEngine) -> None:
    from .dream import refresh
    refresh(engine.brain)


GOLDEN_SET: list[EvalTask] = [
    EvalTask(
        id="dup-exact",
        name="exact duplicate gets merged (sources accumulate)",
        ingests=[
            ("Katzen jagen Maeuse nachts", {"source": "agent/test"}),
            ("Katzen jagen Maeuse nachts", {"source": "human"}),
        ],
        oracle=EvalOracle(
            node_count=1,
            duplicate_merged=[("Katzen jagen Maeuse nachts", ["agent/test", "human"])],
        ),
    ),
    EvalTask(
        id="dup-case-whitespace",
        name="duplicate merged regardless of case + whitespace",
        ingests=[
            ("Katzen jagen Maeuse nachts", {"source": "a"}),
            ("  katzen JAGEN maeuse   NACHTS ", {"source": "b"}),
        ],
        oracle=EvalOracle(node_count=1, duplicate_merged=[("katzen jagen maeuse nachts", ["a", "b"])]),
    ),
    EvalTask(
        id="retrieval-explain",
        name="Retrieval explanations reconstruct scores and show accepted graph context",
        ingests=[("alpha beta", {}), ("alpha gamma", {}), ("omega psi", {})],
        actions=[_link_same_as("alpha beta", "alpha gamma")],
        oracle=EvalOracle(explanations=[
            ExplanationExpectation(query="alpha", node_text="alpha beta",
                                   related_texts=["alpha gamma"]),
            ExplanationExpectation(query="alpha", node_text="omega psi", retrieved=False),
        ]),
    ),
    EvalTask(
        id="dup-disabled",
        name="allow_duplicates=True creates a second node",
        ingests=[
            ("Katzen jagen Maeuse nachts", {}),
            ("Katzen jagen Maeuse nachts", {"allow_duplicates": True}),
        ],
        oracle=EvalOracle(node_count=2),
    ),
    EvalTask(
        id="no-false-positive",
        name="unrelated texts are not deduplicated",
        ingests=[
            ("Katzen jagen Maeuse nachts", {}),
            ("Rust Compiler borrow checker lifetime Regeln", {}),
        ],
        oracle=EvalOracle(node_count=2, nodes_present=[
            "Katzen jagen Maeuse nachts",
            "Rust Compiler borrow checker lifetime Regeln",
        ]),
    ),
    EvalTask(
        id="edge-similar",
        name="similar nodes get connected by an edge (pending <0.95)",
        ingests=[
            ("katze hund tier futter", {}),
            ("katze hund tier spiel", {}),
        ],
        oracle=EvalOracle(
            node_count=2,
            edges=[EdgeExpectation("katze hund tier futter", "katze hund tier spiel", "*", pending=True)],
        ),
    ),
    EvalTask(
        id="conf-auto-accept",
        name="V2: Confidence >=0.95 → edge auto-accepted (pending=False)",
        ingests=[
            ("x x x x x y y y y y z z z z z", {}),
            ("x x x x x y y y y y z z z z w", {"allow_duplicates": True}),
        ],
        oracle=EvalOracle(
            node_count=2,
            edges=[EdgeExpectation(
                "x x x x x y y y y y z z z z z",
                "x x x x x y y y y y z z z z w",
                "*", pending=False, min_confidence=0.95,
            )],
        ),
    ),
    EvalTask(
        id="edge-no-false-link",
        name="unrelated nodes are NOT connected",
        ingests=[
            ("katze hund tier futter", {}),
            ("quantenmechanik wellenfunktion schroedinger", {}),
        ],
        oracle=EvalOracle(
            node_count=2,
            no_edge=[EdgeExpectation("katze hund tier futter", "quantenmechanik wellenfunktion schroedinger", "*")],
        ),
    ),
    EvalTask(
        id="retrieval-hybrid",
        name="V2: hybrid retrieval finds the matching node, not unrelated ones",
        ingests=[
            ("katze hund tier futter", {}),
            ("quantenmechanik wellenfunktion schroedinger", {}),
        ],
        oracle=EvalOracle(
            node_count=2,
            retrieval=[RetrievalExpectation(
                query="katze futter",
                top=1,
                includes=["katze hund tier futter"],
                excludes=["quantenmechanik wellenfunktion schroedinger"],
            )],
        ),
    ),
    EvalTask(
        id="retrieval-rerank-honored",
        name="V2: rerank pass decides the final ranking (cross-encoder pipeline)",
        ingests=[
            ("aaa bbb ccc", {}),
            ("ddd eee fff", {}),
        ],
        oracle=EvalOracle(
            node_count=2,
            retrieval=[RetrievalExpectation(
                query="ddd eee fff",
                top=1,
                includes=["aaa bbb ccc"],
                excludes=["ddd eee fff"],
            )],
        ),
        # ReverseReranker is the deterministic stand-in for a cross-encoder:
        # hybrid would rank "ddd eee fff" first; the rerank pass reverses that.
        # Green only if retrieve() actually honors the reranker.
        reranker=ReverseReranker(),
    ),
    EvalTask(
        id="taxonomy-procedural",
        name="procedural node carries type=procedural",
        ingests=[
            ("Wie ingestiere ich Research: ig ingest ...", {"ntype": "procedural"}),
        ],
        oracle=EvalOracle(node_count=1, nodes_present=["Wie ingestiere ich Research: ig ingest ..."]),
    ),
    EvalTask(
        id="same-as-multilingual",
        name="multilingual pair connected via manual same_as link",
        ingests=[
            ("Katzen jagen Maeuse", {}),
            ("Cats hunt mice", {"allow_duplicates": True}),
        ],
        actions=[_link_same_as("Katzen jagen Maeuse", "Cats hunt mice")],
        oracle=EvalOracle(
            node_count=2,
            edges=[EdgeExpectation("Katzen jagen Maeuse", "Cats hunt mice", "same_as")],
        ),
    ),
    EvalTask(
        id="hygiene-promote",
        name="V2: dual buffer — consolidation promotes probation nodes to active",
        ingests=[
            ("katze hund tier futter", {}),
            ("quantenmechanik wellenfunktion schroedinger", {}),
        ],
        actions=[lambda e: e.consolidate()],
        oracle=EvalOracle(
            node_count=2,
            node_status={
                "katze hund tier futter": "active",
                "quantenmechanik wellenfunktion schroedinger": "active",
            },
        ),
    ),
    EvalTask(
        id="hygiene-demote",
        name="V2: graceful degradation — unused node gets tombstoned",
        ingests=[
            ("katze hund tier futter", {}),
            ("quantenmechanik wellenfunktion schroedinger", {}),
        ],
        actions=[
            lambda e: e.consolidate(),
            lambda e: e.demote_forgotten(
                lambda n: "tombstone" if "katze" in n.text else "record"
            ),
        ],
        oracle=EvalOracle(
            node_count=2,
            node_status={
                "katze hund tier futter": "tombstone",
                "quantenmechanik wellenfunktion schroedinger": "active",
            },
        ),
    ),
    EvalTask(
        id="intent-contradiction",
        name="V2: contradictory statement -> 'contradicts' edge auto-detected",
        ingests=[
            ("Die Erde ist eine Scheibe", {}),
            ("Die Erde ist keine Scheibe", {}),
        ],
        oracle=EvalOracle(
            node_count=2,
            edges=[EdgeExpectation("Die Erde ist eine Scheibe", "Die Erde ist keine Scheibe", "contradicts")],
        ),
    ),
    EvalTask(
        id="intent-supersedes",
        name="V2: newer statement supersedes older → 'supersedes' edge",
        ingests=[
            ("API v1 wird verwendet", {}),
            ("API v2 ersetzt v1", {}),
        ],
        oracle=EvalOracle(
            node_count=2,
            edges=[EdgeExpectation("API v1 wird verwendet", "API v2 ersetzt v1", "supersedes")],
        ),
    ),
    EvalTask(
        id="admit-rule-no-relations",
        name="V2: admit rule — node without relations stays in probation (admit_required)",
        ingests=[
            ("xyzvw abcdefgh ijklmnop", {}),
        ],
        actions=[lambda e: e.consolidate(admit_required=True)],
        oracle=EvalOracle(
            node_count=1,
            node_status={"xyzvw abcdefgh ijklmnop": "probation"},
        ),
    ),
    EvalTask(
        id="admit-rule-with-relations",
        name="V2: admit rule — node WITH declared relations becomes active",
        ingests=[
            ("aaa bbb ccc", {}),
            ("aaa bbb ccc ddd", {"allow_duplicates": True,
                                 "relations": [("aaa bbb ccc", "extends")]}),
        ],
        actions=[lambda e: e.consolidate(admit_required=True)],
        oracle=EvalOracle(
            node_count=2,
            node_status={
                "aaa bbb ccc": "active",
                "aaa bbb ccc ddd": "active",
            },
        ),
    ),
    # GOLDEN (flip 2026-09-10, was `roadmap-confidence-floor`) — Tier-3 self-extension:
    # configurable confidence floor for auto edge suggestions (per-call env kwarg,
    # IG_EDGE_CONF_FLOOR, default 0.0 = no behavior change). Suggestions below the
    # floor are dropped instead of landing pending — protects autonomous cycles
    # from a flood of low-confidence edges. (HashEmbedder measurement: the two
    # texts sit at cos≈0.653 → pending band 0.45–0.95, below floor 0.95.)
    EvalTask(
        id="roadmap-confidence-floor",
        name="Confidence floor rejects weak auto edge suggestions",
        ingests=[
            ("Agentenplanung zerlegt langfristige Aufgaben in hierarchische "
             "Teilziele und prueft Zwischenergebnisse gegen den Zielzustand.", {}),
            ("Agentenplanung in Multi-Agent-Systemen verteilt hierarchische "
             "Teilziele und prueft Zwischenergebnisse gegenseitig.",
             {"env": {"IG_EDGE_CONF_FLOOR": "0.95"}}),
        ],
        oracle=EvalOracle(
            node_count=2,
            # With floor: the 0.653 suggestion is rejected (no similar edge).
            edges=[],
            no_edge=[EdgeExpectation(
                source="Agentenplanung in Multi-Agent-Systemen verteilt",
                target="Agentenplanung zerlegt langfristige Aufgaben",
                kind="similar")],
        ),
    ),

    # Report #3 (2026-09-15): topology communities — two topical clusters form
    # two communities with a structural gap. Registered RED, implemented, then
    # flipped (pass^3 + full suite green).
    EvalTask(
        id="roadmap-communities-two-clusters",
        name="Topology: two topical clusters form two communities with a structural gap",
        ingests=[
            ("alpha beta gamma delta", {}),
            ("alpha beta gamma epsilon", {}),
            ("alpha beta gamma zeta", {}),
            ("omega psi chi phi", {}),
            ("omega psi chi kappa", {}),
            ("omega psi chi lambda", {}),
        ],
        oracle=EvalOracle(
            node_count=6,
            communities=[CommunityExpectation(
                together=[
                    ["alpha beta gamma delta", "alpha beta gamma epsilon",
                     "alpha beta gamma zeta"],
                    ["omega psi chi phi", "omega psi chi kappa",
                     "omega psi chi lambda"],
                ],
                apart=[("alpha beta gamma delta", "omega psi chi phi")],
                gap=[("alpha beta gamma delta", "omega psi chi phi")],
                min_size=2,
            )],
        ),
    ),
    # Report #7 (2026-09-15): BRAIN_REPORT digest renders non-empty, sectioned,
    # content-asserted output. Registered RED, implemented, then flipped.
    EvalTask(
        id="roadmap-brain-report",
        name="BRAIN_REPORT renders non-empty, sectioned, content-asserted output",
        ingests=[
            ("Die Erde ist eine Scheibe", {}),
            ("Die Erde ist keine Scheibe", {}),
        ],
        oracle=EvalOracle(
            node_count=2,
            report_contains=["BRAIN_REPORT", "Intent review queue",
                             "Die Erde ist eine Scheibe"],
        ),
    ),
    # Report #1 (2026-09-15): graph traversal over live edges (flipped). MEASURED under
    # HashEmbedder: the three agent-memory texts sit at cos 0.875/0.875/0.75
    # (similar/similar/extends — inside the 0.75/0.45 bands), the gardening
    # text at 0.13-0.27 (no edges). The MCP surface itself is a read-only
    # projection and CANNOT be an EvalTask (the harness verifies brain
    # end-state only) — same judgement as Late Chunking above; traversal is
    # the measurable new capability underneath it.
    EvalTask(
        id="roadmap-neighbors",
        name="graph traversal reaches hub neighbors at hop 1, isolates stay out",
        ingests=[
            ("agent memory systems store knowledge graphs for retrieval", {}),
            ("agent memory systems store knowledge graphs for retrieval and search", {}),
            ("agent memory systems store knowledge graphs for retrieval but slower", {}),
            ("unrelated note about gardening tomatoes and weather", {}),
        ],
        oracle=EvalOracle(
            node_count=4,
            neighborhoods=[
                NeighborhoodExpectation(
                    node_text="agent memory systems store knowledge graphs for retrieval",
                    expected_neighbor_texts=[
                        "agent memory systems store knowledge graphs for retrieval and search",
                        "agent memory systems store knowledge graphs for retrieval but slower",
                    ],
                    absent_neighbor_texts=[
                        "unrelated note about gardening tomatoes and weather",
                    ],
                    hops=1,
                ),
            ],
        ),
    ),
    # Intent fan-out dam (2026-09-18): registered RED, implemented, flipped.
    # Intent edges carry confidence=None, so the confidence bands can never
    # judge them; the marker heuristic is their only producer and mass-fires in
    # a homogeneous brain — live measurement before the dam: 168 intent edges
    # ever created, 66 invalidated again (39 % false), one source holding 10
    # auto-accepted `contradicts`, 26 false edges added in one cycle.
    # MEASURED fixture (HashEmbedder, real engine path): the marker text fires 6
    # `supersedes` edges at cos 0.866/0.722 (threshold 0.45) and the maximum
    # pairwise cosine is 0.866 < dedupe 0.92, so the case fails on the CAP, not
    # on a missing edge.
    EvalTask(
        id="roadmap-intent-fanout-cap",
        name="Intent edges: auto-accepted fan-out per source is capped, the rest stay pending",
        ingests=[
            ("alpha beta gamma delta training pipeline", {}),
            ("alpha beta gamma epsilon training pipeline", {}),
            ("alpha beta gamma zeta training pipeline", {}),
            ("alpha beta gamma eta training pipeline", {}),
            ("alpha beta gamma theta training pipeline", {}),
            ("alpha beta gamma iota training pipeline", {}),
            ("alpha beta gamma kappa training pipeline ersetzt delta", {}),
        ],
        oracle=EvalOracle(
            node_count=7,
            max_auto_intent_per_source=2,
        ),
    ),
    # Welle A (2026-09-18): the two signals the consolidation half of a memory
    # system runs on — registered RED, implemented, flipped in one session.
    # `roadmap-edge-origin`: a maintenance pass may rewrite heuristic edges but
    # never user-authored ones, so the provenance has to be stored, not inferred
    # from the text (the 96-edge backlog cleanup was exactly that inference by
    # hand). `roadmap-recall-tracking`: promotion/decay needs actual use —
    # recall_count + distinct query fingerprints, folded from a local ledger so
    # the read path stays cheap and git-clean.
    EvalTask(
        id="roadmap-edge-origin",
        name="Edges carry their provenance: suggester kNN vs manual link",
        ingests=[
            ("agent memory systems store knowledge graphs for retrieval", {}),
            ("agent memory systems store knowledge graphs for retrieval and search", {}),
            ("Retrieval-Augmented Generation connects a model to external documents", {}),
            ("Graph RAG combines vector search with multi-hop traversal", {}),
        ],
        actions=[_link_same_as(
            "Retrieval-Augmented Generation connects a model to external documents",
            "Graph RAG combines vector search with multi-hop traversal")],
        oracle=EvalOracle(
            node_count=4,
            edges=[
                # MEASURED (neighbors fixture): these two sit at cos 0.875, i.e.
                # the `similar` band — the suggester produces the edge.
                EdgeExpectation(
                    source="agent memory systems store knowledge graphs for retrieval and search",
                    target="agent memory systems store knowledge graphs for retrieval",
                    kind="similar", origin="suggester"),
                EdgeExpectation(
                    source="Retrieval-Augmented Generation connects a model to external documents",
                    target="Graph RAG combines vector search with multi-hop traversal",
                    kind="same_as", origin="manual"),
            ],
        ),
    ),
    EvalTask(
        id="roadmap-recall-tracking",
        name="Recall tracking: retrieved nodes carry recall counts, untouched ones stay at 0",
        ingests=[
            ("alpha beta gamma delta training pipeline", {}),
            ("omega psi chi phi gardening tomatoes", {}),
        ],
        actions=[
            lambda e: retrieve(e, "alpha beta gamma delta training pipeline", k=1, track=True),
            lambda e: retrieve(e, "alpha beta gamma delta training", k=1, track=True),
            lambda e: aggregate_recalls(e.brain),
        ],
        oracle=EvalOracle(
            node_count=2,
            node_recalls={
                "alpha beta gamma delta training pipeline": 2,
                "omega psi chi phi gardening tomatoes": 0,
            },
        ),
    ),
    # Welle B (2026-09-18): the consolidation half — the dream pass. Measured
    # before building: recall-gated promotion had 0 eligible nodes, a degree gate
    # >= 3 matched 99 % of nodes, the corpus was 27 days old (so no staleness
    # gate can fire), and the 97 near-dup pairs in the review band are
    # demonstrably related-but-distinct — so promotion/decay/auto-merge are NOT
    # part of the pass yet. What IS measurable today: the deterministic refresh
    # and the distillation of communities (30 communities >= 10 nodes cover 94 %
    # of the live brain).
    EvalTask(
        id="roadmap-dream-refresh",
        name="Dream refresh re-derives drifted suggester kinds, leaves manual edges alone",
        ingests=[
            ("agent memory systems store knowledge graphs for retrieval", {}),
            ("agent memory systems store knowledge graphs for retrieval and search", {}),
            ("Retrieval-Augmented Generation connects a model to external documents", {}),
            ("Graph RAG combines vector search with multi-hop traversal", {}),
            # 5th ingest declares a relation explicitly -> origin="manual". Its
            # cosine is in the `similar` band, so a pass that ignored provenance
            # would "correct" a user-authored edge.
            ("agent memory systems store knowledge graphs for retrieval and ranking",
             {"relations": [("agent memory systems store knowledge graphs for retrieval",
                             "extends")]}),
        ],
        actions=[
            # drift the suggester edge (cos 0.875 => must be `similar` again)
            _force_kind("agent memory systems store knowledge graphs for retrieval and search",
                        "agent memory systems store knowledge graphs for retrieval",
                        "extends"),
            _dream_refresh,
        ],
        oracle=EvalOracle(
            node_count=5,
            edges=[
                EdgeExpectation(
                    source="agent memory systems store knowledge graphs for retrieval and search",
                    target="agent memory systems store knowledge graphs for retrieval",
                    kind="similar", origin="suggester"),
                EdgeExpectation(
                    source="agent memory systems store knowledge graphs for retrieval and ranking",
                    target="agent memory systems store knowledge graphs for retrieval",
                    kind="extends", origin="manual"),
            ],
        ),
    ),
    EvalTask(
        id="roadmap-dream-distill",
        name="Dream pass distills each community into one consolidator summary node",
        ingests=[
            ("alpha beta gamma delta", {}),
            ("alpha beta gamma epsilon", {}),
            ("alpha beta gamma zeta", {}),
            ("omega psi chi phi", {}),
            ("omega psi chi kappa", {}),
            ("omega psi chi lambda", {}),
        ],
        actions=[_dream_distill],
        oracle=EvalOracle(
            # 6 members + 2 summary nodes (one per cluster)
            node_count=8,
            # 2 summaries x 3 members, all `origin="consolidator"`
            min_edges_by_origin={"consolidator": 6},
        ),
    ),
    # Welle C (2026-09-18): the agent-facing write path. An agent that consults
    # the brain must be able to leave something in it — under its own provenance
    # (`source="agent"` / `origin="agent"`), never destructively (`forget`
    # tombstones and invalidates, it never deletes), and only when the operator
    # opts in (`ig mcp --write`; the MCP default stays read-only).
    EvalTask(
        id="roadmap-agent-memory",
        name="Agent write path: remember marks provenance, forget tombstones without deleting",
        ingests=[
            ("alpha beta gamma delta", {}),
            ("omega psi chi phi", {}),
        ],
        actions=[
            _agent_remember("a note an agent decided to keep", "alpha beta gamma delta"),
            _agent_forget("omega psi chi phi", reason="superseded by the newer note"),
        ],
        oracle=EvalOracle(
            # 2 ingests + 1 remembered; the forgotten node is NEVER deleted
            node_count=3,
            nodes_present=["a note an agent decided to keep", "omega psi chi phi"],
            node_status={"omega psi chi phi": "tombstone"},
            # the agent-declared relation carries agent provenance
            min_edges_by_origin={"agent": 1},
        ),
    ),
    # Welle B/2 (2026-09-18): the status lifecycle — promotion and decay driven by
    # the recall signal. Gates are data-derived (see graph_engine/dream.py): the
    # case pins them explicitly so it stays readable.
    EvalTask(
        id="roadmap-dream-lifecycle",
        name="Lifecycle pass promotes what is used, demotes what is not, deletes nothing",
        ingests=[
            ("alpha beta gamma delta", {}),
            ("omega psi chi phi", {}),
            ("kappa lambda my tau", {}),
        ],
        actions=[
            _link_same_as("alpha beta gamma delta", "omega psi chi phi"),
            _link_same_as("alpha beta gamma delta", "kappa lambda my tau"),
            # alpha (degree 2) and kappa (degree 1) are recalled; omega is not
            _record_recall("what is used", ["alpha beta gamma delta", "kappa lambda my tau"]),
            _dream_refresh,            # folds the ledger into recall_count
            # stale_days=0 so the decay gate can fire on a fresh fixture — the
            # live default is 30 days (a month of silence).
            _dream_lifecycle(),
        ],
        oracle=EvalOracle(
            # nothing is ever deleted, not even a demoted node
            node_count=3,
            node_status={
                "alpha beta gamma delta": "active",     # used + connected
                "omega psi chi phi": "stale",           # unused + weak + old
                "kappa lambda my tau": "probation",     # used, but not connected
            },
        ),
    ),
    EvalTask(
        id="episodic-auto-consolidation",
        name="Used episodes yield one semantic fact with both sources; repeats do no work",
        ingests=[],
        actions=[
            _seed_episodic_consolidation,
            _record_recall("reply preferences", ["User requested brief replies"]),
            _dream_refresh,
            _consolidate_episodic,
            _consolidate_episodic,
        ],
        oracle=EvalOracle(
            node_count=4,
            nodes_present=["User requested brief replies", "User prefers concise answers",
                           "A button was clicked"],
            node_status={"User prefers concise answers": "probation"},
            edges=[EdgeExpectation("User prefers concise answers",
                                   "User requested brief replies", "extends", pending=False)],
            no_edge=[EdgeExpectation("User prefers concise answers", "A button was clicked", "*")],
            min_edges_by_origin={"consolidator": 2},
        ),
    ),

]



# ---------------------------------------------------------------------------
# Roadmap cases — desired future behavior (turns green once implemented)
# ---------------------------------------------------------------------------

ROADMAP_CASES: list[EvalTask] = [
    # Admit-rule enforcement (V2#3) is implemented → GOLDEN_SET
    # (`admit-rule-no-relations`, `admit-rule-with-relations`).
    # Late chunking (V2#1) deliberately stays NO eval case: as long as there is
    # no real chunking layer (the engine embeds the whole node text), it cannot
    # be specified as an end-state oracle — a case would either turn
    # spuriously green (whole-text embedding satisfies it trivially) or red
    # for the wrong reasons. So it remains a documented roadmap note, not a case.
    #
    # Cross-encoder reranking (V2#1) is implemented → GOLDEN_SET
    # (`retrieval-rerank-honored`).
]

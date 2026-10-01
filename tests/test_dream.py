"""Tests for the dream pass (`graph_engine/dream.py`, `ig dream`).

The consolidation half of the memory system: deterministic maintenance
(`refresh`) and community distillation (`distill`). Both must be non-destructive,
must never touch user-authored edges (`origin="manual"`), and must be idempotent
so a scheduled pass cannot duplicate work.

What is deliberately NOT here: promotion/decay gates and auto-merge. Measured on
the live brain before building: recall-gated promotion had 0 eligible nodes, a
degree gate >= 3 matched 99 % of nodes, the corpus was 27 days old, and the 97
near-dup pairs in the review band are demonstrably related-but-distinct.
"""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.brain import Brain, Edge, Node
from graph_engine.dream import (
    DECAY_DAYS,
    DECAY_MAX_DEGREE,
    PROMOTE_MIN_DEGREE,
    PROMOTE_MIN_RECALL,
    STALE_STATUS,
    SUMMARY_TAG,
    distill,
    lifecycle,
    lifecycle_plan,
    node_age_days,
    plan,
    refresh,
    refresh_plan,
)
from graph_engine.recall import record


def _brain(tmp_path) -> Brain:
    return Brain(str(tmp_path / "brain"), mode="local")


def _node(b: Brain, nid: str, *, status: str = "probation", recalls: int = 0,
          days_old: float = 0.0, tags: list[str] | None = None) -> Node:
    created = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%SZ")
    node = Node(id=nid, text=f"node {nid}", status=status, tags=tags,
                created=created, recall_count=recalls)
    b.write_node(node)
    return node


def _edge(eid: str, src: str, tgt: str) -> Edge:
    return Edge(id=eid, source=src, target=tgt, kind="extends", pending=False,
                origin="suggester", confidence=0.7)


def _two_clusters(b: Brain) -> None:
    """Six nodes in two dense triples — LPA finds two communities."""
    for i in range(3):
        b.write_node(Node(id=f"a{i}", text=f"alpha cluster node {i}"))
        b.write_node(Node(id=f"b{i}", text=f"omega cluster node {i}"))
    edges = []
    for i in range(3):
        for j in range(i + 1, 3):
            edges.append(Edge(id=f"a{i}{j}", source=f"a{i}", target=f"a{j}",
                              kind="extends", pending=False, origin="suggester",
                              confidence=0.7))
            edges.append(Edge(id=f"b{i}{j}", source=f"b{i}", target=f"b{j}",
                              kind="extends", pending=False, origin="suggester",
                              confidence=0.7))
    b.write_edges(edges)


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

def test_plan_reports_and_writes_nothing(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)
    before_nodes = sorted(n.id for n in b.read_nodes())
    before_edges = len(b.read_edges(include_rejected=True))

    result = plan(b, min_community=2)

    assert result.nodes == 6
    assert len(result.distill_candidates) == 2
    assert sorted(n.id for n in b.read_nodes()) == before_nodes
    assert len(b.read_edges(include_rejected=True)) == before_edges
    assert "DREAM PLAN" in result.render()
    assert "Nothing written" in result.render() or "dry run" in result.render()


def test_plan_promotion_needs_recall_and_degree(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)
    # a0 has degree 2 and no recalls -> not eligible under min_degree=2/min_recall=1
    assert plan(b, min_recall=1, min_degree=2, min_community=2).promotion_candidates == []

    record(b, "q", ["a0"])
    refresh(b)
    assert plan(b, min_recall=1, min_degree=2, min_community=2).promotion_candidates == ["a0"]


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------

def test_refresh_rederives_drifted_suggester_kind(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    b.write_node(Node(id="b", text="Thema B"))
    b.write_edges([
        Edge(id="s1", source="a", target="b", kind="extends", pending=False,
             confidence=0.9, origin="suggester"),      # drifted: 0.9 means `similar`
        Edge(id="m1", source="b", target="a", kind="extends", pending=False,
             confidence=0.9, origin="manual"),         # user-authored: untouchable
    ])

    res = refresh(b)

    assert res["kind_changes"] == 1
    kinds = {e.id: e.kind for e in b.read_edges()}
    assert kinds["s1"] == "similar"
    assert kinds["m1"] == "extends", "manual edges are never rewritten"


def test_refresh_is_idempotent(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    b.write_node(Node(id="b", text="Thema B"))
    b.write_edges([Edge(id="s1", source="a", target="b", kind="extends", pending=False,
                        confidence=0.9, origin="suggester")])

    assert refresh(b)["kind_changes"] == 1
    assert refresh(b)["kind_changes"] == 0


def test_refresh_folds_the_recall_ledger(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    record(b, "frage", ["a"])

    res = refresh(b)

    assert res["recalls"] == 1 and res["recall_nodes"] == 1
    assert {n.id: n.recall_count for n in b.read_nodes()}["a"] == 1


def test_refresh_dry_run_writes_nothing(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    b.write_node(Node(id="b", text="Thema B"))
    b.write_edges([Edge(id="s1", source="a", target="b", kind="extends", pending=False,
                        confidence=0.9, origin="suggester")])

    res = refresh(b, dry_run=True)

    assert res["kind_changes"] == 1, "a dry run reports what it WOULD change"
    assert {e.id: e.kind for e in b.read_edges()}["s1"] == "extends", "and writes nothing"


def test_refresh_plan_counts_mismatches(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    b.write_node(Node(id="b", text="Thema B"))
    b.write_edges([Edge(id="s1", source="a", target="b", kind="extends", pending=False,
                        confidence=0.9, origin="suggester")])

    assert refresh_plan(b)["kind_mismatches"] == 1


# ---------------------------------------------------------------------------
# distill
# ---------------------------------------------------------------------------

def test_distill_writes_one_summary_per_community(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)

    res = distill(b, min_size=2, members_per_summary=2)

    assert res["summaries"] == 2 and res["edges"] == 4
    summaries = [n for n in b.read_nodes() if SUMMARY_TAG in (n.tags or [])]
    assert len(summaries) == 2
    for node in summaries:
        assert node.status == "active"
        assert "Community abstraction" in node.text
        assert "consolidator summary" in node.text
    consolidator = [e for e in b.read_edges() if e.origin == "consolidator"]
    assert len(consolidator) == 4
    assert all(e.kind == "extends" and not e.pending for e in consolidator)
    # every summary points at real members of its own community
    ids = {n.id for n in summaries}
    for edge in consolidator:
        assert edge.source in ids and edge.target not in ids


def test_distill_is_idempotent(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)

    first = distill(b, min_size=2, members_per_summary=2)
    second = distill(b, min_size=2, members_per_summary=2)

    assert first["summaries"] == 2
    assert second["summaries"] == 0 and second["edges"] == 0
    assert len([n for n in b.read_nodes() if SUMMARY_TAG in (n.tags or [])]) == 2


def test_distill_respects_min_size_and_limit(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)

    assert distill(b, min_size=4)["summaries"] == 0
    assert distill(b, min_size=2, limit=1)["summaries"] == 1


def test_distill_dry_run_writes_nothing(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)

    res = distill(b, min_size=2, dry_run=True)

    assert res["summaries"] == 2 and res["edges"] == 0
    assert [n for n in b.read_nodes() if SUMMARY_TAG in (n.tags or [])] == []


def test_distill_uses_the_summarizer_seam(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)
    seen = []

    def fake_llm(digest: str) -> str:
        seen.append(digest)
        return "MODEL SUMMARY: " + digest.splitlines()[0]

    res = distill(b, min_size=2, members_per_summary=2, summarizer=fake_llm)

    assert res["used_llm"] is True and res["summaries"] == 2
    assert len(seen) == 2, "the model sees the same extractive evidence"
    texts = [n.text for n in b.read_nodes() if SUMMARY_TAG in (n.tags or [])]
    assert all(t.startswith("MODEL SUMMARY: Community abstraction") for t in texts)


def test_distill_commits_once_per_pass(tmp_path, monkeypatch):
    b = _brain(tmp_path)
    _two_clusters(b)
    calls = []
    monkeypatch.setattr(b, "commit_and_push",
                        lambda message, push=True: calls.append(message))

    distill(b, min_size=2, members_per_summary=2)

    assert len(calls) == 1 and "2 community summaries" in calls[0]


# ---------------------------------------------------------------------------
# lifecycle (promotion / decay)
# ---------------------------------------------------------------------------

def test_lifecycle_promotes_used_and_connected(tmp_path):
    b = _brain(tmp_path)
    _node(b, "used", recalls=1)
    _node(b, "quiet")
    _node(b, "lonely", recalls=1)          # recalled but not connected
    b.write_edges([_edge("e1", "used", "quiet"), _edge("e2", "used", "lonely")])

    res = lifecycle(b, min_recall=1, min_degree=2, stale_days=30)

    status = {n.id: n.status for n in b.read_nodes()}
    assert res["promoted"] == 1
    assert status["used"] == "active", "used + degree 2"
    assert status["quiet"] == "probation", "30 days not reached yet"
    assert status["lonely"] == "probation", "recalled but degree 1 < 2"


def test_lifecycle_decays_unused_weak_and_old(tmp_path):
    b = _brain(tmp_path)
    _node(b, "old", days_old=DECAY_DAYS + 1)
    _node(b, "fresh")
    _node(b, "hub", days_old=DECAY_DAYS + 1)
    _node(b, "talked", days_old=DECAY_DAYS + 1, recalls=2)
    # hub has degree 4 -> above the decay ceiling
    b.write_edges([_edge("e1", "hub", "old"), _edge("e2", "hub", "fresh"),
                   _edge("e3", "hub", "talked"), _edge("e4", "hub", "x0")])
    _node(b, "x0")

    res = lifecycle(b, min_recall=1, min_degree=2, stale_days=DECAY_DAYS,
                    max_degree=DECAY_MAX_DEGREE)

    status = {n.id: n.status for n in b.read_nodes()}
    assert res["staled"] == 1
    assert status["old"] == STALE_STATUS, "unused + weak + old"
    assert status["fresh"] == "probation", "too young to decay"
    assert status["hub"] == "probation", "degree above the ceiling"
    assert status["talked"] == "probation", "recalled -> never decayed"


def test_lifecycle_never_deletes_and_keeps_files(tmp_path):
    b = _brain(tmp_path)
    _node(b, "old", days_old=90)
    path = b.node_path("old")
    before = len(b.read_nodes())

    lifecycle(b, stale_days=30)

    assert b.node_path("old").exists() and path.exists()
    assert len(b.read_nodes()) == before


def test_lifecycle_revives_a_stale_node_that_is_used_again(tmp_path):
    b = _brain(tmp_path)
    _node(b, "stale_one", status=STALE_STATUS, recalls=1)
    _node(b, "other")
    b.write_edges([_edge("e1", "stale_one", "other"), _edge("e2", "stale_one", "x")])

    res = lifecycle(b, min_recall=1, min_degree=2)

    assert res["revived"] == 1 and res["promoted"] == 0
    assert {n.id: n.status for n in b.read_nodes()}["stale_one"] == "active"


def test_lifecycle_never_regrades_summaries(tmp_path):
    """A pass must not demote the nodes a pass wrote."""
    b = _brain(tmp_path)
    _node(b, "summary", status="active", days_old=90, tags=[SUMMARY_TAG])

    res = lifecycle(b, stale_days=30)

    assert res["staled"] == 0
    assert {n.id: n.status for n in b.read_nodes()}["summary"] == "active"


def test_lifecycle_dry_run_writes_nothing(tmp_path):
    b = _brain(tmp_path)
    _node(b, "used", recalls=1)
    _node(b, "old", days_old=90)

    res = lifecycle(b, min_recall=1, min_degree=0, stale_days=30, dry_run=True)

    assert res["promoted"] == 1 and res["staled"] == 1 and res["dry_run"] is True
    status = {n.id: n.status for n in b.read_nodes()}
    assert status["used"] == "probation" and status["old"] == "probation"


def test_lifecycle_commits_once_with_the_gates_in_the_message(tmp_path, monkeypatch):
    b = _brain(tmp_path)
    _node(b, "used", recalls=1)
    _node(b, "old", days_old=90)
    calls = []
    monkeypatch.setattr(b, "commit_and_push",
                        lambda message, push=True: calls.append(message))

    lifecycle(b, min_recall=1, min_degree=0, stale_days=30)

    assert len(calls) == 1
    assert "1 promoted" in calls[0] and "1 stale" in calls[0]
    assert "recall >= 1" in calls[0] and "30d" in calls[0]


def test_lifecycle_plan_matches_the_pass(tmp_path):
    b = _brain(tmp_path)
    _node(b, "used", recalls=1)

    plan_ = lifecycle_plan(b, min_recall=1, min_degree=0, stale_days=30)
    res = lifecycle(b, min_recall=1, min_degree=0, stale_days=30)

    assert plan_["promote"] == ["used"]
    assert res["promoted"] == len(plan_["promote"]) == 1
    assert plan_["gates"]["min_recall"] == 1


def test_plan_uses_the_same_gates_as_the_pass(tmp_path):
    b = _brain(tmp_path)
    _node(b, "used", recalls=1)
    _node(b, "old", days_old=90)

    reported = plan(b, min_recall=1, min_degree=0, stale_days=30, min_community=10)

    assert len(reported.promotion_candidates) == 1
    assert len(reported.decay_candidates) == 1


def test_default_gates_are_the_measured_ones(tmp_path):
    b = _brain(tmp_path)
    _node(b, "recent", days_old=DECAY_DAYS - 1)

    assert (PROMOTE_MIN_RECALL, PROMOTE_MIN_DEGREE) == (1, 2)
    assert DECAY_MAX_DEGREE == 2
    assert lifecycle(b)["staled"] == 0, "a corpus younger than 30 days decays nothing"


def test_node_age_days_handles_bad_timestamps():
    assert node_age_days(Node(text="x", created="not-a-date")) == 0.0
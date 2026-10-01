"""Automatic extraction: gates, provenance, repeats, forgetting and failures."""

import datetime
import subprocess

import pytest

from graph_engine.brain import Brain, Edge, Node
from graph_engine.brain_engine import BrainEngine, consolidation_config_from_env
from graph_engine.consolidation import ConsolidationConfig, consolidate, consolidation_plan
from graph_engine.embedder import HashEmbedder

NOW = datetime.datetime(2026, 10, 2, tzinfo=datetime.timezone.utc)
OPEN = ConsolidationConfig(threshold=0, min_age_days=0)


@pytest.fixture
def brain(tmp_path):
    return Brain(tmp_path / "brain", mode="local")


def event(brain, nid="event", text="User prefers concise answers", **kwargs):
    node = Node(id=nid, text=text, ntype="episodic", status="active",
                created="2026-09-29T00:00:00Z", **kwargs)
    brain.write_node(node)
    return node


def snapshot(brain):
    return {str(p.relative_to(brain.path)): p.read_bytes()
            for p in brain.path.rglob("*") if p.is_file()}


def test_default_recall_and_age_gates(brain):
    event(brain, "eligible", recall_count=1)
    event(brain, "unused")
    event(brain, "young", recall_count=1, observed_at="2026-10-01T12:00:00Z")
    event(brain, "future", recall_count=9, observed_at="2026-10-03T00:00:00Z")
    event(brain, "bad_date", recall_count=9, observed_at="not-a-date")
    dead = event(brain, "dead", recall_count=9)
    dead.status = "tombstone"
    brain.write_node(dead)
    brain.write_node(Node(id="semantic", text="A fact", recall_count=9))
    before = snapshot(brain)
    plan = consolidation_plan(brain, config=ConsolidationConfig(), now=NOW)
    assert plan["candidates"] == ["eligible"]
    assert plan["episodic"] == 5
    assert snapshot(brain) == before


def test_count_trigger_then_oldest_first_bounded_pass(brain):
    event(brain, "newer", observed_at="2026-10-01T00:00:00Z")
    cfg = ConsolidationConfig(threshold=0, min_age_days=1, min_count=2, limit=1)
    assert not consolidate(brain, config=cfg, now=NOW)["triggered"]
    event(brain, "older", text="Another event", observed_at="2026-09-01T00:00:00Z")
    first = consolidate(brain, config=cfg, now=NOW)
    assert first["candidates"] == ["older"] and first["edges"] == 1
    # Count gate is on the remaining eligible pool, not total historical events.
    assert not consolidate(brain, config=cfg, now=NOW)["triggered"]


def test_extracts_preserves_original_and_is_idempotent(brain, monkeypatch):
    original = event(brain)
    original_bytes = brain.node_path(original.id).read_bytes()
    commits = []
    monkeypatch.setattr(brain, "commit_and_push", commits.append)
    first = consolidate(brain, config=OPEN, now=NOW)
    assert (first["created"], first["edges"]) == (1, 1)
    fact = next(n for n in brain.read_nodes() if n.ntype == "semantic")
    assert fact.status == "probation" and fact.source == "consolidator"
    assert fact.text == original.text
    link = brain.read_edges()[0]
    assert (link.source, link.target, link.kind, link.origin, link.pending) == (
        fact.id, original.id, "extends", "consolidator", False)
    assert brain.node_path(original.id).read_bytes() == original_bytes
    before = snapshot(brain)
    second = consolidate(brain, config=OPEN, now=NOW)
    assert second["created"] == second["edges"] == 0
    assert second["processed"] == 1 and len(commits) == 1
    assert snapshot(brain) == before


def test_reuses_semantic_fact_across_events_without_merging_events(brain):
    event(brain, "one", "  Prefers SHORT answers ")
    event(brain, "two", "prefers short   answers")
    brain.write_node(Node(id="existing", text="Prefers short answers", source="human"))
    brain.write_node(Node(id="procedural", text="Prefers short answers", ntype="procedural"))
    result = consolidate(brain, config=OPEN, now=NOW)
    assert (result["created"], result["reused"], result["edges"]) == (0, 2, 2)
    assert {e.source for e in brain.read_edges()} == {"existing"}
    assert brain.read_node("existing").source == "human"
    assert "consolidator" in brain.read_node("existing").sources
    assert len(brain.read_nodes()) == 4


def test_two_events_create_one_fact_and_two_links(brain):
    event(brain, "one")
    event(brain, "two")
    result = consolidate(brain, config=OPEN, now=NOW)
    assert (result["created"], result["reused"], result["edges"]) == (1, 1, 2)
    assert len({e.source for e in brain.read_edges()}) == 1


@pytest.mark.parametrize("review", ["live", "rejected", "invalidated", "forgotten"])
def test_manual_extraction_is_respected_after_review_or_forgetting(brain, review):
    raw = event(brain)
    fact = BrainEngine(brain, HashEmbedder()).extract(raw.id, text="A refined fact")
    links = brain.read_edges(include_rejected=True)
    if review == "rejected":
        links[0].rejected = True
    elif review == "invalidated":
        links[0].valid_to = "2026-10-01T00:00:00Z"
    elif review == "forgotten":
        brain.tombstone_node(fact.id)
    brain.write_edges(links)
    before = snapshot(brain)
    assert consolidate(brain, config=OPEN, now=NOW)["candidates"] == []
    assert snapshot(brain) == before


def test_summary_link_does_not_mark_an_event_extracted(brain):
    event(brain)
    brain.write_node(Node(id="summary", text="Community", tags=["community-summary"]))
    brain.write_edges([Edge(source="summary", target="event", kind="extends",
                            origin="consolidator", pending=False)])
    assert consolidate(brain, config=OPEN, now=NOW)["created"] == 1


def test_matching_summary_is_not_reused_as_a_fact(brain):
    event(brain)
    brain.write_node(Node(id="summary", text="User prefers concise answers",
                          tags=["community-summary"]))
    assert consolidate(brain, config=OPEN, now=NOW)["created"] == 1
    assert brain.read_edges()[0].source != "summary"
    assert consolidate(brain, config=OPEN, now=NOW)["edges"] == 0


def test_forgotten_text_is_not_recreated_from_another_event(brain):
    event(brain)
    brain.write_node(Node(id="forgotten", text="User prefers concise answers", status="tombstone"))
    before = snapshot(brain)
    assert consolidate(brain, config=OPEN, now=NOW)["skipped"] == 1
    assert snapshot(brain) == before


def test_dry_run_never_calls_extractor_sync_or_commit(brain, monkeypatch):
    event(brain)
    before = snapshot(brain)
    def forbidden(*args):
        pytest.fail("dry run attempted an external call or mutation")
    for method in ("ensure_ready", "pull", "write_node", "write_edges", "commit_and_push"):
        monkeypatch.setattr(brain, method, forbidden)
    result = consolidate(brain, config=OPEN, now=NOW, dry_run=True, extractor=forbidden)
    assert result["candidates"] == ["event"] and result["created"] == 0
    assert snapshot(brain) == before


def test_dry_run_on_missing_brain_does_not_initialize(tmp_path):
    brain = Brain(tmp_path / "absent", mode="git")
    assert consolidate(brain, config=OPEN, dry_run=True)["candidates"] == []
    assert not brain.path.exists()


@pytest.mark.parametrize("bad_result", [42, "failure"])
def test_extractor_failure_leaves_entire_batch_unwritten(brain, bad_result):
    event(brain, "a", "First")
    event(brain, "b", "Second")
    before = snapshot(brain)
    def extractor(text):
        if text == "First":
            return "A refined first fact"
        if bad_result == "failure":
            raise RuntimeError("provider failed")
        return bad_result
    with pytest.raises((ValueError, RuntimeError)):
        consolidate(brain, config=OPEN, now=NOW, extractor=extractor)
    assert snapshot(brain) == before


def test_optional_extractor_refines_or_declines(brain):
    event(brain, "a", "User requested concise responses")
    event(brain, "b", "Clicked a button")
    result = consolidate(brain, config=OPEN, now=NOW,
                         extractor=lambda text: "Prefers concise answers" if "User" in text else None)
    assert result["created"] == result["skipped"] == 1
    assert next(n.text for n in brain.read_nodes() if n.ntype == "semantic") == "Prefers concise answers"


def test_naive_and_offset_dates_use_elapsed_time(brain):
    event(brain, "naive", observed_at="2026-09-30T00:00:00")
    event(brain, "offset", observed_at="2026-10-01T02:00:00+02:00")
    plan = consolidation_plan(brain, config=ConsolidationConfig(threshold=0), now=NOW)
    assert plan["candidates"] == ["naive", "offset"]


@pytest.mark.parametrize("env_name,value", [
    ("IG_CONSOLIDATE_THRESHOLD", "-1"), ("IG_CONSOLIDATE_THRESHOLD", "one"),
    ("IG_CONSOLIDATE_MIN_AGE_DAYS", "nan"), ("IG_CONSOLIDATE_MIN_AGE_DAYS", "inf"),
    ("IG_CONSOLIDATE_MIN_COUNT", "0"), ("IG_CONSOLIDATE_LIMIT", "-1"),
])
def test_invalid_environment_is_rejected(monkeypatch, env_name, value):
    monkeypatch.setenv(env_name, value)
    with pytest.raises(ValueError):
        consolidation_config_from_env()


def test_environment_is_read_at_call_time_and_overridable(monkeypatch):
    monkeypatch.setenv("IG_CONSOLIDATE_THRESHOLD", "3")
    assert consolidation_config_from_env().threshold == 3
    monkeypatch.setenv("IG_CONSOLIDATE_THRESHOLD", "5")
    assert consolidation_config_from_env().threshold == 5
    assert consolidation_config_from_env({"threshold": 0}).threshold == 0


def test_git_batch_is_one_commit_and_repeat_has_no_commit(tmp_path):
    brain = Brain(tmp_path / "brain", mode="git")
    brain.ensure_ready()
    event(brain, "one")
    event(brain, "two")
    brain.commit_and_push("seed")
    def count():
        return int(subprocess.check_output(["git", "-C", str(brain.path),
                                            "rev-list", "--count", "HEAD"], text=True))
    before = count()
    assert consolidate(brain, config=OPEN, now=NOW)["edges"] == 2
    assert count() == before + 1
    consolidate(brain, config=OPEN, now=NOW)
    assert count() == before + 1

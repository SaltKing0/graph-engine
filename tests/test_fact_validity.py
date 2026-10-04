"""Dated facts remain reviewable and invalidation survives re-extraction."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from graph_engine.brain import Brain, Edge
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder
from graph_engine.entities import extract_entities
from graph_engine.graph import live_edges
from graph_engine.temporal import edge_timeline, history, valid_at


@pytest.fixture
def brain(tmp_path):
    return Brain(tmp_path / "brain", mode="local")


def extract(brain, start="2000-01-01", end="2999-01-01", *, text="Alice works at Acme.", **kwargs):
    data = {
        "entities": [{"name": "Alice", "type": "person"}, {"name": "Acme", "type": "org"}],
        "facts": [{"subject": "Alice", "predicate": "works_at", "object": "Acme",
                   "evidence": "Alice works at Acme", "valid_from": start, "valid_to": end}],
    }
    result = extract_entities(brain, text, extractor=lambda *_: data, commit=False, **kwargs)
    return next(e for e in brain.read_edges(include_rejected=True) if e.id == result["facts"][0]["id"])


@pytest.mark.parametrize("start,end", [("2000-01-01", "2999-01-01"),
                                      ("2000-01-01", "2001-01-01"),
                                      ("2998-01-01", "2999-01-01")])
@pytest.mark.parametrize("accept", [True, False])
def test_bounded_facts_can_be_reviewed_and_undone(brain, start, end, accept):
    edge = extract(brain, start, end)
    engine = BrainEngine(brain, HashEmbedder())
    resolved = engine.resolve(edge.id, accept=accept)
    assert resolved is not None and not resolved.pending
    assert resolved.rejected is not accept
    assert resolved.valid_to == edge.valid_to
    assert engine.undo(edge.id).pending
    assert engine.resolve(edge.id, accept=accept) is not None


def test_current_bounded_fact_is_visible_across_live_consumers(brain):
    from graph_engine.communities import build_graph
    from graph_engine.dream import _live_graph
    from graph_engine.hygiene import connectivity
    from graph_engine.report import report_data
    from graph_engine.retrieval import explain

    edge = extract(brain, accept_facts=True)
    assert edge.id in {e.id for e in live_edges(brain)}
    assert edge.target in build_graph(brain)[1][edge.source]
    assert edge.id in {e.id for e in _live_graph(brain)[2]}
    assert connectivity(brain).edges == 3  # two mentions plus the fact
    assert report_data(brain)["kinds"]["fact"] == 1
    result = explain(BrainEngine(brain, HashEmbedder()), edge.source, "Alice Acme")
    assert edge.id in {e["id"] for e in result["graph_context"]}


@pytest.mark.parametrize("start,end", [("2000-01-01", "2001-01-01"),
                                      ("2998-01-01", None)])
def test_noncurrent_facts_stay_out_of_live_views(brain, start, end):
    edge = extract(brain, start, end, accept_facts=True)
    assert not edge.is_current and not edge.is_invalidated
    assert edge.id not in {e.id for e in live_edges(brain)}
    state = next(e for e in brain.graph_state()["edges"] if e["id"] == edge.id)
    assert state["current"] is False and state["invalidated"] is False


@pytest.mark.parametrize("start,end", [(None, None), ("2000-01-01", None),
                                      ("2000-01-01", "2999-01-01")])
def test_repeat_cannot_revive_invalidated_facts(brain, start, end):
    edge = extract(brain, start, end, accept_facts=True)
    invalidated = brain.invalidate_edge(edge.id, by_edge_id="correction")
    assert invalidated is not None and invalidated.invalidated_at
    assert invalidated.valid_to == edge.valid_to
    assert invalidated.extracted_validity == edge.extracted_validity
    before = brain.edges_file.read_bytes()
    repeated = extract(brain, start, end, accept_facts=True)
    assert repeated.id == edge.id and repeated.invalidated_by == "correction"
    assert brain.edges_file.read_bytes() == before
    assert not any(e.kind == "fact" for e in live_edges(brain))
    assert brain.restore_edge(edge.id) is None
    assert brain.invalidate_edge(edge.id) is None


def test_dated_evidence_aggregates_and_distinct_windows_remain_separate(brain):
    original = extract(brain)
    repeated = extract(brain, text="Alice works at Acme. Another observation.")
    assert repeated.id == original.id and len(repeated.evidence) == 2
    assert repeated.pending
    different = extract(brain, end="2998-01-01")
    assert different.id != original.id
    undated = extract(brain, None, None)
    assert undated.id not in {original.id, different.id}
    assert extract(brain, None, None).id == undated.id


def test_legacy_closed_fact_stays_invalidated_without_rewrite(brain):
    edge = extract(brain, end=None)
    legacy = edge.to_dict()
    legacy.pop("extracted_validity")
    legacy["valid_to"] = "2999-01-01T00:00:00Z"
    brain.write_edges([Edge(**legacy)])
    before = brain.edges_file.read_bytes()
    loaded = brain.read_edges()[0]
    assert loaded.is_invalidated and not loaded.is_current
    assert brain.resolve_edge(loaded.id, True) is None
    assert brain.restore_edge(loaded.id) is None
    repeated = extract(brain, end=None, accept_facts=True)
    assert repeated.id == loaded.id and repeated.is_invalidated
    # Extraction restores the missing mention links, but never migrates this fact.
    saved = next(e for e in brain.read_edges() if e.kind == "fact")
    assert saved.to_dict() == legacy
    assert before.splitlines()[0] in brain.edges_file.read_bytes().splitlines()


def test_historical_window_and_invalidation_have_separate_boundaries(brain, monkeypatch):
    import graph_engine.brain as storage

    edge = extract(brain, "2020-01-01", "2030-01-01", accept_facts=True)
    monkeypatch.setattr(storage, "_now_iso", lambda: "2025-01-01T00:00:00Z")
    brain.invalidate_edge(edge.id)
    for at, included in [("2019-12-31", False), ("2020-01-01", True),
                         ("2024-12-31", True), ("2025-01-01", False),
                         ("2030-01-01", False)]:
        assert (edge.id in {e.id for e in valid_at(brain, at + "T00:00:00Z")["edges"]}) is included
    expected = {("created", "2020-01-01T00:00:00Z"),
                ("invalidated", "2025-01-01T00:00:00Z"),
                ("expired", "2030-01-01T00:00:00Z")}
    for events in (history(brain, edge.source), edge_timeline(brain)):
        assert {(e["event"], e["timestamp"]) for e in events if e["edge_id"] == edge.id} == expected


def test_validity_end_is_exclusive(brain):
    edge = extract(brain, "2020-01-01", "2030-01-01", accept_facts=True)
    assert edge.is_valid_at(datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert not edge.is_valid_at(datetime(2030, 1, 1, tzinfo=timezone.utc))


def test_bulk_review_skips_invalidations_but_accepts_expired_facts(brain):
    from graph_engine.review import accept_pending

    dead = extract(brain, "2020-01-01", None)
    expired = extract(brain, "2020-01-01", "2021-01-01")
    brain.invalidate_edge(dead.id)
    result = accept_pending(brain, commit=False)
    assert result["accepted"] == [expired.id]
    assert next(e for e in brain.read_edges() if e.id == dead.id).pending


def test_forget_invalidates_scheduled_fact_without_changing_window(brain):
    from graph_engine.agent_memory import forget

    edge = extract(brain, "2998-01-01", "2999-01-01", accept_facts=True)
    forget(brain, edge.source, reason="test", commit=False)
    saved = next(e for e in brain.read_edges() if e.id == edge.id)
    assert saved.is_invalidated and saved.valid_to == edge.valid_to
    assert saved.extracted_validity == edge.extracted_validity


def test_http_review_exposes_validity_separately_from_invalidation(brain, monkeypatch):
    from graph_engine.server import app

    monkeypatch.setenv("IG_BRAIN_PATH", str(brain.path))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    edge = extract(brain, "2020-01-01", "2021-01-01")
    with TestClient(app) as client:
        state = next(e for e in client.get("/api/graph").json()["edges"] if e["id"] == edge.id)
        assert state["pending"] and not state["current"] and not state["invalidated"]
        assert client.post(f"/api/edge/{edge.id}/accept").status_code == 200
        assert client.post(f"/api/edge/{edge.id}/undo").status_code == 200
        assert client.post(f"/api/edge/{edge.id}/reject").status_code == 200


def test_mcp_get_node_keeps_current_bounded_facts(brain, monkeypatch):
    pytest.importorskip("mcp")
    from graph_engine.mcp.server import get_node

    monkeypatch.setenv("IG_BRAIN_PATH", str(brain.path))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    edge = extract(brain, accept_facts=True)
    assert edge.id in {e["id"] for e in get_node(edge.source)["edges"]}

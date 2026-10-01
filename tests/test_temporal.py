"""Tests for temporal reasoning (Phase 2: bi-temporal queries).

Covers:
- valid_at: graph state at a point in time
- history: edge evolution for a node
- when: retrieval restricted to what was known then
- edge_timeline: edge events in a time range
"""

from __future__ import annotations

import pytest

from graph_engine.brain import Brain, Edge, Node


@pytest.fixture
def brain(tmp_path):
    b = Brain(path=tmp_path / "brain", mode="local")
    b.ensure_ready()
    return b


class TestValidAt:
    def test_returns_only_nodes_existing_at_timestamp(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node1, _, _ = engine.ingest("First fact")
        node2, _, _ = engine.ingest("Second fact")
        # valid_at before the nodes were created should return nothing
        result = engine.valid_at("2020-01-01T00:00:00Z")
        ids = {n.id for n in result["nodes"]}
        assert node1.id not in ids
        assert node2.id not in ids

    def test_returns_only_edges_valid_at_timestamp(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node1, _, _ = engine.ingest("First")
        node2, _, _ = engine.ingest("Second")
        # Invalidate an edge
        edges = brain.read_edges(include_rejected=True)
        if edges:
            brain.invalidate_edge(edges[0].id)
        result = engine.valid_at("2020-01-01T00:00:00Z")
        # The invalidated edge should not appear (valid_to > 2020)
        # Actually, valid_to is set to now, so it should not be valid at 2020
        for e in result["edges"]:
            assert e.valid_to is None or e.valid_to > "2020-01-01T00:00:00Z"

    def test_invalid_timestamp_raises(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        with pytest.raises(ValueError, match="Invalid timestamp"):
            engine.valid_at("not-a-date")

    def test_empty_graph(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        result = engine.valid_at("2020-01-01T00:00:00Z")
        assert result["nodes"] == []
        assert result["edges"] == []


class TestHistory:
    def test_returns_edge_events_for_node(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node1, _, _ = engine.ingest("First")
        node2, _, _ = engine.ingest("Second")
        # Create a manual edge
        engine.link(node1.id, node2.id, kind="similar")
        events = engine.history(node1.id)
        assert len(events) >= 1
        assert any(e["event"] == "created" for e in events)

    def test_empty_history_for_isolated_node(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node1, _, _ = engine.ingest("Lonely fact")
        events = engine.history(node1.id)
        assert events == []

    def test_invalidation_creates_event(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node1, _, _ = engine.ingest("First")
        node2, _, _ = engine.ingest("Second")
        engine.link(node1.id, node2.id, kind="similar")
        edges = brain.read_edges(include_rejected=True)
        brain.invalidate_edge(edges[0].id)
        events = engine.history(node1.id)
        assert any(e["event"] == "invalidated" for e in events)

    def test_events_sorted_chronologically(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node1, _, _ = engine.ingest("First")
        node2, _, _ = engine.ingest("Second")
        engine.link(node1.id, node2.id, kind="similar")
        events = engine.history(node1.id)
        timestamps = [e["timestamp"] for e in events if e["timestamp"]]
        assert timestamps == sorted(timestamps)


class TestWhen:
    def test_returns_results_from_past(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node1, _, _ = engine.ingest("Memory systems are important")
        results = engine.when("memory", "2020-01-01T00:00:00Z")
        # node1 was created after 2020, so it should not appear
        assert all(nid != node1.id for nid, _ in results)

    def test_returns_results_from_future(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node1, _, _ = engine.ingest("Memory systems are important")
        results = engine.when("memory", "2099-01-01T00:00:00Z")
        # node1 should appear (it exists by 2099)
        assert any(nid == node1.id for nid, _ in results)

    def test_invalid_timestamp_raises(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        with pytest.raises(ValueError, match="Invalid timestamp"):
            engine.when("query", "not-a-date")

    def test_empty_results_for_unknown_query(self, brain):
        from graph_engine.brain_engine import BrainEngine
        from graph_engine.embedder import HashEmbedder
        # Guarantee zero lexical/dense overlap; semantic models can assign
        # positive similarity to words that do not share any tokens.
        engine = BrainEngine(brain, embedder=HashEmbedder())
        engine.ingest("Something")
        results = engine.when("nonexistent", "2099-01-01T00:00:00Z")
        assert results == []


class TestEdgeTimeline:
    def test_returns_events_in_range(self, brain):
        from graph_engine.brain_engine import BrainEngine
        from graph_engine.temporal import edge_timeline
        engine = BrainEngine(brain)
        node1, _, _ = engine.ingest("First")
        node2, _, _ = engine.ingest("Second")
        engine.link(node1.id, node2.id, kind="similar")
        events = edge_timeline(brain, since="2020-01-01T00:00:00Z")
        assert len(events) >= 1
        assert all(e["timestamp"] >= "2020-01-01T00:00:00Z" for e in events)

    def test_empty_timeline_for_future_range(self, brain):
        from graph_engine.brain_engine import BrainEngine
        from graph_engine.temporal import edge_timeline
        engine = BrainEngine(brain)
        engine.ingest("Something")
        events = edge_timeline(brain, since="2099-01-01T00:00:00Z")
        assert events == []

    def test_until_filter(self, brain):
        from graph_engine.brain_engine import BrainEngine
        from graph_engine.temporal import edge_timeline
        engine = BrainEngine(brain)
        engine.ingest("Something")
        events = edge_timeline(brain, until="2020-01-01T00:00:00Z")
        assert events == []

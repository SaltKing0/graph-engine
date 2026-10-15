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
    def test_current_validity_view_hides_forgotten_evidence_but_history_keeps_events(self, brain):
        from graph_engine.temporal import valid_at, history
        for nid in ("a", "b", "evidence"):
            brain.write_node(Node(nid, id=nid, status="active", created="2000-01-01T00:00:00Z"))
        brain.write_edges([Edge("a", "b", "fact", id="fact", pending=False,
                               valid_from="2000-01-01T00:00:00Z",
                               evidence=[{"node_id": "evidence", "text": "Synthetic quote"}])])
        assert valid_at(brain, "2020-01-01T00:00:00Z")["edges"]
        brain.tombstone_node("evidence")
        assert valid_at(brain, "2020-01-01T00:00:00Z")["edges"] == []
        assert history(brain, "a")[0]["edge_id"] == "fact"

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
    @pytest.mark.parametrize("rerank", [False, True])
    def test_keeps_feedback_tier_and_reranker_semantics(self, brain, tmp_path, rerank):
        import json
        from graph_engine.brain_engine import BrainEngine
        from graph_engine.embedder import HashEmbedder
        from graph_engine.retrieval import retrieve

        past = [Node(text, id=nid, storage_tier=tier, created="2020-01-01")
                for nid, text, tier in [
                    ("first", "alpha", "recall"),
                    ("preferred", "alpha older extra words", "recall"),
                    ("main", "alpha main extra words", "main"),
                    ("archive", "alpha archive", "archival")]]
        reference = Brain(tmp_path / "eligible", mode="local")
        reference.ensure_ready()
        feedback = json.dumps({"version": 1, "judgments": [
            {"query": "alpha", "node_id": nid, "label": "relevant",
             "dense_rank": 1, "bm25_rank": 2} for nid in ("preferred", "future")]})
        for store in (brain, reference):
            for node in past:
                store.write_node(node)
            (store.path / "feedback.json").write_text(feedback)
        brain.write_node(Node("alpha futuretoken", id="future", created="2030-01-01"))

        class ReverseReranker:
            def rerank(self, query, candidates, k):
                assert {nid for nid, _, _ in candidates} == {n.id for n in past}
                return list(reversed(candidates))[:k]

        engines = [BrainEngine(store, HashEmbedder(), reranker=False)
                   for store in (brain, reference)]
        for engine in engines:
            engine.reranker = ReverseReranker() if rerank else None
        expected = retrieve(engines[1], "alpha", k=4, persist=False)
        actual = engines[0].when("alpha", "2021-01-01", k=4)
        assert actual == expected
        assert actual[0][0] == "main" and actual[-1][0] == "archive"
        assert [nid for nid, _ in actual[1:3]] == (
            ["first", "preferred"] if rerank else ["preferred", "first"])

    @pytest.mark.parametrize("rerank", [False, True])
    def test_old_match_survives_newer_matches_beyond_candidate_limit(self, brain, rerank):
        from graph_engine.brain_engine import BrainEngine
        from graph_engine.embedder import HashEmbedder
        from graph_engine.retrieval import retrieve

        brain.write_node(Node("alpha old extra words", id="old", created="2020-01-01"))
        for i in range(40):  # exceeds both 3*k and the default rerank_k=30
            brain.write_node(Node("alpha", id=f"new{i}", created="2030-01-01"))
        seen = []

        class Reranker:
            def rerank(self, query, candidates, k):
                seen.append([nid for nid, _, _ in candidates])
                return candidates[:k]

        engine = BrainEngine(brain, HashEmbedder(), reranker=Reranker() if rerank else False)
        if not rerank:
            engine.reranker = None
        # Warm the ordinary full-corpus index before the temporal call.
        assert "old" not in dict(retrieve(engine, "alpha", k=30, persist=False))
        seen.clear()
        assert [nid for nid, _ in engine.when("alpha", "2021-01-01", k=1)] == ["old"]
        if rerank:
            assert seen == [["old"]]
        # A different cutoff and ordinary search must not reuse a filtered corpus.
        assert engine.when("alpha", "2019-01-01", k=1) == []
        assert engine.when("alpha", "2031-01-01", k=1)[0][0] != "old"
        assert retrieve(engine, "alpha", k=1, persist=False)[0][0] != "old"

    def test_only_eligible_text_is_embedded_and_used_for_bm25(self, brain, monkeypatch):
        from graph_engine.brain_engine import BrainEngine
        from graph_engine.embedder import HashEmbedder
        from graph_engine import retrieval

        brain.write_node(Node("alpha old extra words", id="old", created="2020-01-01"))
        brain.write_node(Node("alpha future", id="new", created="2030-01-01"))
        engine = BrainEngine(brain, HashEmbedder(), reranker=False)
        engine.reranker = None
        texts = []
        original_embed = engine.embedder.embed

        def embed(text):
            texts.append(text)
            return original_embed(text)

        original_bm25 = retrieval.BM25
        corpora = []

        def bm25(corpus):
            corpora.append(corpus)
            return original_bm25(corpus)

        monkeypatch.setattr(engine.embedder, "embed", embed)
        monkeypatch.setattr(retrieval, "BM25", bm25)
        assert engine.when("alpha", "2021-01-01", k=1)
        assert texts == ["alpha", "alpha old extra words"]
        assert corpora == [["alpha old extra words"]]

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


# All four forms name the same instant: naive values are interpreted as UTC.
UTC_MIDNIGHT = ["2021-01-01", "2021-01-01T00:00:00",
                "2021-01-01T00:00:00Z", "2020-12-31T19:00:00-05:00"]


@pytest.mark.parametrize("stored", UTC_MIDNIGHT)
@pytest.mark.parametrize("query", UTC_MIDNIGHT)
def test_valid_at_and_when_normalize_query_and_legacy_creation(brain, stored, query):
    from graph_engine.brain_engine import BrainEngine
    from graph_engine.embedder import HashEmbedder

    brain.write_node(Node("alpha memory", id="alpha", created=stored))
    brain.write_node(Node("alpha future", id="future", created="2021-01-01T00:00:01Z"))
    brain.write_node(Node("alpha forgotten", id="gone", created=stored, status="tombstone"))
    engine = BrainEngine(brain, HashEmbedder(), reranker=False)
    engine.reranker = None
    assert [n.id for n in engine.valid_at(query)["nodes"]] == ["alpha"]
    assert [nid for nid, _ in engine.when("alpha", query)] == ["alpha"]
    assert brain.read_node("alpha").created == stored


@pytest.mark.parametrize("stored", UTC_MIDNIGHT)
@pytest.mark.parametrize("bound", UTC_MIDNIGHT)
def test_edge_timeline_inclusive_bounds_use_instants(brain, stored, bound):
    from graph_engine.temporal import edge_timeline

    brain.write_edges([
        Edge("a", "b", "fact", id="at", pending=False, valid_from=stored,
             valid_to=stored, invalidated_at=stored,
             extracted_validity={"valid_from": stored, "valid_to": stored}),
        Edge("a", "b", "fact", id="before", pending=False,
             valid_from="2021-01-01T00:59:59+01:00"),
        Edge("a", "b", "fact", id="after", pending=False,
             valid_from="2020-12-31T19:00:01-05:00"),
    ])
    events = edge_timeline(brain, since=bound, until=bound)
    assert [(e["edge_id"], e["event"], e["timestamp"]) for e in events] == [
        ("at", "created", stored), ("at", "expired", stored), ("at", "invalidated", stored)]
    assert {e["edge_id"] for e in edge_timeline(brain, since=bound)} == {"at", "after"}
    assert {e["edge_id"] for e in edge_timeline(brain, until=bound)} == {"before", "at"}


def test_edge_history_and_timeline_sort_by_instant(brain):
    from graph_engine.temporal import edge_timeline, history

    brain.write_edges([
        Edge("a", "b", "fact", id="late", pending=False,
             valid_from="2020-12-31T20:00:00-05:00", valid_to="2021-01-01T02:00:00"),
        Edge("a", "b", "fact", id="early", pending=False, valid_from="2021-01-01"),
        Edge("a", "b", "fact", id="middle", pending=False,
             valid_from="2021-01-01T01:30:00+01:00"),
    ])
    for events in (history(brain, "a"), edge_timeline(brain)):
        assert [(e["edge_id"], e["event"]) for e in events] == [
            ("early", "created"), ("middle", "created"),
            ("late", "created"), ("late", "invalidated")]


@pytest.mark.parametrize("bad", ["", "invalid", "2021-02-30", "2021-01-01T25:00:00", 123, {}])
@pytest.mark.parametrize("populated", [False, True])
def test_invalid_temporal_inputs_raise_validation_errors(brain, bad, populated):
    from graph_engine.brain_engine import BrainEngine
    from graph_engine.embedder import HashEmbedder
    from graph_engine.temporal import edge_timeline

    if populated:
        brain.write_node(Node("alpha", id="a", created="2020-01-01", ntype="episodic"))
        brain.write_edges([Edge("a", "b", "fact", pending=False, valid_from="2020-01-01")])
    engine = BrainEngine(brain, HashEmbedder(), reranker=False)
    engine.reranker = None
    for call in (lambda: engine.valid_at(bad), lambda: engine.when("alpha", bad),
                 lambda: edge_timeline(brain, since=bad), lambda: edge_timeline(brain, until=bad),
                 lambda: engine.timeline(since=bad), lambda: engine.timeline(until=bad)):
        with pytest.raises(ValueError, match="Invalid timestamp"):
            call()


@pytest.mark.parametrize("bound", UTC_MIDNIGHT)
def test_episodic_timeline_compares_observed_and_fallback_creation_times(brain, bound):
    from graph_engine.brain_engine import BrainEngine
    from graph_engine.embedder import HashEmbedder

    for nid, observed, created in [
        ("late", "2020-12-31T20:00:00-05:00", "2020-01-01"),
        ("early", None, "2021-01-01"),
        ("middle", "2021-01-01T01:30:00+01:00", "2020-01-01"),
    ]:
        brain.write_node(Node(nid, id=nid, ntype="episodic", created=created, observed_at=observed))
    engine = BrainEngine(brain, HashEmbedder(), reranker=False)
    engine.reranker = None
    assert [n.id for n in engine.timeline()] == ["late", "middle", "early"]
    assert [n.id for n in engine.timeline(since=bound, until=bound)] == ["early"]


@pytest.mark.parametrize("timestamp", UTC_MIDNIGHT)
def test_timestamp_parser_returns_aware_utc(timestamp):
    from datetime import datetime, timezone
    from graph_engine.timestamps import parse_timestamp

    stamp = parse_timestamp(timestamp)
    assert stamp == datetime(2021, 1, 1, tzinfo=timezone.utc)
    assert stamp.tzinfo is timezone.utc


@pytest.mark.parametrize("bad", [None, 123, {}, "", "invalid", "0001-01-01T00:00:00+01:00",
                                "9999-12-31T23:59:59-01:00"])
def test_timestamp_parser_rejects_invalid_or_unrepresentable_utc(bad):
    from graph_engine.timestamps import parse_timestamp

    with pytest.raises(ValueError, match="Invalid timestamp"):
        parse_timestamp(bad)


def test_malformed_legacy_timestamps_keep_tolerant_read_behavior(brain):
    from graph_engine.brain_engine import BrainEngine
    from graph_engine.embedder import HashEmbedder
    from graph_engine.temporal import edge_timeline, history

    brain.write_node(Node("alpha", id="a", created="legacy-unknown", ntype="episodic"))
    brain.write_node(Node("beta", id="b", created="2020-01-01"))
    brain.write_edges([Edge("a", "b", "fact", id="fact", pending=False,
                           valid_from="legacy-unknown", valid_to="2022-01-01")])
    engine = BrainEngine(brain, HashEmbedder(), reranker=False)
    engine.reranker = None
    assert {n.id for n in engine.valid_at("2021-01-01")["nodes"]} == {"a", "b"}
    assert [e.id for e in engine.valid_at("2021-01-01")["edges"]] == ["fact"]
    assert [nid for nid, _ in engine.when("alpha", "2021-01-01")] == ["a"]
    assert engine.timeline() == []
    assert [e["event"] for e in edge_timeline(brain)] == ["invalidated"]
    assert [e["event"] for e in history(brain, "a")] == ["created", "invalidated"]

"""Tests for the episodic layer (Phase 1: episodic memory).

Covers:
- observe: storing raw episodic events (no cosine dedupe, exact-text dedupe)
- extract: episodic → semantic fact extraction with extends edge
- timeline: temporal queries over episodic nodes
- Node serialization: observed_at/context round-trip through markdown
"""

from __future__ import annotations

import pytest

from graph_engine.brain import Brain, Node


@pytest.fixture
def brain(tmp_path):
    b = Brain(path=tmp_path / "brain", mode="local")
    b.ensure_ready()
    return b


class TestObserve:
    def test_creates_episodic_node(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node, dup = engine.observe("User asked about memory systems")
        assert not dup
        assert node.ntype == "episodic"
        assert node.status == "active"
        assert node.text == "User asked about memory systems"

    def test_stores_observed_at_and_context(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node, _ = engine.observe(
            "Agent completed task",
            observed_at="2026-10-01T12:00:00Z",
            context="session-42",
        )
        assert node.observed_at == "2026-10-01T12:00:00Z"
        assert node.context == "session-42"

    def test_exact_text_dedupe(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node1, dup1 = engine.observe("Same event")
        node2, dup2 = engine.observe("Same event")
        assert not dup1
        assert dup2
        assert node1.id == node2.id

    def test_allow_duplicates_creates_second_node(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node1, _ = engine.observe("Same event", allow_duplicates=True)
        node2, _ = engine.observe("Same event", allow_duplicates=True)
        assert node1.id != node2.id

    def test_empty_text_raises(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        with pytest.raises(ValueError, match="Empty text"):
            engine.observe("")

    def test_commits_to_git(self, tmp_path):
        import subprocess
        from graph_engine.brain_engine import BrainEngine
        brain = Brain(path=tmp_path / "brain", mode="git")
        brain.ensure_ready()
        engine = BrainEngine(brain)
        engine.observe("A commit-worthy event")
        log = subprocess.run(
            ["git", "-C", str(brain.path), "log", "--oneline"],
            capture_output=True, text=True,
        )
        assert "observe" in log.stdout


class TestExtract:
    def test_creates_semantic_node(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        episodic, _ = engine.observe("User prefers short answers")
        semantic = engine.extract(episodic.id, text="User prefers concise responses")
        assert semantic.ntype == "semantic"
        assert semantic.status == "probation"
        assert semantic.text == "User prefers concise responses"

    def test_creates_extends_edge(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        episodic, _ = engine.observe("Raw observation")
        semantic = engine.extract(episodic.id)
        edges = brain.read_edges()
        assert len(edges) == 1
        assert edges[0].source == semantic.id
        assert edges[0].target == episodic.id
        assert edges[0].kind == "extends"
        assert edges[0].origin == "consolidator"

    def test_defaults_to_episodic_text(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        episodic, _ = engine.observe("The fact to extract")
        semantic = engine.extract(episodic.id)
        assert semantic.text == "The fact to extract"

    def test_non_episodic_raises(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        node, _, _ = engine.ingest("A semantic fact")
        with pytest.raises(ValueError, match="not episodic"):
            engine.extract(node.id)

    def test_missing_node_raises(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        with pytest.raises(ValueError, match="No node"):
            engine.extract("nonexistent")


class TestTimeline:
    def test_returns_episodic_nodes_only(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        engine.observe("Event 1")
        engine.ingest("Semantic fact")
        nodes = engine.timeline()
        assert len(nodes) == 1
        assert nodes[0].ntype == "episodic"

    def test_sorted_newest_first(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        engine.observe("Older", observed_at="2026-01-01T00:00:00Z")
        engine.observe("Newer", observed_at="2026-06-01T00:00:00Z")
        nodes = engine.timeline()
        assert len(nodes) == 2
        assert nodes[0].text == "Newer"
        assert nodes[1].text == "Older"

    def test_since_filter(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        engine.observe("January", observed_at="2026-01-15T00:00:00Z")
        engine.observe("June", observed_at="2026-06-15T00:00:00Z")
        nodes = engine.timeline(since="2026-03-01T00:00:00Z")
        assert len(nodes) == 1
        assert nodes[0].text == "June"

    def test_until_filter(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        engine.observe("January", observed_at="2026-01-15T00:00:00Z")
        engine.observe("June", observed_at="2026-06-15T00:00:00Z")
        nodes = engine.timeline(until="2026-03-01T00:00:00Z")
        assert len(nodes) == 1
        assert nodes[0].text == "January"

    def test_limit(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        for i in range(10):
            engine.observe(f"Event {i}")
        nodes = engine.timeline(limit=3)
        assert len(nodes) == 3

    def test_empty_timeline(self, brain):
        from graph_engine.brain_engine import BrainEngine
        engine = BrainEngine(brain)
        nodes = engine.timeline()
        assert nodes == []


class TestEpisodicSerialization:
    def test_round_trip_through_markdown(self, brain):
        node = Node(
            text="Episodic event",
            ntype="episodic",
            observed_at="2026-10-01T12:00:00Z",
            context="test-session",
        )
        brain.write_node(node)
        loaded = brain.read_node(node.id)
        assert loaded.ntype == "episodic"
        assert loaded.observed_at == "2026-10-01T12:00:00Z"
        assert loaded.context == "test-session"

    def test_semantic_node_has_no_episodic_fields(self, brain):
        node = Node(text="Semantic fact", ntype="semantic")
        brain.write_node(node)
        loaded = brain.read_node(node.id)
        assert loaded.observed_at is None
        assert loaded.context is None

    def test_to_dict_includes_episodic_fields(self):
        node = Node(
            text="Event",
            ntype="episodic",
            observed_at="2026-10-01T12:00:00Z",
            context="ctx",
        )
        d = node.to_dict()
        assert d["observed_at"] == "2026-10-01T12:00:00Z"
        assert d["context"] == "ctx"

    def test_markdown_contains_observed_at_for_episodic(self, brain):
        node = Node(
            text="Event",
            ntype="episodic",
            observed_at="2026-10-01T12:00:00Z",
        )
        brain.write_node(node)
        raw = (brain.node_path(node.id)).read_text()
        assert "observed_at: 2026-10-01T12:00:00Z" in raw

    def test_markdown_omits_observed_at_for_semantic(self, brain):
        node = Node(text="Fact", ntype="semantic")
        brain.write_node(node)
        raw = (brain.node_path(node.id)).read_text()
        assert "observed_at" not in raw

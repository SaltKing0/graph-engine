"""Tests for the agent-facing write path (Welle C): remember / recall / forget.

Three invariants are the whole point and each is asserted here:
provenance (`source="agent"` on the node, `origin="agent"` on declared edges),
never-destructive (`forget` tombstones + invalidates, the file and history stay),
and one commit per write with the reason recorded.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.agent_memory import (
    AGENT_ORIGIN,
    AGENT_SOURCE,
    forget,
    recall,
    remember,
)
from graph_engine.brain import Brain, Edge, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder
from graph_engine.retrieval import retrieve


def _engine(tmp_path) -> BrainEngine:
    brain = Brain(str(tmp_path / "brain"), mode="local")
    return BrainEngine(brain, embedder=HashEmbedder())


# ---------------------------------------------------------------------------
# remember
# ---------------------------------------------------------------------------

def test_remember_writes_a_provenance_marked_node(tmp_path):
    engine = _engine(tmp_path)
    engine.ingest("alpha beta gamma delta")

    res = remember(engine, "a note an agent decided to keep")

    assert res["written"] is True and res["duplicate"] is False
    node = engine.brain.read_node(res["node_id"])
    assert node is not None
    assert node.source == AGENT_SOURCE
    assert node.text == "a note an agent decided to keep"


def test_remember_is_dedupe_aware(tmp_path):
    engine = _engine(tmp_path)
    text = "agent memory systems store knowledge graphs for retrieval"
    engine.ingest(text)
    before = len(engine.brain.read_nodes())

    res = remember(engine, text)

    assert res["duplicate"] is True and res["written"] is False
    assert len(engine.brain.read_nodes()) == before, "no second node"


def test_remember_declares_relations_with_agent_origin(tmp_path):
    engine = _engine(tmp_path)
    target, _, _ = engine.ingest("alpha beta gamma delta")

    res = remember(engine, "a follow-up note about the alpha cluster",
                   relations=[(target.id, "extends")])

    agent_edges = [e for e in engine.brain.read_edges()
                   if e.origin == AGENT_ORIGIN and not e.rejected]
    assert res["agent_edges"] == 1
    assert len(agent_edges) == 1
    assert agent_edges[0].source == res["node_id"]
    assert agent_edges[0].target == target.id


def test_remember_rejects_empty_text(tmp_path):
    engine = _engine(tmp_path)
    with pytest.raises(ValueError):
        remember(engine, "   ")


def test_remember_tags_are_kept(tmp_path):
    engine = _engine(tmp_path)
    res = remember(engine, "a tagged agent note", tags=["agent", "session"])
    node = engine.brain.read_node(res["node_id"])
    assert node is not None and node.tags == ["agent", "session"]


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------

def test_recall_counts_as_use(tmp_path):
    """The difference to plain search: a recall feeds the promotion signal."""
    engine = _engine(tmp_path)
    node, _, _ = engine.ingest("agent memory systems store knowledge graphs")

    hits = recall(engine, "agent memory graphs", k=3)

    assert hits and hits[0][0] == node.id
    ledger = Path(engine.brain.path) / "recalls.jsonl"
    assert ledger.exists() and len(ledger.read_text().strip().splitlines()) == 1


def test_recall_does_not_write_vectors_by_default(tmp_path):
    """Strict mode: a recall must not fill vectors.jsonl on disk."""
    engine = _engine(tmp_path)
    engine.ingest("agent memory systems store knowledge graphs")
    vec_file = Path(engine.brain.path) / "vectors.jsonl"
    before = vec_file.read_text() if vec_file.exists() else None

    recall(engine, "agent memory", k=2)

    after = vec_file.read_text() if vec_file.exists() else None
    assert before == after


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------

def test_forget_tombstones_without_deleting(tmp_path):
    engine = _engine(tmp_path)
    brain = engine.brain
    keep, _, _ = engine.ingest("alpha beta gamma delta")
    drop, _, _ = engine.ingest("omega psi chi phi")
    brain.write_edges([
        Edge(id="e1", source=drop.id, target=keep.id, kind="extends",
             pending=False, origin="suggester", confidence=0.7),
    ])
    node_file = brain.node_path(drop.id)
    assert node_file.exists()

    res = forget(brain, drop.id, reason="superseded by the newer note")

    assert res["forgotten"] is True and res["edges_invalidated"] == 1
    assert node_file.exists(), "the file is NEVER deleted"
    tombstoned = brain.read_node(drop.id)
    assert tombstoned is not None and tombstoned.status == "tombstone"
    # the edge survives with valid_to set (audit trail), but leaves live views
    # (`read_edges()` is the raw store and keeps invalidated edges on purpose)
    edge = next(e for e in brain.read_edges(include_rejected=True) if e.id == "e1")
    assert edge.valid_to is not None
    from graph_engine.graph import live_edges
    assert [e.id for e in live_edges(brain)] == []


def test_forgotten_node_leaves_search(tmp_path):
    engine = _engine(tmp_path)
    node, _, _ = engine.ingest("agent memory systems store knowledge graphs")

    forget(engine.brain, node.id, reason="no longer relevant")

    hits = retrieve(engine, "agent memory graphs", k=3)
    assert node.id not in [nid for nid, _ in hits]


def test_forget_requires_a_reason(tmp_path):
    engine = _engine(tmp_path)
    node, _, _ = engine.ingest("alpha beta gamma delta")
    with pytest.raises(ValueError, match="reason"):
        forget(engine.brain, node.id, reason="  ")


def test_forget_unknown_node_raises(tmp_path):
    engine = _engine(tmp_path)
    with pytest.raises(ValueError, match="No node with id"):
        forget(engine.brain, "nope00000000", reason="cleanup")


def test_forget_is_idempotent(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    brain = engine.brain
    node, _, _ = engine.ingest("alpha beta gamma delta")
    commits = []
    monkeypatch.setattr(brain, "commit_and_push",
                        lambda message, push=True: commits.append(message))

    first = forget(brain, node.id, reason="first")
    second = forget(brain, node.id, reason="second")

    assert first["forgotten"] is True and first["already"] is False
    assert second["forgotten"] is False and second["already"] is True
    assert len(commits) == 1, "a second forget must not commit again"


def test_forget_records_the_reason_in_the_commit(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    brain = engine.brain
    node, _, _ = engine.ingest("alpha beta gamma delta")
    commits = []
    monkeypatch.setattr(brain, "commit_and_push",
                        lambda message, push=True: commits.append(message))

    forget(brain, node.id, reason="superseded by the newer note")

    assert len(commits) == 1
    assert "superseded by the newer note" in commits[0]
    assert node.id in commits[0]


def test_forget_keeps_the_node_count_stable(tmp_path):
    """Never destructive: a forgotten node is still a node (tombstone)."""
    engine = _engine(tmp_path)
    engine.ingest("alpha beta gamma delta")
    drop, _, _ = engine.ingest("omega psi chi phi")
    before = len(engine.brain.read_nodes())

    forget(engine.brain, drop.id, reason="cleanup")

    assert len(engine.brain.read_nodes()) == before
"""Tests for the brain layer: markdown format, edges, engine loop.

mode="local" — pure filesystem, no git, no network.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.brain import Brain, Node, Edge
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder


def make_brain(tmp_path):
    return Brain(str(tmp_path / "brain"), mode="local")


# ---------- Markdown roundtrip ----------

def test_node_markdown_roundtrip():
    n = Node(text="Katzen jagen Maeuse", source="agent/bot", tags=["tiere", "test"])
    raw = n.to_markdown()
    n2 = Node.from_markdown(raw)
    assert n2.id == n.id and n2.text == n.text and n2.source == "agent/bot"
    assert n2.tags == ["tiere", "test"]


def test_node_roundtrip_umlauts():
    n = Node(text="Ideen mit Ümläuten und ß")
    n2 = Node.from_markdown(n.to_markdown())
    assert n2.text == "Ideen mit Ümläuten und ß"


def test_node_from_markdown_rejects_plain_text():
    import pytest
    with pytest.raises(ValueError):
        Node.from_markdown("kein frontmatter")


# ---------- Brain FS ----------

def test_write_and_read_nodes(tmp_path):
    brain = make_brain(tmp_path)
    brain.write_node(Node(id="aaa", text="Erste Idee"))
    brain.write_node(Node(id="bbb", text="Zweite Idee"))
    nodes = brain.read_nodes()
    assert [n.id for n in nodes] == ["aaa", "bbb"]


def test_edges_roundtrip_and_resolve(tmp_path):
    brain = make_brain(tmp_path)
    e = Edge(source="a", target="b", kind="similar")
    brain.add_edge(e)
    resolved = brain.resolve_edge(e.id, accept=True)
    assert resolved is not None and resolved.pending is False
    assert all(not x.pending for x in brain.read_edges())


def test_edge_reject_removes(tmp_path):
    brain = make_brain(tmp_path)
    e = Edge(source="a", target="b", kind="extends")
    brain.add_edge(e)
    brain.resolve_edge(e.id, accept=False)
    assert brain.read_edges() == []


def test_resolve_unknown_returns_none(tmp_path):
    brain = make_brain(tmp_path)
    assert brain.resolve_edge("gibtsnicht", accept=True) is None


def test_undo_accept_returns_edge_to_inbox(tmp_path):
    brain = make_brain(tmp_path)
    edge = Edge(source="a", target="b", kind="similar")
    brain.add_edge(edge)
    engine = BrainEngine(brain, HashEmbedder())
    engine.resolve(edge.id, accept=True)
    restored = engine.undo(edge.id)
    assert restored.id == edge.id and restored.pending
    assert brain.graph_state()["edges"] == [edge.to_dict()]
    assert engine.undo(edge.id) is None


def test_undo_reject_survives_reload_and_other_decisions(tmp_path):
    brain = make_brain(tmp_path)
    first = Edge(source="a", target="b", kind="similar")
    second = Edge(source="b", target="c", kind="extends")
    brain.add_edge(first)
    brain.resolve_edge(first.id, accept=False)
    assert brain.graph_state()["edges"] == []
    # Adding and resolving other edges must preserve the rejected record.
    brain.add_edge(second)
    brain.resolve_edge(second.id, accept=True)
    reloaded = make_brain(tmp_path)
    restored = reloaded.restore_edge(first.id)
    assert restored.id == first.id and restored.pending and not restored.rejected
    assert len(reloaded.read_edges()) == 2
    assert reloaded.restore_edge("unknown") is None


def test_rejected_edge_cannot_be_resolved_again(tmp_path):
    brain = make_brain(tmp_path)
    edge = Edge(source="a", target="b", kind="similar")
    brain.add_edge(edge)
    brain.resolve_edge(edge.id, accept=False)
    assert brain.resolve_edge(edge.id, accept=True) is None
    assert brain.read_edges() == []


def test_graph_state_shape(tmp_path):
    brain = make_brain(tmp_path)
    brain.write_node(Node(id="a", text="x"))
    brain.add_edge(Edge(source="a", target="a", kind="similar"))
    state = brain.graph_state()
    assert len(state["nodes"]) == 1 and len(state["edges"]) == 1


def test_index_rebuild(tmp_path):
    brain = make_brain(tmp_path)
    brain.write_node(Node(id="a", text="Eine tolle Idee"))
    brain.rebuild_index()
    index = (brain.path / "INDEX.md").read_text(encoding="utf-8")
    assert "nodes/a.md" in index and "Eine tolle Idee" in index


# ---------- Engine-Loop ----------

def test_engine_ingest_creates_files(tmp_path):
    brain = make_brain(tmp_path)
    engine = BrainEngine(brain, HashEmbedder())
    node1, e1, _ = engine.ingest("Katzen jagen Maeuse nachts", source="agent/test")
    node2, e2, _ = engine.ingest("Katzen schlafen am Tag", source="human")
    assert (brain.path / "nodes" / f"{node1.id}.md").exists()
    assert (brain.path / "nodes" / f"{node2.id}.md").exists()
    for edge in e1 + e2:
        assert edge.pending is True
        assert any(x.id == edge.id for x in brain.read_edges())


def test_engine_empty_raises(tmp_path):
    import pytest
    engine = BrainEngine(make_brain(tmp_path), HashEmbedder())
    with pytest.raises(ValueError):
        engine.ingest("   ")


def test_engine_suggests_similar_kind(tmp_path):
    emb = HashEmbedder()
    brain = make_brain(tmp_path)
    engine = BrainEngine(brain, emb)
    _, _, _ = engine.ingest("katze hund tier futter")
    _, edges, _ = engine.ingest("katze hund tier spiel")
    kinds = {e.kind for e in edges}
    assert kinds <= {"similar", "extends"}


def test_engine_dedupes_exact_duplicate(tmp_path):
    emb = HashEmbedder()
    brain = make_brain(tmp_path)
    engine = BrainEngine(brain, emb)
    node1, _, dup1 = engine.ingest("Katzen jagen Maeuse nachts", source="agent/test")
    node2, edges, dup2 = engine.ingest("Katzen jagen Maeuse nachts", source="human")
    assert not dup1 and dup2
    assert node2.id == node1.id
    assert edges == []
    nodes = brain.read_nodes()
    assert len(nodes) == 1
    assert "human" in nodes[0].sources
    assert "agent/test" in nodes[0].sources


def test_engine_dedupe_ignores_case_and_whitespace(tmp_path):
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    node1, _, _ = engine.ingest("Katzen jagen Maeuse nachts")
    node2, _, dup = engine.ingest("  katzen JAGEN maeuse   NACHTS ")
    assert dup and node2.id == node1.id


def test_engine_dedupe_can_be_disabled(tmp_path):
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    n1, _, _ = engine.ingest("Katzen jagen Maeuse nachts")
    n2, _, dup = engine.ingest("Katzen jagen Maeuse nachts", allow_duplicates=True)
    assert not dup and n2.id != n1.id


def test_engine_no_false_positive_dedupe(tmp_path):
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    engine.ingest("Katzen jagen Maeuse nachts")
    _, _, dup = engine.ingest("Rust Compiler borrow checker lifetime Regeln")
    assert not dup


def test_embedding_cache_hit(tmp_path):
    emb = HashEmbedder()
    brain = make_brain(tmp_path)
    engine = BrainEngine(brain, emb)
    engine.ingest("Katzen jagen Maeuse nachts")
    assert (tmp_path / "brain" / "vectors.jsonl").exists()
    calls = emb.calls if hasattr(emb, "calls") else None
    # second ingest: the old node must not be re-embedded
    class Counting(HashEmbedder):
        def __init__(self):
            self.n = 0
        def embed(self, text):
            self.n += 1
            return super().embed(text)
    c = Counting()
    e2 = BrainEngine(brain, c)
    e2.ingest("Hunde bellen laute geraeusche")
    # embed calls: 1 for dup-check new node, 0 for old (cache), 1 cache-fill if old was missing
    assert c.n <= 3


def test_edge_suggestion_dedupe(tmp_path):
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    engine.ingest("katze hund tier futter", allow_duplicates=True)
    n2, _, _ = engine.ingest("katze hund tier spiel")
    before = len(engine.brain.read_edges())
    # third ingest similar to both: no duplicate (source,target) suggestions
    _, edges3, _ = engine.ingest("katze hund tier futter spiel", allow_duplicates=True)
    pairs_before = [(e.source, e.target) for e in engine.brain.read_edges()]
    assert len(pairs_before) == len(set(pairs_before))


def test_engine_link_same_as(tmp_path):
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    n1, _, _ = engine.ingest("Katzen jagen Maeuse")
    n2, _, _ = engine.ingest("Cats hunt mice", allow_duplicates=True)
    edge = engine.link(n1.id, n2.id, "same_as")
    assert edge.kind == "same_as" and not edge.pending
    assert (edge.source, edge.target) in {(e.source, e.target) for e in engine.brain.read_edges()}


def test_engine_link_rejects_unknown_node(tmp_path):
    import pytest
    engine = BrainEngine(make_brain(tmp_path), HashEmbedder())
    n1, _, _ = engine.ingest("Katzen jagen Maeuse")
    with pytest.raises(ValueError):
        engine.link(n1.id, "gibtsnicht", "same_as")


def test_engine_link_rejects_duplicate_edge(tmp_path):
    import pytest
    engine = BrainEngine(make_brain(tmp_path), HashEmbedder())
    n1, _, _ = engine.ingest("Katzen jagen Maeuse")
    n2, _, _ = engine.ingest("Cats hunt mice", allow_duplicates=True)
    engine.link(n1.id, n2.id, "same_as")
    with pytest.raises(ValueError):
        engine.link(n1.id, n2.id, "same_as")


def test_auto_accept_edges(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEAGRAPH_AUTO_ACCEPT", "1")
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    _, edges, _ = engine.ingest("katze hund tier futter")
    _, edges2, _ = engine.ingest("katze hund tier spiel")
    assert all(not e.pending for e in edges2)
    assert not any(e.pending for e in engine.brain.read_edges())
    monkeypatch.delenv("IDEAGRAPH_AUTO_ACCEPT")


def test_default_still_pending(monkeypatch, tmp_path):
    monkeypatch.delenv("IDEAGRAPH_AUTO_ACCEPT", raising=False)
    engine = BrainEngine(make_brain(tmp_path), HashEmbedder())
    engine.ingest("katze hund tier futter")
    _, edges2, _ = engine.ingest("katze hund tier spiel")
    assert all(e.pending for e in edges2)


def test_edge_bi_temporal_fields(tmp_path):
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    _, edges, _ = engine.ingest("katze hund tier futter")
    _, edges2, _ = engine.ingest("katze hund tier spiel")
    e = engine.brain.read_edges()[0]
    assert e.valid_from  # set
    assert e.valid_to is None
    # invalidate instead of delete
    invalidated = engine.brain.invalidate_edge(e.id)
    assert invalidated is not None and invalidated.valid_to is not None
    assert any(x.id == e.id and x.valid_to for x in engine.brain.read_edges())


def test_node_type_taxonomy_roundtrip(tmp_path):
    brain = make_brain(tmp_path)
    emb = HashEmbedder()
    engine = BrainEngine(brain, emb)
    node, _, _ = engine.ingest("Wie ingestiere ich Research-Results: ig ingest ...",
                               ntype="procedural")
    stored = next(n for n in brain.read_nodes() if n.id == node.id)
    assert stored.ntype == "procedural"
    assert "type: procedural" in (brain.node_path(node.id)).read_text()


def test_memory_evolution_appends_crossref(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEAGRAPH_AUTO_ACCEPT", "1")
    emb = HashEmbedder()
    brain = make_brain(tmp_path)
    engine = BrainEngine(brain, emb)
    engine.ingest("katze hund tier futter")
    engine.ingest("katze hund tier spiel")  # strong similarity → evolution
    texts = [n.text for n in brain.read_nodes()]
    assert any("evolved" in t for t in texts)
    monkeypatch.delenv("IDEAGRAPH_AUTO_ACCEPT")


def test_no_evolution_without_auto_accept(monkeypatch, tmp_path):
    monkeypatch.delenv("IDEAGRAPH_AUTO_ACCEPT", raising=False)
    engine = BrainEngine(make_brain(tmp_path), HashEmbedder())
    engine.ingest("katze hund tier futter")
    engine.ingest("katze hund tier spiel")
    assert not any("evolved" in n.text for n in engine.brain.read_nodes())


# ---------- Onboarding: ig init / ensure_ready ----------

def test_init_creates_brain_structure(tmp_path):
    brain = Brain(str(tmp_path / "brain"), mode="local")
    brain.init(remote=None, commit=False)
    assert (brain.path / "nodes").is_dir()
    assert brain.edges_file.exists()
    assert brain.vectors_file.exists()
    assert (brain.path / "INDEX.md").exists()
    # idempotent: a repeated init overwrites nothing
    brain.init(remote=None, commit=False)
    assert (brain.path / "nodes").is_dir()


def test_init_git_sets_main_branch(tmp_path):
    brain = Brain(str(tmp_path / "brain"), mode="git")
    brain.init(remote=None, commit=True)
    branch = subprocess.run(
        ["git", "-C", str(brain.path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True).stdout.strip()
    assert branch == "main"
    # initial commit exists
    log = subprocess.run(["git", "-C", str(brain.path), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert "init" in log


def test_ingest_auto_inits_missing_brain(tmp_path):
    """ensure_ready: `ig ingest` on a fresh machine creates the brain."""
    brain = Brain(str(tmp_path / "brain"), mode="local")
    engine = BrainEngine(brain, HashEmbedder())
    node, _, _ = engine.ingest("Erste Idee fuer den Demo-Graph")
    assert (brain.path / "nodes").is_dir()
    assert any(n.id == node.id for n in brain.read_nodes())


def test_undo_preserves_edge_metadata_and_invalidated_facts(tmp_path):
    brain = make_brain(tmp_path)
    edge = Edge(source="a", target="b", kind="similar", confidence=.82,
                valid_from="2026-08-01T00:00:00Z", invalidated_by="prior-event")
    brain.add_edge(edge)
    brain.resolve_edge(edge.id, accept=False)
    assert brain.restore_edge(edge.id).to_dict() == edge.to_dict()
    brain.resolve_edge(edge.id, accept=True)
    brain.invalidate_edge(edge.id, by_edge_id="new-fact")
    assert brain.restore_edge(edge.id) is None
    saved = brain.read_edges()[0]
    assert saved.valid_to is not None and saved.invalidated_by == "new-fact"


def test_invalidation_preserves_unrelated_undo_record(tmp_path):
    brain = make_brain(tmp_path)
    rejected = Edge(source="a", target="b", kind="similar")
    other = Edge(source="b", target="c", kind="extends", pending=False)
    brain.add_edge(rejected)
    brain.add_edge(other)
    brain.resolve_edge(rejected.id, accept=False)
    brain.invalidate_edge(other.id)
    assert brain.restore_edge(rejected.id).pending

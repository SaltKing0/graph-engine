"""Tests for near-duplicate consolidation (`ig merge`).

Define the expected behavior of merge_nodes: edge redirection,
dedup, self-loop removal, text merging, vector cleanup,
INDEX rebuild — before building further on top of it.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.brain import Brain, Node, Edge
from graph_engine.merge import merge_nodes


def _brain(tmp_path) -> Brain:
    return Brain(str(tmp_path / "brain"), mode="local")


def _add_edge(b: Brain, s: str, t: str, kind: str = "extends") -> None:
    b.add_edge(Edge(source=s, target=t, kind=kind, pending=False))


def test_merge_redirects_edges_and_removes_node(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    b.write_node(Node(id="t", text="Target"))
    _add_edge(b, "d", "t")  # deletee -> target
    r = merge_nodes(b, "s", "d", commit=False)
    nodes = {n.id: n for n in b.read_nodes()}
    # Audit #3 fix: deletee is tombstoned instead of hard-deleted
    assert nodes["d"].status == "tombstone" and "s" in nodes and "t" in nodes
    edges = b.read_edges()
    # d->t was redirected to s->t
    assert any(e.source == "s" and e.target == "t" for e in edges)
    assert not any(e.source == "d" or e.target == "d" for e in edges)
    assert r.edges_redirected == 1


def test_merge_dedupes_shared_target(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    b.write_node(Node(id="t", text="Target"))
    _add_edge(b, "s", "t")
    _add_edge(b, "d", "t")
    r = merge_nodes(b, "s", "d", commit=False)
    edges = b.read_edges()
    assert sum(1 for e in edges if e.source == "s" and e.target == "t") == 1
    assert r.edges_removed >= 1


def test_merge_removes_self_loop(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    _add_edge(b, "s", "d")  # mutual edge -> self loop after merge
    r = merge_nodes(b, "s", "d", commit=False)
    edges = b.read_edges()
    assert not any(e.source == e.target for e in edges)
    assert r.edges_removed >= 1


def test_merge_combines_text(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor-Text"))
    b.write_node(Node(id="d", text="Deletee-Text"))
    merge_nodes(b, "s", "d", commit=False)
    s = next(n for n in b.read_nodes() if n.id == "s")
    assert "Survivor-Text" in s.text and "Deletee-Text" in s.text


def test_merge_drops_vector(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    b.write_node(Node(id="t", text="Target"))
    vec = b.path / "vectors.jsonl"
    vec.write_text(json.dumps({"id": "s", "vec": [1.0]}) + "\n"
                   + json.dumps({"id": "d", "vec": [2.0]}) + "\n"
                   + json.dumps({"id": "t", "vec": [3.0]}) + "\n", encoding="utf-8")
    merge_nodes(b, "s", "d", commit=False)
    ids = {json.loads(l)["id"] for l in vec.read_text().splitlines() if l.strip()}
    assert "d" not in ids and "s" in ids and "t" in ids


def test_merge_rebuilds_index(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    merge_nodes(b, "s", "d", commit=False)
    index = (b.path / "INDEX.md").read_text(encoding="utf-8")
    assert "nodes/d.md" not in index and "nodes/s.md" in index  # tombstone not in index


def test_merge_missing_node_raises(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    try:
        merge_nodes(b, "s", "missing", commit=False)
        assert False, "should raise ValueError"
    except ValueError:
        pass


def test_merge_identical_raises(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    try:
        merge_nodes(b, "s", "s", commit=False)
        assert False, "should raise ValueError"
    except ValueError:
        pass


def test_merge_preserves_only_undo_records_with_surviving_nodes(tmp_path):
    brain = _brain(tmp_path)
    for id in ("survivor", "deletee", "other"):
        brain.write_node(Node(id=id, text=id))
    unrelated = Edge(source="survivor", target="other", kind="similar")
    deleted = Edge(source="deletee", target="other", kind="similar")
    for edge in (unrelated, deleted):
        brain.add_edge(edge)
        brain.resolve_edge(edge.id, accept=False)
    merge_nodes(brain, "survivor", "deletee", commit=False)
    assert brain.read_edges() == []
    assert brain.restore_edge(unrelated.id).pending
    assert brain.restore_edge(deleted.id) is None


# ---------- Audit #3/#9/#41: merge semantics ----------

def test_merge_tombstones_instead_of_resurrecting(tmp_path):
    """Audit #3: deletee was put on probation and lived on — now tombstone."""
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee", status="active"))
    merge_nodes(b, "s", "d", commit=False)
    d = next(n for n in b.read_nodes() if n.id == "d")
    assert d.status == "tombstone"


def test_merge_no_dangling_edges(tmp_path):
    """Audit #3: deletee->third kept pointing at the deletee ID (dangling)."""
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    b.write_node(Node(id="t", text="Third"))
    _add_edge(b, "d", "t")
    merge_nodes(b, "s", "d", commit=False)
    edges = b.read_edges()
    assert edges and edges[0].source == "s" and edges[0].target == "t"
    assert not any(e.source == "d" or e.target == "d" for e in edges)


def test_merge_does_not_invert_directional_intent(tmp_path):
    """Audit #9: deletee->X supersedes was inverted into survivor->X supersedes.

    The survivor does not inherit the claim "supersedes X" — the edge is
    invalidated (valid_to set, history preserved) instead of inverted.
    """
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    b.write_node(Node(id="x", text="X"))
    _add_edge(b, "d", "x", kind="supersedes")
    r = merge_nodes(b, "s", "d", commit=False)
    edges = b.read_edges()
    assert not any(e.kind == "supersedes" and e.source == "s" for e in edges), \
        "intent edge must not be rewritten onto the survivor"
    assert r.edges_invalidated == 1
    # preserve history: check via include_rejected/pending raw data
    raw = [json.loads(l) for l in (b.path / "edges.jsonl").read_text().splitlines() if l.strip()]
    sup = [e for e in raw if e["kind"] == "supersedes"]
    assert sup and sup[0]["valid_to"] is not None  # invalidated, not deleted


def test_merge_redirects_neutral_kinds(tmp_path):
    """Direction-neutral kinds (similar/extends) redirect normally."""
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    b.write_node(Node(id="t", text="Third"))
    _add_edge(b, "d", "t", kind="similar")
    _add_edge(b, "x", "d", kind="extends")
    b.write_node(Node(id="x", text="X"))
    r = merge_nodes(b, "s", "d", commit=False)
    edges = b.read_edges()
    assert any(e.source == "s" and e.target == "t" and e.kind == "similar" for e in edges)
    assert any(e.source == "x" and e.target == "s" and e.kind == "extends" for e in edges)
    assert r.edges_redirected == 2


def test_merge_records_provenance(tmp_path):
    """Audit #41: merge provenance in survivor text + commit message."""
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee-Text"))
    r = merge_nodes(b, "s", "d", commit=False)
    s = next(n for n in b.read_nodes() if n.id == "s")
    assert f"[consolidated from {r.deletee} on" in s.text
    assert "Deletee-Text" in s.text


def test_merge_survivor_vector_refreshed_is_out_of_scope_here(tmp_path):
    """Audit #41 (part): the survivor text grows — the cached vector is now
    stale. The merge documents this; the fix follows in batch 5 (retrieval)."""
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee-Text"))
    b.write_vectors({"s": [1.0, 2.0], "d": [3.0, 4.0]})
    merge_nodes(b, "s", "d", commit=False)
    vecs = b.read_vectors()
    assert "d" not in vecs and "s" in vecs  # deletee vector gone, survivor stays

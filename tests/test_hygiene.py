"""Unit tests for memory hygiene (V2#2): status/probation, consolidation (dedup),
graceful-degradation demotion, invalidated_by provenance (V1#1)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.brain import Brain, Node, Edge, VALID_STATUS
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder


def make_brain(tmp_path) -> Brain:
    return Brain(str(tmp_path / "brain"), mode="local")


def make_engine(tmp_path) -> BrainEngine:
    return BrainEngine(make_brain(tmp_path), HashEmbedder())


# ---------- Status / dual buffer ----------

def test_node_status_defaults_to_probation():
    n = Node(text="neu")
    assert n.status == "probation"


def test_node_status_roundtrip():
    n = Node(text="x", status="active")
    n2 = Node.from_markdown(n.to_markdown())
    assert n2.status == "active"
    assert "status: active" in n.to_markdown()


def test_valid_status():
    # `stale` (Welle B/2) is the demotion target of `ig dream --lifecycle`:
    # a node that is unused, weakly connected and old. It stays a valid status
    # (never a tombstone) so the node remains in the file and in search.
    assert VALID_STATUS == ("probation", "active", "stale", "tombstone")


def test_ingest_creates_probation_node(tmp_path):
    eng = make_engine(tmp_path)
    node, _, _ = eng.ingest("katze hund tier futter")
    stored = next(n for n in eng.brain.read_nodes() if n.id == node.id)
    assert stored.status == "probation"


# ---------- Consolidation (dedup-based) ----------

def test_consolidate_promotes_distinct_probation(tmp_path):
    eng = make_engine(tmp_path)
    eng.ingest("katze hund tier futter")
    eng.ingest("quantenmechanik wellenfunktion schroedinger")
    statuses = {n.status for n in eng.brain.read_nodes()}
    assert statuses == {"probation"}
    report = eng.consolidate()
    assert report["promoted"] == 2 and report["merged"] == 0
    assert {n.status for n in eng.brain.read_nodes()} == {"active"}


def test_consolidate_dedups_cross_probation(tmp_path):
    # Two nearly identical nodes coexist (allow_duplicates) → both probation.
    # Consolidate must DEDUPE them (not merge): one promoted,
    # the duplicate becomes tombstoned.
    eng = make_engine(tmp_path)
    eng.ingest("katze hund tier futter", source="a")
    eng.ingest("katze hund tier futter", source="b", allow_duplicates=True)
    assert len(eng.brain.read_nodes()) == 2
    report = eng.consolidate()
    assert report["merged"] == 1 and report["promoted"] == 1
    nodes = eng.brain.read_nodes()
    assert len(nodes) == 2
    survivor = next(n for n in nodes if n.status == "active")
    tomb = next(n for n in nodes if n.status == "tombstone")
    assert {"a", "b"} <= set(survivor.sources)


def test_consolidate_empty_is_noop(tmp_path):
    assert make_engine(tmp_path).consolidate() == {"promoted": 0, "merged": 0}


# ---------- Graceful Degradation ----------

def test_demote_forgotten_tombstones_active(tmp_path):
    eng = make_engine(tmp_path)
    eng.ingest("katze hund tier futter")
    eng.consolidate()  # → active
    # level_fn: everything becomes tombstone
    count = eng.demote_forgotten(lambda node: "tombstone")
    assert count == 1
    assert all(n.status == "tombstone" for n in eng.brain.read_nodes())


def test_demote_forgotten_keeps_frequent(tmp_path):
    eng = make_engine(tmp_path)
    eng.ingest("katze hund tier futter")
    eng.ingest("quantenmechanik wellenfunktion schroedinger")
    eng.consolidate()  # both active
    # only the node with "katze" is forgotten
    count = eng.demote_forgotten(lambda n: "tombstone" if "katze" in n.text else "record")
    assert count == 1
    statuses = {n.text: n.status for n in eng.brain.read_nodes()}
    assert statuses["katze hund tier futter"] == "tombstone"
    assert statuses["quantenmechanik wellenfunktion schroedinger"] == "active"


# ---------- invalidated_by provenance (V1#1) ----------

def test_invalidate_edge_records_provenance(tmp_path):
    brain = make_brain(tmp_path)
    e1 = Edge(source="a", target="b", kind="extends")
    e2 = Edge(source="b", target="c", kind="similar")
    brain.add_edge(e1)
    brain.add_edge(e2)
    invalidated = brain.invalidate_edge(e1.id, by_edge_id=e2.id)
    assert invalidated is not None
    assert invalidated.valid_to is not None
    assert invalidated.invalidated_by == e2.id
    # roundtrip through the file
    reloaded = next(e for e in brain.read_edges() if e.id == e1.id)
    assert reloaded.invalidated_by == e2.id


# ---------- Intent edges + admit rule (V2#3) ----------

def test_ingest_contradiction_edge(tmp_path):
    eng = make_engine(tmp_path)
    eng.ingest("Die Erde ist eine Scheibe")
    _, edges, _ = eng.ingest("Die Erde ist keine Scheibe, sondern eine Kugel")
    kinds = {e.kind for e in edges}
    assert "contradicts" in kinds
    assert all(not e.pending for e in edges if e.kind == "contradicts")


def test_ingest_supersedes_edge(tmp_path):
    eng = make_engine(tmp_path)
    eng.ingest("API v1 wird verwendet")
    _, edges, _ = eng.ingest("API v2 ersetzt v1")
    assert any(e.kind == "supersedes" for e in edges)


def test_intent_pending_config(tmp_path, monkeypatch):
    # Default (env unset): intent edges are auto-accepted (not pending).
    eng = make_engine(tmp_path)
    eng.ingest("Die Erde ist eine Scheibe")
    _, edges, _ = eng.ingest("Die Erde ist keine Scheibe, sondern eine Kugel")
    assert any(e.kind == "contradicts" and not e.pending for e in edges)
    # With IDEAGRAPH_INTENT_PENDING=1: intent edges become pending (HITL).
    monkeypatch.setenv("IDEAGRAPH_INTENT_PENDING", "1")
    eng2 = make_engine(tmp_path / "b2")  # fresh brain, otherwise dedupe against eng
    eng2.ingest("Die Erde ist eine Scheibe")
    _, edges2, _ = eng2.ingest("Die Erde ist keine Scheibe, sondern eine Kugel")
    assert any(e.kind == "contradicts" and e.pending for e in edges2)


def test_admit_rule_declared_relations(tmp_path):
    eng = make_engine(tmp_path)
    base, _, _ = eng.ingest("Grundlagen der Quantenmechanik")
    _, edges, _ = eng.ingest(
        "Vertiefung zur Quantenmechanik",
        relations=[(base.text, "continues")],
    )
    assert any(e.kind == "continues" for e in edges)
    assert all(not e.pending for e in edges if e.kind == "continues")

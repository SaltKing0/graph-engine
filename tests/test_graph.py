"""Unit tests for graph_engine/graph.py traversal (report #1 phase 1).

All fixtures use deterministic node ids (the LPA lesson applies to BFS
ordering too) and the HashEmbedder; measured cosines put the fixture
texts in the intended bands (similar 0.875, extends 0.75, cross < 0.3).
"""
from __future__ import annotations

import shutil
import tempfile

from graph_engine.brain import Brain, Edge, Node
from graph_engine.graph import live_edges, neighbors, shortest_path

TEXTS = {
    "hub": "agent memory systems store knowledge graphs for retrieval",
    "leafA": "agent memory systems store knowledge graphs for retrieval and search",
    "leafB": "agent memory systems store knowledge graphs for retrieval but slower",
    "far": "unrelated note about gardening tomatoes and weather",
}


def _brain_with_edges() -> tuple[Brain, dict[str, str]]:
    """Nodes written DIRECTLY (no engine.ingest) so the suggester adds no
    edges of its own — every edge in the fixture is explicit."""
    td = tempfile.TemporaryDirectory()
    brain = Brain(td.name, mode="local")
    brain._td = td
    ids: dict[str, str] = {}
    for key, text in TEXTS.items():
        node = Node(id=f"fix_{key}", text=text)
        brain.write_node(node)
        ids[key] = node.id
    return brain, ids


def _teardown(brain: Brain) -> None:
    td = getattr(brain, "_td", None)
    if td is not None:
        shutil.rmtree(td.name, ignore_errors=True)
        td.cleanup()


def _add_edges(brain: Brain, *edges: Edge) -> None:
    brain.write_edges(edges=list(brain.read_edges()) + list(edges))


def test_live_edges_excludes_invalidated_rejected_and_tombstones():
    brain, ids = _brain_with_edges()
    try:
        dead = Node(id="deadnode", text="a tombstoned node")
        brain.write_node(dead)
        dead.status = "tombstone"
        brain.write_node(dead)
        _add_edges(brain,
                   Edge(source=ids["hub"], target=ids["leafA"], kind="similar",
                        pending=False),
                   Edge(source=ids["hub"], target=ids["leafB"], kind="similar",
                        pending=False, valid_to="2026-01-01T00:00:00"),
                   Edge(source=ids["hub"], target=ids["far"], kind="similar",
                        pending=False, rejected=True),
                   Edge(source=ids["hub"], target="deadnode", kind="similar",
                        pending=False))
        live = live_edges(brain)
        assert len(live) == 1
        assert {live[0].source, live[0].target} == {ids["hub"], ids["leafA"]}
    finally:
        _teardown(brain)


def test_live_edges_pending_flag():
    brain, ids = _brain_with_edges()
    try:
        _add_edges(brain, Edge(source=ids["hub"], target=ids["leafA"],
                               kind="similar", pending=True))
        assert live_edges(brain) == []
        assert len(live_edges(brain, include_pending=True)) == 1
    finally:
        _teardown(brain)


def test_neighbors_undirected_hop1_deterministic():
    brain, ids = _brain_with_edges()
    try:
        _add_edges(brain,
                   Edge(source=ids["hub"], target=ids["leafA"], kind="similar",
                        pending=False),
                   Edge(source=ids["hub"], target=ids["leafB"], kind="extends",
                        pending=False))
        nb = neighbors(brain, ids["hub"])
        # documented order: (hops, kind, id) — "extends" sorts before "similar"
        assert [n.id for n in nb] == [ids["leafB"], ids["leafA"]]
        # deterministic across calls
        assert [n.id for n in neighbors(brain, ids["hub"])] == [n.id for n in nb]
        by_id = {n.id: n for n in nb}
        assert by_id[ids["leafA"]].kind == "similar"
        assert by_id[ids["leafA"]].hops == 1
        assert by_id[ids["leafA"]].direction == "out"  # edge points hub -> leafA
        # and the reverse view: from leafA the same edge points "in"
        back = {n.id: n for n in neighbors(brain, ids["leafA"])}
        assert back[ids["hub"]].direction == "in"
    finally:
        _teardown(brain)


def test_neighbors_hops2_reaches_second_ring():
    brain, ids = _brain_with_edges()
    try:
        _add_edges(brain,
                   Edge(source=ids["hub"], target=ids["leafA"], kind="similar",
                        pending=False),
                   Edge(source=ids["leafA"], target=ids["far"], kind="extends",
                        pending=False))
        one = neighbors(brain, ids["hub"], hops=1)
        assert [n.id for n in one] == [ids["leafA"]]
        two = neighbors(brain, ids["hub"], hops=2)
        assert [n.id for n in two] == [ids["leafA"], ids["far"]]
        assert two[0].hops == 1 and two[1].hops == 2
    finally:
        _teardown(brain)


def test_neighbors_kinds_filter_and_limit():
    brain, ids = _brain_with_edges()
    try:
        _add_edges(brain,
                   Edge(source=ids["hub"], target=ids["leafA"], kind="similar",
                        pending=False),
                   Edge(source=ids["hub"], target=ids["leafB"], kind="extends",
                        pending=False))
        sim = neighbors(brain, ids["hub"], kinds=["similar"])
        assert [n.kind for n in sim] == ["similar"]
        limited = neighbors(brain, ids["hub"], limit=1)
        assert len(limited) == 1
        assert limited[0].kind == "extends"  # sorted (hops, kind, id)
    finally:
        _teardown(brain)


def test_neighbors_unknown_node_returns_empty():
    brain, _ = _brain_with_edges()
    try:
        assert neighbors(brain, "nope") == []
    finally:
        _teardown(brain)


def test_shortest_path_direct_and_through_hub():
    brain, ids = _brain_with_edges()
    try:
        _add_edges(brain,
                   Edge(source=ids["hub"], target=ids["leafA"], kind="similar",
                        pending=False),
                   Edge(source=ids["leafA"], target=ids["leafB"], kind="extends",
                        pending=False))
        # direct edge leafA-leafB wins over the 2-hop route via hub
        assert shortest_path(brain, ids["leafA"], ids["leafB"]) ==             [ids["leafA"], ids["leafB"]]
        # hub -> leafB goes through leafA
        assert shortest_path(brain, ids["hub"], ids["leafB"]) ==             [ids["hub"], ids["leafA"], ids["leafB"]]
        assert shortest_path(brain, ids["hub"], ids["hub"]) == [ids["hub"]]
    finally:
        _teardown(brain)


def test_shortest_path_depth_cap_and_unreachable():
    brain, ids = _brain_with_edges()
    try:
        _add_edges(brain,
                   Edge(source=ids["hub"], target=ids["leafA"], kind="similar",
                        pending=False),
                   Edge(source=ids["leafA"], target=ids["leafB"], kind="extends",
                        pending=False))
        # depth cap 1: hub->leafB needs 2 hops
        assert shortest_path(brain, ids["hub"], ids["leafB"], max_depth=1) is None
        # far node has no edges at all
        assert shortest_path(brain, ids["far"], ids["hub"]) is None
    finally:
        _teardown(brain)

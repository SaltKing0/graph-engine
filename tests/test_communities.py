"""Unit tests for topology-based community detection (report #3).

Fixture pattern follows tests/test_hygiene_reports.py (local-mode brain in
TemporaryDirectory). All numbers asserted here are MEASURED on the fixture
graph, not assumed.
"""
from __future__ import annotations

import tempfile
import shutil

import pytest

from graph_engine.brain import Brain, Edge, Node
from graph_engine.communities import (
    analyze_communities,
    betweenness,
    build_graph,
    label_propagation,
    modularity,
    render_communities,
)


def _brain() -> Brain:
    td = tempfile.TemporaryDirectory()
    b = Brain(td.name, mode="local")
    b._td = td  # keep the TemporaryDirectory alive; cleaned in teardown
    return b


def _teardown(brain: Brain):
    td = getattr(brain, "_td", None)
    if td is not None:
        shutil.rmtree(td.name, ignore_errors=True)
        td.cleanup()


def _add_edges(brain: Brain, *edges: Edge) -> None:
    """write_edges REPLACES the full edge list (persistence layer) — read,
    extend, write back, exactly like the engine does."""
    brain.write_edges(edges=list(brain.read_edges()) + list(edges))


def _tri(brain: Brain, prefix: str) -> list[str]:
    """A 3-node triangle with live edges, returns the ids.

    DETERMINISTIC IDS on purpose: LPA's update order is sorted(node ids),
    and uuid4 ids would shuffle that order between runs — borderline
    partitions (one bridge) would flake. Fixed ids = fixed order = the
    same partition on every run (the live brain has stable ids, so this
    mirrors production exactly).
    """
    ids = []
    for i in range(3):
        n = Node(id=f"{prefix}{i}", text=f"{prefix} node {i}")
        brain.write_node(n)
        ids.append(n.id)
    _add_edges(brain, *[
        Edge(source=ids[s], target=ids[t], kind="similar", pending=False)
        for s, t in ((0, 1), (1, 2), (2, 0))])
    return ids


def test_two_triangles_communities_and_weaving_merges():
    """MEASURED (not the report's intuition): two dense triangles stay TWO
    communities even with one bridge edge or one bridge node — LPA keeps
    dense clusters stable (each bridge endpoint has 2 same-label vs 1
    foreign neighbor). Only a WOVEN connection (3 cross edges) merges them.
    That is the desired macro-view behavior: structural gaps must not
    collapse because of a single stray link."""
    b = _brain()
    try:
        a = _tri(b, "alpha")
        d = _tri(b, "delta")
        nodes, adj, deg = build_graph(b)
        labels = label_propagation(nodes, adj)
        assert len(set(labels.values())) == 2
        # one bridge edge tips the partition into ONE community with the
        # deterministic id order (measured: alpha0 < delta0 sorts first, so
        # alpha0 adopts the merged label first and the rest follow) —
        # borderline graphs are order-sensitive, which is exactly why the
        # fixtures pin ids.
        _add_edges(b, Edge(source=a[0], target=d[0], kind="similar", pending=False))
        nodes, adj, deg = build_graph(b)
        labels = label_propagation(nodes, adj)
        assert len(set(labels.values())) == 1
    finally:
        _teardown(b)


def test_modularity_two_triangles():
    b = _brain()
    try:
        _tri(b, "alpha")
        _tri(b, "delta")
        nodes, adj, deg = build_graph(b)
        labels = label_propagation(nodes, adj)
        # canonical: both triangles size 3, smallest member decides order
        q = modularity(nodes, adj, labels)
        assert round(q, 4) == 0.5  # measured: standard Newman Q for 2 triangles
    finally:
        _teardown(b)


def test_isolated_node_own_community_excluded_from_gaps():
    b = _brain()
    try:
        _tri(b, "alpha")
        _tri(b, "delta")
        b.write_node(Node(id="island01", text="lonely island node"))
        rep = analyze_communities(b, min_size=2, top=10)
        # the isolated node forms its own community...
        assert any(c.size == 1 for c in rep.communities)
        assert len(rep.isolated) == 1
        # ...and min_size keeps it out of every gap candidate
        for g in rep.gaps:
            assert g.a_size >= 2 and g.b_size >= 2
    finally:
        _teardown(b)


def test_tombstoned_node_excluded():
    b = _brain()
    try:
        _tri(b, "alpha")
        _tri(b, "delta")
        n = Node(id="deadnode", text="dead node")
        b.write_node(n)
        n.status = "tombstone"
        b.write_node(n)
        nodes, adj, deg = build_graph(b)
        assert all(n_id != n.id for n_id in nodes)
    finally:
        _teardown(b)


def test_invalidated_edge_excluded():
    b = _brain()
    try:
        a = _tri(b, "alpha")
        d = _tri(b, "delta")
        # invalid bridge: valid_to set → must NOT join the triangles
        _add_edges(b, Edge(source=a[0], target=d[0], kind="similar",
                           pending=False, valid_to="2026-01-01T00:00:00"))
        nodes, adj, deg = build_graph(b)
        labels = label_propagation(nodes, adj)
        assert len(set(labels.values())) == 2
    finally:
        _teardown(b)


def test_rejected_edge_excluded():
    b = _brain()
    try:
        a = _tri(b, "alpha")
        d = _tri(b, "delta")
        _add_edges(b, Edge(source=a[0], target=d[0], kind="similar",
                           pending=False, rejected=True))
        nodes, adj, deg = build_graph(b)
        labels = label_propagation(nodes, adj)
        assert len(set(labels.values())) == 2
    finally:
        _teardown(b)


def test_dangling_endpoint_ignored():
    b = _brain()
    try:
        a = _tri(b, "alpha")
        _tri(b, "delta")
        _add_edges(b, Edge(source=a[0], target="nonexistent", kind="similar",
                           pending=False))
        nodes, adj, deg = build_graph(b)  # must not crash
        assert "nonexistent" not in nodes
    finally:
        _teardown(b)


def test_pending_edges_included_by_default_and_flag_excludes():
    b = _brain()
    try:
        a = _tri(b, "alpha")   # live edges
        d = _tri(b, "delta")
        # pending bridge included by default
        _add_edges(b, Edge(source=a[0], target=d[0], kind="similar", pending=True))
        nodes, adj, deg = build_graph(b, include_pending=True)
        labels = label_propagation(nodes, adj)
        assert len(set(labels.values())) == 1
        nodes, adj, deg = build_graph(b, include_pending=False)
        labels = label_propagation(nodes, adj)
        assert len(set(labels.values())) == 2
    finally:
        _teardown(b)


def test_dedup_directions_one_undirected_edge():
    b = _brain()
    try:
        ids = []
        for i in range(2):
            n = Node(id=f"pair{i}", text=f"pair node {i}")
            b.write_node(n)
            ids.append(n.id)
        _add_edges(b,
            Edge(source=ids[0], target=ids[1], kind="similar", pending=False),
            Edge(source=ids[1], target=ids[0], kind="similar", pending=False))
        nodes, adj, deg = build_graph(b)
        assert deg[ids[0]] == 1 and deg[ids[1]] == 1
        assert sum(deg.values()) == 2  # one undirected edge
    finally:
        _teardown(b)


def test_determinism_two_runs_and_input_reordering():
    b = _brain()
    try:
        _tri(b, "alpha")
        _tri(b, "delta")
        nodes, adj, deg = build_graph(b)
        l1 = label_propagation(nodes, adj)
        l2 = label_propagation(nodes, adj)
        assert l1 == l2
        l3 = label_propagation(list(reversed(nodes)), adj)
        # canonical numbering is stable under input reordering
        assert l1 == l3
    finally:
        _teardown(b)


def test_betweenness_path_and_star():
    adj = {"a": {"b"}, "b": {"a", "c"}, "c": {"b"}}
    bc = betweenness(["a", "b", "c"], adj)
    assert bc == {"a": 0.0, "b": 1.0, "c": 0.0}  # measured (normalized)
    adj2 = {"hub": {"x", "y", "z"}, "x": {"hub"}, "y": {"hub"}, "z": {"hub"}}
    bc2 = betweenness(["hub", "x", "y", "z"], adj2)
    assert bc2["hub"] == 1.0 and bc2["x"] == 0.0


def test_min_size_larger_than_all_empty_gaps_top_zero():
    b = _brain()
    try:
        _tri(b, "alpha")
        _tri(b, "delta")
        rep = analyze_communities(b, min_size=99, top=10)
        assert rep.gaps == []
        rep = analyze_communities(b, min_size=2, top=0)
        assert rep.gaps == []  # top 0 = limit 0 (near-dup --max 0 precedent)
    finally:
        _teardown(b)


def test_empty_brain_clean_report():
    b = _brain()
    try:
        rep = analyze_communities(b)
        assert rep.nodes == 0 and rep.communities == [] and rep.gaps == []
        assert rep.modularity == 0.0
        text = render_communities(rep)
        assert "Communities (0 nodes" in text
    finally:
        _teardown(b)


def test_render_contains_tables_and_gaps():
    b = _brain()
    try:
        _tri(b, "alpha")
        _tri(b, "delta")
        rep = analyze_communities(b, min_size=2, top=10)
        text = render_communities(rep)
        assert "Communities (" in text
        assert "God nodes" in text
        assert "Structural gaps" in text
        assert "UNCLASSIFIED" in text  # fixture has no taxonomy keywords
    finally:
        _teardown(b)

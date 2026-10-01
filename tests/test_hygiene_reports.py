"""Tests for the hygiene/status reports (`ig status`, `ig near-dup`).

Define the expected behavior of near_dup_pairs / connectivity /
status_counts before the CLI builds on top of it (measure-first).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.brain import Brain, Node, Edge
from graph_engine.hygiene import (
    near_dup_pairs,
    connectivity,
    status_counts,
    DEFAULT_DEDUP_THRESHOLD,
)


def _brain(tmp_path) -> Brain:
    return Brain(str(tmp_path / "brain"), mode="local")


def _write_vecs(brain: Brain, vecs: dict[str, list[float]]) -> None:
    (brain.path / "vectors.jsonl").write_text(
        "".join(json.dumps({"id": k, "vec": v}) + "\n" for k, v in vecs.items()),
        encoding="utf-8",
    )


def test_near_dup_finds_band_pair(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    b.write_node(Node(id="b", text="Thema A Variante"))
    b.write_node(Node(id="c", text="Ganz anderes Thema"))
    # a=[1,0,0], b=[0.8,0.6,0] -> cos=0.8 (in the band), c=[0,1,0] -> cos(a,c)=0
    _write_vecs(b, {"a": [1, 0, 0], "b": [0.8, 0.6, 0], "c": [0, 1, 0]})
    pairs = near_dup_pairs(b, lo=0.78, hi=0.92)
    assert len(pairs) == 1
    p = pairs[0]
    assert {p.a, p.b} == {"a", "b"}
    assert 0.78 <= p.score < 0.92


def test_near_dup_band_excludes_outside(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="A"))
    b.write_node(Node(id="x", text="X"))
    b.write_node(Node(id="y", text="Y"))
    # x=[1,0,0] (cos 1.0 with a -> >=hi, excluded), y=[0.6,0.8,0] (cos 0.6 -> <lo)
    _write_vecs(b, {"a": [1, 0, 0], "x": [1, 0, 0], "y": [0.6, 0.8, 0]})
    pairs = near_dup_pairs(b, lo=0.78, hi=0.92)
    assert pairs == []  # 1.0 >= hi and 0.6 < lo, both excluded


def test_near_dup_sorted_desc(tmp_path):
    b = _brain(tmp_path)
    for nid in ["a", "b", "c", "d"]:
        b.write_node(Node(id=nid, text=nid))
    # a-b=0.9, a-c=0.8, a-d=0.0 (Einheitsvektoren)
    _write_vecs(b, {
        "a": [1, 0, 0],
        "b": [0.9, 0.4359, 0],
        "c": [0.8, 0.6, 0],
        "d": [0, 1, 0],
    })
    pairs = near_dup_pairs(b, lo=0.78, hi=0.92)
    assert len(pairs) == 2
    assert pairs[0].score > pairs[1].score


def test_connectivity_detects_islands_and_orphans(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="island", text="Insel"))
    b.write_node(Node(id="orphan", text="Orphan"))
    b.write_node(Node(id="weak", text="Schwach"))
    b.write_node(Node(id="hub", text="Hub"))
    # hub-weak, hub-weak2 -> weak has 2 edges; island 1; orphan 0
    b.add_edge(Edge(source="hub", target="weak", kind="extends", pending=False))
    b.add_edge(Edge(source="hub", target="island", kind="extends", pending=False))
    b.add_edge(Edge(source="weak", target="hub", kind="extends", pending=False))
    c = connectivity(b)
    assert c.total == 4
    assert "orphan" in c.orphans
    assert "island" in c.islands  # degree 1
    assert "weak" not in c.islands  # degree 2 (weak, not an island)


def test_status_counts(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="A", status="probation"))
    b.write_node(Node(id="b", text="B", status="active"))
    b.write_node(Node(id="c", text="C", status="tombstone"))
    c = status_counts(b)
    assert c["probation"] == 1 and c["active"] == 1 and c["tombstone"] == 1


def test_default_threshold_constant():
    assert DEFAULT_DEDUP_THRESHOLD == 0.92


def test_connectivity_ignores_tombstones(tmp_path):
    """A tombstone is edge-less BY DESIGN (merge keeps it as history) — it must
    not show up as a phantom orphan/island, or every merge leaves a permanent
    false island the autonomous cycle tries to re-link (found 2026-09-15)."""
    b = _brain(tmp_path)
    b.write_node(Node(id="live", text="Lebendig"))
    b.write_node(Node(id="dead", text="Konsolidiert", status="tombstone"))
    b.add_edge(Edge(source="live", target="live2", kind="extends", pending=False))
    b.write_node(Node(id="live2", text="Auch lebendig"))
    c = connectivity(b)
    assert c.total == 2                      # live nodes only
    assert "dead" not in c.orphans
    assert "dead" not in c.islands
    assert status_counts(b)["tombstone"] == 1  # still visible in the distribution


def test_gaps_coverage_ignores_tombstones(tmp_path):
    """Coverage counts live knowledge: a tombstone must not inflate the total
    or the UNCLASSIFIED bucket."""
    from graph_engine.gaps import analyze_coverage
    b = _brain(tmp_path)
    b.write_node(Node(id="live", text="Ein Subagent uebernimmt eine Delegation."))
    b.write_node(Node(id="dead", text="voelliger unsinn ohne stichwort",
                      status="tombstone"))
    cov = analyze_coverage(b)
    assert cov.total == 1
    assert cov.unclassified == 0  # the live node matches, the tombstone is gone


def test_near_dup_ignores_tombstoned_nodes(tmp_path):
    """A merged deletee is a tombstone: its stale vector must not re-report the pair.

    `ig merge` tombstones the deletee and redirects its edges, but the deletee's
    vector stays in vectors.jsonl — without the live-node filter the merged pair
    re-appears in EVERY `ig near-dup` run forever (the phantom-node class already
    filtered in connectivity()/analyze_coverage()).
    """
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    b.write_node(Node(id="b", text="Thema A Variante", status="tombstone"))
    b.write_node(Node(id="c", text="Thema A Zweite Fassung"))
    # a=[1,0,0]; b=[0.8,0.6,0] -> cos 0.8 (tombstone); c=[0.9,0.4359,0] -> cos 0.9
    _write_vecs(b, {"a": [1, 0, 0], "b": [0.8, 0.6, 0],
                    "c": [0.9, 0.4358898943540674, 0]})
    pairs = near_dup_pairs(b, lo=0.78, hi=0.92)
    got = {frozenset((p.a, p.b)) for p in pairs}
    assert frozenset(("a", "b")) not in got   # tombstoned deletee is not reviewed
    assert frozenset(("a", "c")) in got       # live pairs still are


def test_near_dup_all_tombstones_returns_empty(tmp_path):
    """Two tombstones must not crash the report (the live set drops below 2)."""
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A", status="tombstone"))
    b.write_node(Node(id="b", text="Thema A Variante", status="tombstone"))
    _write_vecs(b, {"a": [1, 0, 0], "b": [0.8, 0.6, 0]})
    assert near_dup_pairs(b, lo=0.78, hi=0.92) == []

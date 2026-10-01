"""Regression: `aggregate` must never fold the same ledger line twice.

Found live 2026-09-18: `dream.refresh()` calls `aggregate(commit=False)` to batch
the commit, but the ledger move/truncate was tied to `commit` — so the counters
were written while the source entries stayed in place, and EVERY refresh folded
them again (`recall_count` 1 -> 2 on a single real ledger line). That inflates
exactly the signal the promotion gates read.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.brain import Brain, Node
from graph_engine.dream import refresh
from graph_engine.recall import aggregate, record


def _brain(tmp_path) -> Brain:
    b = Brain(str(tmp_path / "brain"), mode="local")
    b.write_node(Node(id="a", text="node a"))
    b.write_node(Node(id="b", text="node b"))
    return b


def test_aggregate_is_idempotent_with_commit_false(tmp_path):
    b = _brain(tmp_path)
    record(b, "q one", ["a"])

    first = aggregate(b, commit=False)
    second = aggregate(b, commit=False)

    assert first["recalls"] == 1 and second["recalls"] == 0, "no double count"
    assert {n.id: n.recall_count for n in b.read_nodes()}["a"] == 1
    assert (Path(b.path) / "recalls.jsonl.processed").exists(), "ledger moved"


def test_aggregate_is_idempotent_with_commit_true(tmp_path):
    b = _brain(tmp_path)
    record(b, "q one", ["a"])

    aggregate(b)
    aggregate(b)

    assert {n.id: n.recall_count for n in b.read_nodes()}["a"] == 1


def test_dream_refresh_does_not_inflate_recall_count(tmp_path):
    b = _brain(tmp_path)
    record(b, "q one", ["a", "b"])

    refresh(b)
    refresh(b)
    refresh(b)

    counts = {n.id: n.recall_count for n in b.read_nodes()}
    assert counts == {"a": 1, "b": 1}, f"counters inflated: {counts}"


def test_aggregate_accumulates_across_distinct_events(tmp_path):
    """Two real recalls must still count twice — the fix must not undercount."""
    b = _brain(tmp_path)
    record(b, "q one", ["a"])
    aggregate(b, commit=False)
    record(b, "q two", ["a"])
    aggregate(b, commit=False)

    assert {n.id: n.recall_count for n in b.read_nodes()}["a"] == 2
    assert {n.id: len(n.recall_queries) for n in b.read_nodes()}["a"] == 2


def test_dry_run_keeps_the_ledger(tmp_path):
    b = _brain(tmp_path)
    record(b, "q one", ["a"])

    res = aggregate(b, dry_run=True)

    assert res["recalls"] == 1
    assert (Path(b.path) / "recalls.jsonl").read_text(encoding="utf-8").strip() != ""
    assert not (Path(b.path) / "recalls.jsonl.processed").exists()
    assert {n.id: n.recall_count for n in b.read_nodes()}["a"] == 0
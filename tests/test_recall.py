"""Tests for recall tracking (`graph_engine/recall.py`, `ig recall`).

The signal the consolidation half of the memory system runs on: a memory that
never records what it is asked for cannot decide what to promote or let decay.
The read path must stay cheap (append-only ledger, gitignored) and the counters
are derived data, folded in by `aggregate()`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.brain import Brain, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder
from graph_engine.recall import (
    LEDGER_NAME,
    MAX_QUERY_FINGERPRINTS,
    aggregate,
    fingerprint,
    ledger_path,
    read_ledger,
    record,
    top,
    tracking_enabled,
)
from graph_engine.retrieval import retrieve


def _brain(tmp_path) -> Brain:
    return Brain(str(tmp_path / "brain"), mode="local")


def _engine(tmp_path) -> BrainEngine:
    return BrainEngine(_brain(tmp_path), HashEmbedder())


def test_record_appends_and_aggregate_folds(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    b.write_node(Node(id="b", text="Thema B"))

    record(b, "frage eins", ["a", "b"], ts="2026-09-18T10:00:00+00:00")
    record(b, "frage eins", ["a"], ts="2026-09-18T11:00:00+00:00")
    record(b, "frage zwei", ["a"], ts="2026-09-18T12:00:00+00:00")

    res = aggregate(b)

    assert res["ledger_entries"] == 3
    assert res["recalls"] == 4
    assert res["nodes"] == 2
    nodes = {n.id: n for n in b.read_nodes()}
    assert nodes["a"].recall_count == 3
    assert nodes["a"].recall_queries == sorted([fingerprint("frage eins"),
                                                fingerprint("frage zwei")])
    assert nodes["a"].last_recalled == "2026-09-18T12:00:00+00:00"
    assert nodes["b"].recall_count == 1
    assert read_ledger(b) == [], "the ledger is consumed, not re-read"


def test_aggregate_is_idempotent(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    record(b, "q", ["a"])

    first = aggregate(b)
    second = aggregate(b)

    assert first["recalls"] == 1
    assert second == {"nodes": 0, "recalls": 0, "ledger_entries": 0, "dry_run": False}
    assert {n.id: n.recall_count for n in b.read_nodes()}["a"] == 1


def test_aggregate_keeps_the_processed_ledger(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    record(b, "q", ["a"])

    aggregate(b)

    processed = ledger_path(b).with_name(LEDGER_NAME + ".processed")
    assert processed.exists()
    assert json.loads(processed.read_text(encoding="utf-8").strip())["ids"] == ["a"]


def test_aggregate_dry_run_writes_nothing(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    record(b, "q", ["a"])

    res = aggregate(b, dry_run=True)

    assert res["recalls"] == 1
    assert {n.id: n.recall_count for n in b.read_nodes()}["a"] == 0
    assert len(read_ledger(b)) == 1, "dry run must not consume the ledger"


def test_aggregate_skips_unknown_nodes(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    record(b, "q", ["a", "deleted-node"])

    res = aggregate(b)

    assert res["nodes"] == 1 and res["recalls"] == 2


def test_recall_queries_are_capped(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    for i in range(MAX_QUERY_FINGERPRINTS + 5):
        record(b, f"query {i}", ["a"])

    aggregate(b)

    node = {n.id: n for n in b.read_nodes()}["a"]
    assert node.recall_count == MAX_QUERY_FINGERPRINTS + 5
    assert len(node.recall_queries) == MAX_QUERY_FINGERPRINTS


def test_fingerprint_normalizes_whitespace_and_case():
    assert fingerprint("  Alpha   Beta ") == fingerprint("alpha beta")
    assert fingerprint("alpha beta") != fingerprint("alpha gamma")


def test_tracking_enabled_env_override(monkeypatch):
    monkeypatch.delenv("IG_NO_RECALL_TRACKING", raising=False)
    assert tracking_enabled() is True
    monkeypatch.setenv("IG_NO_RECALL_TRACKING", "1")
    assert tracking_enabled() is False
    assert tracking_enabled({}) is False, "an empty per-call env inherits the process env"
    assert tracking_enabled({"IG_NO_RECALL_TRACKING": "0"}) is True, "explicit override wins"


def test_retrieve_track_writes_ledger(tmp_path):
    eng = _engine(tmp_path)
    eng.ingest("alpha beta gamma delta training pipeline")
    eng.ingest("omega psi chi phi gardening tomatoes")

    hits = retrieve(eng, "alpha beta gamma delta training pipeline", k=1, track=True)

    assert hits, "fixture query must hit"
    entries = read_ledger(eng.brain)
    assert len(entries) == 1
    assert entries[0]["ids"] == [hits[0][0]]


def test_retrieve_without_track_writes_nothing(tmp_path):
    eng = _engine(tmp_path)
    eng.ingest("alpha beta gamma delta training pipeline")

    retrieve(eng, "alpha beta gamma", k=1)

    assert read_ledger(eng.brain) == []


def test_tracking_can_be_disabled_by_env(tmp_path, monkeypatch):
    eng = _engine(tmp_path)
    eng.ingest("alpha beta gamma delta training pipeline")
    monkeypatch.setenv("IG_NO_RECALL_TRACKING", "1")

    retrieve(eng, "alpha beta gamma", k=1, track=True)

    assert read_ledger(eng.brain) == []


def test_node_markdown_roundtrip_preserves_recalls(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A", recall_count=7,
                      recall_queries=["abc123"], last_recalled="2026-09-18T12:00:00+00:00"))
    b.write_node(Node(id="b", text="Thema B"))  # untouched: no recall lines

    raw_a = (Path(b.path) / "nodes" / "a.md").read_text(encoding="utf-8")
    raw_b = (Path(b.path) / "nodes" / "b.md").read_text(encoding="utf-8")
    assert "recalls: 7" in raw_a and "last_recalled" in raw_a
    assert "recalls" not in raw_b, "nodes without recalls must not gain churn lines"

    nodes = {n.id: n for n in b.read_nodes()}
    assert nodes["a"].recall_count == 7
    assert nodes["a"].recall_queries == ["abc123"]
    assert nodes["a"].last_recalled == "2026-09-18T12:00:00+00:00"
    assert nodes["b"].recall_count == 0


def test_top_ranks_recalled_nodes(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A", recall_count=5))
    b.write_node(Node(id="b", text="Thema B", recall_count=9))
    b.write_node(Node(id="c", text="Thema C"))

    assert top(b, 5) == [("b", 9), ("a", 5)]
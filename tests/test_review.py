"""Tests for the intent fan-out dam (`graph_engine/review.py`, `ig accept-pending`).

The dam is the measurable contract of ROADMAP_CASE `roadmap-intent-fanout-cap`:
at most `INTENT_AUTO_ACCEPT_MAX` intent edges per source may be auto-accepted;
everything beyond stays PENDING (kept and reviewable — not dropped, not
invisible).

Why a cap instead of a better heuristic: intent edges carry `confidence=None`,
so the confidence bands can never judge them, and the marker heuristic is their
only producer — it mass-fires in a homogeneous brain (live measurement: 168
intent edges ever created, 66 invalidated again = 39 % false).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.brain import Brain, Edge, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder
from graph_engine.intent import INTENT_KINDS
from graph_engine.review import (
    INTENT_AUTO_ACCEPT_MAX,
    INTENT_AUTO_ACCEPT_MAX_ENV,
    accept_pending,
    intent_auto_accept_max,
    is_live_intent,
)

ANCHOR_WORDS = ("delta", "epsilon", "zeta", "eta", "theta", "iota")
MARKER_TEXT = "alpha beta gamma kappa training pipeline ersetzt delta"


def _brain(tmp_path) -> Brain:
    return Brain(str(tmp_path / "brain"), mode="local")


def _engine(tmp_path) -> BrainEngine:
    return BrainEngine(_brain(tmp_path), HashEmbedder())


def _seed_pending(brain: Brain, specs: list[tuple[str, str, str]]) -> None:
    """specs: [(edge_id, kind, target_node_id)] — all pending, one source."""
    brain.write_node(Node(id="src", text="Quelle"))
    edges = []
    for i, (eid, kind, target) in enumerate(specs):
        brain.write_node(Node(id=target, text=f"Ziel {i}"))
        edges.append(Edge(id=eid, source="src", target=target, kind=kind, pending=True))
    brain.write_edges(edges)


# ---------------------------------------------------------------------------
# The cap at ingest time (the eval case, at unit level with explicit flags)
# ---------------------------------------------------------------------------

def test_ingest_caps_intent_fanout_at_birth(tmp_path):
    eng = _engine(tmp_path)
    for word in ANCHOR_WORDS:
        eng.ingest(f"alpha beta gamma {word} training pipeline")
    node, _edges, _dup = eng.ingest(MARKER_TEXT)

    intent = [e for e in eng.brain.read_edges()
              if e.source == node.id and e.kind in INTENT_KINDS]
    assert len(intent) == 6, "fixture must produce 6 intent edges (measured)"
    assert sum(1 for e in intent if is_live_intent(e)) == INTENT_AUTO_ACCEPT_MAX
    assert sum(1 for e in intent if e.pending) == 6 - INTENT_AUTO_ACCEPT_MAX


def test_intent_pending_env_keeps_everything_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("IDEAGRAPH_INTENT_PENDING", "1")
    eng = _engine(tmp_path)
    for word in ANCHOR_WORDS:
        eng.ingest(f"alpha beta gamma {word} training pipeline")
    node, _edges, _dup = eng.ingest(MARKER_TEXT)

    intent = [e for e in eng.brain.read_edges()
              if e.source == node.id and e.kind in INTENT_KINDS]
    assert len(intent) == 6
    assert not any(is_live_intent(e) for e in intent)


def test_ingest_cap_is_env_overridable(tmp_path):
    eng = _engine(tmp_path)
    for word in ANCHOR_WORDS:
        eng.ingest(f"alpha beta gamma {word} training pipeline")
    node, _edges, _dup = eng.ingest(MARKER_TEXT, env={INTENT_AUTO_ACCEPT_MAX_ENV: "0"})

    intent = [e for e in eng.brain.read_edges()
              if e.source == node.id and e.kind in INTENT_KINDS]
    assert len(intent) == 6
    assert not any(is_live_intent(e) for e in intent)


# ---------------------------------------------------------------------------
# The review path (`ig accept-pending`)
# ---------------------------------------------------------------------------

def test_accept_pending_accepts_similarity_and_caps_intent(tmp_path):
    b = _brain(tmp_path)
    _seed_pending(b, [
        ("e1", "extends", "t0"),        # non-intent → always accepted
        ("e2", "contradicts", "t1"),
        ("e3", "contradicts", "t2"),
        ("e4", "contradicts", "t3"),    # over the cap → held
    ])

    res = accept_pending(b)

    assert res["accepted"] == ["e1", "e2", "e3"]
    assert res["held"] == ["e4"]
    assert res["cap"] == INTENT_AUTO_ACCEPT_MAX
    by_id = {e.id: e for e in b.read_edges()}
    assert by_id["e1"].pending is False
    assert by_id["e2"].pending is False
    assert by_id["e3"].pending is False
    assert by_id["e4"].pending is True, "held edges stay pending, never dropped"


def test_accept_pending_counts_existing_live_intent(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="src", text="Quelle"))
    b.write_node(Node(id="t0", text="Ziel 0"))
    b.write_node(Node(id="t1", text="Ziel 1"))
    b.write_node(Node(id="t2", text="Ziel 2"))
    b.write_edges([
        # already live (accepted earlier) — consumes one slot of the cap
        Edge(id="live1", source="src", target="t0", kind="supersedes", pending=False),
        Edge(id="e1", source="src", target="t1", kind="contradicts", pending=True),
        Edge(id="e2", source="src", target="t2", kind="contradicts", pending=True),
    ])

    res = accept_pending(b)

    assert res["accepted"] == ["e1"]
    assert res["held"] == ["e2"]


def test_accept_pending_cap_zero_holds_every_intent(tmp_path):
    b = _brain(tmp_path)
    _seed_pending(b, [("e1", "extends", "t0"), ("e2", "contradicts", "t1")])

    res = accept_pending(b, max_intent_per_source=0)

    assert res["accepted"] == ["e1"]
    assert res["held"] == ["e2"]


def test_accept_pending_dry_run_writes_nothing(tmp_path):
    b = _brain(tmp_path)
    _seed_pending(b, [("e1", "extends", "t0"), ("e2", "contradicts", "t1")])

    res = accept_pending(b, dry_run=True)

    assert res["accepted"] == ["e1", "e2"]
    assert all(e.pending for e in b.read_edges()), "dry run must not touch the store"


def test_accept_pending_commits_once_for_the_batch(tmp_path, monkeypatch):
    b = _brain(tmp_path)
    _seed_pending(b, [("e1", "extends", "t0"), ("e2", "extends", "t1"),
                      ("e3", "extends", "t2")])
    calls: list[str] = []
    monkeypatch.setattr(b, "commit_and_push",
                        lambda message, push=True: calls.append(message))

    accept_pending(b)

    assert len(calls) == 1, "one commit for the whole batch"
    assert "3 accepted" in calls[0]


def test_accept_pending_is_idempotent(tmp_path):
    b = _brain(tmp_path)
    _seed_pending(b, [("e1", "contradicts", "t0"), ("e2", "contradicts", "t1")])

    first = accept_pending(b)
    second = accept_pending(b)

    assert first["accepted"] == ["e1", "e2"]
    assert second["accepted"] == [] and second["held"] == []


# ---------------------------------------------------------------------------
# Cap resolution
# ---------------------------------------------------------------------------

def test_intent_auto_accept_max_resolution(monkeypatch):
    monkeypatch.delenv(INTENT_AUTO_ACCEPT_MAX_ENV, raising=False)
    assert intent_auto_accept_max() == INTENT_AUTO_ACCEPT_MAX
    assert intent_auto_accept_max({INTENT_AUTO_ACCEPT_MAX_ENV: "5"}) == 5
    monkeypatch.setenv(INTENT_AUTO_ACCEPT_MAX_ENV, "0")
    assert intent_auto_accept_max() == 0, "env beats the module default"
    assert intent_auto_accept_max({INTENT_AUTO_ACCEPT_MAX_ENV: "3"}) == 3, \
        "per-call env beats the process env"


def test_intent_auto_accept_max_rejects_garbage():
    for bad in ("zwei", "-1", "1.5"):
        with pytest.raises(ValueError):
            intent_auto_accept_max({INTENT_AUTO_ACCEPT_MAX_ENV: bad})
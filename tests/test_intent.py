"""Unit tests for intent-typed edges (V2#3): supersedes / contradicts / continues."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.intent import detect_intent


def test_supersedes_replacement_marker():
    assert detect_intent("API v2 ersetzt v1", "API v1 wird verwendet") == "supersedes"


def test_supersedes_requires_shared_subject():
    # marker present, but about a different subject → no supersedes.
    # (Regression: without this check, a node containing a marker word marked
    #  EVERY existing node as supersedes.)
    assert detect_intent("API v2 ersetzt v1", "Die Erde ist eine Scheibe") is None


def test_contradiction_negation():
    assert (
        detect_intent(
            "Die Erde ist keine Scheibe, sondern eine Kugel",
            "Die Erde ist eine Scheibe",
        )
        == "contradicts"
    )


def test_contradiction_requires_shared_subject():
    # negation present, but about a different subject → no contradicts
    assert detect_intent("Katzen sind keine Hunde", "Die Erde ist eine Scheibe") is None


def test_continues_builds_on():
    assert detect_intent(
        "Vertiefung basiert auf der bisherigen Arbeit",
        "Arbeit an X",
    ) == "continues"


def test_no_intent_for_unrelated():
    assert detect_intent("quantenmechanik wellenfunktion", "katze hund tier") is None


def test_no_intent_for_plain_similarity():
    # no intent signal → None (similarity still decides)
    assert detect_intent("katze hund tier futter", "katze hund tier spiel") is None

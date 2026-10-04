"""Explicit judgments adapt retrieval deterministically and survive restarts."""
import json

import pytest

from graph_engine.brain import Brain, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder
from graph_engine.feedback import (FEEDBACK_FILE, cmd_feedback, learning_profile,
                                   read_feedback, record_feedback)
from graph_engine.retrieval import explain, retrieve, rrf_fuse


@pytest.fixture
def engine(tmp_path):
    brain = Brain(tmp_path)
    brain.write_node(Node("alpha zebra orchard", id="a"))
    brain.write_node(Node("alpha zebra turbine", id="b"))
    return BrainEngine(brain, HashEmbedder())


def snapshot(brain):
    return {str(p.relative_to(brain.path)): p.read_bytes() for p in brain.path.rglob("*") if p.is_file()}


def test_feedback_persists_normalizes_and_corrections_replace_votes(engine):
    record_feedback(engine, "  ALPHA   zebra ", "a", "relevant")
    restarted = BrainEngine(Brain(engine.brain.path), HashEmbedder())
    rows = read_feedback(restarted.brain)
    assert len(rows) == 1 and rows[0]["query"] == "alpha zebra"
    record_feedback(restarted, "alpha zebra", "a", "irrelevant")
    assert len(read_feedback(engine.brain)) == 1
    assert read_feedback(engine.brain)[0]["label"] == "irrelevant"
    assert learning_profile(engine.brain, "alpha zebra", engine.brain.read_nodes()).expansion_terms == []


def test_relevance_judgments_change_result_order_and_explanation(engine):
    baseline = retrieve(engine, "alpha zebra", persist=False)
    last = baseline[-1][0]
    record_feedback(engine, "alpha zebra", last, "relevant")
    assert retrieve(engine, "alpha zebra", persist=False)[0][0] == last
    result = explain(engine, last, "alpha zebra")
    assert result["rank"] == 1
    assert result["learning"]["feedback_adjustment"] > 0
    assert result["rrf"]["score"] == pytest.approx(
        result["dense"]["rrf_contribution"] + result["bm25"]["rrf_contribution"]
        + result["learning"]["feedback_adjustment"])
    record_feedback(engine, "alpha zebra", last, "irrelevant")
    assert retrieve(engine, "alpha zebra", persist=False)[-1][0] == last


def test_weights_learn_channel_preference_and_stay_bounded(engine):
    class LexicallyWrongEmbedder:
        def embed(self, text):
            return [0.0, 1.0] if text == "alpha zebra orchard" else [1.0, 0.0]
    engine.embedder = LexicallyWrongEmbedder()
    record_feedback(engine, "orchard", "a", "relevant")
    profile = learning_profile(engine.brain, "other question", engine.brain.read_nodes())
    assert 0.5 <= profile.dense_weight < 1 < profile.bm25_weight <= 1.5
    assert profile.expansion_terms == []
    result = explain(engine, "a", "other question")
    assert result["learning"]["bm25_weight"] > 1


def test_expansion_learns_from_similar_successful_queries(engine):
    record_feedback(engine, "alpha zebra", "a", "relevant")
    profile = learning_profile(engine.brain, "alpha zebra advice", engine.brain.read_nodes())
    assert "orchard" in profile.expansion_terms
    assert len(profile.expansion_terms) <= 5
    assert learning_profile(engine.brain, "unrelated gardening", engine.brain.read_nodes()).expansion_terms == []
    before = snapshot(engine.brain)
    retrieve(engine, "alpha zebra advice", persist=False)
    explain(engine, "a", "alpha zebra advice")
    assert snapshot(engine.brain) == before


def test_invisible_deleted_tombstoned_feedback_cannot_affect_learning(engine):
    record_feedback(engine, "alpha zebra", "a", "relevant")
    only_b = [engine.brain.read_node("b")]
    profile = learning_profile(engine.brain, "alpha zebra", only_b)
    assert profile.expansion_terms == [] and profile.adjustments == {}
    engine.brain.tombstone_node("a")
    assert read_feedback(engine.brain) == []
    assert retrieve(engine, "alpha zebra", persist=False)[0][0] == "b"


@pytest.mark.parametrize("query,node,label", [(" ", "a", "relevant"), ("alpha", "missing", "relevant"),
                                            ("alpha", "a", "perhaps")])
def test_invalid_feedback_does_not_write(engine, query, node, label):
    before = snapshot(engine.brain)
    with pytest.raises(ValueError):
        record_feedback(engine, query, node, label)
    assert snapshot(engine.brain) == before


def test_feedback_cli_and_malformed_store(engine, capsys):
    cmd_feedback(engine, ["alpha zebra", "a", "relevant", "--json"])
    assert json.loads(capsys.readouterr().out)["label"] == "relevant"
    path = engine.brain.path / FEEDBACK_FILE
    path.write_text("broken")
    with pytest.raises(ValueError, match="Cannot read feedback"):
        record_feedback(engine, "alpha zebra", "a", "irrelevant")
    assert path.read_text() == "broken"


def test_weighted_rrf_has_neutral_default_and_validates_weights():
    ranks = [[("a", 1), ("b", 0)], [("b", 1), ("a", 0)]]
    assert rrf_fuse(ranks) == rrf_fuse(ranks, weights=[1, 1])
    assert rrf_fuse(ranks, weights=[0.5, 1.5])[0][0] == "b"
    for weights in ([1], [1, float("nan")], [1, -1]):
        with pytest.raises(ValueError):
            rrf_fuse(ranks, weights=weights)


def test_explanation_reports_applied_penalty_when_score_is_clamped(tmp_path):
    brain = Brain(tmp_path)
    for index in range(70):
        brain.write_node(Node("alpha zebra", id=f"n{index:03}"))
    engine = BrainEngine(brain, HashEmbedder())
    record_feedback(engine, "alpha zebra", "n069", "irrelevant")
    result = explain(engine, "n069", "alpha zebra", k=100, rerank_k=100)
    assert result["rrf"]["score"] == 0
    assert result["dense"]["rrf_contribution"] + result["bm25"]["rrf_contribution"] == pytest.approx(
        -result["learning"]["feedback_adjustment"])

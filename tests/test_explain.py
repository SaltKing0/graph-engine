"""Retrieval explanations must describe the actual ranking without writes."""

from __future__ import annotations

import pytest

from graph_engine.brain import Brain, Edge, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.retrieval import explain, retrieve


class FixtureEmbedder:
    def embed(self, text: str) -> list[float]:
        return {"alpha": [1.0, 0.0], "alpha beta": [0.8, 0.6],
                "alpha gamma": [1.0, 0.0], "omega": [0.0, 1.0]}[text]


@pytest.fixture
def engine(tmp_path):
    brain = Brain(tmp_path / "brain", mode="local")
    brain.ensure_ready()
    for nid, text in [("a", "alpha beta"), ("b", "alpha gamma"), ("c", "omega")]:
        brain.write_node(Node(id=nid, text=text))
    return BrainEngine(brain, embedder=FixtureEmbedder())


def snapshot(brain: Brain) -> dict[str, bytes]:
    return {str(p.relative_to(brain.path)): p.read_bytes()
            for p in brain.path.rglob("*") if p.is_file()}


def test_explain_reconstructs_real_scores_and_ranks(engine):
    result = explain(engine, "a", "alpha")
    hits = retrieve(engine, "alpha", persist=False)
    assert result["retrieved"]
    assert result["rank"] == [nid for nid, _ in hits].index("a") + 1
    assert result["dense"]["score"] == pytest.approx(0.8)
    assert result["dense"]["rank"] == 2
    assert result["bm25"]["rank"] == 1  # tied BM25 scores retain corpus order
    # N=3, df=2, average length=5/3, document length=2, term frequency=1.
    assert result["bm25"]["score"] == pytest.approx(0.4344571362775708)
    assert result["dense"]["rrf_contribution"] == pytest.approx(1 / 62)
    assert result["bm25"]["rrf_contribution"] == pytest.approx(1 / 61)
    assert result["rrf"]["score"] == pytest.approx(1 / 62 + 1 / 61)
    assert result["final_score"] == dict(hits)["a"]
    assert result["final_score_kind"] == "rrf"
    assert result["matched_terms"] == ["alpha"]


def test_explain_cold_brain_never_writes_vectors_or_recall(engine):
    assert not engine.brain.vectors_file.exists()
    before = snapshot(engine.brain)
    explain(engine, "a", "alpha")
    assert snapshot(engine.brain) == before


def test_explain_warm_brain_never_changes_files(engine):
    engine.brain.write_vectors({"a": [0.8, 0.6], "b": [1.0, 0.0], "c": [0.0, 1.0]})
    before = snapshot(engine.brain)
    explain(engine, "a", "alpha")
    assert snapshot(engine.brain) == before


def test_non_hit_and_candidate_cutoff_are_distinct(engine):
    missing = explain(engine, "c", "alpha")
    assert missing["reason"] == "no_overlap"
    assert not missing["retrieved"]
    assert missing["dense"]["score"] == 0.0
    assert missing["dense"]["rank"] is None
    assert missing["rrf"] == {"k": 60, "rank": None, "score": 0.0}
    hits = retrieve(engine, "alpha", persist=False)
    second = hits[1][0]
    assert explain(engine, second, "alpha", k=1)["reason"] == "outside_top_k"
    result = explain(engine, second, "alpha", rerank_k=1)
    assert result["reason"] == "outside_candidate_limit"
    assert result["rrf"]["rank"] == 2
    assert result["final_score"] is None


def test_foreign_dimension_is_unavailable_not_zero(engine):
    engine.brain.write_vectors({"a": [1.0, 0.0, 0.0], "b": [1.0, 0.0], "c": [0.0, 1.0]})
    result = explain(engine, "a", "alpha")
    assert result["retrieved"]  # BM25 still contributes
    assert result["dense"] == {"score": None, "rank": None, "rrf_contribution": 0.0}
    assert result["rrf"]["score"] == result["bm25"]["rrf_contribution"]


def test_negative_dense_score_keeps_actual_fusion_rank_for_bm25_match(engine):
    engine.brain.write_vectors({"a": [-1.0, 0.0], "b": [1.0, 0.0], "c": [0.0, 1.0]})
    result = explain(engine, "a", "alpha")
    assert result["dense"]["score"] == pytest.approx(-1.0)
    assert result["dense"]["rank"] == 2
    assert result["rrf"]["score"] == dict(retrieve(engine, "alpha", persist=False))["a"]


def test_reranker_final_score_and_rank_are_separate_from_rrf(engine):
    class FixedReranker:
        def rerank(self, query, candidates, k):
            # Return b alone with a reranker score unrelated to RRF.
            return [(nid, text, 9.5) for nid, text, _ in candidates if nid == "b"][:k]

    engine.reranker = FixedReranker()
    result = explain(engine, "b", "alpha", k=1)
    assert result["rank"] == 1
    assert result["final_score"] == 9.5
    assert result["final_score_kind"] == "reranker"
    assert result["rrf"]["score"] < 1
    assert result["final_score"] == dict(retrieve(engine, "alpha", k=1, persist=False))["b"]
    assert explain(engine, "a", "alpha", k=1)["reason"] == "outside_top_k"


def test_only_accepted_live_edges_to_other_hits_are_context(engine):
    engine.brain.write_node(Node(id="dead", text="alpha", status="tombstone"))
    edges = [
        Edge(id="live", source="b", target="a", kind="extends", pending=False,
             origin="manual", confidence=0.9),
        Edge(id="pending", source="a", target="b", kind="similar"),
        Edge(id="rejected", source="a", target="b", kind="similar", pending=False,
             rejected=True),
        Edge(id="expired", source="a", target="b", kind="similar", pending=False,
             valid_to="2026-01-01T00:00:00Z"),
        Edge(id="nonhit", source="a", target="c", kind="similar", pending=False),
        Edge(id="tombstone", source="a", target="dead", kind="similar", pending=False),
    ]
    engine.brain.write_edges(edges)
    result = explain(engine, "a", "alpha")
    assert result["graph_used_for_ranking"] is False
    assert result["graph_context"] == [edges[0].to_dict()]
    # Graph edits do not change any score or ranking.
    engine.brain.write_edges([])
    without_edges = explain(engine, "a", "alpha")
    assert without_edges.pop("graph_context") == []
    assert {k: v for k, v in result.items() if k != "graph_context"} == without_edges


@pytest.mark.parametrize("query,k,limit", [(" ", 5, 30), ("alpha", 0, 30), ("alpha", 5, 0)])
def test_invalid_arguments_fail_cleanly(engine, query, k, limit):
    with pytest.raises(ValueError):
        explain(engine, "a", query, k=k, rerank_k=limit)


def test_unknown_and_tombstoned_targets_fail_cleanly(engine):
    with pytest.raises(ValueError, match="No node"):
        explain(engine, "missing", "alpha")
    engine.brain.write_node(Node(id="dead", text="alpha", status="tombstone"))
    with pytest.raises(ValueError, match="tombstoned"):
        explain(engine, "dead", "alpha")

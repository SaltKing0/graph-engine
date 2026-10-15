"""HTTP hybrid search, explanations and deterministic semantic matching."""
import pytest
from fastapi.testclient import TestClient

from graph_engine import runtime
from graph_engine.brain import Brain, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.reranker import ReverseReranker
from graph_engine.server import app


class ParaphraseEmbedder:
    """Different words, same vector; no model download or lexical overlap."""
    def embed(self, text: str) -> list[float]:
        return [1., 0.] if text.lower() in {
            "how can i recover forgotten memories?", "restore archived notes"} else [0., 1.]


@pytest.fixture
def search_client(tmp_path, monkeypatch):
    monkeypatch.delenv("IG_ACCESS_POLICY", raising=False)
    monkeypatch.delenv("IG_GRAPH_HOME", raising=False)
    monkeypatch.delenv("IG_GRAPH", raising=False)
    monkeypatch.setenv("IG_BRAIN_PATH", str(tmp_path / "brain"))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    brain = runtime.make_brain()
    brain.ensure_ready()
    brain.write_node(Node(id="semantic", text="Restore archived notes"))
    brain.write_node(Node(id="other", text="Bananas and apples"))
    brain.write_node(Node(id="deleted", text="Restore archived notes", status="tombstone"))
    engine = BrainEngine(brain, ParaphraseEmbedder())
    monkeypatch.setattr(runtime, "make_engine", lambda: engine)
    with TestClient(app) as client:
        yield client, engine


def snapshot(brain: Brain) -> dict:
    return {str(p.relative_to(brain.path)): p.read_bytes()
            for p in brain.path.rglob("*") if p.is_file()}


def test_ranked_paraphrase_match_and_read_only_explanation(search_client):
    client, engine = search_client
    query = "How can I recover forgotten memories?"
    assert query.lower() not in engine.brain.read_node("semantic").text.lower()
    r = client.get("/api/search", params={"query": query, "k": 1})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    assert data["query"] == query
    assert "not factual confidence" in data["score_note"]
    assert data["results"] == [{"id": "semantic", "snippet": "Restore archived notes",
                                "rank": 1, "score": 1 / 61, "score_kind": "rrf"}]
    assert (engine.brain.path / "recalls.jsonl").exists()
    before = snapshot(engine.brain)
    explained = client.get("/api/search/semantic/explain", params={"query": query, "k": 1})
    assert explained.status_code == 200
    assert explained.headers["cache-control"] == "no-store"
    explanation = explained.json()
    assert explanation["rank"] == 1 and explanation["retrieved"]
    assert explanation["dense"]["rank"] == 1
    assert explanation["bm25"]["score"] == 0
    assert explanation["retrieval_score"] == data["results"][0]["score"]
    assert not explanation["graph_used_for_ranking"]
    assert snapshot(engine.brain) == before


@pytest.mark.parametrize("path", ["/api/search", "/api/search/semantic/explain"])
@pytest.mark.parametrize("params,status", [
    ({}, 422), ({"query": ""}, 422), ({"query": "   "}, 400),
    ({"query": "x" * 501}, 422), ({"query": "ok", "k": 0}, 422),
    ({"query": "ok", "k": 21}, 422), ({"query": "ok", "k": "1.5"}, 422)])
def test_search_bounds_before_engine_construction(search_client, monkeypatch, path, params, status):
    client, _ = search_client
    monkeypatch.setattr(runtime, "make_engine", lambda: pytest.fail("invalid request loaded engine"))
    assert client.get(path, params=params).status_code == status


def test_empty_results_missing_and_tombstoned_explanations(search_client):
    client, engine = search_client
    engine.brain.write_node(Node(id="semantic", text="deleted", status="tombstone"))
    engine.brain.write_node(Node(id="other", text="deleted", status="tombstone"))
    assert client.get("/api/search", params={"query": "anything"}).json()["results"] == []
    for nid in ("unknown", "deleted"):
        assert client.get(f"/api/search/{nid}/explain", params={"query": "anything"}).status_code == 404


def test_snippet_is_bounded_plain_text_and_query_trimmed(search_client):
    client, engine = search_client
    hostile = '<img src=x onerror="window.__pwned=1">'
    engine.brain.write_node(Node(id="hostile", text=hostile + " " + "x" * 300))
    data = client.get("/api/search", params={"query": "  x  ", "k": 20}).json()
    result = next(r for r in data["results"] if r["id"] == "hostile")
    assert data["query"] == "x"
    assert result["snippet"].startswith(hostile)
    assert len(result["snippet"]) == 200 and result["snippet"].endswith("…")
    assert [r["rank"] for r in data["results"]] == list(range(1, len(data["results"]) + 1))


def test_optional_reranking_preserves_rrf_score_kind(search_client):
    client, engine = search_client
    from graph_engine.retrieval import retrieve
    query = "Restore archived notes Bananas"
    original = retrieve(engine, query, k=20, persist=False)
    engine.reranker = ReverseReranker()
    results = client.get("/api/search", params={"query": query, "k": 20}).json()["results"]
    assert [r["id"] for r in results] == [nid for nid, _ in reversed(original)]
    assert {r["id"]: r["score"] for r in results} == dict(original)
    assert all(r["score_kind"] == "rrf" for r in results)

"""API coverage for reversible decisions and live updates; uses an isolated brain."""

import pytest
from fastapi.testclient import TestClient

from graph_engine.brain import Brain, Edge, Node
from graph_engine.server import app


@pytest.fixture
def client_and_edge(tmp_path, monkeypatch):
    path = tmp_path / "brain"
    monkeypatch.setenv("IG_BRAIN_PATH", str(path))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    brain = Brain(str(path))
    brain.write_node(Node(id="first", text="Erste Idee"))
    brain.write_node(Node(id="second", text="Zweite Idee"))
    edge = Edge(source="first", target="second", kind="similar")
    brain.add_edge(edge)
    with TestClient(app) as client:
        yield client, edge


@pytest.mark.parametrize("action", ["accept", "reject"])
def test_saved_decision_can_be_undone_with_live_update(client_and_edge, action):
    client, edge = client_and_edge
    with client.websocket_connect("/ws") as ws:
        assert client.post(f"/api/edge/{edge.id}/{action}").status_code == 200
        assert ws.receive_json()["type"] == "edge_resolved"
        edges = client.get("/api/graph").json()["edges"]
        assert (edges == []) if action == "reject" else (edges[0]["pending"] is False)
        restored = client.post(f"/api/edge/{edge.id}/undo")
        assert restored.status_code == 200
        assert restored.json() == edge.to_dict()
        assert ws.receive_json() == {"type": "edge_restored", "edge": edge.to_dict()}
        assert client.get("/api/graph").json()["edges"] == [edge.to_dict()]
        assert client.post(f"/api/edge/{edge.id}/undo").status_code == 409


def test_unknown_undo_and_local_ui_routes(client_and_edge):
    client, _ = client_and_edge
    assert client.post("/api/edge/unknown/undo").status_code == 409
    for path, content_type in [("/", "text/html"), ("/app.js", "javascript"),
                               ("/review", "text/html"), ("/review.js", "javascript")]:
        response = client.get(path)
        assert response.status_code == 200
        assert content_type in response.headers["content-type"]

def test_api_report_read_only_digest(client_and_edge):
    """Report #7: /api/report returns the digest without mutating anything."""
    client, edge = client_and_edge
    before = client.get("/api/graph").json()
    r = client.get("/api/report")
    assert r.status_code == 200
    data = r.json()
    for key in ("generated_at", "markdown", "nodes", "edges", "kinds",
                "intent_queue", "hubs", "hygiene", "research_next"):
        assert key in data
    assert data["nodes"] == 2 and data["edges"] == 1
    assert "BRAIN_REPORT" in data["markdown"]
    # read-only: nothing changed
    assert client.get("/api/graph").json() == before


def test_api_report_params_validated(client_and_edge):
    """since=garbage → 400 client error with the usage hint (audit #57
    convention: engine ValueErrors are client errors, never 500s)."""
    client, _ = client_and_edge
    r = client.get("/api/report", params={"since": "garbage"})
    assert r.status_code == 400
    assert "--since expects" in str(r.json())
    data = client.get("/api/report", params={"top": 1}).json()
    assert len(data["hubs"]) <= 1


def test_report_page_and_js_served(client_and_edge):
    client, _ = client_and_edge
    assert client.get("/report").status_code == 200
    assert client.get("/report.js").status_code == 200

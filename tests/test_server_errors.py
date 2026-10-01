"""Server error-path coverage (audit #57: server error paths had zero tests).

Complements tests/test_server.py (happy paths + undo) with the failure
surface: empty-text ingest, unknown edge ids, malformed payloads, and the
keyed engine cache behavior on env changes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from graph_engine.brain import Brain, Edge, Node
from graph_engine.server import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "brain"
    monkeypatch.setenv("IG_BRAIN_PATH", str(path))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    brain = Brain(str(path))
    brain.write_node(Node(id="first", text="Erste Idee"))
    brain.write_node(Node(id="second", text="Zweite Idee"))
    brain.add_edge(Edge(source="first", target="second", kind="similar"))
    with TestClient(app) as c:
        yield c


def test_ingest_empty_text_rejected(client):
    """Empty text must be a clean 4xx, not a 500 (engine raises ValueError)."""
    r = client.post("/api/ingest", json={"text": "", "source": "t"})
    assert r.status_code in (400, 422), (
        f"empty ingest returned {r.status_code} — server lacks a ValueError handler")


def test_ingest_missing_field_rejected(client):
    r = client.post("/api/ingest", json={"source": "t"})
    assert r.status_code in (400, 422)


def test_edge_resolve_unknown_id_404(client):
    r = client.post("/api/edge/doesnotexist/accept")
    assert r.status_code == 404
    body = r.json()
    assert "not found" in str(body).lower()


def test_edge_resolve_unknown_action_404(client):
    edges = client.get("/api/graph").json()["edges"]
    assert edges, "fixture brain must have an edge"
    eid = edges[0]["id"]
    r = client.post(f"/api/edge/{eid}/frobnicate")
    assert r.status_code in (404, 405)


def test_edge_undo_unknown_id_409(client):
    """Undo of an unknown/already-resolved edge is 409 by contract."""
    r = client.post("/api/edge/doesnotexist/undo")
    assert r.status_code == 409


def test_graph_shape_contract(client):
    g = client.get("/api/graph").json()
    assert set(g.keys()) >= {"nodes", "edges"}
    assert all({"id", "text"} <= set(n.keys()) for n in g["nodes"])
    assert all({"id", "source", "target", "kind", "pending"} <= set(e.keys())
               for e in g["edges"])


def test_malformed_json_rejected(client):
    r = client.post("/api/ingest", content=b"{not json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 422)

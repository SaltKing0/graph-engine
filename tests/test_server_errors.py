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


def test_report_recovers_from_vector_damage(client, monkeypatch, tmp_path, damaged_vector_cache):
    brain = Brain(str(tmp_path / "brain"), mode="local")
    for nid in ("a", "b"):
        brain.write_node(Node(id=nid, text=nid))
    brain.vectors_file.write_text(damaged_vector_cache, encoding="utf-8")
    before = {p.relative_to(brain.path): p.read_bytes()
              for p in brain.path.rglob("*") if p.is_file()}
    # Reporting must not repair the cache by loading a model.
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "unavailable")
    response = client.get("/api/report")
    assert response.status_code == 200
    assert response.json()["nodes"] == 4
    assert "## Hygiene" in response.json()["markdown"]
    assert before == {p.relative_to(brain.path): p.read_bytes()
                      for p in brain.path.rglob("*") if p.is_file()}

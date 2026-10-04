"""Security boundary and isolation regressions (no network/model required)."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from graph_engine import access, namespaces, runtime
from graph_engine.brain import Brain, Edge, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder


@pytest.fixture
def protected(tmp_path, monkeypatch):
    path = tmp_path / "brain"
    raw = Brain(str(path))
    raw.init()
    for nid in ("public", "private", "readonly"):
        raw.write_node(Node(id=nid, text=f"{nid} knowledge", status="active"))
    raw.write_vectors({"public": [1., 0.], "private": [0., 1.], "readonly": [1., 1.]})
    raw.add_edge(Edge("public", "private", "linked", id="hidden-edge"))
    raw.add_edge(Edge("public", "readonly", "fact", id="hidden-evidence", evidence=[{"node_id": "private", "text": "secret evidence"}]))
    policy = {"graphs": {"default": {"roles": {"owner": "admin", "alice": "editor", "bob": "viewer"},
              "nodes": {"private": {"read": ["owner"], "write": ["owner"]},
                        "readonly": {"write": ["owner"]}}}},
              "tokens": {hashlib.sha256(b"viewer-token").hexdigest(): "bob",
                         hashlib.sha256(b"editor-token").hexdigest(): "alice"}}
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps(policy))
    monkeypatch.setenv("IG_ACCESS_POLICY", str(policy_file))
    monkeypatch.setenv("IG_PRINCIPAL", "alice")
    monkeypatch.setenv("IG_BRAIN_PATH", str(path))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    monkeypatch.delenv("IG_GRAPH_HOME", raising=False)
    monkeypatch.delenv("IG_GRAPH", raising=False)
    return raw, policy_file, policy


def test_nodes_edges_vectors_and_shared_memo_do_not_leak(protected):
    raw, _, _ = protected
    raw.vectors_for({"private", "public"}, lambda _: [1., 0.], persist=False)
    secured = runtime.make_brain()
    assert {n.id for n in secured.read_nodes()} == {"public", "readonly"}
    assert secured.read_edges() == []
    assert "private" not in secured.read_vectors()
    assert "private" not in secured.vectors_for({"public", "private"}, lambda _: [1., 0.])
    with pytest.raises(PermissionError):
        secured.read_node("private")
    with pytest.raises(PermissionError):
        secured.write_node(Node(id="readonly", text="overwrite"))
    with pytest.raises(PermissionError):
        secured.write_node(Node(id="private", text="overwrite"))
    assert raw.read_node("readonly").text == "readonly knowledge"


def test_bulk_rewrites_preserve_hidden_records(protected):
    raw, _, _ = protected
    secured = runtime.make_brain()
    secured.write_edges([])
    secured.write_vectors({"public": [2., 0.], "readonly": [1., 1.]})
    assert len(raw.read_edges()) == 2
    assert raw.read_vectors()["private"] == [0., 1.]
    with pytest.raises(PermissionError):
        secured.add_edge(Edge("public", "readonly", "linked"))
    assert len(raw.read_edges()) == 2


def test_revocation_fail_closed_and_audit(protected):
    _, path, policy = protected
    secured = runtime.make_brain()
    policy["graphs"]["default"]["roles"].pop("alice")
    path.write_text(json.dumps(policy))
    with pytest.raises(PermissionError):
        secured.read_nodes()
    events = [json.loads(line) for line in path.with_suffix(".audit.jsonl").read_text().splitlines()]
    assert events[-1]["allowed"] is False
    assert events[-1]["principal"] == "alice"
    path.write_text("{")
    with pytest.raises(PermissionError):
        runtime.make_brain()


def test_viewer_search_no_cache_or_recall_writes(protected, monkeypatch):
    from graph_engine.retrieval import retrieve
    from graph_engine.recall import record, aggregate
    raw, _, _ = protected
    monkeypatch.setenv("IG_PRINCIPAL", "bob")
    brain = runtime.make_brain()
    before = raw.vectors_file.read_bytes()
    hits = retrieve(BrainEngine(brain, HashEmbedder()), "knowledge", k=10)
    assert "private" not in {nid for nid, _ in hits}
    assert raw.vectors_file.read_bytes() == before
    assert record(brain, "query", ["public"]) == 0
    assert not (raw.path / "recalls.jsonl").exists()
    with pytest.raises(PermissionError):
        brain.write_node(Node(text="no"))
    with pytest.raises(PermissionError):
        aggregate(brain)


def test_http_auth_read_write_report_and_websocket(protected, monkeypatch, tmp_path):
    from graph_engine.server import app
    from starlette.websockets import WebSocketDisconnect
    fallback = tmp_path / "structural.json"
    fallback.write_text(json.dumps([{"kind": "hole", "label": "secret fallback", "node_ids": ["private"]}]))
    monkeypatch.setenv("IG_STRUCTURAL_PATH", str(fallback))
    client = TestClient(app)
    assert client.get("/api/graph").status_code == 401
    assert client.get("/api/graph", headers={"X-Principal": "owner"}).status_code == 401
    headers = {"Authorization": "Bearer viewer-token"}
    result = client.get("/api/graph", headers=headers)
    assert result.status_code == 200
    assert "private" not in result.text and "secret evidence" not in result.text
    report = client.get("/api/report", headers=headers)
    assert report.status_code == 200
    assert "private" not in report.text and "secret fallback" not in report.text
    assert client.post("/api/ingest", headers=headers, json={"text": "no write"}).status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers=headers):
            pass
    result = client.post("/api/ingest", headers={"Authorization": "Bearer editor-token"}, json={"text": "Completely unrelated cheese astronomy", "allow_duplicates": True})
    assert result.status_code == 200


def test_mcp_hidden_node_and_missing_identity(protected, monkeypatch):
    from graph_engine.mcp.server import get_node, brain_status
    assert get_node("private")["ok"] is False
    monkeypatch.setenv("IG_PRINCIPAL", "unknown")
    assert brain_status()["ok"] is False


def test_namespaces_persist_isolate_and_reject_escape(tmp_path, monkeypatch):
    monkeypatch.delenv("IG_ACCESS_POLICY", raising=False)
    monkeypatch.delenv("IG_GRAPH", raising=False)
    monkeypatch.setenv("IG_GRAPH_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    namespaces.create_graph("work")
    namespaces.create_graph("personal")
    namespaces.switch_graph("work")
    runtime.make_brain().write_node(Node(id="same-id", text="work memory"))
    work_engine = runtime.make_engine()
    namespaces.switch_graph("personal")
    assert runtime.make_brain().read_nodes() == []
    runtime.make_brain().write_node(Node(id="same-id", text="personal memory"))
    assert runtime.make_engine() is not work_engine
    namespaces.switch_graph("work")
    assert namespaces.selected() == "work"
    assert runtime.make_brain().read_node("same-id").text == "work memory"
    assert namespaces.list_graphs() == ["personal", "work"]
    for bad in ("../escape", "/tmp", "a/b", ".", "a\\b"):
        with pytest.raises(ValueError):
            namespaces.create_graph(bad)
    (tmp_path / "home" / "graphs" / "alias").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        namespaces.switch_graph("alias")


def test_namespace_policy_filters_lists_and_denies_switch(protected, tmp_path, monkeypatch):
    _, policy_path, policy = protected
    monkeypatch.setenv("IG_GRAPH_HOME", str(tmp_path / "namespaces"))
    monkeypatch.delenv("IG_ACCESS_POLICY")
    namespaces.create_graph("shared")
    namespaces.create_graph("secret")
    policy["graphs"]["shared"] = {"roles": {"alice": "viewer"}}
    policy["graphs"]["secret"] = {"roles": {"owner": "admin"}}
    policy_path.write_text(json.dumps(policy))
    monkeypatch.setenv("IG_ACCESS_POLICY", str(policy_path))
    assert namespaces.list_graphs() == ["shared"]
    namespaces.switch_graph("shared")
    with pytest.raises(PermissionError):
        namespaces.switch_graph("secret")
    with pytest.raises(PermissionError):
        namespaces.create_graph("new")
    assert namespaces.selected() == "shared"


def test_graph_cli_does_not_load_model(tmp_path, monkeypatch, capsys):
    from graph_engine import __main__ as cli
    monkeypatch.delenv("IG_ACCESS_POLICY", raising=False)
    monkeypatch.delenv("IG_GRAPH", raising=False)
    monkeypatch.setenv("IG_GRAPH_HOME", str(tmp_path / "graphs"))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setattr(cli, "make_engine", lambda: pytest.fail("graph CLI loaded model"))
    for args in (["create", "one"], ["switch", "one"], ["list"]):
        monkeypatch.setattr("sys.argv", ["ig", "graph", *args])
        cli.main()
    assert "* one" in capsys.readouterr().out


def test_request_graph_stays_pinned_during_selection_change(tmp_path, monkeypatch):
    monkeypatch.delenv("IG_ACCESS_POLICY", raising=False)
    monkeypatch.delenv("IG_GRAPH", raising=False)
    monkeypatch.setenv("IG_GRAPH_HOME", str(tmp_path / "graphs"))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    namespaces.create_graph("one")
    namespaces.create_graph("two")
    namespaces.switch_graph("one")
    token = namespaces.request_graph.set(namespaces.selected())
    try:
        namespaces.switch_graph("two")
        assert runtime.brain_path().endswith("/one")
    finally:
        namespaces.request_graph.reset(token)
    assert runtime.brain_path().endswith("/two")


def test_editor_global_maintenance_denied_before_writes(protected):
    from graph_engine.dream import refresh, lifecycle, distill
    from graph_engine.merge import merge_nodes
    from graph_engine.consolidation import consolidate
    raw, _, _ = protected
    brain = runtime.make_brain()
    before = {str(p.relative_to(raw.path)): p.read_bytes() for p in raw.path.rglob("*") if p.is_file()}
    for fn in (refresh, lifecycle, distill, consolidate):
        with pytest.raises(PermissionError):
            fn(brain)
    with pytest.raises(PermissionError):
        merge_nodes(brain, "public", "readonly")
    after = {str(p.relative_to(raw.path)): p.read_bytes() for p in raw.path.rglob("*") if p.is_file()}
    assert before == after

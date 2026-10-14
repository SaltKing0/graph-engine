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


@pytest.mark.parametrize("mode", ["extract", "copy", "legacy", "structured", "distill", "entities", "merge"])
def test_derived_memories_inherit_source_acl_on_every_read_surface(protected, monkeypatch, mode):
    from graph_engine.consolidation import consolidate, ConsolidationConfig
    from graph_engine.dream import distill
    from graph_engine.entities import extract_entities
    from graph_engine.merge import merge_nodes
    from graph_engine.retrieval import retrieve
    from graph_engine.context import build_context
    raw, _, _ = protected
    secret = "Alice works at PrivateExampleCo."
    raw.write_node(Node(id="private", text=secret, ntype="episodic",
                        created="2020-01-01T00:00:00Z", status="active"))
    admin = access.SecuredBrain(str(raw.path), graph_name="default", identity="owner")
    engine = BrainEngine(admin, HashEmbedder(), reranker=False)
    before = {n.id for n in raw.read_nodes()}
    if mode == "extract":
        engine.extract("private")
    elif mode in ("copy", "legacy", "structured"):
        options = {}
        if mode == "legacy":
            options["extractor"] = lambda text: text
        elif mode == "structured":
            options["structured_extractor"] = lambda events: dict(version=1, abstain=False,
                facts=[dict(text=secret, evidence=[dict(node_id="private", quote=secret)])])
        consolidate(admin, config=ConsolidationConfig(threshold=0, min_age_days=0),
                    commit=False, **options)
    elif mode == "distill":
        raw.write_edges([Edge("private", "public", "extends", pending=False)])
        distill(admin, min_size=2, members_per_summary=1, commit=False,
                summarizer=lambda digest: secret)
    elif mode == "entities":
        extract_entities(admin, node_id="private", commit=False)
    else:
        merge_nodes(admin, "public", "private", commit=False)
    derived = {n.id for n in raw.read_nodes()} - before if mode != "merge" else {"public"}
    assert derived
    # Both persisted and computed vectors must respect the same source boundary.
    raw.vectors_for(derived, lambda text: [1., 0.])
    viewer = access.SecuredBrain(str(raw.path), graph_name="default", identity="bob")
    assert derived <= {n.id for n in admin.read_nodes()}
    assert derived.isdisjoint(n.id for n in viewer.read_nodes())
    assert derived.isdisjoint(viewer.read_vectors())
    assert viewer.vectors_for(derived, lambda text: pytest.fail("embedded hidden text")) == {}
    for nid in derived:
        with pytest.raises(PermissionError):
            viewer.read_node(nid)
    viewer_engine = BrainEngine(viewer, HashEmbedder(), reranker=False)
    assert derived.isdisjoint(nid for nid, _ in retrieve(viewer_engine, secret, k=20))
    assert "PrivateExampleCo" not in str(build_context(viewer_engine, secret, k=20))
    from graph_engine.server import app
    client = TestClient(app)
    headers = {"Authorization": "Bearer viewer-token"}
    for route in ("/api/graph", "/api/report"):
        response = client.get(route, headers=headers)
        assert response.status_code == 200
        assert "PrivateExampleCo" not in response.text
    pytest.importorskip("mcp")
    monkeypatch.setenv("IG_PRINCIPAL", "bob")
    from graph_engine.mcp.server import get_node, search_brain, build_context as mcp_context
    for nid in derived:
        assert get_node(nid)["ok"] is False
    assert "PrivateExampleCo" not in str(search_brain("Alice", k=20))
    assert "PrivateExampleCo" not in str(mcp_context("Alice", k=20))


def test_current_acl_revocation_transitive_multi_source_and_no_silent_publication(protected):
    raw, path, policy = protected
    raw.write_node(Node("first source", id="s1"))
    raw.write_node(Node("second source", id="s2"))
    raw.write_node(Node("combined secret", id="combined", derived_from=["s1", "s2"]))
    raw.write_node(Node("nested secret", id="nested", derived_from=["combined", "s1"]))
    raw.write_vectors({"combined": [1.], "nested": [2.]})
    viewer = access.SecuredBrain(str(raw.path), graph_name="default", identity="bob")
    assert {"combined", "nested"} <= {n.id for n in viewer.read_nodes()}
    policy["graphs"]["default"]["nodes"]["s2"] = {"read": ["owner"]}
    path.write_text(json.dumps(policy))
    assert {"combined", "nested"}.isdisjoint(n.id for n in viewer.read_nodes())
    assert viewer.read_vectors() == {}
    # An explicit ACL on the derived ID cannot override a source restriction.
    policy["graphs"]["default"]["nodes"]["combined"] = {"read": ["*"]}
    path.write_text(json.dumps(policy))
    assert not viewer.can_access("read", "combined")
    admin = access.SecuredBrain(str(raw.path), graph_name="default", identity="owner")
    admin.write_node(Node("rewritten secret", id="combined"))
    assert raw.read_node("combined").derived_from == ["s1", "s2"]
    assert not viewer.can_access("read", "combined")
    editor = access.SecuredBrain(str(raw.path), graph_name="default", identity="alice")
    with pytest.raises(PermissionError):
        editor.write_node(Node("new derived secret", id="forged", derived_from=["s2"]))
    assert raw.read_node("forged") is None
    policy["graphs"]["default"]["nodes"].pop("s2")
    path.write_text(json.dumps(policy))
    assert viewer.read_node("nested").text == "nested secret"
    assert viewer.read_vectors() == {"combined": [1.], "nested": [2.]}


def test_missing_cyclic_and_malformed_provenance_fail_closed(protected):
    raw, _, _ = protected
    raw.write_node(Node("orphan", id="orphan", derived_from=["absent"]))
    raw.write_node(Node("cycle a", id="cycle-a", derived_from=["cycle-b"]))
    raw.write_node(Node("cycle b", id="cycle-b", derived_from=["cycle-a"]))
    raw.write_node(Node("self cycle", id="self", derived_from=["self"]))
    raw.write_node(Node("bad metadata", id="malformed"))
    node_path = raw.node_path("malformed")
    node_path.write_text(node_path.read_text().replace("type: semantic", 'derived_from: "private"\ntype: semantic'))
    raw.write_vectors({nid: [1.] for nid in ("orphan", "cycle-a", "cycle-b", "self", "malformed", "absent")})
    for identity in ("owner", "bob"):
        secured = access.SecuredBrain(str(raw.path), graph_name="default", identity=identity)
        assert secured.read_vectors() == {}
        for nid in ("orphan", "cycle-a", "cycle-b", "self"):
            assert not secured.can_access("read", nid)
            with pytest.raises(PermissionError):
                secured.read_node(nid)
        assert secured.read_node("malformed") is None
    with pytest.raises(PermissionError):
        secured = access.SecuredBrain(str(raw.path), graph_name="default", identity="owner")
        secured.write_node(Node("self", id="new-cycle", derived_from=["new-cycle"]))


def test_legacy_extractions_and_incomplete_model_lineage(protected):
    raw, _, _ = protected
    raw.write_node(Node("legacy secret", id="legacy", source="human"))
    raw.add_edge(Edge("legacy", "private", "extends", origin="consolidator",
                      rejected=True))
    raw.write_node(Node("legacy name", id="entity", ntype="entity", source="entity-extractor"))
    raw.add_edge(Edge("private", "entity", "mentions", origin="entity-extractor"))
    raw.write_node(Node("old summary", id="summary", tags=["community-summary"], source="consolidator"))
    raw.add_edge(Edge("summary", "public", "extends", origin="consolidator"))
    raw.write_node(Node("old proposal", id="proposal", tags=["consolidation-proposal"], source="consolidator"))
    raw.add_edge(Edge("proposal", "public", "extends", origin="consolidator"))
    viewer = access.SecuredBrain(str(raw.path), graph_name="default", identity="bob")
    assert {"legacy", "entity", "summary", "proposal"}.isdisjoint(n.id for n in viewer.read_nodes())
    admin = access.SecuredBrain(str(raw.path), graph_name="default", identity="owner")
    assert admin.read_node("legacy")
    admin.write_node(Node("edited legacy secret", id="legacy"))
    raw.write_edges([])
    assert raw.read_node("legacy").derived_from == ["private"]
    assert not viewer.can_access("read", "legacy")


def test_structured_batch_inherits_uncited_inputs_and_reused_fact_sources(protected):
    from graph_engine.consolidation import ConsolidationConfig, consolidate
    raw, _, _ = protected
    for nid in ("public", "private"):
        raw.write_node(Node("shared fact", id=nid, ntype="episodic", created="2020-01-01T00:00:00Z"))
    admin = access.SecuredBrain(str(raw.path), graph_name="default", identity="owner")
    consolidate(admin, config=ConsolidationConfig(threshold=0, min_age_days=0), commit=False,
                structured_extractor=lambda events: dict(version=1, abstain=False,
                facts=[dict(text="shared fact", evidence=[dict(node_id="public", quote="shared fact")])]))
    proposal = next(n for n in raw.read_nodes() if "consolidation-proposal" in n.tags)
    assert proposal.derived_from == ["private", "public"]
    viewer = access.SecuredBrain(str(raw.path), graph_name="default", identity="bob")
    assert not viewer.can_access("read", proposal.id)
    # Exact copy reuse accumulates every source, including a public existing note.
    raw.write_edges([])
    raw.write_node(Node("shared fact", id="existing"))
    consolidate(admin, config=ConsolidationConfig(threshold=0, min_age_days=0), commit=False)
    assert raw.read_node("existing").derived_from == ["private", "public"]
    assert not viewer.can_access("read", "existing")


def test_removing_legacy_evidence_preserves_private_lineage(protected):
    raw, _, _ = protected
    raw.write_node(Node("legacy copied secret", id="legacy"))
    raw.write_edges([Edge("legacy", "private", "extends", origin="consolidator")])
    admin = access.SecuredBrain(str(raw.path), graph_name="default", identity="owner")
    admin.write_edges([])
    assert raw.read_edges(include_rejected=True) == []
    assert raw.read_node("legacy").derived_from == ["private"]
    viewer = access.SecuredBrain(str(raw.path), graph_name="default", identity="bob")
    assert not viewer.can_access("read", "legacy")


@pytest.mark.parametrize("invalid", ['null', '"private"', '[null]', '["../private"]'])
def test_malformed_derivation_metadata_is_not_readable(invalid):
    raw = Node("text", derived_from=["private", "public", "private"]).to_markdown()
    assert Node.from_markdown(raw).derived_from == ["private", "public"]
    with pytest.raises(ValueError):
        Node.from_markdown(raw.replace('["private", "public"]', invalid))


def test_derivation_preserves_legacy_node_id_formats(protected):
    raw, _, _ = protected
    for nid in ("node.with.dots", "Deutschä", "name: test"):
        raw.write_node(Node("source", id=nid))
    raw.write_node(Node("derived", id="derived", derived_from=["node.with.dots", "Deutschä", "name: test"]))
    viewer = access.SecuredBrain(str(raw.path), graph_name="default", identity="bob")
    assert viewer.read_node("derived").text == "derived"


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


@pytest.mark.parametrize("origin", [None, "http://testserver", "https://untrusted.example"])
def test_http_auth_read_write_report_and_websocket(protected, monkeypatch, tmp_path, origin):
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
    ws_headers = {**headers, **({"Origin": origin} if origin is not None else {})}
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect("/ws", headers=ws_headers):
            pass
    assert denied.value.code == 1008
    result = client.post("/api/ingest", headers={"Authorization": "Bearer editor-token"}, json={"text": "Completely unrelated cheese astronomy", "allow_duplicates": True})
    assert result.status_code == 200


def test_mcp_hidden_node_and_missing_identity(protected, monkeypatch):
    pytest.importorskip("mcp")
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


@pytest.mark.parametrize("factory", [runtime.make_brain, runtime.make_engine])
def test_graph_identity_and_path_use_one_selection(protected, tmp_path, monkeypatch, factory):
    _, policy_file, policy = protected
    monkeypatch.setenv("IG_GRAPH_HOME", str(tmp_path / "graphs"))
    monkeypatch.delenv("IG_ACCESS_POLICY")
    for name in ("allowed", "secret"):
        namespaces.create_graph(name)
        Brain(str(namespaces.graph_path(name))).write_node(Node(id="same", text=name))
    policy["graphs"]["allowed"] = {"roles": {"alice": "viewer"}}
    policy["graphs"]["secret"] = {"roles": {"owner": "admin"}}
    policy_file.write_text(json.dumps(policy))
    monkeypatch.setenv("IG_ACCESS_POLICY", str(policy_file))
    selections = iter(["allowed", "secret"])
    monkeypatch.setattr(namespaces, "selected", lambda: next(selections))
    result = factory()
    brain = result.brain if isinstance(result, BrainEngine) else result
    assert brain.graph_name == "allowed"
    assert brain.read_node("same").text == "allowed"
    assert next(selections) == "secret"  # no second selection during construction


@pytest.mark.parametrize("factory", [runtime.brain_path, runtime.make_brain, runtime.make_engine])
def test_explicit_graph_without_home_fails_instead_of_using_legacy(monkeypatch, factory):
    monkeypatch.delenv("IG_GRAPH_HOME", raising=False)
    monkeypatch.delenv("IG_ACCESS_POLICY", raising=False)
    monkeypatch.setenv("IG_GRAPH", "personal")
    with pytest.raises(ValueError, match="IG_GRAPH_HOME"):
        factory()


def test_mcp_call_pins_graph_across_selection_change(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from graph_engine.mcp.server import _access_guard
    monkeypatch.delenv("IG_ACCESS_POLICY", raising=False)
    monkeypatch.delenv("IG_GRAPH", raising=False)
    monkeypatch.setenv("IG_GRAPH_HOME", str(tmp_path / "graphs"))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    for name in ("one", "two"):
        namespaces.create_graph(name)
    namespaces.switch_graph("one")

    def operation():
        before = runtime.brain_path()
        namespaces.switch_graph("two")
        return before, runtime.brain_path()

    before, after = _access_guard(operation, "read")()
    assert before == after
    assert after.endswith("/one")
    assert namespaces.selected() == "two"


@pytest.mark.parametrize("metadata", [
    {"source": "human\nid: readonly"},
    {"source": "human\rid: readonly"},
    {"tags": ["safe\nid: readonly"]},
    {"tags": ["safe\u2028id: readonly"]},
])
def test_http_rejects_metadata_identity_injection(protected, metadata):
    from graph_engine.server import app
    raw, _, _ = protected
    before = {n.id: n.to_dict() for n in raw.read_nodes()}
    result = TestClient(app).post("/api/ingest", headers={"Authorization": "Bearer editor-token"},
                                 json={"text": "injected data", "allow_duplicates": True, **metadata})
    assert result.status_code == 400
    assert {n.id: n.to_dict() for n in raw.read_nodes()} == before


def test_duplicate_ingest_rejects_multiline_source(protected):
    from graph_engine.server import app
    raw, _, _ = protected
    client = TestClient(app)
    headers = {"Authorization": "Bearer editor-token"}
    first = client.post("/api/ingest", headers=headers, json={"text": "a distinct new memory"})
    assert first.status_code == 200
    before = {n.id: n.to_dict() for n in raw.read_nodes()}
    result = client.post("/api/ingest", headers=headers,
                         json={"text": "a distinct new memory", "source": "human\nid: readonly"})
    assert result.status_code == 400
    assert {n.id: n.to_dict() for n in raw.read_nodes()} == before


def test_stored_identity_must_match_filename(protected):
    raw, _, _ = protected
    raw.node_path("forged").write_text(Node(id="readonly", text="spoof").to_markdown())
    assert raw.read_node("forged") is None
    assert len([n for n in raw.read_nodes() if n.id == "readonly"]) == 1
    raw.node_path("forged").write_text("---\nid: forged\nid: readonly\n---\nspoof")
    assert raw.read_node("forged") is None


def test_forget_preflights_all_affected_permissions(protected):
    from graph_engine.agent_memory import forget
    raw, _, _ = protected
    raw.add_edge(Edge("public", "readonly", "similar", pending=False))
    before = {str(p.relative_to(raw.path)): p.read_bytes() for p in raw.path.rglob("*") if p.is_file()}
    with pytest.raises(PermissionError):
        forget(runtime.make_brain(), "public", reason="test", commit=False)
    after = {str(p.relative_to(raw.path)): p.read_bytes() for p in raw.path.rglob("*") if p.is_file()}
    assert before == after


def test_feedback_tiers_and_inference_respect_node_access(protected, monkeypatch):
    from graph_engine.feedback import record_feedback, read_feedback
    from graph_engine.inference import infer
    from graph_engine.retrieval import explain
    from graph_engine.tiers import set_tier
    raw, _, _ = protected
    monkeypatch.setenv("IG_PRINCIPAL", "owner")
    record_feedback(runtime.make_engine(), "knowledge private", "private", "relevant", commit=False)
    monkeypatch.setenv("IG_PRINCIPAL", "alice")
    engine = runtime.make_engine()
    assert read_feedback(engine.brain) == []
    assert explain(engine, "public", "knowledge private")["learning"]["expansion_terms"] == []
    for nid in ("readonly", "private"):
        with pytest.raises(PermissionError):
            record_feedback(engine, "knowledge", nid, "relevant", commit=False)
        with pytest.raises(PermissionError):
            set_tier(engine.brain, nid, "main", commit=False)
    with pytest.raises(ValueError, match="No live node"):
        infer(engine.brain, "public -> private")
    record_feedback(engine, "knowledge", "public", "relevant", commit=False)
    set_tier(engine.brain, "public", "main", commit=False)
    assert raw.read_node("public").tier_locked
    monkeypatch.setenv("IG_PRINCIPAL", "owner")
    assert {r["node_id"] for r in read_feedback(runtime.make_brain())} == {"public", "private"}


def test_http_search_acl_viewer_read_only_and_revocation(protected, monkeypatch):
    from graph_engine.server import app
    raw, policy_path, policy = protected
    raw.write_node(Node(id="deleted", text="knowledge", status="tombstone"))
    # Missing vectors must be computed without filling the protected disk cache.
    raw.vectors_file.unlink()
    client = TestClient(app)
    query = {"query": "knowledge", "k": 20}
    headers = {"Authorization": "Bearer viewer-token"}
    for path in ("/api/search", "/api/search/public/explain"):
        assert client.get(path, params=query).status_code == 401
        assert client.get(path, params=query, headers={"Authorization": "Bearer invalid"}).status_code == 401
    before = {str(p.relative_to(raw.path)): p.read_bytes() for p in raw.path.rglob("*") if p.is_file()}
    response = client.get("/api/search", params=query, headers=headers)
    assert response.status_code == 200
    assert {r["id"] for r in response.json()["results"]} == {"public", "readonly"}
    assert "private" not in response.text and "deleted" not in response.text
    explained = client.get("/api/search/public/explain", params=query, headers=headers)
    assert explained.status_code == 200
    assert "private" not in explained.text and "secret evidence" not in explained.text
    assert client.get("/api/search/private/explain", params=query, headers=headers).status_code == 403
    after = {str(p.relative_to(raw.path)): p.read_bytes() for p in raw.path.rglob("*") if p.is_file()}
    assert after == before
    # Editors may record only writable hits, and still cannot persist vectors.
    response = client.get("/api/search", params=query, headers={"Authorization": "Bearer editor-token"})
    assert response.status_code == 200
    ledger = [json.loads(line) for line in (raw.path / "recalls.jsonl").read_text().splitlines()]
    assert ledger[-1]["ids"] == ["public"]
    assert not raw.vectors_file.exists()
    policy["graphs"]["default"]["roles"].pop("bob")
    policy_path.write_text(json.dumps(policy))
    assert client.get("/api/search", params=query, headers=headers).status_code == 403
    assert client.get("/api/search/public/explain", params=query, headers=headers).status_code == 403


def test_context_permission_filtering_main_and_evidence(protected, monkeypatch):
    from graph_engine.context import build_context
    raw, _, _ = protected
    node = raw.read_node("private")
    node.storage_tier, node.tier_locked = "main", True
    raw.write_node(node)
    # Make the hidden fact accepted so filtering must enforce its evidence ACL.
    edges = raw.read_edges()
    for edge in edges:
        edge.pending = False
    raw.write_edges(edges)
    engine = BrainEngine(runtime.make_brain(), HashEmbedder())
    # Even a stale retrieval hit must not bypass visible-node selection.
    monkeypatch.setattr("graph_engine.retrieval.retrieve", lambda *a, **kw:
                        [("private", 1.), ("public", .5)])
    result = build_context(engine, "knowledge")
    assert result["nodes"] == ["public"]
    assert "private" not in json.dumps(result) and "secret evidence" not in json.dumps(result)
    assert result["memories"][0]["evidence"] == []
    pytest.importorskip("mcp")
    from graph_engine.mcp.server import build_context as context_tool
    assert context_tool("knowledge")["nodes"] == ["public"]
    monkeypatch.setenv("IG_PRINCIPAL", "unknown")
    assert context_tool("knowledge")["error"]["code"] == "forbidden"


def test_capture_extraction_readonly_entity_fails_before_subgraph_writes(protected):
    raw, path, policy = protected
    raw.write_node(Node("Alice", id="readonly", ntype="entity", entity_name="Alice", entity_type="person"))
    engine = runtime.make_engine()
    _, _, _, failed = engine.capture("Alice works at Acme.", extraction="rules")
    assert failed["status"] == "failed" and failed["error"] == "access_denied"
    assert raw.read_node("readonly").aliases == []
    assert not any(n.entity_name == "Acme" for n in raw.read_nodes())
    assert not any(e.origin == "entity-extractor" for e in raw.read_edges(True))
    # Grant the existing entity; the saved capture resumes without a second note.
    policy["graphs"]["default"]["nodes"]["readonly"]["write"] = ["owner", "alice"]
    path.write_text(json.dumps(policy))
    result = engine.capture("Alice works at Acme.", extraction="rules")[3]
    assert result["status"] == "complete" and result["retried"]
    assert result["reused_entities"] == 1 and result["created_entities"] == 1
    assert len([n for n in raw.read_nodes() if n.capture]) == 1
    assert raw.read_node("private").text == "private knowledge"
    assert len(raw.read_edges(True)) == 5  # two hidden records + mentions + fact


def test_capture_model_only_receives_accessible_entities(protected, monkeypatch):
    raw, _, _ = protected
    raw.write_node(Node("Hidden Org", id="private", ntype="entity", entity_name="Hidden Org", entity_type="org"))
    seen = []
    def extractor(text, known):
        seen.extend(known)
        return {"entities": [], "facts": []}
    monkeypatch.setenv("IG_ENTITIES_LLM_CMD", "configured-command")
    monkeypatch.setattr("graph_engine.entities.command_extractor", lambda: extractor)
    assert runtime.make_engine().capture("plain note", extraction="model")[3]["status"] == "complete"
    assert seen == []
    assert raw.read_node("private").entity_name == "Hidden Org"


def test_viewer_cannot_capture_or_call_model(protected, monkeypatch):
    raw, _, _ = protected
    monkeypatch.setenv("IG_PRINCIPAL", "bob")
    calls = []
    monkeypatch.setenv("IG_ENTITIES_LLM_CMD", "configured-command")
    monkeypatch.setattr("graph_engine.entities.command_extractor",
                        lambda: lambda *a: calls.append(a))
    with pytest.raises(PermissionError):
        runtime.make_engine().capture("Alice works at Acme.", extraction="model")
    assert not calls and len(raw.read_nodes()) == 3


def test_duplicate_receipt_inherits_current_survivor_permissions(protected, monkeypatch):
    from graph_engine.server import app

    raw, path, policy = protected
    raw.write_node(Node("Alice works at Acme.", id="private", status="active"))
    raw.write_vectors({})
    acl = policy["graphs"]["default"]["nodes"]["private"]
    acl.update(read=["owner", "alice"], write=["owner", "alice"])
    path.write_text(json.dumps(policy))
    engine = runtime.make_engine()
    captured = engine.capture("Alice works at Acme.", extraction="rules")
    receipt_id = captured[3]["source_node_id"]
    assert captured[2] and captured[0].id == "private" and receipt_id != "private"
    raw.write_vectors({receipt_id: [1., 0.]})
    fact_id = next(e.id for e in raw.read_edges() if e.kind == "fact" and e.origin == "entity-extractor")

    monkeypatch.setenv("IG_PRINCIPAL", "bob")
    viewer = runtime.make_brain()
    assert receipt_id not in {n.id for n in viewer.read_nodes()}
    assert not viewer.can_access("read", receipt_id)
    with pytest.raises(PermissionError):
        viewer.read_node(receipt_id)
    assert receipt_id not in viewer.read_vectors()
    assert fact_id not in {e.id for e in viewer.read_edges(True)}
    client = TestClient(app)
    response = client.get("/api/graph", headers={"Authorization": "Bearer viewer-token"})
    assert response.status_code == 200
    assert receipt_id not in response.text and "Alice works at Acme" not in response.text

    # Existing secured instances must observe grants and revocations too.
    acl["read"].append("bob")
    path.write_text(json.dumps(policy))
    assert viewer.read_node(receipt_id).capture["node_id"] == "private"
    assert fact_id in {e.id for e in viewer.read_edges(True)}
    acl["write"] = ["owner"]
    path.write_text(json.dumps(policy))
    assert not engine.brain.can_access("write", receipt_id)
    with pytest.raises(PermissionError):
        engine.brain.write_node(raw.read_node(receipt_id))
    acl["read"].remove("bob")
    path.write_text(json.dumps(policy))
    assert not viewer.can_access("read", receipt_id)


@pytest.mark.parametrize("restricted", ["receipt", "fact_endpoint"])
def test_forget_preflights_capture_family_before_any_tombstones(protected, restricted):
    from graph_engine.agent_memory import forget

    raw, path, policy = protected
    engine = runtime.make_engine()
    node, _, _, extracted = engine.capture("Alice works at Acme.", extraction="rules")
    duplicate = engine.capture(" Alice works at Acme. ", extraction="rules")[3]
    receipt_id = duplicate["source_node_id"]
    assert receipt_id != node.id
    restricted_id = receipt_id if restricted == "receipt" else next(
        n.id for n in raw.read_nodes() if n.entity_name == "Alice")
    policy["graphs"]["default"]["nodes"][restricted_id] = {"read": ["owner"], "write": ["owner"]}
    path.write_text(json.dumps(policy))
    # Keep fact endpoints readable to test their write preflight. The receipt
    # case must discover copies even when they are outside the caller's view.
    if restricted == "fact_endpoint":
        policy["graphs"]["default"]["nodes"][restricted_id]["read"].append("alice")
        path.write_text(json.dumps(policy))
    before = {p.relative_to(raw.path): p.read_bytes() for p in raw.path.rglob("*") if p.is_file()}
    with pytest.raises(PermissionError):
        forget(engine.brain, node.id, reason="remove all captures")
    assert before == {p.relative_to(raw.path): p.read_bytes() for p in raw.path.rglob("*") if p.is_file()}
    assert raw.read_node(extracted["source_node_id"]).status != "tombstone"


@pytest.mark.parametrize("parent", ["missing", "copy"])
def test_orphan_and_cyclic_capture_receipts_fail_closed(protected, parent):
    raw, _, _ = protected
    raw.write_node(Node("restricted copy", id="copy",
        capture=dict(input="restricted copy", node_id=parent, duplicate=True, source="human")))
    brain = runtime.make_brain()
    assert not brain.can_access("read", "copy")
    assert "copy" not in {n.id for n in brain.read_nodes()}
    with pytest.raises(PermissionError):
        brain.read_node("copy")


def test_search_index_never_reuses_unprotected_or_other_principal_cache(protected):
    from graph_engine.retrieval import retrieve
    raw, path, policy = protected
    unprotected = BrainEngine(raw, HashEmbedder(), reranker=False)
    unprotected.reranker = None
    retrieve(unprotected, "private knowledge", persist=False)
    original = unprotected._search_index
    secured = runtime.make_engine()
    secured._search_index = original  # even an accidentally copied snapshot is ignored
    assert "private" not in dict(retrieve(secured, "private knowledge", persist=False))
    # Current policy applies on every call to the same engine.
    policy["graphs"]["default"]["nodes"]["public"] = {"read": ["owner"]}
    path.write_text(json.dumps(policy))
    assert "public" not in dict(retrieve(secured, "public knowledge", persist=False))
    policy["graphs"]["default"]["roles"].pop("alice")
    path.write_text(json.dumps(policy))
    with pytest.raises(PermissionError):
        retrieve(secured, "knowledge", persist=False)

"""Model lifetimes must be independent of authorized corpus lifetimes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from graph_engine import access, namespaces, runtime
from graph_engine.brain import Brain, Node
from graph_engine.embedder import HashEmbedder
from graph_engine.retrieval import retrieve


@pytest.fixture
def models(tmp_path, monkeypatch):
    calls = []

    class Model:
        def __init__(self, name, **options):
            calls.append((name, options))
            time.sleep(.01)  # Let competing cold requests reach model loading.
            self.busy = False

        def encode(self, texts):
            assert not self.busy, "shared model inference overlapped"
            self.busy = True
            try:
                time.sleep(.001)
                adapter = HashEmbedder()
                return np.array(adapter.embed(texts) if isinstance(texts, str)
                                else adapter.embed_batch(texts))
            finally:
                self.busy = False

        def predict(self, pairs, **options):
            assert not self.busy, "shared reranker inference overlapped"
            self.busy = True
            try:
                time.sleep(.001)
                return np.arange(len(pairs), dtype=float)
            finally:
                self.busy = False

    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        SimpleNamespace(SentenceTransformer=Model, CrossEncoder=Model))
    for name in ("IG_GRAPH_HOME", "IG_GRAPH", "IG_ACCESS_POLICY", "IG_PRINCIPAL",
                 "IDEAGRAPH_EMBEDDER_REVISION", "IDEAGRAPH_RERANKER_REVISION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("IG_BRAIN_PATH", str(tmp_path / "brain"))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "st")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER_MODEL", "embedding")
    monkeypatch.setenv("IDEAGRAPH_RERANKER", "ranking")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"graphs": {"default": {"roles": {"alice": "viewer"}}}}))
    monkeypatch.setenv("IG_ACCESS_POLICY", str(policy))
    monkeypatch.setenv("IG_PRINCIPAL", "alice")
    runtime.reset_engine_cache()
    yield calls
    runtime.reset_engine_cache()


def test_protected_requests_reuse_loaded_models(models):
    first = runtime.make_engine()
    sentinel = first.embedder._ensure_model()
    second = runtime.make_engine()
    assert second is not first and second.brain is not first.brain
    assert second.embedder._ensure_model() is sentinel
    assert second.reranker.model is first.reranker.model
    assert len(models) == 2
    assert not runtime._ENGINES  # No protected corpus/identity retained globally.


def test_cached_models_keep_corpus_and_node_permissions_fresh(models, tmp_path):
    raw = Brain(str(tmp_path / "brain"), mode="local")
    raw.init()
    raw.write_node(Node(id="public", text="original knowledge", status="active"))
    raw.write_node(Node(id="private", text="secret knowledge", status="active"))
    policy_path = tmp_path / "policy.json"
    policy = {"graphs": {"default": {"roles": {"alice": "viewer", "owner": "admin"},
                                    "nodes": {"private": {"read": ["owner"]}}}}}
    policy_path.write_text(json.dumps(policy))
    with access_request("default", "owner"):
        owner = runtime.make_engine()
        assert len(retrieve(owner, "knowledge")) == 2
    viewer = runtime.make_engine()
    assert viewer.embedder is owner.embedder
    assert {nid for nid, _ in retrieve(viewer, "knowledge")} == {"public"}
    raw.write_node(Node(id="new", text="new knowledge", status="active"))
    policy["graphs"]["default"]["nodes"]["public"] = {"read": ["owner"]}
    policy_path.write_text(json.dumps(policy))
    fresh = runtime.make_engine()
    assert fresh.embedder is viewer.embedder
    assert {nid for nid, _ in retrieve(fresh, "knowledge")} == {"new"}
    assert {nid for nid, _ in retrieve(viewer, "knowledge")} == {"new"}


@pytest.mark.parametrize("protected", [True, False])
@pytest.mark.parametrize("setting,value,resource", [
    ("IDEAGRAPH_EMBEDDER_MODEL", "other", "embedder"),
    ("IDEAGRAPH_EMBEDDER_REVISION", "a" * 40, "embedder"),
    ("IDEAGRAPH_EMBEDDER", "hash", "embedder"),
    ("IDEAGRAPH_RERANKER", "other", "reranker"),
    ("IDEAGRAPH_RERANKER_REVISION", "b" * 40, "reranker"),
    ("IDEAGRAPH_RERANKER", "none", "reranker"),
])
def test_configuration_changes_invalidate_only_affected_model(models, monkeypatch,
                                                             protected, setting, value, resource):
    if not protected:
        monkeypatch.delenv("IG_ACCESS_POLICY")
    first = runtime.make_engine()
    monkeypatch.setenv(setting, value)
    second = runtime.make_engine()
    assert getattr(second, resource) is not getattr(first, resource)
    other = "embedder" if resource == "reranker" else "reranker"
    assert getattr(second, other) is getattr(first, other)
    if setting.endswith("REVISION"):
        model = second.embedder._ensure_model() if resource == "embedder" else second.reranker.model
        assert model is not None
        assert any(options.get("revision") == value for _, options in models)


@pytest.mark.parametrize("setting,resource", [("IDEAGRAPH_EMBEDDER_MODEL", "embedder"),
                                             ("IDEAGRAPH_RERANKER", "reranker")])
def test_replaced_local_model_is_not_reused(models, tmp_path, monkeypatch, setting, resource):
    folder = tmp_path / "model"
    folder.mkdir()
    weights = folder / "weights.bin"
    weights.write_bytes(b"first")
    monkeypatch.setenv(setting, str(folder))
    first = runtime.make_engine()
    first.embedder._ensure_model()
    weights.write_bytes(b"other")
    second = runtime.make_engine()
    assert getattr(second, resource) is not getattr(first, resource)


@pytest.mark.parametrize("protected", [True, False])
def test_local_model_rollback_after_lazy_load_uses_current_weights(models, tmp_path,
                                                                 monkeypatch, protected):
    if not protected:
        monkeypatch.delenv("IG_ACCESS_POLICY")
    folder = tmp_path / "model"
    folder.mkdir()
    weights = folder / "weights.bin"
    weights.write_text("A")

    class Model:
        def __init__(self, name, **options):
            self.value = 1. if (Path(name) / "weights.bin").read_text() == "A" else 2.

        def encode(self, text):
            return np.array([self.value])

    monkeypatch.setattr(sys.modules["sentence_transformers"], "SentenceTransformer", Model)
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER_MODEL", str(folder))
    first = runtime.make_engine()
    assert first.embedder._model is None
    weights.write_text("B")
    assert first.embedder.embed("query") == [2.]
    weights.write_text("A")
    fresh = runtime.make_engine()
    assert fresh.embedder.embed("query") == [1.]
    assert runtime.make_engine().embedder is fresh.embedder
    assert first.embedder.embed("active caller") == [2.]


@pytest.mark.parametrize("operation", ["ingest", "accept", "reject", "undo", "link"])
def test_async_http_handlers_hash_models_in_worker_thread(models, tmp_path, monkeypatch,
                                                         operation):
    from graph_engine import server

    monkeypatch.delenv("IG_ACCESS_POLICY")
    folder = tmp_path / "model"
    folder.mkdir()
    (folder / "weights.bin").write_bytes(b"weights")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER_MODEL", str(folder))
    engine = runtime.make_engine()  # Exercise a warm cache hit.
    engine.brain.init()
    event_loop_thread = threading.get_ident()
    digest = runtime.local_model_digest
    calls = []

    def checked_digest(model):
        assert threading.get_ident() != event_loop_thread, "model I/O blocked the event loop"
        calls.append(model)
        return digest(model)

    monkeypatch.setattr(runtime, "local_model_digest", checked_digest)
    handlers = {
        "ingest": lambda: server.ingest(server.IngestBody(text="synthetic knowledge")),
        "accept": lambda: server.accept_edge("missing-edge"),
        "reject": lambda: server.reject_edge("missing-edge"),
        "undo": lambda: server.undo_edge("missing-edge"),
        "link": lambda: server.link_edge(server.LinkBody(source="missing", target="also-missing")),
    }
    asyncio.run(handlers[operation]())
    assert str(folder) in calls


def test_resource_retention_and_reset_are_bounded(models, monkeypatch):
    first = runtime.make_engine()
    for index in range(12):
        monkeypatch.setenv("IDEAGRAPH_EMBEDDER_MODEL", f"embedding-{index}")
        monkeypatch.setenv("IDEAGRAPH_RERANKER", f"ranking-{index}")
        runtime.make_engine()
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER_MODEL", "embedding")
    monkeypatch.setenv("IDEAGRAPH_RERANKER", "ranking")
    evicted = runtime.make_engine()
    assert evicted.embedder is not first.embedder
    assert evicted.reranker is not first.reranker
    runtime.reset_engine_cache()
    reset = runtime.make_engine()
    assert reset.embedder is not evicted.embedder
    assert reset.reranker is not evicted.reranker
    # Reset/eviction must not invalidate a resource already in use.
    assert first.embedder.embed("still active")
    assert first.reranker.rerank("query", [("id", "text", 1.)], 1)


def test_failed_model_initialization_can_be_retried(models, monkeypatch):
    constructor = sys.modules["sentence_transformers"].SentenceTransformer
    engine = runtime.make_engine()

    def fail(*args, **kwargs):
        raise RuntimeError("temporary load failure")

    monkeypatch.setattr(sys.modules["sentence_transformers"], "SentenceTransformer", fail)
    with pytest.raises(RuntimeError, match="temporary load failure"):
        engine.embedder.embed("knowledge")
    monkeypatch.setattr(sys.modules["sentence_transformers"], "SentenceTransformer", constructor)
    assert runtime.make_engine().embedder.embed("knowledge")


def test_concurrent_cold_requests_load_once_and_keep_authorization_fresh(models, tmp_path, monkeypatch):
    monkeypatch.setenv("IG_GRAPH_HOME", str(tmp_path / "home"))
    policy = {"graphs": {name: {"roles": {"alice": "viewer", "owner": "admin"},
                                "nodes": {"private": {"read": ["owner"]}}}
                         for name in ("one", "two")}}
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy))
    for name in ("one", "two"):
        raw = Brain(str(namespaces.graph_path(name)), mode="local")
        raw.init()
        for nid in ("public", "private"):
            raw.write_node(Node(id=nid, text=f"{name} {nid} knowledge", status="active"))
    barrier = threading.Barrier(8)

    def search(index):
        graph = "one" if index % 2 else "two"
        identity = "alice" if index % 3 else "owner"
        graph_token = namespaces.request_graph.set(graph)
        identity_token = access.request_principal.set(identity)
        try:
            barrier.wait(timeout=10)
            engine = runtime.make_engine()
            hits = retrieve(engine, "knowledge", k=10)
            assert engine.brain.graph_name == graph
            assert engine.brain.identity == identity
            assert {nid for nid, _ in hits} == ({"public", "private"} if identity == "owner" else {"public"})
            assert all(n.text.startswith(graph) for n in engine.brain.read_nodes())
            return engine
        finally:
            access.request_principal.reset(identity_token)
            namespaces.request_graph.reset(graph_token)

    with ThreadPoolExecutor(max_workers=8) as pool:
        engines = list(pool.map(search, range(8)))
    assert len({id(e.embedder) for e in engines}) == 1
    assert len({id(e.reranker) for e in engines}) == 1
    assert len({id(e) for e in engines}) == 8
    assert len(models) == 2
    # Reusing models must not reuse a prior authorized corpus after revocation.
    policy["graphs"]["one"]["roles"].pop("alice")
    policy_path.write_text(json.dumps(policy))
    prior = next(e for e in engines if e.brain.graph_name == "one" and e.brain.identity == "alice")
    with pytest.raises(PermissionError):
        retrieve(prior, "knowledge")
    with access_request("one", "alice"):
        with pytest.raises(PermissionError):
            runtime.make_engine()
    with access_request("two", "alice"):
        fresh = runtime.make_engine()
        assert fresh.embedder is prior.embedder
        assert {nid for nid, _ in retrieve(fresh, "knowledge")} == {"public"}


@contextmanager
def access_request(graph, identity):
    graph_token = namespaces.request_graph.set(graph)
    identity_token = access.request_principal.set(identity)
    try:
        yield
    finally:
        access.request_principal.reset(identity_token)
        namespaces.request_graph.reset(graph_token)

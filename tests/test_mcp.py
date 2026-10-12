"""Tests for the read-only MCP server (report #1).

Two layers, mirroring the engine's test split:
- format.py helpers: pure unit tests, NO `mcp` import needed.
- tool behavior: in-process client/server session (mcp's memory streams),
  over a seeded temp brain. Skipped entirely when the [mcp] extra is absent
  (CI light job installs only .[dev]).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None

# ---------------------------------------------------------------- format.py

from graph_engine.mcp import format as fmt


def test_snippet_truncates_then_escapes():
    """Order is truncate-then-escape (audit #55): a pipe at the cap must not
    survive into the output."""
    out = fmt.snippet("a" * 200 + "|tail", 200)
    assert out.endswith(fmt.ELLIPSIS)
    assert "|" not in out


def test_snippet_escapes_markdown_breakers():
    assert fmt.snippet("a|b<c>d&e") == "a\\|b\\<c\\>d\\&e"


def test_snippet_empty():
    assert fmt.snippet("") == ""
    assert fmt.snippet(None) == ""


def test_envelopes_shape():
    e = fmt.err("node_not_found", "no node x")
    assert e["ok"] is False and e["error"]["code"] == "node_not_found"
    inv = fmt.invalid("bad k")
    assert inv["ok"] is False and inv["error"]["code"] == "invalid_params"
    miss = fmt.brain_missing("/nope")
    assert miss["ok"] is False and miss["error"]["code"] == "brain_missing"
    nf = fmt.node_not_found("abc123")
    assert nf["error"]["code"] == "node_not_found" and "abc123" in nf["error"]["message"]


# ------------------------------------------------------------ tool behavior

def _seed_brain(root: Path) -> Path:
    """Minimal brain with 2 linked nodes + 1 pending edge (from the proven
    hash-embedder pattern: high word overlap -> similar edge)."""
    brain = root / "brain"
    (brain / "nodes").mkdir(parents=True)
    (brain / "nodes" / "aaaaaaaaaaaa.md").write_text(textwrap.dedent("""\
        ---
        id: aaaaaaaaaaaa
        title: Agent Memory
        created: 2026-09-15T10:00:00
        source: test
        type: semantic
        status: active
        tags: []
        ---
        agent memory agent memory agent memory store
    """), encoding="utf-8")
    (brain / "nodes" / "bbbbbbbbbbbb.md").write_text(textwrap.dedent("""\
        ---
        id: bbbbbbbbbbbb
        title: Agent Memory Design
        created: 2026-09-15T10:05:00
        source: test
        type: semantic
        status: active
        tags: []
        ---
        agent memory agent memory agent memory design
    """), encoding="utf-8")
    (brain / "edges.jsonl").write_text(
        json.dumps({"id": "edge00000001", "source": "aaaaaaaaaaaa",
                    "target": "bbbbbbbbbbbb", "kind": "similar",
                    "pending": True, "confidence": 0.8,
                    "valid_from": "2026-09-15T10:05:00"}) + "\n",
        encoding="utf-8")
    return brain


@pytest.fixture()
def mcp_env(monkeypatch, tmp_path):
    """Point the runtime at a seeded temp brain; hash embedder for speed."""
    brain = _seed_brain(tmp_path)
    monkeypatch.setenv("IG_BRAIN_PATH", str(brain))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    # tests must never leak vectors into a real brain even if persist flips
    monkeypatch.setenv("IG_MCP_CACHE_VECTORS", "0")
    return brain


def _call(tool: str, args: dict):
    """In-process MCP call: client session <-> server over memory streams."""
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session
    from graph_engine.mcp.server import mcp as server

    async def _run():
        low = server._mcp_server
        if callable(low):
            low = low()
        async with create_connected_server_and_client_session(low) as session:
            res = await session.call_tool(tool, args)
            payload = json.loads(res.content[0].text)
            err = getattr(res, "isError", False)
            return payload, err

    return anyio.run(_run)


@pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp extra not installed")
class TestMCPTools:
    def test_search_brain_finds_node(self, mcp_env):
        payload, err = _call("search_brain", {"query": "agent memory"})
        assert err is False
        assert payload["ok"] is True
        assert payload["count"] >= 1
        assert payload["results"][0]["id"] in ("aaaaaaaaaaaa", "bbbbbbbbbbbb")

    def test_search_brain_empty_query_rejected(self, mcp_env):
        payload, err = _call("search_brain", {"query": "   "})
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_params"

    def test_search_brain_k_bounds(self, mcp_env):
        payload, _ = _call("search_brain", {"query": "agent memory", "k": 99})
        assert payload["error"]["code"] == "invalid_params"

    def test_get_node_full(self, mcp_env):
        payload, err = _call("get_node", {"id": "aaaaaaaaaaaa"})
        assert err is False and payload["ok"] is True
        node = payload["node"]
        assert node["id"] == "aaaaaaaaaaaa"
        assert "agent memory" in node["text"]
        assert payload["degree"] == 1
        edge = payload["edges"][0]
        assert edge["kind"] == "similar"
        assert edge["pending"] is True

    def test_get_node_unknown(self, mcp_env):
        payload, _ = _call("get_node", {"id": "zzzzzzzzzzzz"})
        assert payload["error"]["code"] == "node_not_found"

    def test_get_node_max_chars_cap(self, mcp_env):
        payload, _ = _call("get_node", {"id": "aaaaaaaaaaaa", "max_chars": 10**9})
        assert payload["error"]["code"] == "invalid_params"

    def test_neighbors_undirected(self, mcp_env):
        # the fixture edge is pending -> include it explicitly (default
        # excludes pending, tested separately)
        payload, err = _call("neighbors", {"id": "bbbbbbbbbbbb",
                                           "include_pending": True})
        assert err is False and payload["ok"] is True
        assert payload["count"] == 1
        nb = payload["neighbors"][0]
        assert nb["id"] == "aaaaaaaaaaaa"
        assert nb["direction"] == "in"   # edge source is aaaa -> target bbbb
        assert nb["hops"] == 1

    def test_neighbors_pending_excluded_by_default(self, mcp_env):
        payload, _ = _call("neighbors", {"id": "aaaaaaaaaaaa"})
        assert payload["count"] == 0
        payload, _ = _call("neighbors", {"id": "aaaaaaaaaaaa",
                                         "include_pending": True})
        assert payload["count"] == 1

    def test_brain_status(self, mcp_env):
        payload, err = _call("brain_status", {})
        assert err is False and payload["ok"] is True
        assert payload["total"] == 2
        assert payload["pending_edges"] == 1
        assert "/" not in payload["brain_path_basename"]  # basename only

    def test_brain_missing_envelope(self, monkeypatch):
        monkeypatch.setenv("IG_BRAIN_PATH", "/tmp/does-not-exist-ig-mcp")
        monkeypatch.setenv("IG_BRAIN_MODE", "local")
        monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
        payload, _ = _call("search_brain", {"query": "anything"})
        assert payload["ok"] is False
        assert payload["error"]["code"] == "brain_missing"

    def test_persist_false_memoizes(self, mcp_env):
        """The cold-search cost is paid ONCE per process: a second
        persist=False search must not re-embed (the runtime memo)."""
        import sys
        from graph_engine.runtime import make_engine, reset_engine_cache
        reset_engine_cache()
        calls = {"n": 0}
        engine = make_engine()
        orig = engine.embedder.embed

        def counting(text):
            calls["n"] += 1
            return orig(text)

        engine.embedder.embed = counting
        from graph_engine.retrieval import retrieve
        retrieve(engine, "agent memory", k=2, persist=False)
        first = calls["n"]
        assert first > 0
        retrieve(engine, "agent memory", k=2, persist=False)
        # exactly ONE new embed: the query itself (never memoized — it is
        # per-call by nature); the NODE vectors come from the process memo
        assert calls["n"] == first + 1

    def test_read_only_no_vector_file_written(self, mcp_env):
        """The core guarantee: a search with the default strict mode must
        leave vectors.jsonl untouched/absent."""
        vec_file = mcp_env / "vectors.jsonl"
        before = vec_file.read_text() if vec_file.exists() else None
        _call("search_brain", {"query": "agent memory"})
        after = vec_file.read_text() if vec_file.exists() else None
        assert before == after


# ------------------------------------------------------ write path (Welle C)

WRITE_TOOLS = ("remember", "recall", "forget")


@pytest.fixture()
def write_env(mcp_env, monkeypatch):
    """Write mode ON, same seeded brain."""
    monkeypatch.setenv("IG_MCP_WRITE", "1")
    return mcp_env


@pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp extra not installed")
class TestMCPWriteTools:
    """The tools are called directly: registration mutates the module-global
    server, which would leak into the read-only tests above. The real
    `tools/list` surface is asserted by the subprocess test below."""

    def test_write_disabled_by_default(self, mcp_env, monkeypatch):
        monkeypatch.delenv("IG_MCP_WRITE", raising=False)
        from graph_engine.mcp import server
        calls = [server.remember(text="x"),
                 server.recall(query="x"),
                 server.forget(id="aaaaaaaaaaaa", reason="cleanup")]
        for payload in calls:
            assert payload["ok"] is False
            assert payload["error"]["code"] == "write_disabled"
            assert "ig mcp --write" in payload["error"]["message"]

    def test_remember_creates_a_node(self, write_env):
        from graph_engine.mcp import server
        payload = server.remember(text="a note the agent decided to keep")
        assert payload["ok"] is True and payload["duplicate"] is False
        node_file = write_env / "nodes" / f"{payload['node_id']}.md"
        assert node_file.exists()
        assert "source: agent" in node_file.read_text(encoding="utf-8")

    def test_remember_rejects_empty_text(self, write_env):
        from graph_engine.mcp import server
        payload = server.remember(text="   ")
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_params"

    def test_remember_enforces_the_size_cap(self, write_env, monkeypatch):
        from graph_engine.mcp import server
        monkeypatch.setattr(server, "MAX_REMEMBER_CHARS", 20)
        payload = server.remember(text="x" * 50)
        assert payload["error"]["code"] == "invalid_params"
        assert "20" in payload["error"]["message"]

    def test_recall_tracks_and_reports_recall_count(self, write_env):
        from graph_engine.mcp import server
        payload = server.recall(query="agent memory", k=3)
        assert payload["ok"] is True and payload["tracked"] is True
        assert payload["count"] >= 1
        assert "recall_count" in payload["results"][0]
        assert (write_env / "recalls.jsonl").exists()

    def test_recall_validates_like_search(self, write_env):
        from graph_engine.mcp import server
        assert server.recall(query="  ")["error"]["code"] == "invalid_params"
        assert server.recall(query="x", k=99)["error"]["code"] == "invalid_params"

    def test_forget_requires_a_reason(self, write_env):
        from graph_engine.mcp import server
        payload = server.forget(id="aaaaaaaaaaaa", reason="   ")
        assert payload["error"]["code"] == "invalid_params"
        assert "reason" in payload["error"]["message"]

    def test_forget_unknown_node(self, write_env):
        from graph_engine.mcp import server
        payload = server.forget(id="zzzzzzzzzzzz", reason="cleanup")
        assert payload["error"]["code"] == "node_not_found"

    def test_forget_tombstones_without_deleting(self, write_env):
        from graph_engine.mcp import server
        payload = server.forget(id="aaaaaaaaaaaa", reason="obsolete note")
        assert payload["ok"] is True
        assert payload["status"] == "tombstone"
        assert payload["edges_invalidated"] == 1
        assert (write_env / "nodes" / "aaaaaaaaaaaa.md").exists()
        assert "status: tombstone" in (write_env / "nodes" / "aaaaaaaaaaaa.md").read_text(
            encoding="utf-8")


REGISTRATION_SCRIPT = r'''
import json, os
import anyio
from mcp.shared.memory import create_connected_server_and_client_session
from graph_engine.mcp.server import mcp as srv, register_write_tools

register_write_tools()

async def run():
    low = srv._mcp_server
    if callable(low):
        low = low()
    async with create_connected_server_and_client_session(low) as session:
        tools = (await session.list_tools()).tools
        return {t.name: bool(getattr(t.annotations, "readOnlyHint", True))
                for t in tools}

print(json.dumps(anyio.run(run)))
'''


@pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp extra not installed")
def test_write_mode_registers_exactly_the_write_tools(mcp_env, tmp_path):
    """`ig mcp --write` must add the three write tools with readOnlyHint False
    and leave the read-only ones alone. Runs in a subprocess: registration
    mutates the module-global server, which must not leak into this process."""
    import subprocess
    script = tmp_path / "registration.py"
    script.write_text(REGISTRATION_SCRIPT, encoding="utf-8")
    env = dict(os.environ,
               IG_BRAIN_PATH=str(mcp_env), IG_BRAIN_MODE="local",
               IDEAGRAPH_EMBEDDER="hash", IG_MCP_WRITE="1",
               PYTHONPATH=str(Path(__file__).resolve().parent.parent))
    proc = subprocess.run([sys.executable, str(script)], env=env,
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr[-800:]
    flags = json.loads(proc.stdout.strip().splitlines()[-1])

    for name in WRITE_TOOLS:
        assert name in flags, f"{name} not registered in write mode"
        assert flags[name] is False, f"{name} must not claim readOnlyHint"
    for name in ("search_brain", "explain_search", "build_context", "get_node", "neighbors", "brain_status"):
        assert flags.get(name) is True, f"{name} must stay read-only"
    assert len(flags) == 9


@pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp extra not installed")
@pytest.mark.parametrize("write", [False, True])
def test_stdio_cli_roundtrip(mcp_env, write):
    """Initialize and call tools through the real CLI JSON-RPC transport."""
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    before = {p.relative_to(mcp_env): p.read_bytes()
              for p in mcp_env.rglob("*") if p.is_file()}
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("IG_", "IDEAGRAPH_"))}
    env.update(IG_BRAIN_PATH=str(mcp_env), IG_BRAIN_MODE="local",
               IDEAGRAPH_EMBEDDER="hash", IG_MCP_CACHE_VECTORS="0",
               PYTHONPATH=str(Path(__file__).resolve().parent.parent))
    args = ["-m", "graph_engine", "mcp"] + (["--write"] if write else [])

    async def run():
        with anyio.fail_after(30):
            params = StdioServerParameters(command=sys.executable, args=args, env=env)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    await client.initialize()
                    tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                    readonly = {"search_brain", "explain_search", "build_context", "get_node", "neighbors", "brain_status"}
                    assert set(tools) == readonly | (set(WRITE_TOOLS) if write else set())
                    for name, tool in tools.items():
                        assert tool.annotations.readOnlyHint is (name in readonly)

                    async def call(name, arguments):
                        result = await client.call_tool(name, arguments)
                        assert not result.isError
                        payload = json.loads(result.content[0].text)
                        assert payload["ok"] is True, payload
                        return payload

                    found = await call("search_brain", {"query": "agent memory"})
                    assert found["count"] == 2
                    node = await call("get_node", {"id": "aaaaaaaaaaaa"})
                    assert "agent memory" in node["node"]["text"]
                    context = await call("build_context", {"query": "agent memory", "budget": 100})
                    assert context["nodes"] and context["tokens"] <= 100
                    if write:
                        text = "Astronomy telescope Jupiter rings observation"
                        saved = await call("remember", {"text": text})
                        extracted = await call("remember", {
                            "text": "Alice works at Acme.", "extraction": "rules"})
                        assert extracted["extraction"]["status"] == "complete"
                        assert extracted["extraction"]["pending_facts"] == 1
                        retried = await call("remember", {
                            "text": "Alice works at Acme.", "extraction": "rules"})
                        assert retried["node_id"] == extracted["node_id"]
                        assert retried["extraction"]["created_facts"] == 0
                        recalled = await call("recall", {"query": text})
                        assert saved["node_id"] in {n["id"] for n in recalled["results"]}
                        assert recalled["tracked"] is True
                        forgotten = await call("forget", {"id": saved["node_id"],
                                                          "reason": "stdio test cleanup"})
                        assert forgotten["status"] == "tombstone"
                        found = await call("search_brain", {"query": text})
                        assert saved["node_id"] not in {n["id"] for n in found["results"]}

    anyio.run(run)
    if not write:
        after = {p.relative_to(mcp_env): p.read_bytes()
                 for p in mcp_env.rglob("*") if p.is_file()}
        assert after == before, "read-only stdio calls changed the brain"
    else:
        from graph_engine.brain import Brain
        brain = Brain(str(mcp_env), mode="local")
        assert any(n.status == "tombstone" and n.source == "agent" for n in brain.read_nodes())
        assert (mcp_env / "recalls.jsonl").exists()


@pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp extra not installed")
@pytest.mark.parametrize("args", [
    {"query": " "}, {"query": "x" * 501},
    {"query": "memory", "budget": -1}, {"query": "memory", "budget": 8001},
    {"query": "memory", "k": 0}, {"query": "memory", "k": 21},
])
def test_context_tool_bounds(mcp_env, args):
    payload, err = _call("build_context", args)
    assert not err and payload["error"]["code"] == "invalid_params"


@pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp extra not installed")
def test_context_tool_strict_readonly_even_with_cache_enabled(mcp_env, monkeypatch):
    from graph_engine.runtime import reset_engine_cache
    reset_engine_cache()
    monkeypatch.setenv("IG_MCP_CACHE_VECTORS", "1")
    before = {p.relative_to(mcp_env): p.read_bytes() for p in mcp_env.rglob("*") if p.is_file()}
    payload, err = _call("build_context", {"query": "agent memory", "budget": 100})
    assert not err and payload["ok"] and payload["nodes"]
    assert payload["tokens"] <= payload["budget"]
    assert "Approximate" in payload["token_estimate"]
    assert "source: test" in payload["context"]
    after = {p.relative_to(mcp_env): p.read_bytes() for p in mcp_env.rglob("*") if p.is_file()}
    assert before == after
    zero, _ = _call("build_context", {"query": "agent memory", "budget": 0})
    assert zero["nodes"] == [] and zero["context"] == "" and zero["tokens"] == 0


@pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp extra not installed")
def test_context_tool_missing_brain_and_embedder_error(mcp_env, monkeypatch):
    from graph_engine.mcp import server
    monkeypatch.setattr(server, "make_engine", lambda: (_ for _ in ()).throw(RuntimeError("unavailable")))
    assert server.build_context("memory")["error"]["code"] == "embedder_unavailable"
    monkeypatch.setenv("IG_BRAIN_PATH", str(mcp_env / "missing"))
    assert server.build_context("memory")["error"]["code"] == "brain_missing"


@pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP extra not installed")
def test_document_import_provenance_visible_without_writes(tmp_path, monkeypatch):
    from graph_engine.brain import Brain
    from graph_engine.document_import import import_documents
    from graph_engine.mcp.server import get_node
    brain = Brain(str(tmp_path / "brain"), mode="local")
    source = tmp_path / "note.md"
    source.write_text("A source document with provenance.", encoding="utf-8")
    result = import_documents(brain, [source], source_id="public-paper")
    nid = result["files"][0]["chunks"][0]["node_id"]
    monkeypatch.delenv("IG_ACCESS_POLICY", raising=False)
    monkeypatch.delenv("IG_GRAPH_HOME", raising=False)
    monkeypatch.setenv("IG_BRAIN_PATH", str(brain.path))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    before = {p: p.read_bytes() for p in brain.path.rglob("*") if p.is_file()}
    response = get_node(nid)
    assert response["ok"] and response["node"]["document"]["source_id"] == "public-paper"
    assert response["node"]["document_survivor_id"] == nid
    assert {p: p.read_bytes() for p in brain.path.rglob("*") if p.is_file()} == before

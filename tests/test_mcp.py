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
    for name in ("search_brain", "get_node", "neighbors", "brain_status"):
        assert flags.get(name) is True, f"{name} must stay read-only"
    assert len(flags) == 7

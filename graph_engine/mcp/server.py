"""MCP server: the brain as a tool for AI assistants.

stdio transport only — the brain is single-user and private; an HTTP listener
would add an auth/exposure surface for zero benefit.

READ-ONLY BY DEFAULT, and that is a decision, not an oversight: ingest commits
AND pushes to a private repo, and model-initiated writes with no human review
are the single highest-risk thing this surface could do. `ig mcp --write` (or
`IG_MCP_WRITE=1`) adds the agent memory path — `remember` / `recall` / `forget`
(Welle C) — which keeps three invariants: provenance (`source="agent"`,
`origin="agent"`, so "what did a model write?" stays a query), never-destructive
(`forget` tombstones and invalidates, it never deletes), and one commit per
write with the reason in the message.

Engine construction is LAZY (first tool call, not import): `list_tools` and
`brain_status` must never pay the sentence-transformers model load. The
process-wide cache in runtime.make_engine() makes the load a once-per-server
cost instead of once-per-call.
"""
from __future__ import annotations

import os
from functools import wraps

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import format as fmt
from ..runtime import brain_path, make_engine, reset_engine_cache

_INSTRUCTIONS_READ = (
    "Consult the brain before starting non-trivial design or research work; "
    "skip it for routine edits. All tools are read-only."
)
_INSTRUCTIONS_WRITE = (
    "Consult the brain before starting non-trivial design or research work; "
    "skip it for routine edits. Write tools are ENABLED: `remember` keeps a "
    "durable finding (recorded with source=agent), `recall` is a search whose "
    "hits count as use, and `forget` requires a reason — it tombstones a node "
    "instead of deleting it."
)


def _write_enabled() -> bool:
    """Write mode is opt-in per server process (CLI `--write` sets this env)."""
    return os.environ.get("IG_MCP_WRITE", "0") == "1"


mcp = FastMCP(
    "graph_engine",
    instructions=_INSTRUCTIONS_WRITE if _write_enabled() else _INSTRUCTIONS_READ,
)

# The write tools are registered ONLY in write mode, so `tools/list` always
# reflects the server's actual capability (a client that sees a write tool
# should ask its user before calling it — never for a tool it cannot use).
_WRITE_REGISTERED = False
MAX_REMEMBER_CHARS = int(os.environ.get("IG_MCP_MAX_REMEMBER_CHARS", "20000"))


def _cache_vectors() -> bool:
    """DECIDED (2026-09-15): the MCP default is STRICTLY read-only — a
    model-initiated write into the private repo (dirty files → autostash
    churn) must not be the default, and the long-lived stdio server holds
    vectors in the process-wide engine cache anyway. IG_MCP_CACHE_VECTORS=1
    opts back in to disk-cache filling (slower first search per clone)."""
    return os.environ.get("IG_MCP_CACHE_VECTORS", "0") == "1"


def _access_guard(fn, action: str):
    @wraps(fn)
    def guarded(*args, **kwargs):
        from .. import access, runtime
        try:
            if access.policy_path():
                runtime.make_brain().authorize(action)
            return fn(*args, **kwargs)
        except PermissionError:
            return fmt.err("forbidden", "Access denied")
    return guarded


def _tool(fn):
    """Register with the readOnlyHint annotation so untrusted-server clients
    skip approval prompts."""
    return mcp.tool(annotations={"readOnlyHint": True})(_access_guard(fn, "read"))


def _hits_payload(brain, hits: list[tuple[str, float]]) -> list[dict]:
    """Shape retrieval hits for a tool response (search_brain AND recall)."""
    id2node = {n.id: n for n in brain.read_nodes()}
    results = []
    for nid, score in hits:
        node = id2node.get(nid)
        if node is None:
            continue
        results.append({
            "id": node.id,
            "score": round(float(score), 4),
            "snippet": fmt.snippet(node.text),
            "status": node.status,
            "type": node.ntype,
            "tags": node.tags,
            "created": node.created,
            "recall_count": node.recall_count or 0,
        })
    return results


@_tool
def search_brain(query: str, k: int = 5) -> dict:
    """Hybrid search (dense + BM25, RRF-fused) over the knowledge brain.

    `score` is a rank-fusion score (reciprocal-rank fusion), NOT a similarity
    — do not compare it across queries or read it as a confidence.
    """
    query = (query or "").strip()
    if not query:
        return fmt.invalid("query must be a non-empty string")
    if len(query) > 500:
        return fmt.invalid("query exceeds 500 characters")
    if not isinstance(k, int) or k < 1 or k > 20:
        return fmt.invalid("k must be an integer between 1 and 20")
    brain = brain_path()
    if not os.path.isdir(brain):
        return fmt.brain_missing(brain)
    try:
        from ..retrieval import retrieve
        engine = make_engine()
        hits = retrieve(engine, query, k=k, persist=_cache_vectors())
    except RuntimeError as exc:      # embedder unavailable etc.
        return fmt.err("embedder_unavailable", str(exc)[-200:])
    except Exception as exc:         # noqa: BLE001 — the envelope contract:
        return fmt.err("internal",   # a raw traceback over JSON-RPC surfaces
                       f"{type(exc).__name__}: {exc}")  # as an opaque error
    if not hits:
        return {"ok": True, "query": query, "count": 0, "results": [],
                "hint": f"No node matched. Try fewer/more specific terms; "
                        f"the brain has {len(engine.brain.read_nodes())} nodes."}
    results = _hits_payload(engine.brain, hits)
    return {"ok": True, "query": query, "count": len(results),
            "results": results}


@_tool
def get_node(id: str, max_chars: int = fmt.DEFAULT_NODE_CHARS) -> dict:
    """One node by id: full text (capped) + its live edges."""
    node_id = (id or "").strip()
    if not node_id:
        return fmt.invalid("id must be a non-empty string")
    if not isinstance(max_chars, int) or max_chars < 100 or max_chars > fmt.MAX_NODE_CHARS:
        return fmt.invalid(f"max_chars must be an integer between 100 and "
                           f"{fmt.MAX_NODE_CHARS}")
    from ..runtime import make_brain
    brain = make_brain()
    node = brain.read_node(node_id)
    if node is None:
        return fmt.node_not_found(node_id)
    text = node.text or ""
    edges = [e for e in brain.read_edges()
             if e.is_current and not e.rejected
             and node_id in (e.source, e.target)]
    out_edges = []
    id2node = {n.id: n for n in brain.read_nodes()}
    for e in edges:
        other = e.target if e.source == node_id else e.source
        other_node = id2node.get(other)
        out_edges.append({
            "id": e.id,
            "kind": e.kind,
            "direction": "out" if e.source == node_id else "in",
            "other_id": other,
            "other_snippet": fmt.snippet(other_node.text, 80) if other_node else "?",
            "pending": e.pending,
            "confidence": e.confidence,
            "valid_from": e.valid_from,
            "valid_to": e.valid_to,
            **({"predicate": e.predicate,
                "evidence": [{"node_id": item.get("node_id"),
                              "text": fmt.snippet(item.get("text", ""), 200)}
                             for item in e.evidence[:5]]} if e.kind == "fact" else {}),
        })
    return {"ok": True,
            "node": {"id": node.id, "text": text[:max_chars],
                     "created": node.created, "source": node.source,
                     "sources": node.sources, "type": node.ntype,
                     "status": node.status, "tags": node.tags,
                     **({"entity_name": fmt.snippet(node.entity_name or "", 200),
                         "entity_type": node.entity_type,
                         "aliases": [fmt.snippet(a, 200) for a in node.aliases[:20]]}
                        if node.ntype == "entity" else {})},
            "truncated": len(text) > max_chars,
            "text_chars": len(text),
            "edges": out_edges,
            "degree": len(out_edges)}


@_tool
def neighbors(id: str, hops: int = 1, kinds: list[str] | None = None,
              include_pending: bool = False,
              limit: int = fmt.DEFAULT_NEIGHBOR_LIMIT) -> dict:
    """Graph neighborhood of a node over UNDIRECTED live edges (1-2 hops).

    This is the graph question vector search cannot answer: what is this
    idea actually connected to?
    """
    node_id = (id or "").strip()
    if not node_id:
        return fmt.invalid("id must be a non-empty string")
    if not isinstance(hops, int) or hops < 1 or hops > 2:
        return fmt.invalid("hops must be 1 or 2")
    if not isinstance(limit, int) or limit < 1 or limit > fmt.MAX_NEIGHBOR_LIMIT:
        return fmt.invalid(f"limit must be an integer between 1 and "
                           f"{fmt.MAX_NEIGHBOR_LIMIT}")
    from ..runtime import make_brain
    from ..graph import neighbors as graph_neighbors
    brain = make_brain()
    if brain.read_node(node_id) is None:
        return fmt.node_not_found(node_id)
    found = graph_neighbors(brain, node_id, hops=hops, kinds=kinds,
                            include_pending=include_pending, limit=limit)
    kinds_present: dict[str, int] = {}
    for nb in found:
        kinds_present[nb.kind] = kinds_present.get(nb.kind, 0) + 1
    return {"ok": True, "id": node_id, "hops": hops,
            "count": len(found),
            "truncated": len(found) >= limit,
            "neighbors": [{"id": nb.id, "snippet": fmt.snippet(nb.snippet),
                           "kind": nb.kind, "direction": nb.direction,
                           "pending": nb.pending,
                           "confidence": nb.confidence, "hops": nb.hops,
                           **({"predicate": nb.predicate} if nb.predicate else {})}
                          for nb in found],
            "kinds_present": kinds_present}


@_tool
def brain_status() -> dict:
    """Cheap orientation: size, connectivity, pending-review load.

    Returns the brain path BASENAME only — the brain is private and this
    string lands in a model's context.
    """
    from ..hygiene import connectivity, status_counts
    brain_p = brain_path()
    if not os.path.isdir(brain_p):
        return fmt.brain_missing(brain_p)
    from ..runtime import make_brain
    brain = make_brain()
    conn = connectivity(brain)
    counts = status_counts(brain)
    pending = sum(1 for e in brain.read_edges() if e.pending)
    return {"ok": True, "total": conn.total, "edges": conn.edges,
            "max_degree": conn.max_degree,
            "mean_degree": round(conn.mean_degree, 2),
            "orphans": len(conn.orphans), "islands": len(conn.islands),
            "weak": len(conn.weak), "pending_edges": pending,
            "status": {k: counts.get(k, 0)
                       for k in ("active", "probation", "stale", "tombstone")},
            "brain_path_basename": os.path.basename(brain_p.rstrip("/"))}


# ---------------------------------------------------------------------------
# Write path (Welle C) — registered ONLY when write mode is on
# ---------------------------------------------------------------------------

def _write_disabled() -> dict:
    return fmt.err("write_disabled",
                   "This MCP server is read-only. Start it with `ig mcp --write` "
                   "(or IG_MCP_WRITE=1) to enable remember/recall/forget.")


def _write_guard() -> dict | None:
    """Common preconditions for a write tool: mode on + brain present."""
    if not _write_enabled():
        return _write_disabled()
    path = brain_path()
    if not os.path.isdir(path):
        return fmt.brain_missing(path)
    return None


def remember(text: str, tags: list[str] | None = None) -> dict:
    """Store one note in the brain on the agent's behalf (write mode only).

    The node is recorded with `source="agent"` — "what did a model write?" stays
    a query. Dedupe-aware: a near-duplicate merges into the existing node (the
    response says so) instead of creating a second one. One commit per write.
    """
    text = (text or "").strip()
    if not text:
        return fmt.invalid("text must be a non-empty string")
    if len(text) > MAX_REMEMBER_CHARS:
        return fmt.invalid(f"text exceeds {MAX_REMEMBER_CHARS} characters")
    if tags is not None and not isinstance(tags, list):
        return fmt.invalid("tags must be a list of strings")
    blocked = _write_guard()
    if blocked:
        return blocked
    from ..agent_memory import remember as _remember
    try:
        res = _remember(make_engine(), text, tags=tags)
    except ValueError as exc:
        return fmt.invalid(str(exc)[-200:])
    except Exception as exc:          # noqa: BLE001 — envelope contract
        return fmt.err("internal", f"{type(exc).__name__}: {exc}")
    out = {"ok": True, "node_id": res["node_id"], "status": res["status"],
           "edges": res["edges"], "duplicate": res["duplicate"]}
    if res["duplicate"]:
        out["hint"] = ("Near-duplicate: merged into the existing node "
                       "(no second node created).")
    return out


def recall(query: str, k: int = 5) -> dict:
    """Search the brain — and COUNT the hits as use (write mode only).

    This is the difference to `search_brain`: a recall feeds the promotion
    signal (`recall_count`), so a memory the agent actually relied on can later
    be promoted by the dream pass. Use `search_brain` for pure exploration.
    """
    query = (query or "").strip()
    if not query:
        return fmt.invalid("query must be a non-empty string")
    if len(query) > 500:
        return fmt.invalid("query exceeds 500 characters")
    if not isinstance(k, int) or k < 1 or k > 20:
        return fmt.invalid("k must be an integer between 1 and 20")
    blocked = _write_guard()
    if blocked:
        return blocked
    from ..agent_memory import recall as _recall
    try:
        engine = make_engine()
        hits = _recall(engine, query, k=k, persist=_cache_vectors())
        results = _hits_payload(engine.brain, hits)
    except RuntimeError as exc:
        return fmt.err("embedder_unavailable", str(exc)[-200:])
    except Exception as exc:          # noqa: BLE001
        return fmt.err("internal", f"{type(exc).__name__}: {exc}")
    return {"ok": True, "query": query, "count": len(results),
            "tracked": True, "results": results}


def forget(id: str, reason: str) -> dict:
    """Remove a node from every live view — WITHOUT deleting it (write mode only).

    Sets the node to `tombstone` (it leaves search, graph and hygiene) and
    invalidates its live edges; the file and the history stay. `reason` is
    mandatory and is recorded in the commit message.
    """
    node_id = (id or "").strip()
    if not node_id:
        return fmt.invalid("id must be a non-empty string")
    if not (reason or "").strip():
        return fmt.invalid("reason must be a non-empty string — it is recorded "
                           "in the commit message")
    blocked = _write_guard()
    if blocked:
        return blocked
    from ..runtime import make_brain
    from ..agent_memory import forget as _forget
    brain = make_brain()
    if brain.read_node(node_id) is None:
        return fmt.node_not_found(node_id)
    try:
        res = _forget(brain, node_id, reason=reason)
    except ValueError as exc:
        return fmt.invalid(str(exc)[-200:])
    except Exception as exc:          # noqa: BLE001
        return fmt.err("internal", f"{type(exc).__name__}: {exc}")
    return {"ok": True, "node_id": res["node_id"], "status": res["status"],
            "edges_invalidated": res["edges_invalidated"],
            "already_forgotten": res.get("already", False),
            "hint": "Tombstoned, not deleted: the node file and its history remain."}


def _write_tool(fn):
    """Register a WRITE tool: `readOnlyHint: False` so clients ask their user
    before letting a model write into the private brain."""
    return mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))(_access_guard(fn, "write"))


def register_write_tools() -> int:
    """Register remember/recall/forget. Called by `ig mcp --write`. Idempotent."""
    global _WRITE_REGISTERED
    if not _write_enabled():
        raise RuntimeError("write mode is off — set IG_MCP_WRITE=1 first")
    if _WRITE_REGISTERED:
        return 0
    for fn in (remember, recall, forget):
        _write_tool(fn)
    _WRITE_REGISTERED = True
    return 3


def main() -> None:
    """Entry point (`ig mcp` / `ig-mcp`): stdio JSON-RPC, nothing else on
    stdout — stdout IS the transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

"""The agent-facing write path (Welle C): remember / recall / forget.

The engine had a human write path (`ig ingest`, `ig link`) and a strictly
read-only MCP surface. An agent that CONSULTS the brain should also be able to
LEAVE something in it — under its own provenance, never destructively, and only
when the operator opts in (`ig mcp --write`).

Provenance is the whole point (Welle A): agent-written nodes carry
`source="agent"` and agent-declared edges `origin="agent"`, so "what did a model
put in here, and what did it connect?" stays a query instead of a guess.

Never destructive (the house rule): `forget` tombstones the node — it leaves
every live view (`retrieve`, `graph`, `hygiene`) but stays in the file, and its
live edges get `valid_to` instead of being deleted, so the audit trail survives.
"""
from __future__ import annotations

from .brain import Brain, Edge, Node, _now_iso
from .brain_engine import BrainEngine

AGENT_SOURCE = "agent"          # node provenance: a model wrote this
AGENT_ORIGIN = "agent"          # edge provenance: a model declared this
FORGET_STATUS = "tombstone"     # never delete — hide from live views


def remember(engine: BrainEngine, text: str, *, tags: list[str] | None = None,
             ntype: str = "semantic",
             relations: list[tuple[str, str]] | None = None,
             allow_duplicates: bool = False) -> dict:
    """Write one note on an agent's behalf.

    Dedupe-aware (a near-duplicate merges into the existing node instead of
    creating a second one) and provenance-marked: the node carries
    `source="agent"`, declared relations carry `origin="agent"`. Commits once
    (that is `ingest`'s own commit), so an agent write is one history entry.
    """
    if not (text or "").strip():
        raise ValueError("Empty text cannot be remembered.")
    node, edges, is_dup = engine.ingest(
        text, source=AGENT_SOURCE, tags=tags, ntype=ntype,
        relations=relations, allow_duplicates=allow_duplicates,
        edge_origin=AGENT_ORIGIN)
    agent_edges = [e for e in edges if e.origin == AGENT_ORIGIN]
    return {"node_id": node.id, "duplicate": is_dup, "edges": len(edges),
            "agent_edges": len(agent_edges), "status": node.status,
            "origin": AGENT_ORIGIN, "written": not is_dup}


def recall(engine: BrainEngine, query: str, k: int = 5, *,
           persist: bool = False) -> list[tuple[str, float]]:
    """A search that COUNTS AS USE.

    Agent recalls feed the promotion signal (`recall_count`), so a memory the
    agent actually relied on can later be promoted by the dream pass.
    `search_brain` stays the side-effect-free variant for exploration.
    """
    from .retrieval import retrieve
    return retrieve(engine, query, k=k, track=True, persist=persist)


def forget(brain: Brain, node_id: str, *, reason: str,
           commit: bool = True, push: bool = True) -> dict:
    """Hide a node from every live view — without deleting it.

    Sets `status="tombstone"` (out of `retrieve`, `graph`, `hygiene` — the file
    and its history stay) and `valid_to` on every live edge touching it, in ONE
    commit. `reason` is mandatory and lands in the commit message: the record of
    WHY must survive with the decision. Idempotent: forgetting a tombstone again
    is a no-op, not an error.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("forget requires a reason — it lands in the commit message.")
    node = brain.read_node(node_id)
    if node is None:
        raise ValueError(f"No node with id {node_id!r}.")
    if node.status == FORGET_STATUS:
        return {"node_id": node_id, "status": FORGET_STATUS, "edges_invalidated": 0,
                "forgotten": False, "already": True, "reason": reason}

    now = _now_iso()
    edges = brain.read_edges(include_rejected=True)
    invalidated = 0
    for e in edges:
        if e.valid_to is None and not e.rejected and node_id in (e.source, e.target):
            e.valid_to = now          # keep the edge, drop it from live views
            invalidated += 1
    node.status = FORGET_STATUS
    brain.write_node(node)
    brain.write_edges(edges)
    brain.rebuild_index()
    if commit:
        brain.commit_and_push(
            f"agent forget: {node_id} — {reason} "
            f"({invalidated} edge(s) invalidated, node tombstoned)", push=push)
    return {"node_id": node_id, "status": FORGET_STATUS,
            "edges_invalidated": invalidated, "forgotten": True,
            "already": False, "reason": reason, "text": (node.text or "")[:120]}
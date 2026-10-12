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
edges are invalidated instead of deleted, so the audit trail survives.
"""
from __future__ import annotations

from .brain import Brain, Edge, Node, _now_iso
from .brain_engine import BRAIN_LOCK, BrainEngine

AGENT_SOURCE = "agent"          # node provenance: a model wrote this
AGENT_ORIGIN = "agent"          # edge provenance: a model declared this
FORGET_STATUS = "tombstone"     # never delete — hide from live views


def remember(engine: BrainEngine, text: str, *, tags: list[str] | None = None,
             ntype: str = "semantic",
             relations: list[tuple[str, str]] | None = None,
             allow_duplicates: bool = False, extraction: str | None = None,
             accept_facts: bool = False) -> dict:
    """Write one note on an agent's behalf.

    Dedupe-aware (a near-duplicate merges into the existing node instead of
    creating a second one) and provenance-marked: the node carries
    `source="agent"`, declared relations carry `origin="agent"`. Commits once
    (that is `ingest`'s own commit) by default. Optional entity extraction
    uses a separate commit after exact-input capture; inspect its status even
    when the note itself was successfully captured.
    """
    if not (text or "").strip():
        raise ValueError("Empty text cannot be remembered.")
    node, edges, is_dup, extracted = engine.capture(
        text, source=AGENT_SOURCE, tags=tags, ntype=ntype,
        relations=relations, allow_duplicates=allow_duplicates,
        edge_origin=AGENT_ORIGIN, extraction=extraction, accept_facts=accept_facts)
    agent_edges = [e for e in edges if e.origin == AGENT_ORIGIN]
    result = {"node_id": node.id, "duplicate": is_dup, "edges": len(edges),
            "agent_edges": len(agent_edges), "status": node.status,
            "origin": AGENT_ORIGIN, "written": not is_dup and not (extracted and extracted["retried"])}
    if extracted is not None:
        result["extraction"] = extracted
    return result


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
    and its history stay), along with its live capture receipts, and invalidates
    every undecided/live edge referencing those nodes or their evidence, in ONE
    commit. `reason` is mandatory and lands in the commit message: the record of
    WHY must survive with the decision. Repeating a completed forget is a no-op.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("forget requires a reason — it lands in the commit message.")
    with BRAIN_LOCK:
        brain.authorize("write", node_id)
        node = brain.read_node(node_id)
        if node is None:
            raise ValueError(f"No node with id {node_id!r}.")
        receipts = brain.capture_receipts(node_id)
        if node.status == FORGET_STATUS and not receipts:
            return {"node_id": node_id, "status": FORGET_STATUS, "edges_invalidated": 0,
                    "forgotten": False, "already": True, "reason": reason}

        forgotten = {n.id for n in [node, *receipts]}
        for nid in forgotten:
            brain.authorize("write", nid)
        now = _now_iso()
        edges = brain.read_edges(include_rejected=True)
        by_id = {e.id: e for e in edges}
        invalidated = 0
        for e in edges:
            affected = [e.source, e.target, *(item.get("node_id") for item in e.evidence)]
            if e.kind == "fact_replacement":
                for key in ("old_fact_id", "new_fact_id"):
                    fact = by_id.get((e.replacement or {}).get(key))
                    if fact is not None:
                        affected.extend([fact.source, fact.target,
                                         *(item.get("node_id") for item in fact.evidence)])
            if not e.is_invalidated and not e.rejected and forgotten.intersection(affected):
                # Authorize the whole family and affected edges before any
                # tombstone, including facts supported by an evidence copy.
                for nid in affected:
                    brain.authorize("write", nid)
                e.invalidate(now)    # Also invalidate scheduled/expired extracted facts.
                invalidated += 1
        for n in [node, *receipts]:
            n.status = FORGET_STATUS
            brain.write_node(n)
        brain.write_edges(edges)
        brain.rebuild_index()
        if commit:
            brain.commit_and_push(
                f"agent forget: {node_id} — {reason} "
                f"({invalidated} edge(s) invalidated, node and {len(receipts)} capture receipt(s) tombstoned)",
                push=push)
        return {"node_id": node_id, "status": FORGET_STATUS,
                "edges_invalidated": invalidated, "forgotten": True,
                "already": False, "reason": reason, "text": (node.text or "")[:120]}

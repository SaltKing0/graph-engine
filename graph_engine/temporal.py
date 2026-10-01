"""Temporal reasoning (Phase 2): bi-temporal queries over the graph.

The engine has bi-temporal edges (valid_from/valid_to) since the Zep/Graphiti
lesson, but no way to QUERY them. This module adds the read side:

  valid_at(brain, timestamp)  — the graph as it was at a point in time
  history(brain, node_id)     — how a node's edges evolved over time
  when(engine, query, at)     — retrieval restricted to what was known then

All functions are read-only. They never modify the brain.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .brain import Brain, Edge, Node
    from .brain_engine import BrainEngine


def _parse_ts(ts: str) -> datetime.datetime:
    """Parse ISO-8601 timestamp, tolerating 'Z' suffix."""
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _is_valid_at(edge: "Edge", ts: datetime.datetime) -> bool:
    """Was this edge valid at the given timestamp?

    An edge is valid at T when:
    - valid_from <= T (it had been created by then)
    - valid_to is None OR valid_to > T (it had not been invalidated yet)
    """
    try:
        valid_from = _parse_ts(edge.valid_from) if edge.valid_from else None
    except (ValueError, TypeError):
        valid_from = None
    try:
        valid_to = _parse_ts(edge.valid_to) if edge.valid_to else None
    except (ValueError, TypeError):
        valid_to = None

    if valid_from and valid_from > ts:
        return False
    if valid_to and valid_to <= ts:
        return False
    return True


def valid_at(brain: "Brain", timestamp: str) -> dict:
    """The graph as it was at a point in time.

    Returns {nodes: [...], edges: [...]} — only nodes and edges that were
    live at the given timestamp. Nodes are included if they existed (created
    <= T) and were not yet tombstoned. Edges are included if they were valid
    at T (see _is_valid_at).
    """
    try:
        ts = _parse_ts(timestamp)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid timestamp: {timestamp!r}")

    nodes: list[Node] = []
    for n in brain.read_nodes():
        if n.status == "tombstone":
            continue
        try:
            created = _parse_ts(n.created) if n.created else None
        except (ValueError, TypeError):
            created = None
        if created and created > ts:
            continue
        nodes.append(n)

    edges: list[Edge] = []
    for e in brain.read_edges(include_rejected=True):
        if e.pending or e.rejected:
            continue
        if _is_valid_at(e, ts):
            edges.append(e)

    return {"nodes": nodes, "edges": edges}


def history(brain: "Brain", node_id: str) -> list[dict]:
    """How a node's edges evolved over time.

    Returns a chronological list of edge events (creation, invalidation)
    involving this node, sorted by timestamp. Each entry has:
    {timestamp, event, edge_id, kind, other_node, origin}
    """
    events: list[dict] = []
    for e in brain.read_edges(include_rejected=True):
        if node_id not in (e.source, e.target):
            continue
        other = e.target if e.source == node_id else e.source
        # Creation event
        events.append({
            "timestamp": e.valid_from,
            "event": "created",
            "edge_id": e.id,
            "kind": e.kind,
            "other_node": other,
            "origin": e.origin,
            "rejected": e.rejected,
        })
        # Invalidation event
        if e.valid_to:
            events.append({
                "timestamp": e.valid_to,
                "event": "invalidated",
                "edge_id": e.id,
                "kind": e.kind,
                "other_node": other,
                "origin": e.origin,
                "rejected": e.rejected,
            })
    events.sort(key=lambda x: x["timestamp"] or "")
    return events


def when(engine: "BrainEngine", query: str, at: str, k: int = 5) -> list[tuple[str, float]]:
    """Retrieval restricted to what was known at a point in time (Phase 2).

    Runs the normal hybrid retrieval, then filters the results to only
    include nodes that existed at the given timestamp. This is the
    "what did I know then?" query — useful for understanding how the
    brain's knowledge has evolved.
    """
    from .retrieval import retrieve

    # Parse timestamp FIRST — an invalid timestamp must raise even when
    # there are no results to filter.
    try:
        ts = _parse_ts(at)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid timestamp: {at!r}")

    # Get the full ranking (no tracking — this is a historical query)
    results = retrieve(engine, query, k=k * 3, track=False)
    if not results:
        return []

    # Filter to nodes that existed at the timestamp
    filtered: list[tuple[str, float]] = []
    for node_id, score in results:
        node = engine.brain.read_node(node_id)
        if node is None:
            continue
        if node.status == "tombstone":
            continue
        try:
            created = _parse_ts(node.created) if node.created else None
        except (ValueError, TypeError):
            created = None
        if created and created > ts:
            continue
        filtered.append((node_id, score))
        if len(filtered) >= k:
            break

    return filtered


def edge_timeline(brain: "Brain", *, since: str | None = None,
                  until: str | None = None) -> list[dict]:
    """All edge events (created/invalidated) in a time range.

    Useful for "what changed in the brain recently?" — the temporal
    equivalent of `ig report --since`.
    """
    events: list[dict] = []
    for e in brain.read_edges(include_rejected=True):
        if e.pending or e.rejected:
            continue
        try:
            vf = _parse_ts(e.valid_from) if e.valid_from else None
        except (ValueError, TypeError):
            vf = None
        try:
            vt = _parse_ts(e.valid_to) if e.valid_to else None
        except (ValueError, TypeError):
            vt = None

        if vf:
            if since and vf < _parse_ts(since):
                pass  # still include, filtered below
            if until and vf > _parse_ts(until):
                pass
            events.append({
                "timestamp": e.valid_from,
                "event": "created",
                "edge_id": e.id,
                "kind": e.kind,
                "source": e.source,
                "target": e.target,
                "origin": e.origin,
            })
        if vt:
            events.append({
                "timestamp": e.valid_to,
                "event": "invalidated",
                "edge_id": e.id,
                "kind": e.kind,
                "source": e.source,
                "target": e.target,
                "origin": e.origin,
            })

    # Filter by range
    if since:
        events = [e for e in events if (e["timestamp"] or "") >= since]
    if until:
        events = [e for e in events if (e["timestamp"] or "") <= until]

    events.sort(key=lambda x: x["timestamp"] or "")
    return events

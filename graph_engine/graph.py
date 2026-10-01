"""Graph traversal over live edges (report #1, MCP phase 1).

SDK-free and CLI-reusable: the MCP `neighbors` tool and any future CLI
command share these functions. The undirected view is deliberate — "what
is this node connected to" does not care which endpoint was newer at
ingest time (edges always point newest -> older).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .brain import Brain, Edge, Node


@dataclass
class Neighbor:
    id: str
    snippet: str
    kind: str
    direction: str      # "out" (this node is the source) | "in"
    pending: bool
    confidence: float | None
    hops: int


def live_edges(brain: Brain, include_pending: bool = False) -> list[Edge]:
    """Edges that count as real relations: not invalidated (valid_to set),
    not rejected, endpoints not tombstoned (hygiene.py precedent — tombstones
    are edge-less BY DESIGN), and optionally not pending."""
    node_status = {n.id: n.status for n in brain.read_nodes()}
    out = []
    for e in brain.read_edges():
        if e.valid_to is not None or e.rejected:
            continue
        if e.source in node_status and node_status[e.source] == "tombstone":
            continue
        if e.target in node_status and node_status[e.target] == "tombstone":
            continue
        if e.pending and not include_pending:
            continue
        out.append(e)
    return out


def neighbors(brain: Brain, node_id: str, hops: int = 1,
              kinds: list[str] | None = None,
              include_pending: bool = False,
              limit: int | None = None) -> list[Neighbor]:
    """BFS over the UNDIRECTED live-edge set, deterministic order.

    Ordering: by (hops, kind, id) so tests are stable regardless of dict
    iteration order. `limit` caps the RESULT (after sorting), not the
    per-hop expansion — a cap during expansion would make the result
    order-dependent in a subtle way.
    """
    edges = live_edges(brain, include_pending=include_pending)
    if kinds is not None:
        allowed = set(kinds)
        edges = [e for e in edges if e.kind in allowed]
    adj: dict[str, list[tuple[str, Edge, str]]] = {}
    for e in edges:
        adj.setdefault(e.source, []).append((e.target, e, "out"))
        adj.setdefault(e.target, []).append((e.source, e, "in"))

    id2node = {n.id: n for n in brain.read_nodes()}
    seen: dict[str, int] = {node_id: 0}
    results: list[Neighbor] = []
    queue = deque([node_id])
    while queue:
        cur = queue.popleft()
        depth = seen[cur]
        if depth >= hops:
            continue
        for other, edge, direction in sorted(adj.get(cur, []),
                                             key=lambda t: (t[1].kind, t[0])):
            if other in seen:
                continue
            seen[other] = depth + 1
            node = id2node.get(other)
            results.append(Neighbor(
                id=other,
                snippet=(node.text if node else "?"),
                kind=edge.kind,
                direction=direction if depth == 0 else
                          ("in" if direction == "out" else "out"),
                pending=edge.pending,
                confidence=edge.confidence,
                hops=depth + 1,
            ))
            queue.append(other)
    results.sort(key=lambda nb: (nb.hops, nb.kind, nb.id))
    if limit is not None:
        results = results[:limit]
    return results


def shortest_path(brain: Brain, a: str, b: str, max_depth: int = 4,
                  include_pending: bool = False) -> list[str] | None:
    """BFS shortest path a -> b over undirected live edges, depth-capped.
    Returns the node id sequence INCLUDING both endpoints, or None."""
    if a == b:
        return [a]
    edges = live_edges(brain, include_pending=include_pending)
    adj: dict[str, list[str]] = {}
    for e in edges:
        adj.setdefault(e.source, []).append(e.target)
        adj.setdefault(e.target, []).append(e.source)
    prev: dict[str, str] = {a: a}
    depth: dict[str, int] = {a: 0}
    queue = deque([a])
    while queue:
        cur = queue.popleft()
        if depth[cur] >= max_depth:
            continue
        for nxt in sorted(adj.get(cur, [])):
            if nxt in prev:
                continue
            prev[nxt] = cur
            depth[nxt] = depth[cur] + 1
            if nxt == b:
                return _walk(prev, b)
            queue.append(nxt)
    return None


def _walk(prev: dict[str, str], end: str) -> list[str]:
    path = [end]
    while prev[path[-1]] != path[-1]:
        path.append(prev[path[-1]])
    return list(reversed(path))

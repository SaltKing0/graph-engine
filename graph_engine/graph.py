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
    predicate: str | None = None


def edge_support_ids(edge: Edge, edges_by_id: dict[str, Edge]) -> set[str] | None:
    """All referenced nodes, or None for malformed persisted support metadata.

    Lifecycle and permission filters share this parsing so a bad replacement
    cannot abort unrelated reads or decisions. Raw storage retains the record.
    """
    def record_ids(source: str | None, target: str | None, evidence: list[dict]) -> set[str] | None:
        if (not isinstance(source, str) or not isinstance(target, str)
                or not isinstance(evidence, list)
                or any(not isinstance(item, dict) or not isinstance(item.get("node_id"), str)
                       for item in evidence)):
            return None
        return {source, target, *(item["node_id"] for item in evidence)}

    ids = record_ids(edge.source, edge.target, edge.evidence)
    if ids is None or edge.kind != "fact_replacement":
        return ids
    meta = edge.replacement
    if not isinstance(meta, dict):
        return None
    for key in ("old_fact_id", "new_fact_id"):
        fact_id = meta.get(key)
        fact = edges_by_id.get(fact_id) if isinstance(fact_id, str) else None
        if fact is None or fact.kind != "fact":
            return None
        support = record_ids(fact.source, fact.target, fact.evidence)
        if support is None:
            return None
        ids.update(support)
    if "decision" in meta:
        decision = meta["decision"]
        if not isinstance(decision, dict) or set(decision) != {"before", "after"}:
            return None
        for rows in decision.values():
            if not isinstance(rows, list):
                return None
            for row in rows:
                if not isinstance(row, dict):
                    return None
                support = record_ids(row.get("source"), row.get("target"), row.get("evidence", []))
                if support is None:
                    return None
                ids.update(support)
    return ids


def edges_with_live_support(nodes: list[Node], edges: list[Edge]) -> list[Edge]:
    """Lifecycle filter, independent of fact validity and review state.

    Callers supply authorized records. Missing/tombstoned endpoints or evidence
    hide the whole record, including replacement facts and embedded undo quotes.
    Raw storage and explicit history/snapshots retain these records.
    """
    live = {node.id for node in nodes if node.status != "tombstone"}
    by_id = {edge.id: edge for edge in edges}
    return [edge for edge in edges
            if (ids := edge_support_ids(edge, by_id)) is not None and ids <= live]


def live_view(brain: Brain) -> tuple[dict[str, Node], list[Edge]]:
    """Authorized live nodes and supported records, retaining temporal review data."""
    nodes = [node for node in brain.read_nodes() if node.status != "tombstone"]
    # Replacement dependencies may be rejected facts, so filter support before
    # choosing which review states to expose.
    edges = edges_with_live_support(nodes, brain.read_edges(include_rejected=True))
    return {node.id: node for node in nodes}, [edge for edge in edges if not edge.rejected]


def live_edges(brain: Brain, include_pending: bool = False) -> list[Edge]:
    """Edges that count as real relations: currently valid and not invalidated,
    not rejected, with live endpoints/evidence, and optionally not pending."""
    _, edges = live_view(brain)
    out = []
    for e in edges:
        if not e.is_current or e.rejected:
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
                predicate=edge.predicate,
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
        node = brain.read_node(a)
        return [a] if node is not None and node.status != "tombstone" else None
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

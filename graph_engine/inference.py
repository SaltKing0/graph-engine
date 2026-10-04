"""Read-only, evidence-backed relationship queries without an LLM.

Connectivity is not entailment. Only homogeneous is_a/part_of fact chains
and explicit same_as chains are transitive. Similarity, extends, arbitrary
predicates and contradictions never acquire transitive logical meaning.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import re
from typing import TYPE_CHECKING

from .brain import Brain, Edge, Node

if TYPE_CHECKING:
    from .brain_engine import BrainEngine

TRANSITIVE = frozenset({"is_a", "part_of", "same_as"})


def _snapshot(brain: Brain) -> tuple[dict[str, Node], list[Edge]]:
    nodes = {n.id: n for n in brain.read_nodes() if n.status != "tombstone"}
    now = datetime.now(timezone.utc)
    # Check both endpoints and actual start dates, including legacy edges.
    edges = sorted((e for e in brain.read_edges()
                    if e.source in nodes and e.target in nodes
                    and not e.pending and not e.rejected and e.is_current
                    and e.is_valid_at(now)), key=lambda e: e.id)
    return nodes, edges


def _resolve(nodes: dict[str, Node], reference: str) -> str:
    reference = reference.strip().strip('"\'').strip()
    if reference in nodes:
        return reference
    key = reference.casefold()
    matches = sorted(n.id for n in nodes.values()
                     if key in {s.casefold() for s in
                                [n.text.strip(), n.entity_name or "", *n.aliases] if s})
    if not matches:
        raise ValueError(f"No live node matches {reference!r}; use a node ID or exact name.")
    if len(matches) != 1:
        raise ValueError(f"Ambiguous node {reference!r}; use an ID: {', '.join(matches)}")
    return matches[0]


def _query_pair(query: str) -> tuple[str, str]:
    query = query.strip()
    if "->" in query:
        parts = query.split("->")
        if len(parts) == 2 and all(p.strip() for p in parts):
            return parts[0].strip(), parts[1].strip()
    patterns = [
        r"(?:what is (?:the )?)?relationship between (.+?) and (.+?)\??",
        r"how (?:does|is) (.+?) (?:relate(?:d)?|connected) to (.+?)\??",
    ]
    for pattern in patterns:
        match = re.fullmatch(pattern, query, flags=re.IGNORECASE)
        if match:
            return match[1].strip(), match[2].strip()
    raise ValueError("Use 'A -> B', 'relationship between A and B', or "
                     "'How does A relate to B?' (exact names or node IDs).")


def _relation(edge: Edge) -> str:
    return edge.predicate or "fact" if edge.kind == "fact" else edge.kind


def _adjacency(edges: list[Edge], relation: str | None = None) -> dict[str, list[tuple[str, Edge]]]:
    adj: dict[str, list[tuple[str, Edge]]] = {}
    for edge in edges:
        if relation is not None:
            if _relation(edge) != relation:
                continue
            # A generic kind named part_of is not a structured fact.
            if edge.kind != "fact" and edge.kind != "same_as":
                continue
        adj.setdefault(edge.source, []).append((edge.target, edge))
        if relation is None or relation == "same_as":
            adj.setdefault(edge.target, []).append((edge.source, edge))
    for links in adj.values():
        links.sort(key=lambda pair: (pair[0], pair[1].id))
    return adj


def _walks(start: str, adj: dict[str, list[tuple[str, Edge]]], max_depth: int,
           *, target: str | None = None, limit: int | None = None) -> list[dict]:
    """Deterministic BFS: one shortest evidence path per reachable node."""
    queue = deque([(start, [start], [])])
    seen = {start}
    paths = []
    while queue:
        current, node_ids, steps = queue.popleft()
        if len(steps) >= max_depth:
            continue
        for other, edge in adj.get(current, []):
            if other in seen:
                continue
            seen.add(other)
            new_steps = [*steps, {"edge_id": edge.id, "source": edge.source,
                                 "target": edge.target, "relation": _relation(edge),
                                 "direction": "out" if edge.source == current else "in"}]
            new_ids = [*node_ids, other]
            path = {"node_ids": new_ids, "steps": new_steps, "hops": len(new_steps)}
            if target is None or other == target:
                paths.append(path)
                if target is not None or (limit is not None and len(paths) >= limit):
                    return paths
            queue.append((other, new_ids, new_steps))
    return paths


def _contradictions(edges: list[Edge], relevant: set[str],
                    relations: list[dict] | None = None) -> list[dict]:
    conflicts = []
    facts: dict[tuple[str, str, str], list[str]] = {}
    for edge in edges:
        if edge.source not in relevant or edge.target not in relevant:
            continue
        if _relation(edge) == "contradicts":
            conflicts.append({"kind": "recorded", "source": edge.source,
                              "target": edge.target, "edge_ids": [edge.id]})
        if edge.kind == "fact" and edge.predicate:
            facts.setdefault((edge.source, edge.predicate, edge.target), []).append(edge.id)
    # Include inferred support so a direct not_part_of can conflict with a
    # multi-hop part_of proof. Negative predicates themselves are not transitive.
    for relation in relations or []:
        if relation["inferred"]:
            key = relation["source"], relation["relation"], relation["target"]
            facts.setdefault(key, []).extend(relation["edge_ids"])
    for (source, predicate, target), ids in sorted(facts.items()):
        if predicate.startswith("not_"):
            positive = facts.get((source, predicate[4:], target))
            if positive:
                conflicts.append({"kind": "opposing_facts", "source": source,
                                  "target": target, "relation": predicate[4:],
                                  "edge_ids": sorted(set(ids + positive))})
    return conflicts


def infer(brain: Brain, query: str, *, max_depth: int = 4) -> dict:
    """Answer a pair query with direct facts, conservative inference and paths.

    Results are bounded by max_depth and describe stored assertions, not
    independently verified real-world facts. No brain files are written.
    """
    if not 1 <= max_depth <= 20:
        raise ValueError("max_depth must be between 1 and 20")
    left, right = _query_pair(query)
    nodes, edges = _snapshot(brain)
    source, target = _resolve(nodes, left), _resolve(nodes, right)
    paths = (_walks(source, _adjacency(edges), max_depth, target=target)
             if source != target else [{"node_ids": [source], "steps": [], "hops": 0}])
    relations = []
    for edge in edges:
        if {edge.source, edge.target} == {source, target}:
            relations.append({"source": edge.source, "target": edge.target,
                              "relation": _relation(edge), "inferred": False,
                              "edge_ids": [edge.id], "rule": "recorded_edge"})
    for predicate in sorted(TRANSITIVE):
        # Direction matters: report reverse proofs with their real endpoints.
        pairs = [(source, target)] if predicate == "same_as" else [(source, target), (target, source)]
        for start, end in pairs:
            proof = _walks(start, _adjacency(edges, predicate), max_depth, target=end)
            if proof and proof[0]["hops"] > 1:
                path = proof[0]
                relations.append({"source": start, "target": end, "relation": predicate,
                                  "inferred": True, "rule": f"transitive_{predicate}",
                                  "edge_ids": [s["edge_id"] for s in path["steps"]]})
                if path not in paths:
                    paths.append(path)
    relevant = {source, target} | {nid for p in paths for nid in p["node_ids"]}
    conflicts = _contradictions(edges, relevant, relations)
    evidence_ids = ({s["edge_id"] for p in paths for s in p["steps"]}
                    | {eid for r in relations for eid in r["edge_ids"]}
                    | {eid for c in conflicts for eid in c["edge_ids"]})
    labels = {nid: nodes[nid].entity_name or nodes[nid].text for nid in sorted(relevant)}
    statements = [f"{labels[r['source']]} --{r['relation']}--> {labels[r['target']]}"
                  + (" (transitive)" if r["inferred"] else " (recorded)") for r in relations]
    if source == target:
        answer = "Both references resolve to the same node."
    elif statements:
        answer = "; ".join(statements) + "."
    elif paths:
        answer = (f"Connected by a {paths[0]['hops']}-edge path; this connection "
                  "does not establish a transitive relation.")
    else:
        answer = f"No connection found within {max_depth} hops."
    if conflicts:
        answer += f" {len(conflicts)} recorded contradiction(s) or opposing fact(s) in the evidence."
    return {"query": query, "source": source, "target": target, "answer": answer,
            "max_depth": max_depth, "relations": relations, "paths": paths,
            "contradictions": conflicts, "nodes": labels,
            "edges": [e.to_dict() for e in edges if e.id in evidence_ids]}


def explain_node(brain: Brain, node_id: str, *, max_depth: int = 2, limit: int = 20) -> dict:
    """Explain a node's current graph context; never claim it caused retrieval."""
    if not 1 <= max_depth <= 20 or not 1 <= limit <= 1000:
        raise ValueError("max_depth must be 1..20 and limit must be 1..1000")
    nodes, edges = _snapshot(brain)
    if node_id not in nodes:
        raise ValueError(f"No live node with id {node_id!r}.")
    found = _walks(node_id, _adjacency(edges), max_depth, limit=limit + 1)
    paths = found[:limit]
    relevant = {node_id} | {nid for path in paths for nid in path["node_ids"]}
    context = [e for e in edges if e.source in relevant and e.target in relevant]
    return {"node_id": node_id, "text": nodes[node_id].text,
            "graph_used_for_ranking": False, "max_depth": max_depth, "limit": limit,
            "truncated": len(found) > limit, "paths": paths,
            "graph_context": [e.to_dict() for e in context],
            "contradictions": _contradictions(context, relevant),
            "explanation": "Current graph paths are context only. Use --query to recompute "
                           "retrieval scores; graph paths are not used by hybrid ranking."}


def print_paths(paths: list[dict]) -> None:
    for path in paths:
        parts = [path["node_ids"][0]]
        for step, nid in zip(path["steps"], path["node_ids"][1:]):
            arrow = (f"--{step['relation']}[{step['edge_id']}]-->" if step["direction"] == "out"
                     else f"<--{step['relation']}[{step['edge_id']}]--")
            parts.extend([arrow, nid])
        print("  " + " ".join(parts))


def cmd_infer(engine: BrainEngine, args: list[str]) -> None:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(prog="ig infer", description=infer.__doc__)
    parser.add_argument("query", nargs="+")
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(args)
    try:
        result = infer(engine.brain, " ".join(options.query), max_depth=options.max_depth)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if options.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["answer"])
        print("Evidence paths:")
        print_paths(result["paths"])
        for conflict in result["contradictions"]:
            print(f"  Conflict {conflict['source']} / {conflict['target']}: "
                  + ", ".join(conflict["edge_ids"]))

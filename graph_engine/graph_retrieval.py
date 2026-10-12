"""Bounded graph relevance, never transitive fact inference or storage writes."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import math

from .brain import Brain, Edge


@dataclass(frozen=True)
class GraphOptions:
    """Explicit opt-in; limits bound traversal, not the initial file scan."""
    hops: int = 2
    seed_limit: int = 3
    candidate_limit: int = 50
    max_degree: int = 20
    visit_limit: int = 500
    weight: float = 0.5
    decay: float = 0.5
    kinds: tuple[str, ...] = ("fact", "mentions", "extends", "related", "linked")
    focal_id: str | None = None

    def __post_init__(self) -> None:
        for name, maximum in (("hops", 3), ("seed_limit", 10), ("candidate_limit", 200),
                              ("max_degree", 50), ("visit_limit", 5000)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"graph {name} must be an integer between 1 and {maximum}")
        for name in ("weight", "decay"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError(f"graph {name} must be finite and in (0, 1]")
        allowed = {"fact", "mentions", "extends", "related", "linked", "similar", "supports", "refines"}
        if (not isinstance(self.kinds, tuple) or not self.kinds
                or any(not isinstance(kind, str) or kind not in allowed for kind in self.kinds)
                or len(set(self.kinds)) != len(self.kinds)):
            raise ValueError("graph kinds must be unique positive relationship kinds")
        if self.focal_id is not None and (not isinstance(self.focal_id, str) or not self.focal_id.strip() or len(self.focal_id) > 200):
            raise ValueError("graph focal_id must be an explicit node ID of 1 to 200 characters")


def graph_options(hops: int = 0, focal_id: str | None = None) -> GraphOptions | None:
    """Shared surface contract: zero disables; a focal ID requires opt-in."""
    if type(hops) is not int or not 0 <= hops <= 3:
        raise ValueError("graph_hops must be an integer between 0 and 3")
    if not hops:
        if focal_id is not None:
            raise ValueError("focal_id requires graph_hops > 0")
        return None
    return GraphOptions(hops=hops, focal_id=focal_id)


def eligible_edges(brain: Brain, live_ids: set[str], at: datetime) -> list[Edge]:
    """Access-filtered, accepted, current relationships with live evidence.

    Validate dates strictly here even though general temporal queries tolerate
    malformed legacy dates. Future legacy edges are also excluded.
    """
    result = []
    for edge in brain.read_edges():
        if (edge.pending is not False or edge.rejected is not False or edge.is_invalidated
                or edge.invalidated_by is not None
                or edge.source not in live_ids or edge.target not in live_ids
                or any(not isinstance(item, dict) or item.get("node_id") not in live_ids
                       for item in edge.evidence)):
            continue
        try:
            for value in (edge.valid_from, edge.valid_to, edge.invalidated_at):
                if value is not None:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError):
            continue
        if edge.is_valid_at(at):
            result.append(edge)
    return sorted(result, key=lambda edge: edge.id)


@dataclass
class GraphTrace:
    options: GraphOptions | None = None
    at: str | None = None
    seeds: list[dict] = field(default_factory=list)
    contributions: dict[str, float] = field(default_factory=dict)
    paths: dict[str, list[dict]] = field(default_factory=dict)
    truncation: set[str] = field(default_factory=set)
    visits: int = 0
    cap: float = 0.0

    def summary(self) -> dict:
        return {"enabled": self.options is not None,
                "graph_used_for_ranking": bool(self.contributions),
                "options": asdict(self.options) if self.options else None,
                "evaluated_at": self.at, "seeds": self.seeds,
                "contribution_cap": self.cap, "expanded_count": len(self.contributions),
                "visits": self.visits, "truncated": bool(self.truncation),
                "truncation_reasons": sorted(self.truncation),
                "semantics": "Connectivity is retrieval context, not logical entailment."}


def expand(brain: Brain, live_ids: set[str], ranked: list[tuple[str, float]],
           options: GraphOptions | None) -> GraphTrace:
    trace = GraphTrace(options=options)
    if options is None:
        return trace
    if options.focal_id is not None:
        focal = brain.read_node(options.focal_id)  # direct ACL check
        if focal is None or focal.status == "tombstone" or focal.id not in live_ids:
            raise ValueError("focal_id must identify an accessible live node")
    at = datetime.now(timezone.utc)
    trace.at = at.isoformat()
    positive = [(nid, score) for nid, score in ranked if score > 0]
    seeds = positive[:options.seed_limit]
    if options.focal_id is None and len(positive) > options.seed_limit:
        trace.truncation.add("seed_limit")
    # Focal retrieval is explicitly scoped to this anchor, rather than mixing
    # unrelated query seeds. Its anchor score is fixed, never a fact confidence.
    if options.focal_id is not None:
        seeds = [(options.focal_id, max(dict(ranked).get(options.focal_id, 0.0), 1 / 61))]
    trace.seeds = [{"id": nid, "score": score, "focal": nid == options.focal_id}
                   for nid, score in seeds]
    trace.cap = options.weight * max((score for _, score in seeds), default=0.0)
    if not seeds:
        return trace
    adj: dict[str, list[tuple[str, Edge, str]]] = {}
    for edge in eligible_edges(brain, live_ids, at):
        if edge.kind not in options.kinds or edge.source == edge.target:
            continue
        adj.setdefault(edge.source, []).append((edge.target, edge, "out"))
        adj.setdefault(edge.target, []).append((edge.source, edge, "in"))
    # Count distinct neighbors so parallel assertions cannot manufacture hubs
    # or amplify a result. First shortest path per seed wins deterministically.
    degree = {nid: len({other for other, _, _ in arcs}) for nid, arcs in adj.items()}
    for nid in adj:
        adj[nid].sort(key=lambda arc: (arc[0], arc[1].id, arc[2]))
    for seed_id, seed_score in seeds:
        seen = {seed_id}
        queue = deque([(seed_id, [], seed_score * options.weight)])
        while queue:
            current, steps, strength = queue.popleft()
            if len(steps) >= options.hops:
                if any(other not in seen for other, _, _ in adj.get(current, [])):
                    trace.truncation.add("hop_limit")
                continue
            if degree.get(current, 0) > options.max_degree:
                trace.truncation.add("degree_limit")
                continue
            for other, edge, direction in adj.get(current, []):
                if trace.visits >= options.visit_limit:
                    trace.truncation.add("visit_limit")
                    return trace
                trace.visits += 1
                if other in seen:
                    continue
                seen.add(other)
                if degree.get(other, 0) > options.max_degree:
                    trace.truncation.add("degree_limit")
                    continue
                if other not in trace.contributions and len(trace.contributions) >= options.candidate_limit:
                    trace.truncation.add("candidate_limit")
                    continue
                factor = (options.decay if steps else 1.0) / math.sqrt(max(1, degree[current]) * max(1, degree[other]))
                contribution = strength * factor
                path = [*steps, {"edge_id": edge.id, "from": current, "to": other,
                                "direction": direction, "degree_from": degree[current],
                                "degree_to": degree[other], "factor": factor,
                                "edge": edge.to_dict()}]
                total = trace.contributions.get(other, 0.0)
                applied = min(contribution, max(0.0, trace.cap - total))
                trace.contributions[other] = total + applied
                trace.paths.setdefault(other, []).append({"seed_id": seed_id, "seed_score": seed_score,
                    "steps": path, "hops": len(path), "raw_contribution": contribution,
                    "contribution": applied})
                queue.append((other, path, contribution))
    return trace

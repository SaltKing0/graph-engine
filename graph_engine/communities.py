"""Topology-based community detection and structural gap analysis.

A MACRO view over the brain's graph: which dense regions exist, which
nodes route between them (god nodes), and which pairs of well-developed
communities are suspiciously disconnected (structural gaps). Read-only —
nothing here writes to the brain, and no derived artifact is persisted
(the partition changes on every ingest; persisting it would be pure
git churn in a repo where every commit is knowledge).

Algorithms are hand-rolled stdlib on purpose:
- Label propagation (LPA) instead of Louvain/Leiden: deterministic with
  a fixed iteration order and smallest-label tie-break, ~40 lines, and
  measured Q=0.6685 on the live graph — a hand-rolled modularity
  optimizer would buy little for ~200 lines of untested numerics.
- Brandes betweenness, exact by default (measured 11.3 s at ~1.8k
  nodes) with a deterministic pivot sample for brains an order of
  magnitude larger.
- Configuration-model null for gap ranking: expected cross edges
  comdeg_a * comdeg_b / (2m); deficit = (expected - observed)/expected.

networkx is deliberately NOT used: it is not a declared dependency and
absent in CI (it only appears locally as a transitive dep of torch).
"""

from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass, field

from .brain import Brain
from .gaps import DEFAULT_TAXONOMY, _node_text, normalize

# LPA converges fast on small-world graphs (measured: 17 iterations on
# the live graph); the cap only guards pathological cycles.
MAX_LPA_ITER = 50
DEFAULT_MIN_COMMUNITY = 15
DEFAULT_TOP = 10


@dataclass
class Community:
    id: int
    members: list[str] = field(default_factory=list)   # sorted node ids
    size: int = 0
    internal_edges: int = 0
    degree_sum: int = 0
    label: str = "UNCLASSIFIED"
    sample: str = ""


@dataclass
class GodNode:
    id: str
    degree: int
    betweenness: float
    text: str


@dataclass
class StructuralGap:
    a: int
    b: int
    a_label: str = ""
    b_label: str = ""
    a_size: int = 0
    b_size: int = 0
    observed_edges: int = 0
    expected_edges: float = 0.0
    deficit: float = 0.0
    bridge_nodes: list[str] = field(default_factory=list)
    a_samples: list[str] = field(default_factory=list)
    b_samples: list[str] = field(default_factory=list)


@dataclass
class CommunityReport:
    nodes: int
    edges: int
    modularity: float
    communities: list[Community]
    god_nodes: list[GodNode]
    gaps: list[StructuralGap]
    isolated: list[str]
    betweenness_sample: int | None    # None = exact
    unclassified: int = 0             # share of nodes without a taxonomy label


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(brain: Brain, include_pending: bool = True
                ) -> tuple[list[str], dict[str, set[str]], Counter]:
    """Undirected adjacency over live nodes and live edges.

    Excludes: tombstoned nodes (they are edge-less append-only history —
    including them manufactures phantom singleton communities, the exact
    bug that once made the autonomous cycle try to re-link a dead node),
    rejected edges (read_edges default), valid_to-invalidated edges
    (hygiene precedent: they no longer count toward connectivity),
    dangling endpoints, and self-loops. A->B and B->A deduplicate into
    ONE undirected edge (link() is direction-sensitive, so both can
    coexist in storage). Pending edges are included by default: on a
    fresh brain every similarity edge is pending, and topology over zero
    edges is useless — the --no-pending variant exists for strictness.
    """
    nodes = [n for n in brain.read_nodes() if n.status != "tombstone"]
    id_set = {n.id for n in nodes}
    adj: dict[str, set[str]] = {nid: set() for nid in id_set}
    seen: set[frozenset[str]] = set()
    deg: Counter = Counter()
    m = 0
    for e in brain.read_edges():
        if e.valid_to is not None or e.rejected:
            continue
        if not include_pending and e.pending:
            continue
        if e.source == e.target:
            continue
        if e.source not in id_set or e.target not in id_set:
            continue
        key = frozenset((e.source, e.target))
        if key in seen:
            continue
        seen.add(key)
        adj[e.source].add(e.target)
        adj[e.target].add(e.source)
        deg[e.source] += 1
        deg[e.target] += 1
        m += 1
    ordered = sorted(id_set)          # deterministic iteration everywhere
    return ordered, adj, deg


# ---------------------------------------------------------------------------
# Label propagation (deterministic)
# ---------------------------------------------------------------------------

def label_propagation(nodes: list[str], adj: dict[str, set[str]],
                      max_iter: int = MAX_LPA_ITER) -> dict[str, int]:
    """Deterministic LPA returning CANONICAL labels 0..k-1.

    Iterates sorted(nodes); each node adopts the neighbour label with the
    highest count, ties broken by the SMALLEST label id; converges on a
    fixpoint or max_iter. Raw labels never escape this function: they are
    canonicalized once at the boundary (communities sorted by size desc,
    then smallest member id) — mixing raw and canonical indices is a real
    ZeroDivisionError trap (it happened in the measurement script that
    produced report #3).
    """
    if not nodes:
        return {}
    labels: dict[str, int] = {n: i for i, n in enumerate(sorted(nodes))}
    for _ in range(max_iter):
        changed = False
        for node in sorted(nodes):
            counts: Counter = Counter()
            for nb in adj.get(node, ()):  # deterministic: sets are only summed
                counts[labels[nb]] += 1
            if not counts:
                continue
            best = max(counts.values())
            # smallest label id wins ties
            target = min(l for l, c in counts.items() if c == best)
            if labels[node] != target:
                labels[node] = target
                changed = True
        if not changed:
            break
    # Canonicalize: group by raw label, order communities by size desc then
    # smallest member id, renumber 0..k-1.
    groups: dict[int, list[str]] = {}
    for node, lab in labels.items():
        groups.setdefault(lab, []).append(node)
    ordered = sorted(groups.values(),
                     key=lambda ms: (-len(ms), min(ms)))
    canon: dict[str, int] = {}
    for new_id, members in enumerate(ordered):
        for node in members:
            canon[node] = new_id
    return canon


def modularity(nodes: list[str], adj: dict[str, set[str]],
               labels: dict[str, int]) -> float:
    """Newman modularity of the partition over the undirected graph."""
    m = sum(len(nbs) for nbs in adj.values()) / 2.0
    if m == 0:
        return 0.0
    degrees = {n: len(adj.get(n, ())) for n in nodes}
    same: Counter = Counter()
    for n in nodes:
        for nb in adj.get(n, ()):
            if labels[nb] == labels[n]:
                same[labels[n]] += 1
    q = 0.0
    for cid in set(labels.values()):
        members = [n for n in nodes if labels[n] == cid]
        intra = same[cid] / 2.0
        deg_sum = sum(degrees[n] for n in members)
        q += intra / m - (deg_sum / (2.0 * m)) ** 2
    return q


# ---------------------------------------------------------------------------
# Betweenness (Brandes)
# ---------------------------------------------------------------------------

def betweenness(nodes: list[str], adj: dict[str, set[str]],
                sample: int | None = None) -> dict[str, float]:
    """Brandes betweenness, normalized to [0, 1] (undirected convention:
    divide by (n-1)(n-2)/2). sample=None = exact, sample=N = N deterministic
    pivots (every ceil(len/N)-th id in sorted order) — a documented
    approximation, never a random one."""
    if not nodes:
        return {}
    ordered = sorted(nodes)
    if sample is not None and 0 < sample < len(ordered):
        step = math.ceil(len(ordered) / sample)
        sources = ordered[::step]
    else:
        sources = ordered
    bc: dict[str, float] = {n: 0.0 for n in ordered}
    for s in sources:
        # Brandes single-source pass
        stack: list[str] = []
        preds: dict[str, list[str]] = {n: [] for n in ordered}
        sigma: dict[str, float] = {n: 0.0 for n in ordered}
        sigma[s] = 1.0
        dist: dict[str, int] = {n: -1 for n in ordered}
        dist[s] = 0
        queue: deque[str] = deque([s])
        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in sorted(adj.get(v, ())):   # sorted for determinism
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    preds[w].append(v)
        delta: dict[str, float] = {n: 0.0 for n in ordered}
        while stack:
            w = stack.pop()
            for v in preds[w]:
                delta[v] += sigma[v] / sigma[w] * (1.0 + delta[w])
            if w != s:
                bc[w] += delta[w]
    if sample is not None and len(sources) < len(ordered):
        scale = len(ordered) / len(sources)
        for n in bc:
            bc[n] *= scale
    # Undirected: running BFS from every source counts each unordered pair
    # twice — halve, then normalize to [0, 1] by (n-1)(n-2)/2.
    for n in bc:
        bc[n] /= 2.0
    norm = (len(ordered) - 1) * (len(ordered) - 2) / 2.0
    if norm > 0:
        for n in bc:
            bc[n] /= norm
    return bc


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _classify(label_counts: Counter) -> str:
    if not label_counts:
        return "UNCLASSIFIED"
    return label_counts.most_common(1)[0][0]


def analyze_communities(brain: Brain, min_size: int = DEFAULT_MIN_COMMUNITY,
                        top: int = DEFAULT_TOP, betweenness_sample: int | None = None,
                        include_pending: bool = True, taxonomy: dict | None = None,
                        with_members: bool = False,
                        exclude_ids: set[str] | None = None) -> CommunityReport:
    """Full topology report: partition, god nodes, structural gaps.

    `exclude_ids` removes nodes from the partition entirely. A derived node (a
    consolidator summary) must not feed back into the structure it summarizes:
    otherwise a second dream pass partitions a different graph and cannot be
    idempotent — the summary nodes join their own communities and shift them.
    """
    nodes, adj, deg = build_graph(brain, include_pending=include_pending)
    if exclude_ids:
        keep = [n for n in nodes if n not in exclude_ids]
        keep_set = set(keep)
        adj = {n: {m for m in adj[n] if m in keep_set} for n in keep}
        deg = Counter({n: d for n, d in deg.items() if n in keep_set})
        nodes = keep
    id2text = {n.id: n.text for n in brain.read_nodes() if n.status != "tombstone"}
    labels = label_propagation(nodes, adj)
    q = modularity(nodes, adj, labels)
    tax = taxonomy or DEFAULT_TAXONOMY

    # Pre-compute per-node taxonomy hits once (normalize + _node_text reused
    # from gaps.py so both views classify identically).
    norm_tax = {area: [normalize(k) for k in kws] for area, kws in tax.items()}
    node_area: dict[str, Counter] = {}
    for nid in nodes:
        text = normalize(_node_text_raw(id2text.get(nid, "")))
        hits: Counter = Counter()
        for area, kws in norm_tax.items():
            if any(kw in text for kw in kws):
                hits[area] += 1
        node_area[nid] = hits

    communities: list[Community] = []
    groups: dict[int, list[str]] = {}
    for nid in nodes:
        groups.setdefault(labels[nid], []).append(nid)
    for cid, members in groups.items():
        members = sorted(members)
        internal = sum(1 for n in members for nb in adj[n] if labels[nb] == cid) // 2
        label_counts: Counter = Counter()
        for n in members:
            label_counts.update(node_area[n].keys())
        # Highest-degree member's text as the sample (degree is what the
        # partition actually routed on; text of a random member would not).
        hub = max(members, key=lambda n: (deg[n], n))
        communities.append(Community(
            id=cid, members=members if with_members else [],
            size=len(members), internal_edges=internal,
            degree_sum=sum(deg[n] for n in members),
            label=_classify(label_counts),
            sample=_short_text(id2text.get(hub, "")),
        ))

    # God nodes: degree AND betweenness (their rankings diverge substantially —
    # mean |delta rank| 247 of 1761 on the live graph — so degree alone would
    # misname the hubs the brain actually routes through).
    bc = betweenness(nodes, adj, sample=betweenness_sample)
    top_bc = sorted(nodes, key=lambda n: (-bc[n], n))[:5]
    god_nodes = [GodNode(id=n, degree=deg[n], betweenness=round(bc[n], 1),
                         text=_short_text(id2text.get(n, ""))) for n in top_bc]

    # Structural gaps vs the configuration-model null.
    gaps = _structural_gaps(communities, labels, adj, deg, id2text, min_size, top)

    isolated = sorted(n for n in nodes if deg[n] == 0)
    unclassified = sum(1 for n in nodes if _classify(node_area[n]) == "UNCLASSIFIED")
    return CommunityReport(
        nodes=len(nodes), edges=sum(deg.values()) // 2, modularity=q,
        communities=communities, god_nodes=god_nodes, gaps=gaps,
        isolated=isolated, betweenness_sample=betweenness_sample,
        unclassified=unclassified,
    )


def _structural_gaps(communities: list[Community], labels: dict[str, int],
                     adj: dict[str, set[str]], deg: Counter,
                     id2text: dict[str, str], min_size: int,
                     top: int) -> list[StructuralGap]:
    """Deficit-ranked missing links between well-developed communities.

    deficit = (expected - observed) / expected with
    expected = comdeg_a * comdeg_b / (2m) (configuration-model null).
    Tie-break by expected desc. Pairs with expected <= 0 are skipped
    (division-by-zero trap hit by the report's own measurement script).
    """
    big = [c for c in communities if c.size >= min_size]
    m = sum(deg.values()) / 2.0
    if m == 0 or len(big) < 2:
        return []
    # Cross-edge counts per community pair + bridge nodes (touch both sides).
    cross: dict[tuple[int, int], int] = {}
    bridges: dict[int, set[str]] = {c.id: set() for c in big}
    member_of = labels
    big_ids = {c.id for c in big}
    for n in member_of:
        if member_of[n] not in big_ids:
            continue
        for nb in adj.get(n, ()):
            other = member_of.get(nb)
            if other is None or other == member_of[n]:
                continue
            if other not in big_ids:
                continue
            key = (min(member_of[n], other), max(member_of[n], other))
            cross[key] = cross.get(key, 0) + 1
            bridges[member_of[n]].add(n)
            bridges[other].add(nb)
    # observed pairs were counted twice (once per endpoint side)
    cross = {k: v // 2 for k, v in cross.items()}

    comdeg = {c.id: c.degree_sum for c in big}
    by_id = {c.id: c for c in big}
    candidates = []
    for i, a in enumerate(big):
        for b in big[i + 1:]:
            expected = comdeg[a.id] * comdeg[b.id] / (2.0 * m)
            if expected <= 0:
                continue
            observed = cross.get((a.id, b.id), 0)
            deficit = (expected - observed) / expected
            candidates.append((deficit, expected, a, b, observed))
    candidates.sort(key=lambda t: (-t[0], -t[1]))
    result = []
    for deficit, expected, a, b, observed in candidates[:max(top, 0)]:
        result.append(StructuralGap(
            a=a.id, b=b.id, a_label=a.label, b_label=b.label,
            a_size=a.size, b_size=b.size, observed_edges=observed,
            expected_edges=round(expected, 1), deficit=round(deficit, 2),
            bridge_nodes=sorted(bridges[a.id] & bridges[b.id]),
            a_samples=_samples(a.id, member_of, id2text, deg),
            b_samples=_samples(b.id, member_of, id2text, deg),
        ))
    return result


def _samples(cid: int, labels: dict[str, int], id2text: dict[str, str],
             deg: Counter, k: int = 2) -> list[str]:
    """k highest-degree members' short texts as evidence for a gap side."""
    members = sorted((n for n, c in labels.items() if c == cid),
                     key=lambda n: (-deg[n], n))
    return [_short_text(id2text.get(n, "")) for n in members[:k]]


def _short_text(text: str, limit: int = 72) -> str:
    text = " ".join((text or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def _node_text_raw(text: str) -> str:
    """gaps._node_text operates on Node objects; here we hold raw texts."""
    import re
    m = re.match(r"^---\n.*?\n---\n\n?(.*)$", text or "", re.DOTALL)
    if m:
        return m.group(1).strip()
    return (text or "").strip()


def structural_gaps(brain: Brain, min_size: int = DEFAULT_MIN_COMMUNITY,
                    top: int = 5) -> list[dict]:
    """Provider seam for the BRAIN_REPORT (report #7's contract).

    Returns rows of {"kind", "label", "node_ids", "score", "hint"} — the
    report renders them and never computes communities itself. Reuses
    analyze_communities (one pass, no duplicate logic).
    """
    rep = analyze_communities(brain, min_size=min_size, top=top,
                              betweenness_sample=200)
    id2text = {n.id: n.text for n in brain.read_nodes() if n.status != "tombstone"}
    rows: list[dict] = []
    big = [c for c in rep.communities if c.size >= min_size][:top]
    for c in big:
        rows.append({"kind": "community", "label": c.label,
                     "node_ids": c.members or [], "score": float(c.size),
                     "hint": c.sample})
    # NOTE: no 'god' rows — the report's own Hubs section already renders
    # hub nodes from degree; emitting them here double-renders and, worse,
    # makes the provider non-empty on tiny brains where the rows are noise.
    for gp in rep.gaps:
        hint = (f"C{gp.a} ({gp.a_label}, n={gp.a_size}) <-> "
                f"C{gp.b} ({gp.b_label}, n={gp.b_size}): "
                f"{gp.observed_edges} of {gp.expected_edges} expected edges; "
                f"evidence: {' / '.join((gp.a_samples + gp.b_samples)[:2])}")
        rows.append({"kind": "hole", "label": f"{gp.a_label} <-> {gp.b_label}",
                     "node_ids": [], "score": float(gp.deficit), "hint": hint})
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_communities(report: CommunityReport) -> str:
    lines: list[str] = []
    uncl = f", {report.unclassified} unclassified" if report.unclassified else ""
    lines.append(f"Communities ({report.nodes} nodes / {report.edges} edges · "
                 f"{len(report.communities)} communities · Q={report.modularity:.3f}{uncl}):")
    lines.append(f"{'#':>4}{'Nodes':>7}{'Degree':>8}  Area (dominant)".ljust(0)
                 + f"{'':2}Sample")
    for c in report.communities:
        lines.append(f"{c.id:>4}{c.size:>7}{c.degree_sum:>8}  {c.label:<38} {c.sample}")
    if report.god_nodes:
        lines.append("")
        lines.append("God nodes (degree / betweenness):")
        for g in report.god_nodes:
            lines.append(f"{g.degree:>4} / {g.betweenness:>9.1f}  {g.id}  {g.text}")
    if report.gaps:
        lines.append("")
        lines.append(f"Structural gaps (top {len(report.gaps)} · communities >= "
                     f"{DEFAULT_MIN_COMMUNITY} nodes, deficit vs. configuration null):")
        for gp in report.gaps:
            # C-ids disambiguate: several communities can share one dominant
            # label, so a label-only line can render the same pair twice.
            lines.append(f"[{gp.deficit:.2f}] C{gp.a} ({gp.a_label}, n={gp.a_size})"
                         f" <-> C{gp.b} ({gp.b_label}, n={gp.b_size})   "
                         f"{gp.observed_edges} edges, {gp.expected_edges} expected")
            for side, cid, samples in (("a", gp.a, gp.a_samples),
                                       ("b", gp.b, gp.b_samples)):
                if samples:
                    lines.append(f"    C{cid}: {' / '.join(samples)}")
    if report.isolated:
        lines.append("")
        lines.append(f"Isolated nodes ({len(report.isolated)}): "
                     + ", ".join(report.isolated[:10]))
    return "\n".join(lines)

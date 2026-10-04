"""Hygiene/status analysis (`ig status`, `ig near-dup`).

Read-only reports that support brain maintenance:

- `near_dup_pairs` — finds near-duplicate pairs in the cosine band below the
  auto-dedup threshold (0.92). These pairs need a manual
  `ig merge` decision (see `graph_engine.merge`).
- `connectivity` / `status_counts` — islands, weak nodes, orphans and
  status distribution, so underpopulation and the hygiene backlog become visible.

Everything is read-only — nothing on the brain is modified.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .brain import Brain

# Auto-dedup threshold in brain_engine (cos >= 0.92 -> merge). Pairs below it,
# but close enough, are candidates for manual consolidation.
DEFAULT_DEDUP_THRESHOLD = 0.92
DEFAULT_NEAR_LO = 0.78


@dataclass
class NearDup:
    score: float
    a: str
    b: str
    a_text: str
    b_text: str


_VEC_CACHE: dict[tuple[str, float, int], tuple[list[str], np.ndarray]] = {}


def _load_vectors(brain: Brain) -> tuple[list[str], np.ndarray]:
    """Reads vectors.jsonl; uses the dominant dimension (384 real vs 64 hash).

    Audit #38: float32 rounds band-boundary cases wrong (0.9199999990 float64
    -> 0.9200000167 float32 — the pair falls through BOTH mechanisms: no dup
    in the engine, but not in the review band either). Hence float64.
    Audit #60: results are cached keyed by (path, mtime, size) — repeated
    report calls within one process skip the re-parse; any write to the file
    invalidates the entry automatically."""
    vec_file = brain.path / "vectors.jsonl"
    if not vec_file.exists():
        return [], np.zeros((0, 0), dtype=np.float64)
    try:
        st = vec_file.stat()
        key = (str(vec_file), st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key is not None and key in _VEC_CACHE:
        return _VEC_CACHE[key]
    vecs: dict[str, list[float]] = {}
    lens: Counter = Counter()
    for l in vec_file.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        try:
            o = json.loads(l)
        except json.JSONDecodeError:
            continue  # Audit #17 family: a corrupt line does not kill the report
        vecs[o["id"]] = o["vec"]
        lens[len(o["vec"])] += 1
    if not vecs:
        return [], np.zeros((0, 0), dtype=np.float64)
    dom = max(lens, key=lambda k: lens[k])
    ids = [n for n, v in vecs.items() if len(v) == dom]
    V = np.array([vecs[n] for n in ids], dtype=np.float64)
    V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-12)
    if key is not None:
        _VEC_CACHE[key] = (ids, V)
    return ids, V


def near_dup_pairs(
    brain: Brain,
    lo: float = DEFAULT_NEAR_LO,
    hi: float = DEFAULT_DEDUP_THRESHOLD,
    max_pairs: int | None = None,
) -> list[NearDup]:
    """Finds near-duplicate pairs in the cosine band [lo, hi), descending by score.

    Audit #38: the upper band end is inclusive-consistent with the engine — a
    float64 cos of 0.9199999990 is NOT a dup in the engine (0.92 threshold),
    so it must appear in the review band. An epsilon buffer at `hi` prevents
    rounding from dropping such pairs out of both mechanisms.
    Audit #39: the pair iteration runs vectorized (triu mask) instead of in
    O(N²) Python loops (4M iterations @2k, ~50 s @20k)."""
    ids, V = _load_vectors(brain)
    if len(ids) < 2:
        return []
    # Tombstones are edge-less BY DESIGN (`ig merge` redirects the deletee's edges
    # away), so a merged deletee keeps its stale vector in vectors.jsonl and would
    # re-report the very pair it was merged for on EVERY run — the same phantom-node
    # class as the connectivity()/gaps filter. Review only live nodes.
    nodes = brain.read_nodes()
    live = {n.id for n in nodes if n.status != "tombstone"}
    keep = [i for i, nid in enumerate(ids) if nid in live]
    if len(keep) < 2:
        return []
    ids = [ids[i] for i in keep]
    V = V[keep]
    S = V @ V.T
    np.fill_diagonal(S, -1.0)
    band = (S >= lo) & (S < hi + 1e-6)
    band = np.triu(band, k=1)
    ii, jj = np.nonzero(band)
    texts = {n.id: n.text for n in nodes}
    pairs = [NearDup(float(S[i][j]), ids[int(i)], ids[int(j)],
                     texts.get(ids[int(i)], ids[int(i)])[:72],
                     texts.get(ids[int(j)], ids[int(j)])[:72])
             for i, j in zip(ii, jj)]
    pairs.sort(key=lambda p: p.score, reverse=True)
    if max_pairs is not None:
        # Audit #60: `if max_pairs:` treated max_pairs=0 as "unbounded" —
        # 0 means limit 0 (no pairs).
        pairs = pairs[:max_pairs]
    return pairs


@dataclass
class Connectivity:
    total: int
    edges: int
    islands: list[str]   # degree <= 1
    weak: list[str]      # degree == 2
    orphans: list[str]   # degree == 0
    max_degree: int
    mean_degree: float


def connectivity(brain: Brain) -> Connectivity:
    nodes = brain.read_nodes()
    # Tombstones are edge-less BY DESIGN (merge redirects their edges away and
    # keeps the node as append-only history) — counting them made every merge
    # leave a permanent phantom "orphan/island" in the status report, and the
    # autonomous cycle then tried to re-link a dead node (found 2026-09-15).
    nodes = [n for n in nodes if n.status != "tombstone"]
    edges = brain.read_edges()
    # Audit #40: invalidated or out-of-window edges no longer count toward
    # connectivity — otherwise the status report would contradict the
    # admit-rule logic (_has_relation correctly ignores them).
    live_edges = [e for e in edges if e.is_current]
    deg: Counter = Counter()
    for e in live_edges:
        deg[e.source] += 1
        deg[e.target] += 1
    ids = [n.id for n in nodes]
    islands = [n for n in ids if deg[n] <= 1]
    weak = [n for n in ids if deg[n] == 2]
    orphans = [n for n in ids if deg[n] == 0]
    vals = [deg[n] for n in ids] or [0]
    return Connectivity(
        total=len(ids),
        edges=len(live_edges),
        islands=islands,
        weak=weak,
        orphans=orphans,
        max_degree=max(vals),
        mean_degree=sum(vals) / len(vals),
    )


def status_counts(brain: Brain) -> Counter:
    c: Counter = Counter()
    for n in brain.read_nodes():
        c[n.status] += 1
    return c


def render_status(brain: Brain) -> str:
    c = connectivity(brain)
    st = status_counts(brain)
    lines = [
        f"Status ({c.total} nodes / {c.edges} edges):",
        f"  Degree: max={c.max_degree} mean={c.mean_degree:.1f}",
        f"  Orphans (0 edges): {len(c.orphans)}",
        f"  Islands (<=1 edge): {len(c.islands)}",
        f"  Weak (==2 edges): {len(c.weak)}",
        f"  Status: {dict(st)}",
    ]
    if c.islands:
        lines.append("  Island nodes: " + ", ".join(c.islands[:15]) + (" …" if len(c.islands) > 15 else ""))
    if c.orphans:
        lines.append("  Orphan nodes: " + ", ".join(c.orphans[:15]) + (" …" if len(c.orphans) > 15 else ""))
    return "\n".join(lines)


def render_near_dup(pairs: list[NearDup]) -> str:
    if not pairs:
        return "No near-duplicates in the band."
    lines = [f"{len(pairs)} near-duplicate pairs (review consolidation via `ig merge`):"]
    for p in pairs:
        lines.append(f"[{p.score:.3f}] {p.a} ↔ {p.b}")
        lines.append(f"    {p.a_text}")
        lines.append(f"    {p.b_text}")
    return "\n".join(lines)

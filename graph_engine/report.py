"""Generated state-of-the-brain digest (BRAIN_REPORT).

One page answering: what changed since last time, what needs a human
decision, and where is the graph structurally thin. Pure read-only over
nodes/*.md frontmatter, edges.jsonl and the precomputed vectors.jsonl —
nothing here writes to the brain, embeds, or calls `ig search` (that
would re-embed; the report must stay cheap and side-effect free).

Deliberately NOT regenerated on ingest: INDEX.md already rides the
ingest RMW chain, and the coverage pass alone costs ~5.8 s on a live
brain. Staleness is stated explicitly in the header (head_sha +
commits_behind) instead of hidden.

Sections deliberately cut (measured on the live brain): a status
distribution section (a constant: everything probation), a pending
inbox (always empty — the cycle auto-accepts), and a coverage section
(saturated taxonomy, +5.8 s — kept behind the opt-in `--coverage`).
"""
from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone

from .brain import Brain, _atomic_write
from .hygiene import connectivity, near_dup_pairs, status_counts

# Confidence bands (suggester.py): <0.45 no edge, 0.45-0.75 extends,
# 0.75-0.95 similar, >=0.95 auto-accept. The report mirrors these bands.
BANDS = ((0.45, "none"), (0.75, "low"), (0.95, "mid"), (float("inf"), "auto"))
INTENT_KINDS = ("contradicts", "supersedes")
DEFAULT_SINCE_HOURS = 24
DEFAULT_TOP = 10


# ---------------------------------------------------------------------------
# Escaping helpers
# ---------------------------------------------------------------------------

def _md_cell(text: str, limit: int = 60) -> str:
    """Table cell: truncate FIRST, then escape pipes (Audit #55 order)."""
    text = " ".join((text or "").split())
    text = text[:limit]
    return text.replace("|", "\\|")


def _short(text: str, limit: int = 72) -> str:
    text = " ".join((text or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


# ---------------------------------------------------------------------------
# Git provenance (read-only)
# ---------------------------------------------------------------------------

def _git(brain: Brain, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", brain.path, *args],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def _provenance(brain: Brain) -> dict:
    if not brain.can_access("admin"):
        return {"head_sha": None, "dirty_files": 0}
    sha = _git(brain, "rev-parse", "--short", "HEAD")
    behind = 0
    if sha:
        n = _git(brain, "rev-list", "--count", f"{sha}..HEAD")
        # rev-list sha..HEAD is 0 by construction; the meaningful number is
        # how far the REMOTE has moved — but a read-only report must not
        # fetch. Report the local working-tree dirtiness instead: the
        # number of uncommitted changes signals "INDEX.md moved, report
        # may be stale" without any network call.
        dirty = _git(brain, "status", "--porcelain")
        behind = len([l for l in (dirty or "").splitlines() if l.strip()])
    return {"head_sha": sha, "dirty_files": behind}


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

def _parse_since(opts: dict) -> datetime:
    since = opts.get("since")
    if since is None:
        return datetime.now(timezone.utc) - timedelta(hours=DEFAULT_SINCE_HOURS)
    if isinstance(since, (int, float)):
        return datetime.now(timezone.utc) - timedelta(hours=float(since))
    text = str(since).strip()
    try:
        return datetime.now(timezone.utc) - timedelta(hours=float(text))
    except ValueError:
        pass
    iso = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise ValueError(
            f"--since expects hours (e.g. 24) or ISO datetime, got: {text!r}"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _band(conf: float | None) -> str:
    if conf is None:
        return "none"
    for upper, name in BANDS:
        if conf < upper:
            return name
    return "auto"


def _load_structural(brain: Brain) -> list[dict]:
    """Structural-gap provider seam (report #7 §3.6).

    The report renders structural findings, it never computes them:
    provider is `graph_engine.communities.structural_gaps(brain)` when
    importable, else a JSON file at $IG_STRUCTURAL_PATH. Returns []
    when absent — the section is then omitted entirely, never empty.
    Contract: list of {"kind": "community"|"god"|"hole", "label": str,
    "node_ids": list[str], "score": float, "hint": str}.
    """
    rows: list = []
    try:
        from .communities import structural_gaps  # type: ignore
        got = structural_gaps(brain)
        if isinstance(got, list) and got:
            return got
    except ImportError:
        pass
    # Importable provider absent or empty (e.g. no community qualifies at
    # min_size on a small brain) → fall back to the JSON file seam.
    if hasattr(brain, "identity"):
        return []  # externally precomputed findings have no graph/ACL provenance
    path = os.environ.get("IG_STRUCTURAL_PATH", "")
    if path and os.path.exists(path):
        try:
            got = json.loads(open(path, encoding="utf-8").read())
            if isinstance(got, list):
                rows = got
        except (OSError, ValueError):
            pass
    return rows


def report_data(brain: Brain, **opts) -> dict:
    """Machine-readable report payload (--json and GET /api/report)."""
    nodes = [n for n in brain.read_nodes() if n.status != "tombstone"]
    edges = [e for e in brain.read_edges() if e.is_current]
    id2node = {n.id: n for n in nodes}
    since = _parse_since(opts)
    top = max(int(opts.get("top") or DEFAULT_TOP), 0)

    # --- deltas since the window start
    new_nodes = [n for n in nodes if _ts(n.created) >= since]
    new_edges = [e for e in edges if _ts(e.valid_from) >= since]
    new_intent = [e for e in new_edges if e.kind in INTENT_KINDS]
    new_tombstones = [n for n in brain.read_nodes()
                      if n.status == "tombstone" and _ts(n.created) >= since]

    # --- edge kinds + confidence bands
    kinds = Counter(e.kind for e in edges)
    bands = Counter(_band(e.confidence) for e in edges)
    only_extends = 0
    node_kinds: dict[str, set[str]] = {}
    for e in edges:
        for nid in (e.source, e.target):
            node_kinds.setdefault(nid, set()).add(e.kind)
    for nid, ks in node_kinds.items():
        if ks == {"extends"}:
            only_extends += 1

    # --- intent review queue: grouped by source, fan-out desc
    by_source: Counter = Counter()
    pending_by_source: Counter = Counter()
    kinds_by_source: dict[str, set[str]] = {}
    for e in edges:
        if e.kind in INTENT_KINDS:
            by_source[e.source] += 1
            kinds_by_source.setdefault(e.source, set()).add(e.kind)
            if e.pending:
                pending_by_source[e.source] += 1
    intent_queue = []
    for sid, fan in by_source.most_common(top):
        node = id2node.get(sid)
        ks = kinds_by_source.get(sid, set())
        intent_queue.append({
            "source": sid,
            "fan_out": fan,
            "pending": pending_by_source.get(sid, 0),
            "kind": "mixed" if len(ks) > 1 else next(iter(ks)),
            "title": _short(node.text) if node else "?",
            "warn": fan >= 3,
        })

    # --- hubs + degree percentiles (same live-edge rule as hygiene)
    deg: Counter = Counter()
    for e in edges:
        deg[e.source] += 1
        deg[e.target] += 1
    hubs = []
    for nid, d in sorted(deg.items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
        node = id2node.get(nid)
        hubs.append({"id": nid, "degree": d,
                     "title": _short(node.text) if node else "?"})
    degs = sorted(deg.get(n.id, 0) for n in nodes)
    percentiles = _pct(degs)

    # --- structural gaps (provider seam; omitted when absent)
    # 'god' rows duplicate the Hubs section — render hole/community only.
    structural = [r for r in _load_structural(brain)
                  if r.get("kind") in ("hole", "community")][:top] if top else []

    # --- hygiene pointer (REUSED, not reimplemented)
    conn = connectivity(brain)
    nd = near_dup_pairs(brain, max_pairs=1)
    near_dup_total = len(near_dup_pairs(brain, max_pairs=10_000)) \
        if opts.get("full_near_dup") else None
    statuses = status_counts(brain)

    # --- research next: derived from the queue and structural rows
    research = []
    for q in intent_queue[:3]:
        research.append(f"resolve {q['fan_out']}x {q['kind']} from "
                        f"{q['source']} — {q['title']}")
    for row in structural[:2]:
        research.append(row.get("hint") or f"bridge {row.get('label', 'gap')}")

    return {
        "generated_at": _now_iso(),
        "brain": str(brain.path) if brain.can_access("admin") else brain.path.name,
        "head_sha": _provenance(brain)["head_sha"],
        "dirty_files": _provenance(brain)["dirty_files"],
        "nodes": len(nodes),
        "edges": len(edges),
        "since": since.isoformat(),
        "deltas": {
            "nodes": len(new_nodes),
            "edges": len(new_edges),
            "intent_edges": len(new_intent),
            "tombstones": len(new_tombstones),
        },
        "kinds": dict(kinds),
        "confidence_bands": dict(bands),
        "extends_only_nodes": only_extends,
        "intent_queue": intent_queue,
        "hubs": hubs,
        "degree_percentiles": percentiles,
        "structural": structural,
        "hygiene": {
            "orphans": len(conn.orphans),
            "islands": len(conn.islands),
            "weak": len(conn.weak),
            "near_dup_pairs": near_dup_total,
            "statuses": dict(statuses),
        },
        "research_next": research[:5],
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _pct(sorted_deg: list[int]) -> dict:
    if not sorted_deg:
        return {"p50": 0, "p90": 0, "p99": 0}
    def at(q: float) -> int:
        idx = min(int(q * len(sorted_deg)), len(sorted_deg) - 1)
        return sorted_deg[idx]
    return {"p50": at(0.50), "p90": at(0.90), "p99": at(0.99)}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_report(brain: Brain, **opts) -> str:
    data = report_data(brain, **opts)
    if opts.get("coverage"):
        from .gaps import analyze_coverage, find_gaps
        cov = analyze_coverage(brain)
        gaps = find_gaps(cov, int(opts.get("min_coverage") or 10))
        data["coverage"] = {"areas": {a.name: a.count for a in cov.areas},
                            "unclassified": cov.unclassified,
                            "gaps": gaps}
    lines: list[str] = []
    lines.append("# BRAIN_REPORT")
    lines.append("")
    lines.append(f"generated: {data['generated_at']} · head {data['head_sha'] or 'n/a'}"
                 f" · dirty files: {data['dirty_files']}"
                 f" (report may lag INDEX.md — regenerate with `ig report --write`)")
    lines.append(f"brain: {data['brain']} · {data['nodes']} nodes / {data['edges']} live edges")
    lines.append("")
    d = data["deltas"]
    lines.append(f"## Since {data['since'][:19].replace('T', ' ')}")
    lines.append(f"nodes +{d['nodes']} · edges +{d['edges']} · "
                 f"intent edges +{d['intent_edges']} · tombstones +{d['tombstones']}")
    lines.append("")
    lines.append("## Edge mix")
    kinds = " · ".join(f"{k} {v}" for k, v in
                       sorted(data["kinds"].items(), key=lambda kv: -kv[1]))
    bands = " · ".join(f"{k} {v}" for k, v in
                       sorted(data["confidence_bands"].items()))
    lines.append(f"kinds: {kinds}")
    lines.append(f"confidence: {bands}")
    share = (100 * data["extends_only_nodes"] / data["nodes"]) if data["nodes"] else 0
    lines.append(f"{data['extends_only_nodes']}/{data['nodes']} nodes "
                 f"({share:.0f}%) hang on `extends` ONLY — the graph is one "
                 "weak edge kind deep")
    lines.append("")
    lines.append("## Intent review queue")
    if data["intent_queue"]:
        lines.append("fan-out by source (contradicts/supersedes, confidence=None — "
                     "fan-out is the false-positive signal; `pending` = held back "
                     "for `ig pending` by the intent cap):")
        for q in data["intent_queue"]:
            warn = " ⚠ HIGH FAN-OUT" if q["warn"] else ""
            held = f" · {q['pending']} pending" if q.get("pending") else ""
            lines.append(f"{q['fan_out']}x [{q['kind']}] {q['source']} "
                         f"\"{q['title']}\"{held}{warn}")
    else:
        lines.append("no intent edges — nothing to review")
    lines.append("")
    lines.append("## Hubs")
    p = data["degree_percentiles"]
    lines.append(f"degree p50 {p['p50']} / p90 {p['p90']} / p99 {p['p99']}")
    for h in data["hubs"][:5]:
        lines.append(f"{h['degree']:>4}  {h['id']}  {h['title']}")
    if data.get("structural"):
        lines.append("")
        lines.append("## Structural gaps")
        for row in data["structural"]:
            lines.append(f"[{row.get('kind', 'hole')}] {row.get('label', '?')} "
                         f"score {row.get('score', 0)} — {row.get('hint', '')}")
    lines.append("")
    lines.append("## Hygiene")
    h = data["hygiene"]
    statuses = h["statuses"]
    prob = statuses.get("probation", 0)
    act = statuses.get("active", 0)
    stale = statuses.get("stale", 0)
    nd = h.get("near_dup_pairs")
    nd_txt = f", {nd} near-dup pairs" if nd is not None else ""
    lines.append(f"orphans {h['orphans']} / islands {h['islands']} / "
                 f"weak {h['weak']}{nd_txt} → ig status / ig near-dup")
    lines.append(f"{prob} probation / {act} active / {stale} stale — the status "
                 "lifecycle is driven by `ig dream --lifecycle`: used + connected "
                 "promotes, unused + weakly connected + old demotes to stale "
                 "(a demotion, never a deletion)")
    if data.get("coverage"):
        c = data["coverage"]
        lines.append("")
        lines.append("## Coverage (opt-in)")
        top_areas = sorted(c["areas"].items(), key=lambda kv: -kv[1])[:5]
        lines.append(" · ".join(f"{k} {v}" for k, v in top_areas)
                     + f" · {c['unclassified']} unclassified"
                     + (f" · gaps: {', '.join(c['gaps'])}" if c["gaps"]
                        else " · no gaps"))
    lines.append("")
    lines.append("## Research next")
    if data["research_next"]:
        for i, r in enumerate(data["research_next"], 1):
            lines.append(f"{i}. {r}")
    else:
        lines.append("nothing queued — ingest new material")
    return "\n".join(lines)

def write_report(brain: Brain, **opts) -> str:
    """Write BRAIN_REPORT.md at the brain root (tracked, renders on GitHub).

    Returns the rendered markdown. The caller decides whether to commit —
    in a cron cycle the write rides the cycle's commit (one commit per
    generation, report #7 §5); from the CLI pass commit=True.
    """
    brain.authorize("admin")
    md = render_report(brain, **opts)
    if not md.strip():
        # A blank generated artifact destroys the workflow value (the
        # Graphify GRAPH_REPORT.md lesson) — fail loudly, never write empty.
        raise RuntimeError("render_report produced an empty report; refusing to write BRAIN_REPORT.md")
    _atomic_write(brain.path / "BRAIN_REPORT.md", md + "\n")
    return md

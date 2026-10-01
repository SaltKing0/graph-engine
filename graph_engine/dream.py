"""The dream pass: what the brain does when nobody is ingesting.

The ingest half of this engine is strong (dedupe, typed edges, provenance,
evals). The other half of a memory system — consolidation — was missing: nothing
promoted, nothing decayed, nothing was ever distilled, `consolidate()` was dead
code. This module is that half, split into three explicitly requested steps so
nothing happens implicitly:

    plan()     — the eligibility report (`ig dream` / `--dry-run`). No writes.
                 Every gate is a flag; the numbers tell you what a pass WOULD do
                 before it does anything.
    refresh()  — deterministic maintenance: re-derive similarity kinds from the
                 stored cosine (suggester edges only — manual edges are
                 user-authored), fold the recall ledger, rebuild INDEX, refresh
                 BRAIN_REPORT. Never destructive.
    distill()  — one abstraction node per community (extractive by default;
                 `summarizer=` / `--llm` swaps in a model). Marked
                 `origin="consolidator"` so the next pass can tell what a pass
                 wrote.
    lifecycle()— promotion and decay from the recall signal: probation → active
                 (used and connected), probation/active → stale (unused, weakly
                 connected, old), stale → active again (used once more). Never
                 destructive: `stale` is a demotion, the node stays in the file.

Reference points (both are the same shape): OpenClaw's dreaming (light/REM/deep,
promotion only through gates, consolidation turn that merges duplicates and
retires superseded entries) and the Hermes curator (deterministic transitions
that never delete, pinned/cron-referenced entries protected, LLM consolidation
OFF by default). The gates are DERIVED FROM THE LIVE DISTRIBUTION, not copied
from those systems — see `lifecycle_plan` for the measurement behind each
number. The merge axis (97 pairs in the review band) is a REVIEW list, not an
auto-merge: the top pairs are demonstrably related-but-distinct.
"""

from __future__ import annotations

import collections
import datetime
import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from typing import Callable

from .brain import Brain, Edge, Node
from .communities import analyze_communities
from .hygiene import connectivity, near_dup_pairs
from .intent import INTENT_KINDS
from .similarity import cosine

# --- Lifecycle gates (measured 2026-09-18 on the live brain, not guessed) -----
# recall distribution: 5 nodes with recall_count > 0, all of them degree >= 2;
# degree: min 2 / p25 3 / median 5 / p75 7; age: median 11.9 d, oldest 26.7 d.
# So: "used at least once AND connected" is the honest promotion bar at this
# size (a gate of recall >= 3 would have promoted exactly 0 nodes), the corpus
# minimum degree 2 means "not an island", 30 days is a month of silence, and
# degree <= 2 is the weakest tail (24 nodes). Decay cannot fire before the
# corpus is 30 days old — that is the honest outcome, not a reason to lower it.
PROMOTE_MIN_RECALL = 1
PROMOTE_MIN_DEGREE = 2
DECAY_DAYS = 30
DECAY_MAX_DEGREE = 2
STALE_STATUS = "stale"

# Similarity kinds are re-derived from the stored cosine with the band rule the
# suggester uses (`suggester.py`): >= 0.75 same topic, below that builds-on.
SIMILAR_BAND = 0.75
# Communities of at least this size are distillable; a pass writes at most
# `DREAM_MAX_DISTILL` summary nodes so one run stays reviewable.
DREAM_MIN_COMMUNITY = 10
DREAM_MAX_DISTILL = 10
# Members a summary links to (strongest by degree inside the community).
DREAM_MEMBERS_PER_SUMMARY = 5
SUMMARY_TAG = "community-summary"


@dataclass
class DreamPlan:
    """What a pass WOULD do under the given gates (nothing written)."""

    nodes: int = 0
    edges: int = 0
    promotion_candidates: list[str] = field(default_factory=list)
    decay_candidates: list[str] = field(default_factory=list)
    merge_candidates: list[tuple[str, str, float]] = field(default_factory=list)
    distill_candidates: list[tuple[int, int]] = field(default_factory=list)  # (cid, size)
    refresh: dict = field(default_factory=dict)

    def render(self) -> str:
        lines = ["# DREAM PLAN (dry run — nothing written)", ""]
        lines.append(f"brain: {self.nodes} live nodes · {self.edges} live edges")
        lines.append("")
        lines.append(f"## Promotion candidates: {len(self.promotion_candidates)}")
        lines.append(f"## Decay candidates: {len(self.decay_candidates)}")
        lines.append(f"## Merge candidates (review, never auto): {len(self.merge_candidates)}")
        for a, b, score in self.merge_candidates[:5]:
            lines.append(f"  {score:.3f}  {a!r}")
            lines.append(f"           {b!r}")
        lines.append(f"## Distill candidates: {len(self.distill_candidates)} communities")
        for cid, size in self.distill_candidates[:10]:
            lines.append(f"  C{cid}  size {size}")
        lines.append("## Refresh")
        for key, value in sorted(self.refresh.items()):
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)


def node_age_days(node: Node, now: "datetime.datetime | None" = None) -> float:
    """Age in days from `created`; 0.0 when the timestamp is unparseable."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        t = datetime.datetime.fromisoformat((node.created or "").replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (now - t).total_seconds() / 86400


def _live_graph(brain: Brain) -> tuple[dict[str, Node], collections.Counter, list[Edge]]:
    """Live nodes (no tombstones) + degree over live edges + those edges."""
    nodes = {n.id: n for n in brain.read_nodes() if n.status != "tombstone"}
    edges = [e for e in brain.read_edges(include_rejected=True)
             if not e.pending and not e.rejected and e.valid_to is None]
    degree: collections.Counter = collections.Counter()
    for e in edges:
        degree[e.source] += 1
        degree[e.target] += 1
    return nodes, degree, edges


def lifecycle_plan(brain: Brain, *, min_recall: int = PROMOTE_MIN_RECALL,
                   min_degree: int = PROMOTE_MIN_DEGREE,
                   stale_days: int = DECAY_DAYS,
                   max_degree: int = DECAY_MAX_DEGREE) -> dict:
    """Who the lifecycle pass would touch under these gates. Read-only.

    Gates are data-derived (measured 2026-09-18 on the live brain), not copied
    from another system: `min_recall=1` because the ledger is young and "used
    once and connected" is the honest bar at this size; `min_degree=2` is the
    corpus minimum (every live node has >= 2 edges, so it means "not an island");
    `stale_days=30` is a month of silence; `max_degree=2` is the weakest tail.
    """
    nodes, degree, _ = _live_graph(brain)
    summaries = _summary_ids(brain)
    now = datetime.datetime.now(datetime.timezone.utc)

    def used(nid: str) -> bool:
        return getattr(nodes[nid], "recall_count", 0) >= min_recall

    promote, revive, decay = [], [], []
    for nid, n in nodes.items():
        if nid in summaries:
            continue          # derived nodes: a pass never re-grades its own output
        deg = degree.get(nid, 0)
        if n.status == "probation" and used(nid) and deg >= min_degree:
            promote.append(nid)
        elif n.status == STALE_STATUS and used(nid) and deg >= min_degree:
            revive.append(nid)   # decay is reversible: being used again revives
        elif (n.status in ("probation", "active")
              and getattr(n, "recall_count", 0) == 0
              and deg <= max_degree
              and node_age_days(n, now) >= stale_days):
            decay.append(nid)
    return {"promote": promote, "revive": revive, "decay": decay,
            "gates": {"min_recall": min_recall, "min_degree": min_degree,
                      "stale_days": stale_days, "max_degree": max_degree}}


def lifecycle(brain: Brain, *, min_recall: int = PROMOTE_MIN_RECALL,
              min_degree: int = PROMOTE_MIN_DEGREE, stale_days: int = DECAY_DAYS,
              max_degree: int = DECAY_MAX_DEGREE, dry_run: bool = False,
              commit: bool = True) -> dict:
    """Promotion and decay: the status lifecycle, one commit, never destructive.

    ROADMAP_CASE `roadmap-dream-lifecycle`.

    probation → active (used and connected), active/probation → stale (unused,
    weakly connected, old), stale → active again (used once more). Nothing is
    deleted and nothing leaves the file: `stale` is a demotion, not a removal —
    it takes the node out of the promotion pool and marks it for the report.
    """
    plan_ = lifecycle_plan(brain, min_recall=min_recall, min_degree=min_degree,
                           stale_days=stale_days, max_degree=max_degree)
    promote, revive, decay = plan_["promote"], plan_["revive"], plan_["decay"]

    if not dry_run and (promote or revive or decay):
        nodes = {n.id: n for n in brain.read_nodes()}
        for nid in promote + revive:
            nodes[nid].status = "active"        # used + connected = consolidated
            brain.write_node(nodes[nid])
        for nid in decay:
            nodes[nid].status = STALE_STATUS    # demotion, never a removal
            brain.write_node(nodes[nid])
        brain.rebuild_index()
        if commit:
            brain.commit_and_push(
                f"dream lifecycle: {len(promote)} promoted, {len(revive)} revived, "
                f"{len(decay)} stale (recall >= {min_recall} and degree >= "
                f"{min_degree}; unused, degree <= {max_degree}, age >= {stale_days}d)")

    return {"promoted": len(promote), "revived": len(revive), "staled": len(decay),
            "candidates": {"promote": len(promote), "revive": len(revive),
                           "decay": len(decay)},
            "dry_run": dry_run}


def plan(brain: Brain, *, min_recall: int = PROMOTE_MIN_RECALL,
         min_degree: int = PROMOTE_MIN_DEGREE, stale_days: int = DECAY_DAYS,
         min_community: int = DREAM_MIN_COMMUNITY,
         merge_band: tuple[float, float] = (0.78, 0.92)) -> DreamPlan:
    """Eligibility report for every axis. Read-only."""
    nodes, degree, edges = _live_graph(brain)
    life = lifecycle_plan(brain, min_recall=min_recall, min_degree=min_degree,
                          stale_days=stale_days)
    promotion = life["promote"] + life["revive"]
    decay = life["decay"]

    merges = [(f"{nodes[p.a].text.split(chr(10))[0][:46]}"
               if p.a in nodes else p.a,
               f"{nodes[p.b].text.split(chr(10))[0][:46]}"
               if p.b in nodes else p.b, p.score)
              for p in near_dup_pairs(brain, lo=merge_band[0], hi=merge_band[1])]
    rep = analyze_communities(brain, min_size=min_community, top=DREAM_MAX_DISTILL,
                              exclude_ids=_summary_ids(brain))
    distill = [(c.id, c.size) for c in rep.communities if c.size >= min_community]

    refresh = refresh_plan(brain)
    return DreamPlan(nodes=len(nodes), edges=len(edges),
                     promotion_candidates=promotion, decay_candidates=decay,
                     merge_candidates=merges, distill_candidates=distill,
                     refresh=refresh)


def refresh_plan(brain: Brain) -> dict:
    """What `refresh()` would change (read-only)."""
    from .recall import read_ledger
    edges = [e for e in brain.read_edges(include_rejected=True)
             if not e.pending and not e.rejected and e.valid_to is None]
    mismatched = [e for e in edges
                  if e.origin == "suggester" and e.confidence is not None
                  and e.kind in ("extends", "similar")
                  and e.kind != _expected_kind(e.confidence)]
    conn = connectivity(brain)
    return {
        "kind_mismatches": len(mismatched),
        "islands": len(conn.islands),
        "orphans": len(conn.orphans),
        "recall_ledger_entries": len(read_ledger(brain)),
    }


def _expected_kind(confidence: float) -> str:
    return "similar" if confidence >= SIMILAR_BAND else "extends"


def refresh(brain: Brain, *, dry_run: bool = False, commit: bool = True) -> dict:
    """Deterministic maintenance. Never destructive, never touches manual edges.

    1. Re-derive the kind of SUGGESTER similarity edges from the stored cosine
       (the band rule). Manual edges keep whatever kind the user chose — that is
       the whole point of the provenance field.
    2. Fold the recall ledger into the node counters (`recall.aggregate`).
    3. Rebuild INDEX.md and regenerate the tracked BRAIN_REPORT.md.
    One commit for the whole pass.
    """
    from .recall import aggregate as aggregate_recalls
    from .report import write_report

    changed = []
    edges = brain.read_edges(include_rejected=True)
    for edge in edges:
        if (edge.origin == "suggester" and edge.confidence is not None
                and edge.kind in ("extends", "similar")
                and edge.valid_to is None and not edge.rejected):
            expected = _expected_kind(edge.confidence)
            if edge.kind != expected:
                changed.append((edge.id, edge.kind, expected))
                if not dry_run:
                    edge.kind = expected
    if changed and not dry_run:
        brain.write_edges(edges)

    recall_res = {"nodes": 0, "recalls": 0}
    if not dry_run:
        recall_res = aggregate_recalls(brain, commit=False)
        brain.rebuild_index()
        try:
            write_report(brain, write=True)
        except Exception:
            # A report failure must never fail the pass (same rule as the cycle).
            pass
        if commit:
            brain.commit_and_push(
                f"dream refresh: {len(changed)} kind(s) re-derived, "
                f"{recall_res['recalls']} recall(s) folded, INDEX + report refreshed")

    return {"kind_changes": len(changed), "kinds": changed[:10],
            "recall_nodes": recall_res["nodes"], "recalls": recall_res["recalls"],
            "dry_run": dry_run}


def _summary_ids(brain: Brain) -> set[str]:
    """Ids of nodes a previous pass wrote — excluded from the next partition."""
    return {n.id for n in brain.read_nodes() if SUMMARY_TAG in (n.tags or [])}


def distill(brain: Brain, *, min_size: int = DREAM_MIN_COMMUNITY,
            limit: int = DREAM_MAX_DISTILL, members_per_summary: int = DREAM_MEMBERS_PER_SUMMARY,
            summarizer: Callable[[str], str] | None = None,
            dry_run: bool = False, commit: bool = True) -> dict:
    """One abstraction node per community — the actual "dreaming" step.

    Extractive by default (deterministic, free, reproducible): the digest names
    the community size, its dominant taxonomy area, the internal edge mix and its
    strongest members. `summarizer=` swaps in a model (the CLI wires `--llm`);
    the digest is then handed to it as the prompt, so the model sees the same
    evidence the extractive path uses.

    Idempotent: the summary id is derived from the member set, so a second pass
    over an unchanged community finds the node and skips it. Summary nodes are
    `status="active"` (a distillation is a deliberate consolidation act) and
    carry the `community-summary` tag; their edges are `origin="consolidator"`.
    """
    nodes = {n.id: n for n in brain.read_nodes() if n.status != "tombstone"}
    edges = [e for e in brain.read_edges(include_rejected=True)
             if not e.pending and not e.rejected and e.valid_to is None]
    degree: collections.Counter = collections.Counter()
    for e in edges:
        degree[e.source] += 1
        degree[e.target] += 1

    rep = analyze_communities(brain, min_size=min_size, top=limit, with_members=True,
                              exclude_ids=_summary_ids(brain))
    candidates = [c for c in rep.communities if c.size >= min_size][:limit]

    summaries = 0
    new_edges: list[Edge] = []
    for community in candidates:
        members = [m for m in community.members if m in nodes]
        if not members:
            continue
        summary_id = _summary_id(members)
        if summary_id in nodes:
            continue  # already distilled (idempotent)
        digest = _community_digest(brain, members, nodes, degree, edges, community.label)
        text = summarizer(digest) if summarizer is not None else digest
        summaries += 1
        if dry_run:
            continue
        brain.write_node(Node(id=summary_id, text=text, source="consolidator",
                              tags=[SUMMARY_TAG], ntype="semantic", status="active"))
        nodes[summary_id] = Node(id=summary_id, text=text)
        strongest = sorted(members, key=lambda m: (-degree.get(m, 0), m))[:members_per_summary]
        for member in strongest:
            new_edges.append(Edge(source=summary_id, target=member, kind="extends",
                                  pending=False, origin="consolidator"))

    if new_edges and not dry_run:
        all_edges = brain.read_edges(include_rejected=True) + new_edges
        brain.write_edges(all_edges)
        brain.rebuild_index()
        if commit:
            brain.commit_and_push(
                f"dream distill: {summaries} community summar{'y' if summaries == 1 else 'ies'}, "
                f"{len(new_edges)} consolidator edges")

    return {"summaries": summaries, "edges": len(new_edges),
            "communities": len(candidates), "used_llm": summarizer is not None,
            "dry_run": dry_run}


def _community_digest(brain: Brain, member_ids: list[str], nodes: dict[str, Node],
                      degree: collections.Counter, edges: list[Edge],
                      dominant_area: str) -> str:
    """Deterministic (extractive) digest of a community — the default summary."""
    member_set = set(member_ids)
    members = [nodes[m] for m in member_ids if m in nodes]
    hubs = sorted(member_ids, key=lambda m: -degree.get(m, 0))[:8]
    # The edge-mix census counts every non-rejected edge (pending included):
    # it describes what the community looks like, it is not a validity claim.
    census_edges = brain.read_edges(include_rejected=True)
    kinds = collections.Counter(e.kind for e in census_edges
                                if e.source in member_set or e.target in member_set)
    titles = [nodes[h].text.split("\n")[0][:90] for h in hubs if h in nodes]
    mix = ", ".join(f"{k} {v}" for k, v in kinds.most_common(6)) or "none yet"
    lines = [
        f"Community abstraction ({len(members)} nodes, dominant area: {dominant_area}).",
        f"Edge mix inside the community: {mix}.",
        "Strongest members:",
    ]
    lines += [f"- {t}" for t in titles[:5]]
    lines.append("This node is a consolidator summary: it exists to make the "
                 "community retrievable as a unit, not to replace its members.")
    return "\n".join(lines)


def _summary_id(member_ids: list[str]) -> str:
    """Deterministic id from the member set: re-running a pass is idempotent."""
    digest = hashlib.sha1("|".join(sorted(member_ids)).encode("utf-8")).hexdigest()
    return "c" + digest[:11]
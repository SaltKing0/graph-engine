"""Manual near-duplicate consolidation (`ig merge`).

Consolidates two closely related nodes into one: all edges of the node
being removed are redirected to the survivor (identical accepted assertions
deduplicated, newly created self-loops removed), the text is appended to
preserve information, and the removed node is marked as a tombstone (never
hard-deleted — the graph remains an append-only history). INDEX.md is rebuilt
and everything is written in ONE commit.

Audit #3/#9/#41 fixes:
- The deletee is tombstoned instead of being set to probation, and its file
  is no longer deleted before the edge rewrite (half-written state
  on a crash mid-merge).
- Edges with intent semantics (`supersedes`, `contradicts`, `continues`,
  `replaces`, …) are NOT blindly redirected: a deletee→X `supersedes`
  edge says "the deletee supersedes X" — after the merge the survivor is the
  continuation of the deletee's content, so the edge is redirected to
  survivor→X ONLY if the direction stays semantically valid.
  For supersedes/replaces/contradicts (deletee as source) the edge
  is invalidated instead (valid_to set) rather than making a possibly
  wrong statement about the survivor; extends/similar/linked edges
  are direction-neutral enough for a redirect.
- Merge provenance: the merge commit and the survivor node document
  the deletee ID and timestamp; the deletee's status remains traceable
  as a tombstone.

This is the manual complement to automatic ingest dedup (cos >= 0.92):
near-duplicates in the ~0.78–0.92 range stay below the auto threshold and
need this consolidation. Destructive — use with care, ideally after
a dry run on a brain copy.
"""
from __future__ import annotations

from .write_guard import write_operation

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .brain import Brain, Edge

# Intent edges with directed semantics: a redirect deletee→X to
# survivor→X would invert the statement (Audit #9). They are invalidated
# instead of redirected. Direction-neutral kinds (similar/extends/same_as/…)
# are redirected normally.
DIRECTIONAL_KINDS = frozenset({
    "supersedes", "ersetzt", "contradicts", "replaces", "obsoletes",
    "korrigiert", "widerspricht",
})


@dataclass
class MergeResult:
    survivor: str
    deletee: str
    edges_redirected: int
    edges_removed: int  # redirected self-loops + duplicate assertions
    edges_invalidated: int = 0  # directed intent edges (not redirectable)
    redirected_ids: list[str] = field(default_factory=list)
    invalidated_ids: list[str] = field(default_factory=list)


def _edge_identity(edge: Edge, source: str, target: str) -> str:
    """Compare complete assertions after redirect, preserving review/history IDs."""
    record = edge.to_dict()
    record.update(source=source, target=target)
    # Only ordinary accepted assertions may collapse. Inbox items, explicit
    # reviews and history records have individually addressable decision IDs,
    # even when all their other metadata happens to match.
    if not (edge.pending or edge.rejected or edge.is_invalidated
            or edge.valid_to is not None or edge.invalidated_by is not None
            or edge.replacement is not None or edge.superseded_by is not None
            or edge.reviewed_at is not None or edge.reviewed_by is not None
            or edge.kind in ("fact", "fact_replacement")):
        record.pop("id")
    # Includes kind, ordered endpoints, validity, confidence and all serialized
    # provenance. Canonicalize nested dicts as well as the top-level fields.
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


def _redirect_edges(edges: list[Edge], survivor: str, deletee: str,
                    now_iso: str) -> tuple[list[Edge], int, int, int, list[str], list[str]]:
    """Preserve untouched records; deduplicate only redirected assertions.

    Directed intent edges (DIRECTIONAL_KINDS) with the deletee as source are
    invalidated (valid_to set) instead of redirected — the survivor has not
    necessarily inherited the statement "supersedes X" (Audit #9).
    """
    new_edges: list[Edge] = []
    # Reserve untouched identities first so a redirected duplicate never
    # replaces an existing survivor edge just because it appears earlier.
    seen = {_edge_identity(e, e.source, e.target) for e in edges
            if deletee not in (e.source, e.target)}
    removed = 0
    redirected = 0
    invalidated = 0
    redirected_ids: list[str] = []
    invalidated_ids: list[str] = []
    for e in edges:
        if deletee not in (e.source, e.target) or e.kind in ("fact", "fact_replacement"):
            # Entity identities cannot be text-merged (guard below). Preserve
            # all fact windows/evidence and each replacement decision's unique
            # identity when unrelated semantic notes are merged. Untouched
            # relationships also keep their order, IDs and metadata verbatim.
            new_edges.append(e)
            continue
        s, t = e.source, e.target
        if s == deletee or t == deletee:
            if e.kind in DIRECTIONAL_KINDS and s == deletee:
                # The statement no longer holds about the survivor — historicize the edge.
                if not e.is_invalidated:
                    e.invalidate(now_iso)
                    invalidated += 1
                    invalidated_ids.append(e.id)
                new_edges.append(e)
                continue
            if s == deletee:
                s = survivor
                redirected += 1
            if t == deletee:
                t = survivor
                redirected += 1
            redirected_ids.append(e.id)
        if s == t:  # self-loop after merge
            removed += 1
            continue
        key = _edge_identity(e, s, t)
        if key in seen:  # identical assertion after redirect
            removed += 1
            continue
        seen.add(key)
        e.source, e.target = s, t
        new_edges.append(e)
    return new_edges, removed, redirected, invalidated, redirected_ids, invalidated_ids


def _drop_vector(brain: Brain, deletee: str) -> None:
    vectors = brain.read_vectors()
    if deletee in vectors:
        del vectors[deletee]
        brain.write_vectors(vectors)


@write_operation
def merge_nodes(
    brain: Brain,
    survivor_id: str,
    deletee_id: str,
    commit: bool = True,
    embedder=None,
) -> MergeResult:
    """Consolidates the deletee into the survivor. Destructive; one commit.

    embedder (optional): when given, the survivor vector is recomputed after
    the text append — without it the old vector would remain and search
    would dedupe/rank against the PRE-merge text (audit finding
    "survivor vector stale"). The CLI always passes the engine embedder.
    """
    brain.authorize("admin")
    if survivor_id == deletee_id:
        raise ValueError("Survivor and deletee are identical.")
    # Git mode: repo existence + fresh pull BEFORE the mutation — otherwise
    # the merge can work on a stale state and the history diverges
    # (audit finding "merge_nodes makes no pull()").
    brain.ensure_ready()
    brain.pull()
    from .decision_memory import check_merge
    check_merge(brain, {survivor_id, deletee_id})
    nodes = {n.id: n for n in brain.read_nodes()}
    if survivor_id not in nodes:
        raise ValueError(f"Node not found: {survivor_id}")
    if deletee_id not in nodes:
        raise ValueError(f"Node not found: {deletee_id}")
    survivor, deletee = nodes[survivor_id], nodes[deletee_id]
    if survivor.ntype == "entity" or deletee.ntype == "entity":
        raise ValueError("Entity identities cannot be merged as near-duplicate text; use explicit aliases.")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    from .access import derivation_parents, provenance_allowed
    all_edges = brain.read_edges(include_rejected=True)
    previous_parents = derivation_parents(nodes, all_edges)
    survivor.text = (
        survivor.text.rstrip()
        + f"\n\n[consolidated from {deletee_id} on {now_iso}: {deletee.text.strip()}]"
    )
    survivor.derived_from = sorted(previous_parents.get(survivor_id, set()) | {deletee_id})

    # Redirect + deduplicate edges — BEFORE deleting the deletee file
    # (Audit #3: previously the node file was unlinked first; a crash
    # between unlink and edge rewrite left a half-merged state with
    # dangling edges pointing to a no-longer-existing node).
    # Keep unrelated dismissed suggestions in place for undo. Decisions about
    # the deleted node cannot be restored after consolidation.
    edges = deepcopy([e for e in all_edges
                      if not (e.rejected and deletee_id in (e.source, e.target))])
    new_edges, removed, redirected, invalidated, redirected_ids, invalidated_ids = \
        _redirect_edges(edges, survivor_id, deletee_id, now_iso)
    planned_edges = new_edges
    parents = derivation_parents(nodes, planned_edges)
    affected = {survivor_id, deletee_id} | {
        nid for nid in parents if parents[nid] != previous_parents.get(nid, set())}
    saved_sources = {nid: set(nodes[nid].derived_from) for nid in affected if nid in nodes}
    for nid, sources in saved_sources.items():
        nodes[nid].derived_from = sorted(sources | previous_parents.get(nid, set()))
    # Recover legacy input metadata before inferring lineage from the new edges:
    # an extraction whose edge disappears is still a complete derived record.
    parents = derivation_parents(nodes, planned_edges)
    # Retain legacy dependencies even when their evidence is redirected. Check
    # the entire affected lineage before changing files, including raw Brain
    # callers that may enable protected access later.
    for nid, sources in previous_parents.items():
        parents.setdefault(nid, set()).update(sources)
    if any(not provenance_allowed(nid, nodes, parents, lambda _: True)
           for nid in affected if nid in nodes):
        raise ValueError("Merge would create cyclic or unavailable provenance")
    # Persist the checked lineage before its evidence edges disappear. Crashes
    # can retain extra restrictions, but cannot remove source permissions.
    for nid in sorted(affected - {survivor_id}):
        node = nodes.get(nid)
        if node is not None and parents[nid] - saved_sources[nid]:
            node.derived_from = sorted(parents[nid])
            brain.write_node(node)
    brain.write_edges(planned_edges)

    # Merge text (information preservation) — with merge provenance (Audit #41)
    survivor.derived_from = sorted(parents[survivor_id])
    brain.write_node(survivor)

    # Tombstone the deletee (never hard-delete — Audit #3: previously unlink
    # + status loss, dangling edges could point to a "living" probation node)
    brain.tombstone_node(deletee_id)

    # Remove vector
    _drop_vector(brain, deletee_id)

    # Refresh the survivor vector: the text has grown, the old vector
    # represents the pre-merge text (audit finding: "survivor vector stale").
    if embedder is not None:
        normalized = " ".join(survivor.text.lower().split())
        from .vector_cache import model_identity
        brain.cache_vectors({survivor_id: list(embedder.embed(normalized))},
                            embedder_key=model_identity(embedder))

    # Rebuild INDEX
    brain.rebuild_index()

    if commit:
        try:
            brain.commit_and_push(
                f"merge: {deletee_id} consolidated into {survivor_id} "
                f"({redirected} redirected, {invalidated} invalidated, {removed} removed)")
        except Exception as exc:
            # Audit #31: preserve local writes/commits on sync failure,
            # heal the derived index and raise an actionable error.
            try:
                brain.rebuild_index()
            except Exception:
                pass
            raise RuntimeError(
                "merge applied but commit/push failed — changes remain local and may "
                "already be committed. Inspect git status/log before retrying sync. "
                f"{exc}") from exc

    return MergeResult(
        survivor=survivor_id,
        deletee=deletee_id,
        edges_redirected=redirected,
        edges_removed=removed,
        edges_invalidated=invalidated,
        redirected_ids=redirected_ids,
        invalidated_ids=invalidated_ids,
    )

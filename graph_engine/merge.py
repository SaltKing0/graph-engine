"""Manual near-duplicate consolidation (`ig merge`).

Consolidates two closely related nodes into one: all edges of the node
being removed are redirected to the survivor (deduplicated, no
self-loops), the text is appended to preserve information, and the
removed node is marked as a tombstone (never hard-deleted — the
graph remains an append-only history). INDEX.md is rebuilt and everything
is written in ONE commit.

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

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .brain import Brain

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
    edges_removed: int  # self-loops + duplicate pairs
    edges_invalidated: int = 0  # directed intent edges (not redirectable)
    redirected_ids: list[str] = field(default_factory=list)
    invalidated_ids: list[str] = field(default_factory=list)


def _redirect_edges(edges: list, survivor: str, deletee: str,
                    now_iso: str) -> tuple[list, int, int, int, list[str], list[str]]:
    """Redirect the deletee's edges to the survivor; removes self-loops + duplicates.

    Directed intent edges (DIRECTIONAL_KINDS) with the deletee as source are
    invalidated (valid_to set) instead of redirected — the survivor has not
    necessarily inherited the statement "supersedes X" (Audit #9).
    """
    new_edges: list = []
    seen: set[tuple] = set()
    removed = 0
    redirected = 0
    invalidated = 0
    redirected_ids: list[str] = []
    invalidated_ids: list[str] = []
    for e in edges:
        s, t = e.source, e.target
        if s == deletee or t == deletee:
            if e.kind in DIRECTIONAL_KINDS and s == deletee:
                # The statement no longer holds about the survivor — historicize the edge.
                if e.valid_to is None:
                    e.valid_to = now_iso
                    invalidated += 1
                    invalidated_ids.append(e.id)
                else:
                    removed += 1
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
        key = tuple(sorted((s, t)))
        if key in seen:  # duplicate pair (survivor already had that target)
            removed += 1
            continue
        seen.add(key)
        e.source, e.target = s, t
        new_edges.append(e)
    return new_edges, removed, redirected, invalidated, redirected_ids, invalidated_ids


def _drop_vector(brain: Brain, deletee: str) -> None:
    vec_file: Path = brain.path / "vectors.jsonl"
    if not vec_file.exists():
        return
    lines = [l for l in vec_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    keep = [l for l in lines if json.loads(l).get("id") != deletee]
    brain.write_vectors({json.loads(l)["id"]: json.loads(l)["vec"] for l in keep})


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
    if survivor_id == deletee_id:
        raise ValueError("Survivor and deletee are identical.")
    # Git mode: repo existence + fresh pull BEFORE the mutation — otherwise
    # the merge can work on a stale state and the history diverges
    # (audit finding "merge_nodes makes no pull()").
    brain.ensure_ready()
    brain.pull()
    nodes = {n.id: n for n in brain.read_nodes()}
    if survivor_id not in nodes:
        raise ValueError(f"Node not found: {survivor_id}")
    if deletee_id not in nodes:
        raise ValueError(f"Node not found: {deletee_id}")
    survivor, deletee = nodes[survivor_id], nodes[deletee_id]
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Redirect + deduplicate edges — BEFORE deleting the deletee file
    # (Audit #3: previously the node file was unlinked first; a crash
    # between unlink and edge rewrite left a half-merged state with
    # dangling edges pointing to a no-longer-existing node).
    edges = brain.read_edges(include_rejected=False)
    new_edges, removed, redirected, invalidated, redirected_ids, invalidated_ids = \
        _redirect_edges(edges, survivor_id, deletee_id, now_iso)
    # Keep unrelated dismissed suggestions available for undo. Decisions about
    # the deleted node cannot be restored after consolidation.
    rejected = [e for e in brain.read_edges(include_rejected=True)
                if e.rejected and deletee_id not in (e.source, e.target)]
    brain.write_edges(new_edges + rejected)

    # Merge text (information preservation) — with merge provenance (Audit #41)
    survivor.text = (
        survivor.text.rstrip()
        + f"\n\n[consolidated from {deletee_id} on {now_iso}: {deletee.text.strip()}]"
    )
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
        vecs = brain.read_vectors()
        vecs[survivor_id] = list(embedder.embed(normalized))
        brain.write_vectors(vecs)

    # Rebuild INDEX
    brain.rebuild_index()

    if commit:
        try:
            brain.commit_and_push(
                f"merge: {deletee_id} consolidated into {survivor_id} "
                f"({redirected} redirected, {invalidated} invalidated, {removed} removed)")
        except Exception:
            # Audit #31: the merge mutations are on disk but uncommitted —
            # heal the derived index and raise an actionable error.
            try:
                brain.rebuild_index()
            except Exception:
                pass
            raise RuntimeError(
                "merge applied but commit/push failed — changes are on disk "
                "UNCOMMITTED. Recovery: `git -C <brain> add -A && git commit` "
                "or retry the merge (it is idempotent against the merged state).") from None

    return MergeResult(
        survivor=survivor_id,
        deletee=deletee_id,
        edges_redirected=redirected,
        edges_removed=removed,
        edges_invalidated=invalidated,
        redirected_ids=redirected_ids,
        invalidated_ids=invalidated_ids,
    )

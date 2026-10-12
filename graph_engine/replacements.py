"""Evidence-backed replacement review, stored alongside edges in one atomic file.

Proposals are review records, never graph relations. Extraction cannot resolve
one. Git commits retain each decision; undo only restores its exact before-state
while the affected facts and all supporting nodes remain unchanged and live.
"""
from __future__ import annotations

from .brain import Brain, Edge, _now_iso

KIND = "fact_replacement"


def plan_replacement(edges: list[Edge], old: Edge, new: Edge, *, reason: str,
                     basis: str, effective_at: str | None) -> tuple[Edge | None, bool]:
    """Plan without writes; an old/new pair has one immutable review identity."""
    prior = next((e for e in edges if e.kind == KIND and e.replacement
                  and e.replacement["old_fact_id"] == old.id
                  and e.replacement["new_fact_id"] == new.id), None)
    if prior:
        return prior, False
    if (old.kind != "fact" or new.kind != "fact" or old.source != new.source
            or old.predicate != new.predicate or old.target == new.target
            or old.pending or old.rejected or old.is_invalidated or old.superseded_by
            or new.rejected or new.is_invalidated or new.superseded_by):
        return None, False
    # A bounded historical claim that ended before this event cannot conflict.
    if effective_at and old.valid_to and old.valid_to <= effective_at:
        return None, False
    old_start = (old.extracted_validity or {}).get("valid_from")
    if effective_at and old_start and effective_at <= old_start:
        return None, False  # Do not manufacture an empty/backwards interval.
    if old_start and new.valid_to and new.valid_to <= old_start:
        return None, False
    evidence = [dict(e) for e in old.evidence]
    evidence.extend(dict(e) for e in new.evidence if e not in evidence)
    proposal = Edge(old.source, new.target, KIND, origin="entity-extractor",
                    evidence=evidence, replacement=dict(
                        old_fact_id=old.id, new_fact_id=new.id, reason=reason,
                        basis=basis, effective_at=effective_at))
    edges.append(proposal)
    return proposal, True


def _live_and_authorized(brain: Brain, edges: list[Edge]) -> bool:
    ids = {nid for e in edges for nid in
           [e.source, e.target, *(s.get("node_id") for s in e.evidence)]}
    # Complete authorization precedes every mutation, including rejection/undo.
    for nid in ids:
        if not isinstance(nid, str):
            return False
        brain.authorize("write", nid)
        node = brain.read_node(nid)
        if node is None or node.status == "tombstone":
            return False
    return True


def resolve_replacement(brain: Brain, edges: list[Edge], proposal: Edge, *,
                        accept: bool = False, undo: bool = False) -> Edge | None:
    meta = proposal.replacement or {}
    by_id = {e.id: e for e in edges}
    old, new = (by_id.get(meta.get(key)) for key in ("old_fact_id", "new_fact_id"))
    if old is None or new is None or not _live_and_authorized(brain, [proposal, old, new]):
        return None
    if (old.kind != "fact" or new.kind != "fact" or old.source != new.source
            or old.predicate != new.predicate or old.target == new.target):
        return None
    if proposal.is_invalidated or (undo and proposal.pending) or (not undo and (not proposal.pending or proposal.rejected)):
        return None
    if undo:
        decision = meta.get("decision")
        if not proposal.rejected:
            if not decision or [old.to_dict(), new.to_dict()] != decision["after"]:
                return None  # A later forget/review/extraction must never be undone.
            restored = [Edge(**row) for row in decision["before"]]
            for fact in restored:
                edges[edges.index(by_id[fact.id])] = fact
        elif old.is_invalidated or new.is_invalidated or old.rejected or new.rejected:
            return None
        meta.pop("decision", None)
        proposal.pending, proposal.rejected = True, False
        proposal.reviewed_at = None
    else:
        if old.is_invalidated or new.is_invalidated or old.rejected or new.rejected or old.superseded_by or new.superseded_by:
            return None
        if accept:
            if old.pending:
                return None
            effective_at = meta["effective_at"]
            old_start = (old.extracted_validity or {}).get("valid_from")
            if ((new.extracted_validity or {}).get("valid_from") != effective_at
                    or (effective_at and old_start and effective_at <= old_start)
                    or (effective_at and old.valid_to and old.valid_to <= effective_at)):
                return None  # The reviewed claims/window must still match the proposal.
            before = [old.to_dict(), new.to_dict()]
            reviewed_at = _now_iso()
            # Unknown event date: retire the assertion at review time without
            # inventing a real-world valid_to. Known dates close that interval;
            # future replacements therefore leave the old fact live until then.
            if effective_at is None:
                old.invalidate(reviewed_at)
            else:
                old.valid_to = min(old.valid_to, effective_at) if old.valid_to else effective_at
            old.superseded_by = proposal.id
            old.reviewed_at = new.reviewed_at = reviewed_at
            old.reviewed_by = new.reviewed_by = proposal.id
            new.pending = False
            meta["decision"] = dict(before=before, after=[old.to_dict(), new.to_dict()])
        proposal.pending, proposal.rejected = False, not accept
        proposal.reviewed_at = _now_iso()
    brain.write_edges(edges)
    return proposal

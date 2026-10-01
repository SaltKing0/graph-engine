"""Pending-edge review policy: accept suggestions, but cap intent fan-out.

`ig pending` lists the suggestions the suggester left for review. Accepting all
of them is right for similarity edges (they carry a cosine confidence) and wrong
for intent edges:

  - intent edges (`contradicts`/`supersedes`/`continues`) carry
    `confidence=None`, so the 0.95 auto-accept band can never judge them;
  - their only producer is the marker heuristic in `intent.py`, which
    mass-fires in a homogeneous brain — measured live: 168 intent edges ever
    created, 66 of them invalidated again (39 % false), one source holding 10
    auto-accepted `contradicts`, and 26 false edges added in a single cycle;
  - they are auto-accepted at birth, so `ig pending` never showed them and the
    false positives stayed invisible until someone read the graph.

The dam: per source node at most `INTENT_AUTO_ACCEPT_MAX` intent edges may be
auto-accepted. Everything beyond that stays pending and waits for a human. It is
a bound, not a repair — the repair class is semantic (a marker heuristic cannot
read descriptive negation); the measurable contract lives in the ROADMAP_CASE
`roadmap-intent-fanout-cap` and is enforced in `brain_engine.ingest` at birth
plus here on the review path.
"""

from __future__ import annotations

import os
from collections import Counter

from .brain import Brain, Edge
from .intent import INTENT_KINDS

# How many intent edges one source node may auto-accept. Overridable per call
# (eval cases) and per deployment (env), never silently.
INTENT_AUTO_ACCEPT_MAX = 2
INTENT_AUTO_ACCEPT_MAX_ENV = "IG_INTENT_AUTO_ACCEPT_MAX"


def intent_auto_accept_max(env: dict[str, str] | None = None) -> int:
    """Resolve the cap: per-call env > process env > `INTENT_AUTO_ACCEPT_MAX`."""
    raw = (env or {}).get(INTENT_AUTO_ACCEPT_MAX_ENV,
                          os.environ.get(INTENT_AUTO_ACCEPT_MAX_ENV))
    if raw is None or raw == "":
        return INTENT_AUTO_ACCEPT_MAX
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"{INTENT_AUTO_ACCEPT_MAX_ENV} must be an integer, got: {raw!r}")
    if value < 0:
        raise ValueError(
            f"{INTENT_AUTO_ACCEPT_MAX_ENV} must be >= 0, got: {value}")
    return value


def is_live_intent(edge: Edge) -> bool:
    """A currently valid, accepted intent edge (the thing the cap bounds)."""
    return (edge.kind in INTENT_KINDS and not edge.pending
            and not edge.rejected and edge.valid_to is None)


def accept_pending(brain: Brain, *, max_intent_per_source: int | None = None,
                   dry_run: bool = False, env: dict[str, str] | None = None,
                   commit: bool = True) -> dict:
    """Accept pending edges; hold intent edges beyond the per-source cap.

    Non-intent pending edges are accepted (their confidence is the signal).
    Intent pending edges are accepted only while the source's live intent count
    stays under the cap; the rest are HELD (still pending) for `ig pending`.

    Returns {"accepted": [ids], "held": [ids], "cap": int, "dry_run": bool}.
    Deterministic: pending edges are processed in sorted-id order, so two runs
    over the same state decide identically.
    """
    cap = (max_intent_per_source if max_intent_per_source is not None
           else intent_auto_accept_max(env))
    edges = brain.read_edges(include_rejected=True)
    live_intent = Counter(e.source for e in edges if is_live_intent(e))
    accepted: list[str] = []
    held: list[str] = []
    for edge in sorted((e for e in edges if e.pending and not e.rejected),
                       key=lambda e: e.id):
        if edge.kind in INTENT_KINDS:
            if live_intent[edge.source] >= cap:
                held.append(edge.id)
                continue
            live_intent[edge.source] += 1
        edge.pending = False
        accepted.append(edge.id)
    if accepted and not dry_run:
        brain.write_edges(edges)
        if commit:
            brain.commit_and_push(
                f"edge review: {len(accepted)} accepted, "
                f"{len(held)} intent held for review")
    return {"accepted": accepted, "held": held, "cap": cap, "dry_run": dry_run}
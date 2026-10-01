#!/usr/bin/env python3
"""One-time migration: backfill `Edge.origin` on a brain written before 0.5.5.

Edges created before the `origin` field existed carry no provenance, so a
maintenance pass cannot tell machine guesses from user-authored links. The
inference is the one that had to be done by hand for the 2026-09-18 backlog
cleanup, applied once to the whole store:

    kind in (contradicts|supersedes|continues)   -> "intent"    (marker heuristic)
    confidence is not None                       -> "suggester" (cosine kNN)
    otherwise                                    -> "manual"    (ig link / seed)

Usage (dry run first, ALWAYS on a copy — see the skill's data-mutation rule):

    python3 tools/backfill_origin.py --brain ~/graph-engine-brain --mode local
    python3 tools/backfill_origin.py --brain ~/graph-engine-brain --mode git --apply

Idempotent: edges that already carry an origin are left untouched.
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from graph_engine.brain import Brain
from graph_engine.intent import INTENT_KINDS


def infer(edge) -> str:
    if edge.kind in INTENT_KINDS:
        return "intent"
    if edge.confidence is not None:
        return "suggester"
    return "manual"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default=str(pathlib.Path.home() / "graph-engine-brain"))
    ap.add_argument("--mode", default="git", choices=["git", "local"])
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    brain = Brain(args.brain, mode=args.mode)
    edges = brain.read_edges(include_rejected=True)
    counts: collections.Counter = collections.Counter()
    todo = []
    for edge in edges:
        if getattr(edge, "origin", None):
            counts["already"] += 1
            continue
        origin = infer(edge)
        counts[origin] += 1
        todo.append((edge, origin))

    print(f"brain: {args.brain} (mode={args.mode})")
    print(f"edges: {len(edges)} · already tagged: {counts['already']}")
    print(f"to backfill: {len(todo)}  "
          f"(intent {counts['intent']} · suggester {counts['suggester']} · "
          f"manual {counts['manual']})")
    if not args.apply:
        print("DRY RUN — nothing written.")
        return 0
    if not todo:
        print("nothing to do.")
        return 0

    for edge, origin in todo:
        edge.origin = origin
    brain.write_edges(edges)
    brain.commit_and_push(
        f"migrate: backfill edge origin on {len(todo)} edges "
        f"(intent {counts['intent']} · suggester {counts['suggester']} · "
        f"manual {counts['manual']})")
    after = collections.Counter(e.origin for e in brain.read_edges(include_rejected=True))
    print("after:", dict(after))
    return 0


if __name__ == "__main__":
    sys.exit(main())
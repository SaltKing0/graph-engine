#!/usr/bin/env python3
"""ig_adapt — the adaptive controller for the self-evolving GraphEngine cycle.

Reads metrics.jsonl (written by ig_cycle.py) and updates cycle_strategy.json,
which the cron orchestrator consumes to steer the NEXT cycle. This closes the
feedback loop: the brain becomes the training signal for its own growth process.

Strategy decisions (all data-driven):
  - topic_weights: thin areas (weighted by user focus) get higher priority next run.
  - findings_rules: high island rate -> demand stronger connectivity instructions;
    high dup rate -> stricter novelty threshold; marker hits -> extend the ban list.
  - batch_size: runs that timed out shrink the batch (4 -> 3), healthy runs grow
    it back (max 4, VPS limit).

Usage:
  python3 tools/ig_adapt.py [--engine <engine-repo>]
                            [--metrics ~/.cache/graph_engine/ig_metrics.jsonl]
                            [--strategy ~/.cache/graph_engine/cycle_strategy.json]
                            [--engine <engine-repo>] [--print]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

DEFAULT_METRICS = os.path.expanduser("~/.cache/graph_engine/ig_metrics.jsonl")
DEFAULT_STRATEGY = os.path.expanduser("~/.cache/graph_engine/cycle_strategy.json")
DEFAULT_ENGINE = str(Path(__file__).resolve().parents[1])

FOCUS_AREAS = {"Multi-Agent-Systeme", "Agent-Harness & Orchestrierung"}


def load_metrics(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows = []
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return rows


def gap_counts(engine: str, brain: str = "") -> dict[str, int]:
    """Read current gap counts via the engine's gaps command (JSON).

    Audit #34: the brain path was hardcoded — it overrode the caller's env and
    silently produced empty gap weights on any other machine/brain. Now: explicit
    --brain flag wins, then IG_BRAIN_PATH from the environment, then the engine
    default."""
    env = dict(os.environ)
    if brain:
        env["IG_BRAIN_PATH"] = os.path.abspath(os.path.expanduser(brain))
    elif not env.get("IG_BRAIN_PATH"):
        env["IG_BRAIN_PATH"] = "~/graph-engine-brain"  # engine's neutral default
    eng_py = os.path.join(engine, ".venv", "bin", "python")
    if not os.path.exists(eng_py):
        # No venv (CI, plain `pip install`): the running interpreter has the
        # engine importable, so use it instead of silently dropping the weights.
        eng_py = sys.executable
    r = subprocess.run([eng_py, "-m", "graph_engine", "gaps", "--json"],
                       capture_output=True, text=True, env=env, cwd=engine)
    if r.returncode != 0:
        return {}
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}
    return {a["name"]: a["count"] for a in data.get("areas", [])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", default=DEFAULT_METRICS)
    ap.add_argument("--strategy", default=DEFAULT_STRATEGY)
    ap.add_argument("--engine", default=DEFAULT_ENGINE)
    ap.add_argument("--brain", default="",
                    help="brain path for gap weights (default: IG_BRAIN_PATH env, "
                         "then the engine's default brain)")
    ap.add_argument("--print", action="store_true")
    args = ap.parse_args()

    rows = load_metrics(args.metrics)
    if not rows:
        strat = {"topic_weights": {}, "findings_rules": [], "batch_size": 4,
                 "note": "default: no metrics yet"}
        if args.print:
            print(json.dumps(strat, indent=2, ensure_ascii=False))
            return 0
        os.makedirs(os.path.dirname(args.strategy), exist_ok=True)
        with open(args.strategy, "w", encoding="utf-8") as f:
            json.dump(strat, f, indent=2, ensure_ascii=False)
        print(f"default strategy written: {args.strategy}")
        return 0

    # Only consider recent runs (last 6) for adaptation.
    recent = rows[-6:]
    strat: dict = {"topic_weights": {}, "findings_rules": [], "batch_size": 4}

    # --- batch_size: timeout shrink / healthy grow ---
    timeouts = sum(1 for r in recent if r.get("timed_out"))
    if timeouts >= 2:
        strat["batch_size"] = 3
    elif timeouts == 0 and all(r.get("nodes_added", 0) > 0 for r in recent[-3:]):
        strat["batch_size"] = 4

    # --- topic_weights: thin areas weighted by focus get boosted ---
    gaps = gap_counts(args.engine, args.brain)
    total = sum(gaps.values()) or 1
    weights = {}
    for area, count in gaps.items():
        thinness = 1.0 - (count / total)  # thin areas score high
        focus = area in FOCUS_AREAS
        weights[area] = round((2.0 if focus else 1.0) * (1.0 + thinness), 3)
    strat["topic_weights"] = weights

    # --- findings_rules from quality signals ---
    islands = sum(r.get("islands_found", 0) for r in recent)
    ingested = sum(r.get("nodes_added", 0) for r in recent)
    if ingested and islands / ingested > 0.1:
        strat["findings_rules"].append(
            "Island-Rate hoch (>10%): Findings muessen stark vernetzt sein — "
            "Subagenten erhalten die Anschlussfaehigkeit-Vorgabe (2+ Bezuege zu "
            "bestehenden Brain-Themen pro Finding).")
    dups = sum(r.get("true_merges", 0) for r in recent)
    if dups >= 3:
        strat["findings_rules"].append(
            "Duplikat-Rate hoch: Novelty-Check (ig search) strenger — erst bei "
            "Score < 0.02 akzeptieren statt 0.03.")
    marker_words: set[str] = set()
    for r in recent:
        marker_words.update(r.get("marker_words", []))
    if marker_words:
        strat["findings_rules"].append(
            "Marker-Treffer in letzten Laeufen: Subagenten-Prompt um diese "
            "Woerter ergaenzen: " + ", ".join(sorted(marker_words)))
        strat["blocked_marker_words"] = sorted(marker_words)

    if args.print:
        print(json.dumps(strat, indent=2, ensure_ascii=False))
        return 0
    os.makedirs(os.path.dirname(args.strategy), exist_ok=True)
    with open(args.strategy, "w", encoding="utf-8") as f:
        json.dump(strat, f, indent=2, ensure_ascii=False)
    print(f"strategy written: {args.strategy}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

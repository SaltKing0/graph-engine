#!/usr/bin/env python3
"""ig_cycle — the mechanical research-ingest cycle for the GraphEngine brain.

Runs the full SAFE ingest pipeline for a batch of subagent-produced findings:
  collect (glob /tmp/dogfood_*.txt, dedup) → marker-scan (fail on intent markers)
  → dry-run on a copy → real ingest (git, INTENT_PENDING=1) → accept edges
  → report node count + islands.

The RESEARCH part (spawning subagents to write the findings) is done by the
orchestrator (agent / cron) around this script. This script is the reproducible,
safety-checked mechanical core. It NEVER ingests blind: a marker hit or a failed
dry-run aborts before anything touches the real brain.

Audit #5: the marker scan normalizes Unicode (NFKD + homoglyph folding) and
matches on word boundaries with span-scoped allowlist handling — a homoglyph
swap ("nіcht" with a Cyrillic і) or an innocent word elsewhere in the line
("Stätte" whitelisting a "statt" elsewhere) can no longer bypass the gate.

Usage:
  python3 tools/ig_cycle.py [--glob '/tmp/dogfood_*.txt'] [--brain ~/graph-engine-brain]
                            [--engine <engine-repo>] [--dry-run-only]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata

DEFAULT_METRICS = os.path.expanduser("~/.cache/graph_engine/ig_metrics.jsonl")

# Intent-marker substrings (exact) that must NOT appear in a finding.
MARKERS = [
    "ersetzt", "statt", "anstelle", "keine", "kein", "nicht", "sondern",
    "falsch", "basiert auf", "aufbauend", "weiterentwickelt", "verfeinert",
    "erweitert um", "uebersetzt", "ersetzbar", "verfeinerung",
]
# Allowlisted innocent substrings that CONTAIN a marker (false positives).
# Span-scoped: only the span of an allowlist match suppresses marker hits
# INSIDE that span — never marker hits elsewhere in the finding (Audit #5b).
ALLOW = ["stattet", "stätte", "Nichtabstreitbarkeit", "Unabstreitbarkeit"]

# Homoglyph folding table: lookalike codepoints → ASCII lookalike. Anything
# that NFKD doesn't already fold gets mapped here before matching.
_HOMOGLYPHS = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "і": "i", "ѕ": "s", "ј": "j", "һ": "h", "ԁ": "d", "ɡ": "g", "ⅼ": "l",
    "ν": "v", "ν": "v", "о": "o", "ｎ": "n", "ｋ": "k", "ｔ": "t",
    "０": "0", "１": "1", "３": "3", "５": "5",
}


def _fold(text: str) -> str:
    """NFKD-normalize, strip combining marks, fold homoglyphs, casefold.

    This is the CANONICAL form used for marker matching: any visually-plausible
    disguise of a marker word (Cyrillic і, fullwidth chars, combining marks,
    uppercase) folds to the same canonical string as the honest spelling.
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.translate(str.maketrans(_HOMOGLYPHS))
    return text.casefold()


def _marker_spans(folded: str, marker: str) -> list[tuple[int, int]]:
    """Word-boundary spans of `marker` in the folded text.

    Word-boundary on both ends (letter-class check) so substrings inside
    unrelated words (e.g. a marker inside a longer technical term) don't fire —
    the allowlist handles the legitimate compound-word exceptions instead.
    """
    spans = []
    if not marker:
        return spans
    for m in re.finditer(re.escape(marker), folded):
        a, b = m.start(), m.end()
        before = folded[a - 1] if a > 0 else " "
        after = folded[b] if b < len(folded) else " "
        if not (before.isalnum() or after.isalnum()):
            spans.append((a, b))
    return spans


def _allow_spans(folded: str) -> list[tuple[int, int]]:
    spans = []
    for a in ALLOW:
        af = _fold(a)
        start = 0
        while True:
            i = folded.find(af, start)
            if i < 0:
                break
            spans.append((i, i + len(af)))
            start = i + 1
    return spans


def _covered_by_allow(spans: list[tuple[int, int]], allow: list[tuple[int, int]]) -> bool:
    for (a, b) in spans:
        for (la, lb) in allow:
            if a >= la and b <= lb:
                break
        else:
            return False
    return True


def marker_scan(findings: list[tuple[str, str]]) -> list[str]:
    bad = []
    for src, finding in findings:
        folded = _fold(finding)
        allow_spans = _allow_spans(folded)
        for m in MARKERS:
            spans = _marker_spans(folded, _fold(m))
            if not spans:
                continue
            if _covered_by_allow(spans, allow_spans):
                continue  # every hit sits inside an allowlisted innocent word
            bad.append(f"{src}: contains marker '{m}'")
    return bad


def collect(files: list[str]) -> list[tuple[str, str]]:
    seen = set()
    out: list[tuple[str, str]] = []
    for f in sorted(files):
        for ln in open(f, encoding="utf-8"):
            ln = ln.rstrip("\n")
            if not ln.strip():
                continue
            if "\t" in ln:
                src, finding = ln.split("\t", 1)
            else:
                src, finding = "dogfood/gap?", ln
            if finding in seen:
                continue
            seen.add(finding)
            out.append((src, finding))
    return out


def run(cmd: list[str], env: dict, cwd: str) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed ({r.returncode}): {' '.join(cmd)}\n{r.stderr[-800:]}")
    return r.stdout + r.stderr


def write_metrics(entry: dict, path: str = DEFAULT_METRICS) -> None:
    """Append one JSON line to the metrics log (Tier 1: self-measurement).

    Audit #28: the append holds an exclusive flock so concurrent cycles
    (or a cycle racing a manual adapt run) can't interleave half-written
    JSON lines."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import fcntl
        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError as e:
        print(f"metrics write failed (non-fatal): {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="/tmp/dogfood_*.txt")
    _repo_root = Path(__file__).resolve().parents[1]
    # `~/…` defaults must be expanded: Path("~/graph-engine-brain") does not
    # expand the tilde, so the documented cron invocation (no --brain) aborted
    # with "brain not found" even though the brain existed (found 2026-09-15).
    ap.add_argument("--brain", default=os.path.expanduser(
        os.environ.get("IG_BRAIN_PATH", "~/graph-engine-brain")))
    ap.add_argument("--engine", default=os.environ.get("IG_ENGINE_PATH", str(_repo_root)))
    ap.add_argument("--dry-run-only", action="store_true")
    ap.add_argument("--copy", default="",
                    help="dry-run copy dir (default: unique mkdtemp in /tmp)")
    ap.add_argument("--metrics", default=DEFAULT_METRICS,
                    help="metrics JSONL path (default: %s)" % DEFAULT_METRICS)
    args = ap.parse_args()

    t0 = time.time()
    try:
        n_before = len([f for f in os.listdir(os.path.join(args.brain, "nodes"))
                        if f.endswith(".md")])
    except FileNotFoundError:
        # Audit #28: a missing brain crashed with a raw traceback — friendly abort.
        print(f"brain not found or has no nodes/ dir: {args.brain}")
        return 1
    # Engine venv python (has numpy/st embedder); fall back to current interpreter.
    eng_py = os.path.join(args.engine, ".venv", "bin", "python")
    if not os.path.exists(eng_py):
        eng_py = sys.executable
    files = sorted(glob.glob(args.glob))
    if not files:
        print("NO findings files matched", args.glob)
        return 1
    findings = collect(files)
    if not findings:
        print("no findings after dedup")
        return 1
    print(f"collect: {len(files)} files -> {len(findings)} findings")

    bad = marker_scan(findings)
    if bad:
        print("MARKER FAIL (abort, nothing ingested):")
        for b in bad:
            print("  -", b)
        write_metrics({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "aborted": "marker", "marker_fails": len(bad),
                       "marker_words": sorted({m for _, f in findings for m in MARKERS
                                               if _marker_spans(_fold(f), _fold(m))
                                               and not _covered_by_allow(
                                                   _marker_spans(_fold(f), _fold(m)),
                                                   _allow_spans(_fold(f)))}),
                       "findings": len(findings)}, path=args.metrics)
        return 1
    print("marker-scan: CLEAN")

    # Dry-run on a copy (exclude .git, per skill). Audit #28: the copy path is a
    # unique mkdtemp by default — a fixed /tmp/ig-brain-dryrun collided across
    # concurrent cycles (one cycle rmtree'd the copy another was using).
    copy_dir = args.copy or tempfile.mkdtemp(prefix="ig-brain-dryrun-")
    if os.path.exists(copy_dir):
        shutil.rmtree(copy_dir)
    os.makedirs(copy_dir)
    shutil.copytree(os.path.join(args.brain, "nodes"), os.path.join(copy_dir, "nodes"))
    for f in ("edges.jsonl", "vectors.jsonl", "INDEX.md"):
        shutil.copy(os.path.join(args.brain, f), os.path.join(copy_dir, f))
    # The cycle is a production pipeline, so the real embedder is the default —
    # but an explicit IDEAGRAPH_EMBEDDER from the caller wins. Otherwise a
    # caller that asked for the hash embedder (tests, light installs without
    # the [st] extra) still pulled a model download in here.
    cycle_embedder = os.environ.get("IDEAGRAPH_EMBEDDER", "st")
    dry_env = dict(os.environ, IG_BRAIN_PATH=copy_dir, IG_BRAIN_MODE="local",
                   IDEAGRAPH_INTENT_PENDING="1", IDEAGRAPH_EMBEDDER=cycle_embedder)
    dry_islands = []
    for src, finding in findings:
        out = run([eng_py, "-m", "graph_engine", "ingest", finding, "--source", src],
                  dry_env, args.engine)
        n = out.count("Suggestion:")
        m = __import__("re").search(r"Node (\w{12}):", out)
        if m and n == 0:
            dry_islands.append(m.group(1))
    print(f"dry-run: {len(findings)} findings on copy, islands={dry_islands}")
    if args.dry_run_only:
        print("dry-run-only: stopping (brain untouched)")
        return 0

    # Real ingest (git, INTENT_PENDING safety net). Audit #6: --brain/IG_BRAIN_PATH
    # is passed THROUGH to the real ingest — before, git_env only set the mode,
    # the ingest landed in the env default path while the metrics counted args.brain.
    git_env = dict(os.environ, IG_BRAIN_MODE="git", IG_BRAIN_PATH=os.path.abspath(args.brain),
                   IDEAGRAPH_INTENT_PENDING="1", IDEAGRAPH_EMBEDDER=cycle_embedder)
    real_islands = []
    dups = 0
    failed: list[str] = []
    for src, finding in findings:
        # Audit #28: per-finding error handling — one failed ingest no longer
        # aborts mid-batch (earlier findings committed, later lost, no metrics,
        # review_edges never ran). Failed findings are recorded and skipped.
        try:
            out = run([eng_py, "-m", "graph_engine", "ingest", finding, "--source", src],
                      git_env, args.engine)
        except RuntimeError as e:
            failed.append(f"{src}: {str(e)[-200:]}")
            continue
        if "Duplicate" in out and "merged into" in out:
            dups += 1
        n = out.count("Suggestion:")
        m = __import__("re").search(r"Node (\w{12}):", out)
        if m and n == 0:
            real_islands.append(m.group(1))
    print(f"ingest: {len(findings) - len(failed)} ok, {len(failed)} failed, "
          f"{dups} dup-merged, 0-edge islands={real_islands}")
    for f_ in failed:
        print("  FAILED:", f_)

    # Accept pending edges in ONE commit — through the ENGINE's review policy
    # (`ig accept-pending`), which accepts every non-intent pending edge but
    # caps auto-accepted intent edges per source (graph_engine/review.py;
    # ROADMAP_CASE `roadmap-intent-fanout-cap`). The previous path called an
    # accept-ALL script by default, which is exactly the leak the cap closes:
    # intent edges are auto-accepted at birth with confidence=None, so the
    # confidence bands cannot judge them and a marker word mass-fires.
    # IG_REVIEW_SCRIPT stays available as an EXPLICIT opt-in escape hatch for a
    # custom policy (no default path — an unset variable must not silently
    # bypass the cap).
    out = run([eng_py, "-m", "graph_engine", "accept-pending"], git_env, args.engine)
    print(out.strip().splitlines()[0] if out.strip() else "review: no output")
    review = os.environ.get("IG_REVIEW_SCRIPT", "")
    if review and os.path.exists(review):
        out = run([eng_py, review], git_env, args.engine)
        print(f"IG_REVIEW_SCRIPT override: "
              f"{out.strip().splitlines()[-1] if out.strip() else 'no output'}")

    # Regenerate BRAIN_REPORT.md (report #7): rides the cycle as its own commit
    # (one commit per generation). A report failure must never fail the cycle.
    try:
        out = run([eng_py, "-m", "graph_engine", "report", "--write"],
                  git_env, args.engine)
        line = out.strip().splitlines()[-1] if out.strip() else ""
        print(f"report: {line or 'no output'}")
    except RuntimeError as e:
        print(f"report: skipped ({str(e)[-160:]})")

    # Dream pass (Welle B/C): deterministic maintenance, community distillation
    # and the status lifecycle, in one engine command — never destructive, one
    # commit per step. Like the report step, a failure must never fail the cycle.
    # `--distill` only writes what is new (deterministic summary ids), so the
    # first cycle after this landed adds 30 summaries and later cycles add none
    # until the topology actually changes.
    try:
        out = run([eng_py, "-m", "graph_engine", "dream", "--refresh", "--distill",
                   "--lifecycle"], git_env, args.engine)
        for line in out.strip().splitlines():
            if line.startswith(("refresh:", "distill:", "lifecycle:")):
                print(f"dream: {line}")
    except RuntimeError as e:
        print(f"dream: skipped ({str(e)[-160:]})")

    # Report node count + write Tier-1 metrics.
    n_nodes = len([f for f in os.listdir(os.path.join(args.brain, "nodes"))
                   if f.endswith(".md")])
    print(f"nodes now: {n_nodes}")
    print(f"ISLANDS_TO_FIX: {real_islands}")
    write_metrics({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "nodes_before": n_before, "nodes_after": n_nodes,
                   "nodes_added": n_nodes - n_before,
                   "findings": len(findings),
                   "failed": len(failed),
                   "true_merges": dups,
                   "islands_found": len(real_islands),
                   "duration_s": round(time.time() - t0, 1),
                   "timed_out": False}, path=args.metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main())

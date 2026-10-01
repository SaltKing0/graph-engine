"""Pipeline tools smoke tests (audit #57: tools/ had zero test coverage).

Runs ig_cycle / ig_adapt / ig_evolve as subprocesses against temp brains —
the same way the cron job invokes them. These are behavioral smoke tests:
exit codes, output contracts, and the safety gates, not internals.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
# sys.executable = the interpreter running pytest (repo venv locally, the CI
# environment on GitHub Actions, where no .venv exists).
PY = sys.executable


def _env(tmp_path, **extra) -> dict:
    env = dict(os.environ,
               IDEAGRAPH_EMBEDDER="hash",
               PYTHONPATH=str(REPO))
    env.update(extra)
    return env


@pytest.fixture()
def brain(tmp_path):
    """An initialized local brain."""
    b = tmp_path / "brain"
    subprocess.run([PY, "-m", "graph_engine", "init"],
                   capture_output=True, text=True,
                   env=_env(tmp_path, IG_BRAIN_MODE="local", IG_BRAIN_PATH=str(b)),
                   check=True)
    return b


# ---------------------------------------------------------------------------
# ig_cycle
# ---------------------------------------------------------------------------

def test_cycle_missing_brain_aborts_cleanly(tmp_path):
    """#28: a missing brain is a friendly abort, not a traceback."""
    r = subprocess.run(
        [PY, str(REPO / "tools" / "ig_cycle.py"),
         "--brain", str(tmp_path / "nonexistent"), "--engine", str(REPO)],
        capture_output=True, text=True, env=_env(tmp_path), timeout=120)
    assert r.returncode != 0
    assert "Traceback" not in r.stderr


def test_cycle_default_brain_expands_tilde(tmp_path):
    """The documented cron invocation passes NO --brain: the `~/graph-engine-brain`
    default must be tilde-expanded, otherwise the run aborts with "brain not
    found" although the brain exists (found 2026-09-15)."""
    home = tmp_path / "home"
    home.mkdir()
    b = home / "graph-engine-brain"
    subprocess.run([PY, "-m", "graph_engine", "init"], capture_output=True, text=True,
                   env=_env(tmp_path, IG_BRAIN_MODE="local", IG_BRAIN_PATH=str(b)),
                   check=True)
    findings = tmp_path / "findings"
    findings.mkdir()
    (findings / "dogfood_t.txt").write_text("Ein Agent plant seine Schritte.\n",
                                            encoding="utf-8")
    env = _env(tmp_path, HOME=str(home))
    env.pop("IG_BRAIN_PATH", None)  # the default path is what we are testing
    r = subprocess.run(
        [PY, str(REPO / "tools" / "ig_cycle.py"),
         "--engine", str(REPO), "--glob", str(findings / "*.txt"),
         "--dry-run-only"],
        capture_output=True, text=True, env=env, timeout=300)
    assert "brain not found" not in r.stdout
    assert r.returncode == 0, r.stderr[-500:]


def test_cycle_dry_run_on_empty_brain(tmp_path, brain):
    """A dry-run cycle completes, reports islands, and does NOT write metrics
    (dry runs must not pollute the production metrics stream the adapt loop reads)."""
    findings = tmp_path / "findings"
    findings.mkdir()
    (findings / "dogfood_test.txt").write_text(
        "The scheduler assigns one worker per queued job.\n"
        "The scheduler retries failed jobs up to three times.\n", encoding="utf-8")
    metrics = tmp_path / "metrics.jsonl"
    r = subprocess.run(
        [PY, str(REPO / "tools" / "ig_cycle.py"),
         "--brain", str(brain), "--engine", str(REPO),
         "--glob", str(findings / "*.txt"),
         "--dry-run-only",
         "--metrics", str(metrics)],
        capture_output=True, text=True, env=_env(tmp_path), timeout=300)
    assert r.returncode == 0, r.stderr[-500:]
    assert "dry-run: 2 findings on copy" in r.stdout
    assert not metrics.exists()  # dry-run writes no metrics by design


def test_cycle_real_ingest_metrics(tmp_path, brain):
    """Real-ingest cycle (local mode via IG_BRAIN_PATH) writes metrics with
    true_merges (#28) and duplicates become merges, not new nodes."""
    findings = tmp_path / "findings"
    findings.mkdir()
    text = "The scheduler assigns one worker per queued job.\n"
    (findings / "dogfood_a.txt").write_text(text, encoding="utf-8")
    metrics = tmp_path / "metrics.jsonl"
    base_cmd = [PY, str(REPO / "tools" / "ig_cycle.py"),
                "--brain", str(brain), "--engine", str(REPO),
                "--glob", str(findings / "*.txt"),
                "--metrics", str(metrics)]
    env = _env(tmp_path, IG_BRAIN_MODE="local", IG_BRAIN_PATH=str(brain),
               IDEAGRAPH_INTENT_PENDING="1")
    r1 = subprocess.run(base_cmd, capture_output=True, text=True, env=env, timeout=300)
    assert r1.returncode == 0, r1.stderr[-500:]
    # second cycle with the SAME finding -> duplicate -> merge
    (findings / "dogfood_b.txt").write_text(text, encoding="utf-8")
    r2 = subprocess.run(base_cmd, capture_output=True, text=True, env=env, timeout=300)
    assert r2.returncode == 0, r2.stderr[-500:]
    rows = [json.loads(l) for l in
            metrics.read_text(encoding="utf-8").strip().splitlines()]
    assert rows[-1].get("true_merges", 0) >= 1


# ---------------------------------------------------------------------------
# ig_adapt
# ---------------------------------------------------------------------------

def test_adapt_missing_brain_degrades_gracefully(tmp_path):
    """#34: a missing --brain degrades to default strategy, never a traceback."""
    r = subprocess.run(
        [PY, str(REPO / "tools" / "ig_adapt.py"),
         "--engine", str(REPO), "--brain", str(tmp_path / "nope"),
         "--metrics", str(tmp_path / "m.jsonl"), "--print"],
        capture_output=True, text=True, env=_env(tmp_path), timeout=120)
    assert r.returncode == 0
    assert "Traceback" not in r.stderr
    out = json.loads(r.stdout)
    assert out.get("topic_weights") == {}  # no gap weights from a missing brain


def test_adapt_runs_on_real_brain_dir(tmp_path, brain):
    r = subprocess.run(
        [PY, str(REPO / "tools" / "ig_adapt.py"),
         "--engine", str(REPO), "--brain", str(brain),
         "--metrics", str(tmp_path / "m.jsonl"),
         "--strategy", str(tmp_path / "cycle_strategy.json"), "--print"],
        capture_output=True, text=True, env=_env(tmp_path), timeout=120)
    assert r.returncode == 0, r.stderr[-300:]


# ---------------------------------------------------------------------------
# ig_evolve
# ---------------------------------------------------------------------------

def test_evolve_list_cases(tmp_path):
    """--list prints the evolve history; the path is overridable for tests.

    The history lives in the user's cache dir, so the test seeds its own file
    (IG_EVOLVE_HISTORY) instead of asserting on whatever the machine happens
    to have — that made it pass locally and fail in CI.
    """
    hist = tmp_path / "ig_evolve_history.jsonl"
    hist.write_text(json.dumps({
        "ts": "2026-01-01T00:00:00Z", "case_id": "roadmap-confidence-floor",
        "action": "propose", "passed": False, "suite_tail": "1 failed"}) + "\n",
        encoding="utf-8")
    r = subprocess.run(
        [PY, str(REPO / "tools" / "ig_evolve.py"),
         "--engine", str(REPO), "--list"],
        capture_output=True, text=True,
        env=_env(tmp_path, IG_EVOLVE_HISTORY=str(hist)), timeout=120)
    assert r.returncode == 0
    assert "roadmap-confidence-floor" in r.stdout
    assert "propose" in r.stdout


def test_evolve_list_without_history(tmp_path):
    """An empty history is a clean message, not an error."""
    r = subprocess.run(
        [PY, str(REPO / "tools" / "ig_evolve.py"),
         "--engine", str(REPO), "--list"],
        capture_output=True, text=True,
        env=_env(tmp_path, IG_EVOLVE_HISTORY=str(tmp_path / "none.jsonl")),
        timeout=120)
    assert r.returncode == 0
    assert "no evolve history yet" in r.stdout


def test_evolve_flip_unknown_case_fails_cleanly(tmp_path):
    """A never-proposed case id is refused by the PROPOSE->FLIP gate."""
    r = subprocess.run(
        [PY, str(REPO / "tools" / "ig_evolve.py"),
         "--engine", str(REPO), "--flip", "no-such-case"],
        capture_output=True, text=True, env=_env(tmp_path), timeout=300)
    assert r.returncode == 1
    assert "no 'propose' entry" in r.stdout
    assert "Traceback" not in r.stderr


def test_evolve_propose_contract_errors(tmp_path):
    """--propose contract: spec must be a FILE, id must start with 'roadmap-',
    and the case must already exist in ROADMAP_CASES. These checks run BEFORE
    any history write, so the production history file is never touched."""
    # raw JSON string instead of a file path -> clean error
    r_bad = subprocess.run(
        [PY, str(REPO / "tools" / "ig_evolve.py"),
         "--engine", str(REPO), "--propose", json.dumps({"id": "roadmap-x"})],
        capture_output=True, text=True, env=_env(tmp_path), timeout=120)
    assert r_bad.returncode != 0
    assert "Traceback" not in r_bad.stderr
    # well-formed spec file but unknown case -> refused before eval
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps({
        "id": "roadmap-nonexistent-case", "name": "x",
        "ingests": [["alpha beta", {"source": "t"}]],
        "oracle": {"node_count": 1}}), encoding="utf-8")
    r = subprocess.run(
        [PY, str(REPO / "tools" / "ig_evolve.py"),
         "--engine", str(REPO), "--propose", str(spec_file)],
        capture_output=True, text=True, env=_env(tmp_path), timeout=120)
    assert r.returncode == 1
    assert "not yet in ROADMAP_CASES" in r.stdout
    assert "Traceback" not in r.stderr

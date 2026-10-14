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

def _tree_snapshot(root: Path) -> dict:
    """Record contents, links and modification times, including Git history."""
    snapshot = {}
    for path in [root, *sorted(root.rglob("*"))]:
        stat = path.lstat()
        content = (os.readlink(path) if path.is_symlink()
                   else path.read_bytes() if path.is_file() else None)
        snapshot[str(path.relative_to(root))] = (stat.st_mode, stat.st_mtime_ns, content)
    return snapshot


@pytest.fixture()
def cycle_source(tmp_path, brain):
    from graph_engine.brain import Brain, Node

    Brain(brain, mode="local").write_node(Node("Synthetic source memory", id="source"))
    (brain / "sentinel.txt").write_text("source must survive", encoding="utf-8")
    for args in (["init"], ["add", "."],
                 ["-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                  "commit", "-m", "Synthetic source history"]):
        subprocess.run(["git", "-C", str(brain), *args], check=True,
                       capture_output=True, text=True)
    findings = tmp_path / "findings.txt"
    findings.write_text("The scheduler assigns one worker per queued job.\n",
                        encoding="utf-8")
    return brain, findings


@pytest.mark.parametrize("dry_run_only", [True, False])
@pytest.mark.parametrize("destination", [
    "same", "dotdot_alias", "ancestor", "descendant", "nested_descendant",
    "source_symlink", "destination_symlink", "ancestor_symlink",
    "source_parent_symlink", "unrelated_symlink", "unrelated_parent_symlink",
    "dangling_symlink", "symlink_loop", "existing_directory", "empty_directory", "existing_file",
    "missing_parent", "marker_existing_directory",
])
def test_cycle_rejects_unsafe_copy_without_mutation(tmp_path, cycle_source,
                                                 destination, dry_run_only):
    brain, findings = cycle_source
    source = brain
    copy = tmp_path / "copy"
    if destination == "same":
        copy = brain
    elif destination == "dotdot_alias":
        copy = brain / ".." / brain.name
    elif destination == "ancestor":
        copy = tmp_path
    elif destination == "descendant":
        copy = brain / "copy"
    elif destination == "nested_descendant":
        copy = brain / "new-parent" / "copy"
    elif destination == "source_symlink":
        source = tmp_path / "source-alias"
        source.symlink_to(brain, target_is_directory=True)
        copy = brain / "copy"
    elif destination in {"destination_symlink", "ancestor_symlink"}:
        copy.symlink_to(brain if destination == "destination_symlink" else tmp_path,
                        target_is_directory=True)
    elif destination == "source_parent_symlink":
        alias = tmp_path / "source-alias"
        alias.symlink_to(brain, target_is_directory=True)
        copy = alias / "copy"
    elif destination in {"unrelated_symlink", "unrelated_parent_symlink"}:
        unrelated = tmp_path / "unrelated"
        unrelated.mkdir()
        (unrelated / "sentinel.txt").write_text("unrelated must survive", encoding="utf-8")
        copy.symlink_to(unrelated, target_is_directory=True)
        if destination == "unrelated_parent_symlink":
            copy = copy / "new-copy"
    elif destination == "dangling_symlink":
        copy.symlink_to(tmp_path / "absent", target_is_directory=True)
    elif destination == "symlink_loop":
        copy.symlink_to(copy, target_is_directory=True)
    elif destination in {"existing_directory", "empty_directory", "marker_existing_directory"}:
        copy.mkdir()
        if destination != "empty_directory":
            (copy / "sentinel.txt").write_text("unrelated must survive", encoding="utf-8")
        if destination == "marker_existing_directory":
            findings.write_text("This is nicht safe.\n", encoding="utf-8")
    elif destination == "existing_file":
        copy.write_text("unrelated must survive", encoding="utf-8")
    elif destination == "missing_parent":
        copy = tmp_path / "missing-parent" / "copy"
    before = _tree_snapshot(tmp_path)
    cmd = [PY, str(REPO / "tools" / "ig_cycle.py"),
           "--brain", str(source), "--engine", str(REPO),
           "--glob", str(findings), "--copy", str(copy),
           "--metrics", str(tmp_path / "metrics.jsonl")]
    if dry_run_only:
        cmd.append("--dry-run-only")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env=_env(tmp_path), timeout=120)
    assert _tree_snapshot(tmp_path) == before
    assert r.returncode != 0
    assert "unsafe --copy" in r.stdout
    assert "Traceback" not in r.stderr


@pytest.mark.parametrize("explicit_copy", [True, False])
def test_cycle_safe_copy_preserves_source(tmp_path, cycle_source, explicit_copy):
    brain, findings = cycle_source
    before = _tree_snapshot(brain)
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    copy = tmp_path / "copy"
    cmd = [PY, str(REPO / "tools" / "ig_cycle.py"),
           "--brain", str(brain), "--engine", str(REPO),
           "--glob", str(findings), "--dry-run-only",
           "--metrics", str(tmp_path / "metrics.jsonl")]
    if explicit_copy:
        cmd.extend(["--copy", str(copy)])
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env=_env(tmp_path, TMPDIR=str(temporary)), timeout=120)
    assert r.returncode == 0, r.stderr[-500:]
    assert "dry-run: 1 findings on copy" in r.stdout
    assert _tree_snapshot(brain) == before
    assert not (tmp_path / "metrics.jsonl").exists()
    assert list(temporary.glob("ig-brain-dryrun-*")) == []
    if explicit_copy:
        assert len(list((copy / "nodes").glob("*.md"))) == 2
        assert not (copy / ".git").exists()
        assert not (copy / "sentinel.txt").exists()


def test_cycle_default_copy_cleanup_on_failure(tmp_path, cycle_source):
    brain, findings = cycle_source
    (brain / "INDEX.md").unlink()
    before = _tree_snapshot(brain)
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    r = subprocess.run(
        [PY, str(REPO / "tools" / "ig_cycle.py"),
         "--brain", str(brain), "--engine", str(REPO),
         "--glob", str(findings), "--dry-run-only"],
        capture_output=True, text=True,
        env=_env(tmp_path, TMPDIR=str(temporary)), timeout=120)
    assert r.returncode != 0
    assert "dry-run copy failed" in r.stdout
    assert "Traceback" not in r.stderr
    assert _tree_snapshot(brain) == before
    assert list(temporary.glob("ig-brain-dryrun-*")) == []


def test_cycle_rejects_temporary_directory_inside_source(tmp_path, cycle_source):
    brain, findings = cycle_source
    before = _tree_snapshot(tmp_path)
    r = subprocess.run(
        [PY, str(REPO / "tools" / "ig_cycle.py"),
         "--brain", str(brain), "--engine", str(REPO),
         "--glob", str(findings), "--dry-run-only"],
        capture_output=True, text=True,
        env=_env(tmp_path, TMPDIR=str(brain)), timeout=120)
    assert r.returncode != 0
    assert "set TMPDIR outside it" in r.stdout
    assert "Traceback" not in r.stderr
    assert _tree_snapshot(tmp_path) == before


def test_cycle_copy_creation_race_preserves_destination(tmp_path, cycle_source, monkeypatch):
    """Another process claims the destination between validation and mkdir."""
    from tools import ig_cycle

    brain, _ = cycle_source
    copy = tmp_path / "copy"
    validate = ig_cycle._validate_copy_path
    before = {}

    def claim_destination(source: Path, destination: str) -> Path:
        path = validate(source, destination)
        path.mkdir()
        (path / "sentinel.txt").write_text("another process owns this", encoding="utf-8")
        before.update(_tree_snapshot(tmp_path))
        return path

    monkeypatch.setattr(ig_cycle, "_validate_copy_path", claim_destination)
    with pytest.raises(FileExistsError):
        with ig_cycle._dry_run_copy(brain, str(copy)):
            pytest.fail("must refuse the newly claimed destination")
    assert _tree_snapshot(tmp_path) == before


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
    from graph_engine.brain import Brain, Node
    memory = Brain(brain, mode="local")
    memory.write_node(Node(id="episode", text="User prefers tea with breakfast",
                           ntype="episodic", status="active", recall_count=1,
                           created="2020-01-01T00:00:00Z"))
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
    assert "dream: consolidate: 1 fact(s) created" in r1.stdout
    assert any(n.ntype == "semantic" and n.text == "User prefers tea with breakfast"
               for n in memory.read_nodes())
    # second cycle with the SAME finding -> duplicate -> merge
    (findings / "dogfood_b.txt").write_text(text, encoding="utf-8")
    r2 = subprocess.run(base_cmd, capture_output=True, text=True, env=env, timeout=300)
    assert r2.returncode == 0, r2.stderr[-500:]
    assert "dream: consolidate: 0 fact(s) created" in r2.stdout
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

"""Offline worker gates, scheduling, real deadlines and local coordination."""
from __future__ import annotations

from dataclasses import replace
import json
import multiprocessing as mp
import os
import shlex
import signal
import subprocess
import sys
import threading
import time

import pytest

from graph_engine import namespaces
from graph_engine.brain import Brain, Edge, Node
from graph_engine.maintenance import MaintenanceConfig, MaintenanceWorker, PassFailure, perform_pass
from graph_engine.write_guard import git_deadline, run_git

pytestmark = pytest.mark.skipif(os.name != "posix", reason="worker supports Linux/macOS")


@pytest.fixture
def brain(tmp_path, monkeypatch):
    for name in ("IG_ACCESS_POLICY", "IG_PRINCIPAL", "IG_GRAPH_HOME", "IG_GRAPH", "IG_BRAIN_REMOTE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("IG_BRAIN_PATH", str(tmp_path / "brain"))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    # Worker must never load an embedder, including the default ST embedder.
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "unavailable")
    raw = Brain(str(tmp_path / "brain"))
    raw.init()
    return raw


def test_injected_clock_fixed_delay_and_recovery():
    now, starts, events, waits = [0.0], [], [], []
    stop = threading.Event()

    def runner(config, action):
        starts.append(now[0])
        now[0] += 7
        if len(starts) == 1:
            raise PassFailure("model_timeout")
        stop.set()
        return {"created": 1, "proposals": "private text"}

    def wait(seconds):
        waits.append(seconds)
        now[0] += seconds
        return False

    worker = MaintenanceWorker(MaintenanceConfig(actions=("consolidate",), interval=10),
                               clock=lambda: now[0], wait=wait, stop=stop, runner=runner, emit=events.append)
    assert worker.run() == 0
    assert starts == [0, 17]  # delay follows completion, no catch-up/overlap
    assert waits == [10]
    assert events[2]["event"] == "pass_failed"
    assert events[2]["duration_seconds"] == 7
    assert events[4]["counts"] == {"created": 1}
    assert "private text" not in json.dumps(events)


def test_overlap_prevention_and_shutdown_between_actions():
    entered, release, events = threading.Event(), threading.Event(), []
    worker = None

    def runner(config, action):
        entered.set()
        assert release.wait(5)
        worker.stop.set()
        return {}

    worker = MaintenanceWorker(MaintenanceConfig(), runner=runner, emit=events.append)
    thread = threading.Thread(target=worker.cycle)
    thread.start()
    try:
        assert entered.wait(5)
        assert worker.cycle() is False
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert [e["action"] for e in events if e["event"] == "pass_started"] == ["refresh"]
    assert any(e.get("reason") == "already_running" for e in events)


def test_failure_skips_dependent_actions_and_once_exit():
    called, events = [], []

    def runner(config, action):
        called.append(action)
        raise PassFailure("writer_busy")

    worker = MaintenanceWorker(MaintenanceConfig(), runner=runner, emit=events.append)
    assert worker.run(once=True) == 1
    assert called == ["refresh"]
    assert not worker.stop.is_set()


def test_uncertain_partial_write_stops_for_inspection():
    events = []

    def runner(config, action):
        raise PassFailure("storage_failure", retryable=False)

    worker = MaintenanceWorker(MaintenanceConfig(), runner=runner, emit=events.append)
    assert worker.run() == 1
    assert worker.stop.is_set()
    assert events[2]["retryable"] is False


@pytest.mark.parametrize("changes", [
    {"interval": float("nan")}, {"interval": 0}, {"pass_timeout": -1},
    {"lock_timeout": float("inf")}, {"model_timeout": 0}, {"limit": 0},
    {"max_records": 0}, {"max_input_bytes": -1}, {"actions": ()},
    {"actions": ("merge",)}, {"actions": ("refresh", "refresh")},
    {"graph": "../escape"}, {"extract_model": True},
    {"actions": ("consolidate",), "extract_model": True, "model_timeout": 120},
])
def test_invalid_config(changes):
    with pytest.raises(ValueError):
        MaintenanceConfig(**changes)


def test_bounded_lifecycle_is_repeatable_and_never_deletes(brain):
    for nid in ("c", "b", "a"):
        brain.write_node(Node("old note", id=nid, created="2020-01-01T00:00:00Z", status="probation"))
    config = MaintenanceConfig(actions=("lifecycle",), limit=1)
    for nid in ("a", "b", "c"):
        assert perform_pass(config, "lifecycle")["staled"] == 1
        assert brain.read_node(nid).status == "stale"
    assert perform_pass(config, "lifecycle")["staled"] == 0
    assert len(brain.read_nodes()) == 3


def test_copy_consolidation_pending_bounded_and_idempotent(brain, monkeypatch, tmp_path):
    marker = tmp_path / "model-called"
    monkeypatch.setenv("IG_CONSOLIDATE_STRUCTURED_CMD", f"touch {shlex.quote(str(marker))}")
    monkeypatch.setenv("IG_CONSOLIDATE_LLM_CMD", f"touch {shlex.quote(str(marker))}")
    for nid in ("a", "b"):
        brain.write_node(Node("same private evidence", id=nid, ntype="episodic",
                              created="2020-01-01T00:00:00Z", recall_count=2))
    existing = Edge("a", "b", "linked", id="review-me", pending=True)
    brain.add_edge(existing)
    config = MaintenanceConfig(actions=("consolidate",), limit=1)
    result = perform_pass(config, "consolidate")
    assert result["created"] == 1
    assert result["pending_proposals"] == 1
    assert perform_pass(config, "consolidate")["reused"] == 1
    assert perform_pass(config, "consolidate")["created"] == 0
    assert len(brain.read_nodes()) == 3
    assert all(e.pending for e in brain.read_edges())
    assert not marker.exists()
    assert brain.read_node("a").text == "same private evidence"


def test_refresh_noop_and_report_failure_are_observable(brain, monkeypatch):
    from graph_engine import report
    assert perform_pass(MaintenanceConfig(), "refresh")["recalls"] == 0
    assert perform_pass(MaintenanceConfig(), "refresh")["recalls"] == 0

    def failed(*args, **kwargs):
        raise RuntimeError("secret token and private node text")

    monkeypatch.setattr(report, "write_report", failed)
    with pytest.raises(PassFailure) as caught:
        perform_pass(MaintenanceConfig(), "refresh")
    assert caught.value.code == "storage_failure"
    assert not caught.value.retryable
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("family", ["nodes", "edges.jsonl", "vectors.jsonl", "recalls.jsonl", "bytes"])
def test_input_limits_fail_before_mutation(brain, family):
    config = MaintenanceConfig(max_records=1)
    if family in ("nodes", "bytes"):
        brain.write_node(Node("a", id="a"))
        brain.write_node(Node("b", id="b"))
        if family == "bytes":
            config = replace(config, max_records=10, max_input_bytes=1)
    else:
        (brain.path / family).write_text("{}\n{}\n")
    before = {p.relative_to(brain.path): p.read_bytes() for p in brain.path.rglob("*") if p.is_file()}
    with pytest.raises(PassFailure, match="input_limit") as caught:
        perform_pass(config, "refresh")
    assert caught.value.retryable
    assert before == {p.relative_to(brain.path): p.read_bytes() for p in brain.path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("identity", ["", "viewer", "editor", "admin"])
def test_required_admin_identity_and_policy_revocation(brain, monkeypatch, tmp_path, identity):
    policy = tmp_path / "policy.json"
    data = {"graphs": {"default": {"roles": {"admin": "admin", "viewer": "viewer", "editor": "editor"}}}}
    policy.write_text(json.dumps(data))
    monkeypatch.setenv("IG_ACCESS_POLICY", str(policy))
    monkeypatch.setenv("IG_PRINCIPAL", identity)
    config = MaintenanceConfig(actions=("lifecycle",))
    if identity != "admin":
        with pytest.raises(PassFailure, match="access_denied"):
            perform_pass(config, "lifecycle")
    else:
        assert perform_pass(config, "lifecycle")["promoted"] == 0
        data["graphs"]["default"]["roles"]["admin"] = "viewer"
        policy.write_text(json.dumps(data))
        with pytest.raises(PassFailure, match="access_denied"):
            perform_pass(config, "lifecycle")


def test_graph_selection_is_fixed_and_context_restored(brain, monkeypatch, tmp_path):
    monkeypatch.setenv("IG_GRAPH_HOME", str(tmp_path / "graphs-home"))
    for name in ("one", "two"):
        raw = Brain(str(namespaces.graph_path(name)))
        raw.init()
        raw.write_node(Node("old", id=name, created="2020-01-01T00:00:00Z", status="probation"))
    (namespaces.home() / "selected").write_text("two\n")
    config = MaintenanceConfig(graph="one", actions=("lifecycle",))
    assert perform_pass(config, "lifecycle")["staled"] == 1
    assert Brain(str(namespaces.graph_path("two"))).read_node("two").status == "probation"
    assert namespaces.selected() == "two"


def _hold(path, ready, release):
    with Brain(path).write_guard():
        ready.set()
        release.wait(10)


def test_lock_timeout_and_recovery_use_shared_guard(brain):
    ctx = mp.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    process = ctx.Process(target=_hold, args=(str(brain.path), ready, release))
    process.start()
    try:
        assert ready.wait(5)
        config = MaintenanceConfig(actions=("lifecycle",), lock_timeout=0.05)
        with pytest.raises(PassFailure, match="writer_busy") as caught:
            perform_pass(config, "lifecycle")
        assert caught.value.retryable
    finally:
        release.set()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
    assert perform_pass(config, "lifecycle")["staled"] == 0


def _command(script: str) -> str:
    return shlex.join([sys.executable, "-c", script])


def test_model_timeout_before_writes_and_next_pass_recovers(brain, monkeypatch):
    brain.write_node(Node("private event", id="event", ntype="episodic", recall_count=2,
                          created="2020-01-01T00:00:00Z"))
    monkeypatch.setenv("IG_CONSOLIDATE_STRUCTURED_CMD", _command("import time; time.sleep(10)"))
    config = MaintenanceConfig(actions=("consolidate",), extract_model=True,
                               model_timeout=0.05, pass_timeout=2)
    with pytest.raises(PassFailure, match="model_timeout") as caught:
        perform_pass(config, "consolidate")
    assert caught.value.retryable
    assert len(brain.read_nodes()) == 1
    assert brain.read_edges() == []
    monkeypatch.setenv("IG_CONSOLIDATE_STRUCTURED_CMD", _command(
        'import json,sys; e=json.load(sys.stdin)["events"][0]; '
        'print(json.dumps({"version":1,"abstain":False,"facts":[{"text":"private event",'
        '"evidence":[{"node_id":e["node_id"],"quote":e["text"]}]}]}))'))
    config = replace(config, model_timeout=1)
    assert perform_pass(config, "consolidate")["created"] == 1
    assert all(e.pending for e in brain.read_edges())
    assert perform_pass(config, "consolidate")["created"] == 0


def test_malformed_model_is_retryable_and_redacted(brain, monkeypatch):
    brain.write_node(Node("secret", id="event", ntype="episodic", recall_count=2,
                          created="2020-01-01T00:00:00Z"))
    monkeypatch.setenv("IG_CONSOLIDATE_STRUCTURED_CMD", _command('print("private token")'))
    config = MaintenanceConfig(actions=("consolidate",), extract_model=True)
    events = []
    worker = MaintenanceWorker(config, emit=events.append)
    assert worker.run(once=True) == 1
    assert events[2]["error"] == "model_output_invalid"
    assert events[2]["retryable"] is True
    assert "private token" not in json.dumps(events)
    assert len(brain.read_nodes()) == 1


def test_pass_deadline_unwinds_and_stops_after_entering_mutation(brain, monkeypatch):
    import graph_engine.maintenance as maintenance
    previous = signal.getsignal(signal.SIGALRM)

    def stalled(*args, **kwargs):
        time.sleep(10)

    monkeypatch.setattr(maintenance, "lifecycle", stalled)
    started = time.monotonic()
    with pytest.raises(PassFailure, match="pass_timeout") as caught:
        perform_pass(MaintenanceConfig(actions=("lifecycle",), pass_timeout=0.05), "lifecycle")
    assert time.monotonic() - started < 1
    assert not caught.value.retryable
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
    with brain.write_guard(timeout=0):
        pass


def test_bounded_git_timeout_kills_descendants_and_releases_guard(brain, tmp_path):
    marker = tmp_path / "should-not-complete"
    script = ('import os,time; from pathlib import Path; '
              'os.fork(); time.sleep(0.5); Path(' + repr(str(marker)) + ').touch(); time.sleep(10)')
    with pytest.raises(subprocess.TimeoutExpired):
        with brain.write_guard(), git_deadline(time.monotonic() + 0.05):
            run_git([sys.executable, "-c", script], capture_output=True, text=True)
    with brain.write_guard(timeout=0):
        pass
    time.sleep(0.6)
    assert not marker.exists()


def test_cli_once_and_explicit_start_without_embedder(brain):
    result = subprocess.run([sys.executable, "-m", "graph_engine", "maintenance", "--once",
                             "--actions", "lifecycle"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert [row["event"] for row in rows] == ["worker_started", "pass_started", "pass_completed", "worker_stopped"]
    imported = subprocess.run([sys.executable, "-c", "import graph_engine.maintenance; import graph_engine.server"],
                              capture_output=True, text=True, timeout=10)
    assert imported.returncode == 0, imported.stderr
    assert "worker_started" not in imported.stdout


def test_cli_sigterm_interrupts_idle_wait(brain, tmp_path):
    log = tmp_path / "worker.jsonl"
    with log.open("w") as output:
        proc = subprocess.Popen([sys.executable, "-m", "graph_engine", "maintenance",
                                 "--actions", "lifecycle", "--interval", "3600"],
                                stdout=output, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while "pass_completed" not in log.read_text() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert "pass_completed" in log.read_text()
            proc.send_signal(signal.SIGTERM)
            _, err = proc.communicate(timeout=3)
            assert proc.returncode == 0, err
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    assert json.loads(log.read_text().splitlines()[-1])["event"] == "worker_stopped"


def test_cli_rejects_unconfigured_model_and_named_graph(brain):
    for args in (["--graph", "other"], ["--extract-model", "--actions", "consolidate"]):
        env = dict(os.environ)
        env.pop("IG_CONSOLIDATE_STRUCTURED_CMD", None)
        result = subprocess.run([sys.executable, "-m", "graph_engine", "maintenance", "--once", *args],
                                env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == 2
        assert "worker_started" not in result.stdout


def test_missing_brain_does_not_initialize_implicitly(brain):
    import shutil
    shutil.rmtree(brain.path)
    with pytest.raises(PassFailure, match="brain_uninitialized"):
        perform_pass(MaintenanceConfig(), "refresh")
    assert not brain.path.exists()


def test_git_noop_consolidation_leaves_head_clean(brain, monkeypatch):
    monkeypatch.setenv("IG_BRAIN_MODE", "git")
    raw = Brain(str(brain.path), mode="git")
    raw.init()
    raw.write_node(Node("evidence", id="event", ntype="episodic", recall_count=2,
                        created="2020-01-01T00:00:00Z"))
    raw.commit_and_push("event")
    config = MaintenanceConfig(actions=("consolidate",))
    assert perform_pass(config, "consolidate")["created"] == 1
    head = subprocess.check_output(["git", "-C", str(raw.path), "rev-parse", "HEAD"])
    assert perform_pass(config, "consolidate")["created"] == 0
    assert subprocess.check_output(["git", "-C", str(raw.path), "rev-parse", "HEAD"]) == head
    assert subprocess.check_output(["git", "-C", str(raw.path), "status", "--porcelain"]) == b""
    assert all(e.pending for e in raw.read_edges())


def test_failed_push_stops_worker_and_preserves_local_commit(brain, monkeypatch, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    raw = Brain(str(tmp_path / "git-brain"), mode="git")
    raw.init(remote=str(bare))
    raw.write_node(Node("evidence", id="event", ntype="episodic", recall_count=2,
                        created="2020-01-01T00:00:00Z"))
    raw.commit_and_push("event")
    hook = bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o700)
    monkeypatch.setenv("IG_BRAIN_PATH", str(raw.path))
    monkeypatch.setenv("IG_BRAIN_MODE", "git")
    events = []
    worker = MaintenanceWorker(MaintenanceConfig(actions=("consolidate",)), emit=events.append)
    assert worker.run() == 1
    assert events[2]["error"] == "storage_failure"
    assert events[2]["retryable"] is False
    assert len(raw.read_nodes()) == 2
    assert subprocess.check_output(["git", "-C", str(raw.path), "status", "--porcelain"]) == b""
    assert subprocess.check_output(["git", "-C", str(raw.path), "rev-parse", "HEAD"]) != subprocess.check_output(
        ["git", "-C", str(bare), "rev-parse", "main"])


def test_git_hook_output_is_redacted_from_worker_streams(brain, monkeypatch):
    monkeypatch.setenv("IG_BRAIN_MODE", "git")
    raw = Brain(str(brain.path), mode="git")
    raw.init()
    raw.write_node(Node("private evidence", id="event", ntype="episodic", recall_count=2,
                        created="2020-01-01T00:00:00Z"))
    raw.commit_and_push("event")
    hook = raw.path / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nprintf 'private stdout token\\n'\n"
                    "printf 'private stderr token\\n' >&2\nexit 1\n")
    hook.chmod(0o700)
    result = subprocess.run([sys.executable, "-m", "graph_engine", "maintenance", "--once",
                             "--actions", "consolidate"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert result.stderr == ""
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert rows[2]["error"] == "storage_failure"
    assert rows[2]["retryable"] is False
    assert "private" not in result.stdout
    # Failure remains inspectable on disk rather than in unredacted logs.
    assert len(raw.read_nodes()) == 2


@pytest.mark.parametrize("action", ["refresh", "lifecycle", "consolidate"])
def test_remote_updates_cannot_bypass_input_check(brain, monkeypatch, tmp_path, action):
    # A fresh installation/CI runner may have no global committer identity.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    def git(*args):
        return subprocess.run(["git", *map(str, args)], check=True, capture_output=True, text=True)

    bare, publisher = tmp_path / "remote.git", tmp_path / "publisher"
    git("init", "--bare", "-b", "main", bare)
    monkeypatch.setenv("IG_BRAIN_MODE", "git")
    raw = Brain(str(brain.path), mode="git")
    raw.init(remote=str(bare))
    git("-C", raw.path, "config", "user.name", "test")
    git("-C", raw.path, "config", "user.email", "test@example.com")
    raw.write_node(Node("old a", id="a", created="2020-01-01T00:00:00Z"))
    raw.commit_and_push("event")
    git("clone", bare, publisher)
    (publisher / "nodes" / "b.md").write_text(
        Node("old b", id="b", created="2020-01-01T00:00:00Z").to_markdown())
    git("-C", publisher, "add", "-A")
    git("-C", publisher, "-c", "user.name=test", "-c", "user.email=test@example.com",
        "commit", "-m", "concurrent event")
    original_pull, pulls = Brain.pull, []

    def publish_after_pull(self):
        original_pull(self)
        pulls.append(self.path)
        if len(pulls) == 1:
            git("-C", publisher, "push", "origin", "main")

    monkeypatch.setattr(Brain, "pull", publish_after_pull)
    config = MaintenanceConfig(actions=(action,), max_records=1)
    if action == "consolidate":
        perform_pass(config, action)  # No eligible events, so no commit/push.
    else:
        # Writes use the checked snapshot. Since origin advanced, the push must
        # fail rather than importing unchecked data to make it succeed.
        with pytest.raises(PassFailure, match="storage_failure") as caught:
            perform_pass(config, action)
        assert not caught.value.retryable
    assert len(pulls) == 1
    assert raw.read_node("b") is None
    # The next pass pulls the new corpus, then rejects it before processing.
    with pytest.raises(PassFailure, match="input_limit") as caught:
        perform_pass(config, action)
    assert caught.value.retryable
    assert raw.read_node("b").status == "probation"
    assert raw.read_node("b").storage_tier == "recall"


def test_pass_deadline_during_model_is_retryable_and_recovers(brain, monkeypatch):
    import graph_engine.maintenance as maintenance
    brain.write_node(Node("private evidence", id="event", ntype="episodic", recall_count=2,
                          created="2020-01-01T00:00:00Z"))
    before = {p.relative_to(brain.path): p.read_bytes() for p in brain.path.rglob("*") if p.is_file()}
    original_check = maintenance._check_input

    def slow_check(*args):
        original_check(*args)
        time.sleep(0.5)  # Less pass budget remains than the model's own timeout.

    monkeypatch.setattr(maintenance, "_check_input", slow_check)
    monkeypatch.setenv("IG_CONSOLIDATE_STRUCTURED_CMD", _command("import time; time.sleep(10)"))
    config = MaintenanceConfig(actions=("consolidate",), extract_model=True,
                               pass_timeout=1, model_timeout=0.8)
    events = []
    worker = MaintenanceWorker(config, emit=events.append)
    assert worker.run(once=True) == 1
    assert events[2]["error"] == "pass_timeout"
    assert events[2]["retryable"] is True
    assert not worker.stop.is_set()
    assert before == {p.relative_to(brain.path): p.read_bytes() for p in brain.path.rglob("*") if p.is_file()}
    with brain.write_guard(timeout=0):
        pass
    monkeypatch.setattr(maintenance, "_check_input", original_check)
    monkeypatch.setenv("IG_CONSOLIDATE_STRUCTURED_CMD", _command(
        'print(\'{"version":1,"abstain":true,"facts":[]}\')'))
    assert worker.cycle()
    assert events[-1]["event"] == "pass_completed"

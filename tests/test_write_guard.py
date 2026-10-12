"""Real competing processes, deterministic barriers, no network/model calls."""
from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from graph_engine.brain import Brain, Edge, Node
from graph_engine.brain_engine import BrainEngine, write_lock_timeout_from_env
from graph_engine.embedder import HashEmbedder
from graph_engine.write_guard import BrainWriteTimeout, lock_path

CTX = mp.get_context("spawn")


def _holder(path: str, ready, release) -> None:
    with Brain(path).write_guard():
        ready.set()
        if not release.wait(20):
            raise RuntimeError("test holder was not released")


def _git_child_holder(path: str, ready: str, release: str) -> None:
    from graph_engine.write_guard import run_git
    with Brain(path).write_guard():
        script = ("from pathlib import Path; import time, sys; "
                  "Path(sys.argv[1]).touch(); "
                  "exec('while not Path(sys.argv[2]).exists():\\n time.sleep(0.01)')")
        run_git([sys.executable, "-c", script, ready, release], check=True)


def _interrupted_git_write(path: str, ready, release) -> None:
    brain = Brain(path, mode="git")
    with brain.write_guard():
        brain.pull()
        brain.write_node(Node("complete atomic file before interruption", id="interrupted"))
        ready.set()
        release.wait(20)  # interruption happens after write, before commit
        brain.commit_and_push("interrupted batch")


def _writers(path: str, barrier, worker: int, action: str, mode: str) -> None:
    brain = Brain(path, mode=mode)
    engine = BrainEngine(brain, HashEmbedder())
    barrier.wait(timeout=20)
    if action == "duplicates":
        engine.ingest("The user prefers replies in German.", source=f"source{worker}")
    elif action == "entities":
        engine.capture("Alice works at Acme.", extraction="rules")
    elif action == "unique":
        for i in range(3):
            engine.ingest(f"Separate record {worker}/{i}", allow_duplicates=True,
                          source=f"source{worker}")
    elif action == "rmw":
        for i in range(4):
            with brain.write_guard():
                node = brain.read_node("counter")
                vectors = brain.read_vectors()
                # Widen the exact stale-read window the contract protects.
                time.sleep(0.01)
                node.recall_count += 1
                brain.write_node(node)
                vectors[f"{worker}-{i}"] = [float(worker), float(i)]
                brain.write_vectors(vectors)
                brain.add_edge(Edge("counter", "counter", "linked", id=f"{worker}-{i}"))
    elif action == "recorder":
        from graph_engine.recall import record
        for i in range(30):
            record(brain, f"query {worker}-{i}", ["counter"])
    elif action == "aggregator":
        from graph_engine.recall import aggregate
        for _ in range(10):
            aggregate(brain, commit=False)
    else:
        raise AssertionError(action)


def _run_writers(path: Path, actions: list[str], mode: str = "local") -> None:
    barrier = CTX.Barrier(len(actions))
    children = [CTX.Process(target=_writers, args=(str(path), barrier, i, action, mode))
                for i, action in enumerate(actions)]
    try:
        for child in children:
            child.start()
        for child in children:
            child.join(30)
            assert not child.is_alive(), "writer hung"
            assert child.exitcode == 0
    finally:
        for child in children:
            if child.is_alive():
                child.kill()
                child.join(5)


@pytest.fixture
def held_brain(tmp_path):
    path = tmp_path / "brain"
    ready, release = CTX.Event(), CTX.Event()
    holder = CTX.Process(target=_holder, args=(str(path), ready, release))
    holder.start()
    try:
        assert ready.wait(10)
        yield path, holder, release
    finally:
        if holder.is_alive():
            release.set()
        holder.join(5)
        if holder.is_alive():
            holder.kill()
            holder.join(5)


def test_canonical_alias_timeout_and_reentrant_instances(held_brain, tmp_path):
    path, _, release = held_brain
    path.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(path, target_is_directory=True)
    assert lock_path(alias) == lock_path(path)
    before = time.monotonic()
    with pytest.raises(BrainWriteTimeout, match="IG_WRITE_LOCK_TIMEOUT"):
        with Brain(str(alias)).write_guard(timeout=0.1):
            pytest.fail("alias bypassed lock")
    assert time.monotonic() - before < 2
    release.set()
    with Brain(str(path)).write_guard(timeout=5):
        with Brain(str(alias / ".." / "brain")).write_guard(timeout=0):
            Brain(str(alias)).write_node(Node("nested", id="n"))
    assert Brain(str(path)).read_node("n").text == "nested"


def test_terminated_writer_releases_kernel_lock(held_brain):
    path, holder, _ = held_brain
    artifact = lock_path(path)
    inode = artifact.stat().st_ino
    holder.kill()
    holder.join(5)
    assert holder.exitcode != 0
    with Brain(str(path)).write_guard(timeout=1):
        Brain(str(path)).write_node(Node("after killed writer", id="n"))
    assert artifact.stat().st_ino == inode  # no stale-lock deletion/recreation


def test_thread_wait_is_bounded_and_reentrant(tmp_path):
    brain = Brain(str(tmp_path / "brain"))
    outcomes = []

    def contender() -> None:
        try:
            with brain.write_guard(timeout=0.05):
                outcomes.append("acquired")
        except BrainWriteTimeout:
            outcomes.append("busy")

    with brain.write_guard():
        thread = threading.Thread(target=contender)
        thread.start()
        thread.join(2)
        assert not thread.is_alive()
        with Brain(str(brain.path)).write_guard(timeout=0):
            pass
    assert outcomes == ["busy"]


@pytest.mark.parametrize("raw", ["nan", "inf", "-1", "3601", "abc", ""])
def test_invalid_wait_configuration(monkeypatch, raw):
    monkeypatch.setenv("IG_WRITE_LOCK_TIMEOUT", raw)
    with pytest.raises(ValueError, match="IG_WRITE_LOCK_TIMEOUT"):
        write_lock_timeout_from_env()


def test_separate_process_rmw_keeps_all_records(tmp_path):
    brain = Brain(str(tmp_path / "brain"))
    brain.write_node(Node("counter", id="counter"))
    _run_writers(brain.path, ["rmw"] * 3)
    assert brain.read_node("counter").recall_count == 12
    assert len(brain.read_vectors()) == 12
    assert len(brain.read_edges()) == 12
    for file in (brain.edges_file, brain.vectors_file):
        rows = [json.loads(line) for line in file.read_text().splitlines()]
        assert len({row["id"] for row in rows}) == 12


def test_recording_during_aggregation_loses_no_recalls(tmp_path):
    from graph_engine.recall import aggregate, read_ledger
    brain = Brain(str(tmp_path / "brain"))
    brain.write_node(Node("counter", id="counter"))
    _run_writers(brain.path, ["recorder", "aggregator", "recorder"])
    aggregate(brain, commit=False)
    assert brain.read_node("counter").recall_count == 60
    assert read_ledger(brain) == []
    aggregate(brain, commit=False)
    assert brain.read_node("counter").recall_count == 60


def _git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


@pytest.mark.parametrize("action", ["duplicates", "unique", "entities"])
def test_simultaneous_git_writers_have_clean_commits(tmp_path, action):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)],
                   check=True, capture_output=True)
    brain = Brain(str(tmp_path / "brain"), mode="git")
    brain.init(remote=str(bare))
    _run_writers(brain.path, [action] * 3, mode="git")
    nodes = brain.read_nodes()
    if action == "duplicates":
        assert len(nodes) == 1
        assert set(nodes[0].sources) == {"source0", "source1", "source2"}
    elif action == "unique":
        assert len(nodes) == 9
        assert len(brain.read_vectors()) == 9
    else:
        assert len([n for n in nodes if n.ntype == "entity"]) == 2
        assert len([n for n in nodes if n.capture]) == 1
        assert len([e for e in brain.read_edges() if e.kind == "fact"]) == 1
    assert _git(brain.path, "status", "--porcelain") == ""
    assert _git(brain.path, "rev-parse", "HEAD") == _git(bare, "rev-parse", "main")
    assert not any(".lock" in name for name in _git(brain.path, "ls-files").splitlines())
    _git(brain.path, "fsck", "--no-dangling")
    assert not (brain.path / ".git" / "index.lock").exists()


def test_cli_and_http_report_actionable_busy(held_brain, monkeypatch):
    from fastapi.testclient import TestClient
    from graph_engine import runtime
    from graph_engine.server import app
    path, _, _ = held_brain
    monkeypatch.setenv("IG_BRAIN_PATH", str(path))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    monkeypatch.setenv("IG_WRITE_LOCK_TIMEOUT", "0.05")
    monkeypatch.delenv("IG_ACCESS_POLICY", raising=False)
    runtime.reset_engine_cache()
    response = TestClient(app).post("/api/ingest", json={"text": "contending writer"})
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert "busy" in response.json()["error"]
    # HTTP errors don't disclose local filesystem paths.
    assert str(path) not in response.text
    result = subprocess.run([sys.executable, "-m", "graph_engine", "ingest", "cli writer"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "Brain writer busy" in result.stderr + result.stdout
    assert "IG_WRITE_LOCK_TIMEOUT" in result.stderr + result.stdout
    assert not (path / "nodes").exists()
    runtime.reset_engine_cache()


def test_read_only_vectors_create_no_lock_artifact(tmp_path):
    brain = Brain(str(tmp_path / "absent-brain"))
    assert brain.vectors_for(set(), lambda _: [], persist=False) == {}
    assert list(tmp_path.iterdir()) == []


def test_all_mutation_families_wait_before_reading(held_brain, monkeypatch):
    from graph_engine import agent_memory, consolidation, dream, entities, feedback, recall, review, tiers
    from graph_engine.merge import merge_nodes
    from graph_engine.report import write_report
    path, _, _ = held_brain
    monkeypatch.setenv("IG_WRITE_LOCK_TIMEOUT", "0")
    brain = Brain(str(path))
    engine = BrainEngine(brain, HashEmbedder())
    operations = [
        lambda: engine.ingest("note"),
        lambda: engine.capture("Alice works at Acme.", extraction="rules"),
        lambda: engine.observe("event"),
        lambda: engine.extract("n"),
        lambda: engine.resolve("e", True),
        lambda: engine.undo("e"),
        lambda: engine.link("n", "m"),
        lambda: engine.consolidate(),
        lambda: engine.demote_forgotten(lambda _: "tombstone"),
        lambda: entities.extract_entities(brain, "Alice works at Acme."),
        lambda: consolidation.consolidate(brain),
        lambda: dream.refresh(brain),
        lambda: dream.lifecycle(brain),
        lambda: dream.distill(brain),
        lambda: merge_nodes(brain, "n", "m"),
        lambda: tiers.set_tier(brain, "n", "main"),
        lambda: tiers.rebalance(brain),
        lambda: feedback.record_feedback(engine, "query", "n", "relevant"),
        lambda: recall.record(brain, "query", ["n"]),
        lambda: recall.record(brain=brain, query="query", node_ids=["n"]),
        lambda: recall.aggregate(brain),
        lambda: review.accept_pending(brain),
        lambda: agent_memory.forget(brain, "n", reason="test"),
        lambda: write_report(brain),
        lambda: brain.init(),
        lambda: brain.add_edge(Edge("n", "m", "linked")),
        lambda: brain.vectors_for({"n"}, lambda _: [1.0]),
    ]
    for operation in operations:
        with pytest.raises(BrainWriteTimeout):
            operation()
    assert not path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX descriptor inheritance")
def test_git_child_keeps_guard_after_parent_death(tmp_path):
    path = tmp_path / "brain"
    ready, release = tmp_path / "ready", tmp_path / "release"
    owner = CTX.Process(target=_git_child_holder, args=(str(path), str(ready), str(release)))
    owner.start()
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        owner.kill()
        owner.join(5)
        with pytest.raises(BrainWriteTimeout):
            with Brain(str(path)).write_guard(timeout=0.05):
                pass
        release.touch()
        with Brain(str(path)).write_guard(timeout=5):
            pass
    finally:
        release.touch()
        if owner.is_alive():
            owner.kill()
        owner.join(5)


def test_interruption_before_commit_leaves_recoverable_git_state(tmp_path):
    brain = Brain(str(tmp_path / "brain"), mode="git")
    brain.init()
    ready, release = CTX.Event(), CTX.Event()
    owner = CTX.Process(target=_interrupted_git_write, args=(str(brain.path), ready, release))
    owner.start()
    try:
        assert ready.wait(10)
        owner.kill()
        owner.join(5)

        assert brain.read_node("interrupted").text == "complete atomic file before interruption"
        assert "interrupted.md" in _git(brain.path, "status", "--porcelain", "--untracked-files=all")
        # The next writer can commit the pending file; no reset or stale-lock deletion.
        BrainEngine(brain, HashEmbedder()).ingest("next writer", allow_duplicates=True)
        assert len(brain.read_nodes()) == 2
        assert _git(brain.path, "status", "--porcelain") == ""
        _git(brain.path, "fsck", "--no-dangling")
    finally:
        if owner.is_alive():
            release.set()
            owner.kill()
        owner.join(5)


def test_failed_push_preserves_local_commit_and_can_retry_sync(tmp_path, capsys):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)],
                   check=True, capture_output=True)
    brain = Brain(str(tmp_path / "brain"), mode="git")
    brain.init(remote=str(bare))
    hook = bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o700)
    with pytest.raises(RuntimeError, match="commit IS local"):
        BrainEngine(brain, HashEmbedder()).ingest("saved despite rejected push")
    assert "UNCOMMITTED" not in capsys.readouterr().err
    assert len(brain.read_nodes()) == 1
    assert _git(brain.path, "status", "--porcelain") == ""
    assert _git(brain.path, "rev-parse", "HEAD") != _git(bare, "rev-parse", "main")
    hook.unlink()
    brain.commit_and_push("retry sync", sync_pending=True)
    assert _git(brain.path, "rev-parse", "HEAD") == _git(bare, "rev-parse", "main")

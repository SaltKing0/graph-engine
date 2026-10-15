"""Regression: `aggregate` must never fold the same ledger line twice.

Found live 2026-09-18: `dream.refresh()` calls `aggregate(commit=False)` to batch
the commit, but the ledger move/truncate was tied to `commit` — so the counters
were written while the source entries stayed in place, and EVERY refresh folded
them again (`recall_count` 1 -> 2 on a single real ledger line). That inflates
exactly the signal the promotion gates read.
"""
import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.brain import Brain, Node
from graph_engine.dream import refresh
from graph_engine.recall import aggregate, record, fingerprint, ledger_path


def _brain(tmp_path) -> Brain:
    b = Brain(str(tmp_path / "brain"), mode="local")
    b.write_node(Node(id="a", text="node a"))
    b.write_node(Node(id="b", text="node b"))
    return b


def test_aggregate_is_idempotent_with_commit_false(tmp_path):
    b = _brain(tmp_path)
    record(b, "q one", ["a"])

    first = aggregate(b, commit=False)
    second = aggregate(b, commit=False)

    assert first["recalls"] == 1 and second["recalls"] == 0, "no double count"
    assert {n.id: n.recall_count for n in b.read_nodes()}["a"] == 1
    assert (Path(b.path) / "recalls.jsonl.processed").exists(), "ledger moved"


def test_aggregate_is_idempotent_with_commit_true(tmp_path):
    b = _brain(tmp_path)
    record(b, "q one", ["a"])

    aggregate(b)
    aggregate(b)

    assert {n.id: n.recall_count for n in b.read_nodes()}["a"] == 1


def test_dream_refresh_does_not_inflate_recall_count(tmp_path):
    b = _brain(tmp_path)
    record(b, "q one", ["a", "b"])

    refresh(b)
    refresh(b)
    refresh(b)

    counts = {n.id: n.recall_count for n in b.read_nodes()}
    assert counts == {"a": 1, "b": 1}, f"counters inflated: {counts}"


def test_aggregate_accumulates_across_distinct_events(tmp_path):
    """Two real recalls must still count twice — the fix must not undercount."""
    b = _brain(tmp_path)
    record(b, "q one", ["a"])
    aggregate(b, commit=False)
    record(b, "q two", ["a"])
    aggregate(b, commit=False)

    assert {n.id: n.recall_count for n in b.read_nodes()}["a"] == 2
    assert {n.id: len(n.recall_queries) for n in b.read_nodes()}["a"] == 2


def test_dry_run_keeps_the_ledger(tmp_path):
    b = _brain(tmp_path)
    record(b, "q one", ["a"])

    res = aggregate(b, dry_run=True)

    assert res["recalls"] == 1
    assert (Path(b.path) / "recalls.jsonl").read_text(encoding="utf-8").strip() != ""
    assert not (Path(b.path) / "recalls.jsonl.processed").exists()
    assert {n.id: n.recall_count for n in b.read_nodes()}["a"] == 0


@pytest.mark.parametrize("fail_after", [1, 2])
def test_retry_after_durable_counter_write(tmp_path, monkeypatch, fail_after):
    b = _brain(tmp_path)
    record(b, "first query", ["a", "b"], ts="2026-10-14T10:00:00Z")
    record(b, "second query", ["b"], ts="2026-10-14T11:00:00Z")
    original = ledger_path(b).read_bytes()
    write = b.write_node
    calls = 0

    def interrupted(node):
        nonlocal calls
        write(node)
        calls += 1
        if calls == fail_after:
            raise OSError("after durable counter write")

    with monkeypatch.context() as patch:
        patch.setattr(b, "write_node", interrupted)
        with pytest.raises(OSError):
            aggregate(b, commit=False)

    # Recovery must work with a new Brain instance, not an in-memory receipt.
    recovered = Brain(str(b.path), mode="local")
    aggregate(recovered, commit=False)
    aggregate(recovered, commit=False)
    a, b_node = recovered.read_node("a"), recovered.read_node("b")
    assert a.recall_count == 1
    assert b_node.recall_count == 2
    assert a.recall_queries == [fingerprint("first query")]
    assert b_node.recall_queries == sorted(map(fingerprint, ["first query", "second query"]))
    assert a.last_recalled == "2026-10-14T10:00:00Z"
    assert b_node.last_recalled == "2026-10-14T11:00:00Z"
    assert (b.path / "recalls.jsonl.processed").read_bytes() == original


def test_retry_sync_after_local_commit(tmp_path, monkeypatch):
    b = Brain(str(tmp_path / "brain"), mode="git")
    b.init()
    b.write_node(Node("node a", id="a"))
    record(b, "q", ["a"])
    commit = b.commit_and_push
    calls = []

    def interrupted(message, **kwargs):
        commit(message, push=False)
        raise OSError("after local commit, before push")

    with monkeypatch.context() as patch:
        patch.setattr(b, "commit_and_push", interrupted)
        with pytest.raises(OSError):
            aggregate(b)

    def synced(message, **kwargs):
        calls.append(kwargs)
        commit(message, **kwargs)

    monkeypatch.setattr(b, "commit_and_push", synced)
    aggregate(b)
    assert b.read_node("a").recall_count == 1
    assert calls and calls[0].get("sync_pending") is True


@pytest.mark.parametrize(("boundary", "commit"), [
    (boundary, commit)
    for boundary in [
        "rotate", "journal_before", "journal_after", "archive_partial", "archive_after",
        "checkpoint_before", "checkpoint_after", "cleanup", "rebalance", "commit_before",
        "commit_after",
    ]
    for commit in [False, True]
    if commit or not boundary.startswith("commit_")
])
def test_generation_recovers_every_boundary(tmp_path, monkeypatch, boundary, commit):
    from graph_engine import recall, tiers

    b = _brain(tmp_path)
    # Seed real historical counters and archive bytes; recovery must retain both.
    old = b.read_node("b")
    old.recall_count = 1
    old.recall_queries = ["historic"]
    old.last_recalled = "2026-01-01T00:00:00Z"
    b.write_node(old)
    prior = b'{"legacy": "previous archive"}\n'
    processed = b.path / "recalls.jsonl.processed"
    processed.write_bytes(prior)
    # Legacy lines have no event IDs; identical real events still count twice.
    record(b, "first query", ["a", "b"])
    line = ledger_path(b).read_bytes()
    with ledger_path(b).open("ab") as fh:
        fh.write(line)
    record(b, "second query", ["b"])
    source = ledger_path(b).read_bytes()

    def fail():
        raise OSError("synthetic interruption: " + boundary)

    with monkeypatch.context() as patch:
        if boundary == "rotate":
            replace = recall.os.replace

            def interrupted(src, dst):
                replace(src, dst)
                if Path(dst).name == "pending.jsonl":
                    fail()

            patch.setattr(recall.os, "replace", interrupted)
        elif boundary.startswith(("journal_", "checkpoint_")):
            atomic_write = recall._atomic_write
            checkpoint = boundary.startswith("checkpoint_")

            def interrupted(path, content):
                hit = (path.name == "projection.json"
                       and json.loads(content)["applied"] == checkpoint)
                if hit and boundary.endswith("before"):
                    fail()
                atomic_write(path, content)
                if hit:
                    fail()

            patch.setattr(recall, "_atomic_write", interrupted)
        elif boundary.startswith("archive_"):
            archive = recall._archive_generation

            def interrupted(path, pending, offset):
                if boundary == "archive_partial":
                    # A real partial append, including a split JSON line.
                    with path.open("ab") as fh:
                        fh.write(pending.read_bytes()[:17])
                else:
                    archive(path, pending, offset)
                fail()

            patch.setattr(recall, "_archive_generation", interrupted)
        elif boundary == "cleanup":
            unlink = Path.unlink

            def interrupted(path, *args, **kwargs):
                unlink(path, *args, **kwargs)
                if path.name == "pending.jsonl":
                    fail()

            patch.setattr(Path, "unlink", interrupted)
        elif boundary == "rebalance":
            rebalance = tiers.rebalance

            def interrupted(*args, **kwargs):
                rebalance(*args, **kwargs)
                fail()

            patch.setattr(tiers, "rebalance", interrupted)
        else:
            sync = b.commit_and_push

            def interrupted(*args, **kwargs):
                if boundary == "commit_after":
                    sync(*args, **kwargs)
                fail()

            patch.setattr(b, "commit_and_push", interrupted)
        with pytest.raises(OSError, match="synthetic interruption"):
            aggregate(b, commit=commit)

    # Recording can continue between attempts; do not truncate these new events.
    record(b, "new after interruption", ["a"])
    new_source = ledger_path(b).read_bytes()
    edited = b.read_node("a")
    edited.text = "edited after interruption"
    edited.tags = ["keep"]
    b.write_node(edited)
    before = {p: p.read_bytes() for p in b.path.rglob("*") if p.is_file()}
    aggregate(b, dry_run=True, commit=commit)
    assert {p: p.read_bytes() for p in b.path.rglob("*") if p.is_file()} == before

    recovered = Brain(str(b.path), mode="local")
    result = aggregate(recovered, commit=commit)
    assert result["recalls"] == 6
    assert aggregate(recovered, commit=commit)["recalls"] == 0
    a, bn = recovered.read_node("a"), recovered.read_node("b")
    assert (a.recall_count, bn.recall_count) == (3, 4)
    assert set(a.recall_queries) == set(map(fingerprint, ["first query", "new after interruption"]))
    assert bn.recall_queries == ["historic"] + sorted(map(fingerprint, ["first query", "second query"]))
    assert a.last_recalled and bn.last_recalled
    assert a.storage_tier == bn.storage_tier == "main"
    assert a.text == "edited after interruption" and a.tags == ["keep"]
    assert processed.read_bytes() == prior + source + new_source
    assert ledger_path(b).read_bytes() == b""
    assert not (b.path / ".recall" / "projection.json").exists()
    assert not (b.path / ".recall" / "pending.jsonl").exists()


def test_process_death_after_counter_write(tmp_path):
    import subprocess

    b = _brain(tmp_path)
    record(b, "q", ["a", "b"])
    script = '''
import os, sys
from graph_engine.brain import Brain
from graph_engine.recall import aggregate
b = Brain(sys.argv[1], mode="local")
write = b.write_node
def killed(node):
    write(node)
    os._exit(77)
b.write_node = killed
aggregate(b, commit=False)
'''
    child = subprocess.run([sys.executable, "-c", script, str(b.path)], check=False)
    assert child.returncode == 77
    aggregate(b, commit=False)
    assert {n.id: n.recall_count for n in b.read_nodes()} == {"a": 1, "b": 1}


def test_recovery_does_not_resurrect_deleted_node(tmp_path, monkeypatch):
    from graph_engine import recall

    b = _brain(tmp_path)
    record(b, "q", ["a", "b"])

    def interrupted(*args):
        raise OSError("interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(recall, "_archive_generation", interrupted)
        with pytest.raises(OSError):
            aggregate(b, commit=False)
    b.node_path("b").unlink()
    aggregate(b, commit=False)
    assert b.read_node("b") is None
    assert b.read_node("a").recall_count == 1


def test_recovery_pushes_existing_commit_to_real_remote(tmp_path):
    import subprocess

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)],
                   check=True, capture_output=True)
    b = Brain(str(tmp_path / "brain"), mode="git")
    b.init(remote=str(remote))
    b.write_node(Node("node a", id="a"))
    record(b, "q", ["a"])
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    with pytest.raises(RuntimeError, match="git push failed"):
        aggregate(b)
    assert b.read_node("a").recall_count == 1
    assert (b.path / ".recall" / "projection.json").exists()
    hook.unlink()

    aggregate(Brain(str(b.path), mode="git"))
    pushed = subprocess.check_output(
        ["git", "--git-dir", str(remote), "show", "main:nodes/a.md"], text=True)
    assert "recalls: 1\n" in pushed
    tracked = subprocess.check_output(
        ["git", "-C", str(b.path), "ls-files"], text=True)
    assert ".recall/" not in tracked
    assert not (b.path / ".recall" / "projection.json").exists()

"""Git-mode + crash-safety tests (audit #57: all tests ran mode="local" only).

Covers: git-mode ingest/commit/push against a local bare remote, pull --rebase
on a stale clone, push-failure signaling (#31), and truncated-JSONL recovery.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from graph_engine.brain import Brain, Edge, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder


def _git(*args: str, cwd: str = None) -> subprocess.CompletedProcess:
    kwargs = {"capture_output": True, "text": True}
    if cwd is not None:
        kwargs["cwd"] = cwd
    return subprocess.run(["git", *args], **kwargs)


@pytest.fixture()
def remote(tmp_path):
    """A bare git remote + an initialized git-mode brain cloned from it."""
    bare = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(bare))
    brain = Brain(str(tmp_path / "brain"), mode="git", remote=str(bare))
    brain.init(remote=str(bare), commit=True)
    return bare, brain


def test_git_mode_ingest_commits(remote):
    bare, brain = remote
    engine = BrainEngine(brain, HashEmbedder())
    engine.ingest("Git mode commits every ingest", source="test")
    log = _git("log", "--oneline", cwd=str(brain.path)).stdout
    assert "ingest" in log.lower() or "+" in log
    # pushed to remote
    _git("fetch", "origin", cwd=str(brain.path))
    head_local = _git("rev-parse", "HEAD", cwd=str(brain.path)).stdout.strip()
    head_remote = _git("rev-parse", "origin/main", cwd=str(brain.path)).stdout.strip()
    assert head_local == head_remote


def test_git_mode_stale_clone_pulls_rebase(remote, tmp_path):
    """Two engines on the same remote: the second one pulls before writing."""
    bare, brain1 = remote
    # second clone of the same remote
    brain2 = Brain(str(tmp_path / "brain2"), mode="git", remote=str(bare))
    brain2.init(remote=str(bare), commit=True)
    BrainEngine(brain1, HashEmbedder()).ingest("First engine writes node A", source="t1")
    # brain2 was cloned before brain1's write — ensure_ready must pull it in
    engine2 = BrainEngine(brain2, HashEmbedder())
    engine2.ingest("Second engine writes node B", source="t2")
    texts = {n.text for n in brain2.read_nodes()}
    assert any("node A" in t for t in texts)


def test_git_mode_push_failure_signals_cleanly(remote, tmp_path):
    """#31: a push failure is an actionable error, local commit is NOT lost."""
    bare, brain = remote
    engine = BrainEngine(brain, HashEmbedder())
    engine.ingest("Node before the remote disappears", source="test")
    # break the remote (simulate network/permission failure)
    broken = tmp_path / "broken.git"
    bare.rename(broken)
    with pytest.raises(Exception) as exc:
        engine.ingest("Node while the remote is gone", source="test")
    # actionable message, not a bare stack of git noise
    msg = str(exc.value)
    assert ("push" in msg.lower()) or ("commit" in msg.lower())
    # the local commit exists — nothing lost
    log = _git("log", "--oneline", cwd=str(brain.path)).stdout
    assert len(log.strip().splitlines()) >= 2
    # and the derived index is consistent (healed or rebuilt)
    assert (brain.path / "INDEX.md").exists()


def test_truncated_jsonl_recovery(tmp_path):
    """#17-family: a truncated final line (crash mid-write) doesn't kill reads.

    Node records are per-file markdown; the JSONL stores edges + vectors."""
    brain = Brain(str(tmp_path / "brain"), mode="local")
    brain.write_node(Node(id="a", text="alpha"))
    brain.write_node(Node(id="b", text="beta"))
    brain.write_vectors({"a": [1.0, 0.0], "b": [0.0, 1.0]})
    brain.write_edges([Edge(source="a", target="b", kind="similar")])
    # simulate a crash mid-write on BOTH jsonl files
    with (brain.path / "vectors.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"id": "c", "vec": [0.5')
    with (brain.path / "edges.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"source": "a", "target"')
    # good data survives, partial lines are skipped
    assert {n.text for n in brain.read_nodes()} == {"alpha", "beta"}
    assert len(brain.read_edges()) == 1
    vecs = brain.read_vectors()
    assert "a" in vecs and "b" in vecs and "c" not in vecs


def test_init_against_existing_remote_clones(tmp_path):
    """Regression: onboarding a second machine must clone, not fork the brain.

    `ig init --remote <brain>` on a machine without a clone used to create a
    second, unrelated root commit; the push was then rejected as a
    non-fast-forward and the brain looked broken.
    """
    bare = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(bare))
    first = Brain(str(tmp_path / "brain1"), mode="git", remote=str(bare))
    first.init(remote=str(bare), commit=True)
    BrainEngine(first, HashEmbedder()).ingest("First engine writes node A", source="t1")

    second = Brain(str(tmp_path / "brain2"), mode="git", remote=str(bare))
    second.init(remote=str(bare), commit=True)  # must clone the existing brain
    assert any("node A" in n.text for n in second.read_nodes())

    # and it stays pushable afterwards
    BrainEngine(second, HashEmbedder()).ingest("Second engine writes node B", source="t2")
    _git("fetch", "origin", cwd=str(second.path))
    head = _git("rev-parse", "HEAD", cwd=str(second.path)).stdout.strip()
    remote_head = _git("rev-parse", "origin/main", cwd=str(second.path)).stdout.strip()
    assert head == remote_head


def test_crash_between_node_and_edge_write_leaves_readable_brain(tmp_path):
    """#31-family: an interrupted ingest sequence leaves a READABLE brain."""
    brain = Brain(str(tmp_path / "brain"), mode="local")
    brain.write_node(Node(id="a", text="alpha"))
    brain.add_edge(Edge(source="a", target="a", kind="similar"))
    # simulate half-written edges file
    edges_file = brain.path / "edges.jsonl"
    with edges_file.open("a", encoding="utf-8") as fh:
        fh.write('{"source": "a", "target"')
    nodes = brain.read_nodes()
    edges = brain.read_edges()
    assert len(nodes) == 1
    assert len(edges) == 1  # the good edge survives, the partial line is skipped

"""Storage tiers are independent, persisted, and honored across reranking."""
from datetime import datetime, timezone

import pytest

from graph_engine.brain import Brain, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder
from graph_engine.recall import aggregate, record
from graph_engine.reranker import ReverseReranker
from graph_engine.retrieval import explain, retrieve
from graph_engine.tiers import cmd_tier, rebalance, recommended_tier, set_tier

NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def test_tier_roundtrip_and_legacy_default():
    node = Node("alpha", storage_tier="archival", tier_locked=True, ntype="episodic", status="stale")
    restored = Node.from_markdown(node.to_markdown())
    assert restored.storage_tier == "archival" and restored.tier_locked
    assert restored.status == "stale" and restored.ntype == "episodic"
    assert restored.to_dict()["storage_tier"] == "archival"
    legacy = "---\nid: old\ncreated: 2020-01-01T00:00:00Z\n---\n\nalpha"
    assert Node.from_markdown(legacy).storage_tier == "recall"
    with pytest.raises(ValueError, match="storage tier"):
        Node("alpha", storage_tier="other")


@pytest.mark.parametrize("tier,count,last,created,expected", [
    ("recall", 3, "2026-10-03T00:00:00Z", "2025-01-01", "main"),
    ("archival", 1, "2026-10-03T00:00:00Z", "2025-01-01", "recall"),
    ("main", 3, "2026-09-20T00:00:00Z", "2025-01-01", "main"),
    ("main", 9, "2026-09-03T00:00:00Z", "2025-01-01", "recall"),
    ("recall", 100, "2026-07-01T00:00:00Z", "2025-01-01", "archival"),
    ("recall", 0, None, "2025-01-01", "archival"),
    ("main", 0, None, "invalid", "main"),
])
def test_policy_uses_recall_and_age(tier, count, last, created, expected):
    node = Node("alpha", storage_tier=tier, recall_count=count, last_recalled=last, created=created)
    assert recommended_tier(node, now=NOW) == expected


def test_manual_tiers_are_pinned_and_auto_resets(tmp_path):
    brain = Brain(tmp_path)
    brain.write_node(Node("alpha", id="a", created="2000-01-01"))
    assert set_tier(brain, "a", "main").tier_locked
    assert rebalance(brain, now=NOW) == []
    assert set_tier(brain, "a", None).storage_tier == "archival"
    assert not brain.read_node("a").tier_locked
    with pytest.raises(ValueError, match="No node"):
        set_tier(brain, "missing", "main")


def test_rebalance_dry_run_tombstones_and_idle_aggregation(tmp_path):
    brain = Brain(tmp_path)
    brain.write_node(Node("alpha", id="old", created="2000-01-01"))
    brain.write_node(Node("alpha", id="dead", created="2000-01-01", status="tombstone"))
    before = {p.name: p.read_bytes() for p in (tmp_path / "nodes").iterdir()}
    assert rebalance(brain, dry_run=True, now=NOW) == [{"node_id": "old", "from": "recall", "to": "archival"}]
    aggregate(brain, dry_run=True)
    assert before == {p.name: p.read_bytes() for p in (tmp_path / "nodes").iterdir()}
    aggregate(brain)
    assert brain.read_node("old").storage_tier == "archival"
    assert brain.read_node("dead").storage_tier == "recall"


def test_aggregation_automatically_promotes_recalled_memory(tmp_path):
    brain = Brain(tmp_path)
    brain.write_node(Node("alpha", id="a", storage_tier="archival"))
    for _ in range(3):
        record(brain, "alpha", ["a"])
    aggregate(brain)
    assert brain.read_node("a").storage_tier == "main"


@pytest.mark.parametrize("rerank", [False, True])
def test_tiers_precede_candidate_cutoff_and_reranker(tmp_path, rerank):
    brain = Brain(tmp_path)
    for nid, tier in [("a", "archival"), ("b", "recall"), ("c", "main")]:
        brain.write_node(Node("alpha", id=nid, storage_tier=tier))
    engine = BrainEngine(brain, HashEmbedder())
    if rerank:
        engine.reranker = ReverseReranker()
    assert [nid for nid, _ in retrieve(engine, "alpha", persist=False)] == ["c", "b", "a"]
    assert retrieve(engine, "alpha", k=1, rerank_k=1, persist=False)[0][0] == "c"
    result = explain(engine, "c", "alpha", k=1)
    assert result["rank"] == 1 and result["storage_tier"] == "main"
    assert explain(engine, "a", "alpha", rerank_k=1)["reason"] == "outside_candidate_limit"


def test_tier_cli_read_set_and_rebalance(tmp_path, capsys):
    brain = Brain(tmp_path)
    brain.write_node(Node("alpha", id="a"))
    engine = BrainEngine(brain, HashEmbedder())
    cmd_tier(engine, ["a", "archival", "--json"])
    assert '"storage_tier": "archival"' in capsys.readouterr().out
    cmd_tier(engine, ["a"])
    assert "manual" in capsys.readouterr().out
    cmd_tier(engine, ["--rebalance", "--dry-run", "--json"])
    assert '"dry_run": true' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cmd_tier(engine, ["a", "--dry-run"])

"""Tests for context window management (Phase 3: smart context assembly).

Covers:
- estimate_tokens: rough token estimation
- build_context: context assembly with budget
- hierarchical_context: main → recall → archival tiers
- context_for_prompt: simple interface
- context_stats: statistics about context build
"""

from __future__ import annotations

import pytest

from graph_engine.brain import Brain


@pytest.fixture
def brain(tmp_path):
    b = Brain(path=tmp_path / "brain", mode="local")
    b.ensure_ready()
    return b


@pytest.fixture
def engine(brain):
    from graph_engine.brain_engine import BrainEngine
    return BrainEngine(brain)


class TestEstimateTokens:
    def test_empty_string(self):
        from graph_engine.context import estimate_tokens
        assert estimate_tokens("") == 0

    def test_ascii_text(self):
        from graph_engine.context import estimate_tokens
        # 40 ASCII chars ≈ 10 tokens
        assert estimate_tokens("a" * 40) == 10

    def test_cjk_text(self):
        from graph_engine.context import estimate_tokens
        # 10 CJK chars ≈ 10 tokens
        assert estimate_tokens("汉" * 10) == 10

    def test_mixed_text(self):
        from graph_engine.context import estimate_tokens
        # 20 ASCII + 10 CJK = 5 + 10 = 15 tokens
        assert estimate_tokens("a" * 20 + "汉" * 10) == 15


class TestBuildContext:
    def test_empty_brain(self, engine):
        from graph_engine.context import build_context
        result = build_context(engine, "query")
        assert result["context"] == ""
        assert result["tokens"] == 0
        assert result["nodes"] == []
        assert result["truncated"] is False

    def test_returns_context_with_nodes(self, engine):
        from graph_engine.context import build_context
        engine.ingest("Memory systems are important for AI agents")
        engine.ingest("Retrieval augmented generation combines search with LLMs")
        result = build_context(engine, "memory systems")
        assert result["context"] != ""
        assert result["tokens"] > 0
        assert len(result["nodes"]) > 0
        assert result["truncated"] is False

    def test_respects_budget(self, engine):
        from graph_engine.context import build_context
        for i in range(20):
            # Keep the budget fixture large even when a semantic embedder
            # considers these near-identical notes duplicates.
            engine.ingest(f"Fact number {i} about memory systems and AI agents",
                          allow_duplicates=True)
        result = build_context(engine, "memory", budget=100)
        assert result["tokens"] <= 100
        assert result["truncated"] is True

    def test_no_budget_truncation(self, engine):
        from graph_engine.context import build_context
        engine.ingest("Short fact")
        result = build_context(engine, "short", budget=10000)
        assert result["truncated"] is False

    def test_includes_metadata(self, engine):
        from graph_engine.context import build_context
        engine.ingest("Memory systems are important")
        result = build_context(engine, "memory", include_metadata=True)
        assert "[semantic" in result["context"]

    def test_excludes_metadata(self, engine):
        from graph_engine.context import build_context
        engine.ingest("Memory systems are important")
        result = build_context(engine, "memory", include_metadata=False)
        assert "[semantic" not in result["context"]


class TestHierarchicalContext:
    def test_returns_same_as_build_context(self, engine):
        from graph_engine.context import hierarchical_context, build_context
        engine.ingest("Memory systems are important for AI agents")
        result = hierarchical_context(engine, "memory")
        expected = build_context(engine, "memory", budget=4000)
        assert result["context"] == expected["context"]
        assert result["tokens"] == expected["tokens"]


class TestContextForPrompt:
    def test_returns_string(self, engine):
        from graph_engine.context import context_for_prompt
        engine.ingest("Memory systems are important")
        result = context_for_prompt(engine, "memory")
        assert isinstance(result, str)
        assert "Memory systems" in result

    def test_empty_for_no_results(self, engine):
        from graph_engine.context import context_for_prompt
        result = context_for_prompt(engine, "nonexistent")
        assert result == ""


class TestContextStats:
    def test_returns_stats(self, engine):
        from graph_engine.context import context_stats
        for i in range(10):
            engine.ingest(f"Fact {i} about memory systems")
        stats = context_stats(engine, "memory")
        assert stats["query"] == "memory"
        assert stats["budget"] == 4000
        assert "tiers" in stats
        assert "main" in stats["tiers"]
        assert "recall" in stats["tiers"]
        assert "archival" in stats["tiers"]

    def test_empty_stats(self, engine):
        from graph_engine.context import context_stats
        stats = context_stats(engine, "nonexistent")
        assert stats["tiers"] == {}


def _write(engine, nid, text="memory content", tier="recall", **kwargs):
    from graph_engine.brain import Node
    node = Node(id=nid, text=text, storage_tier=tier, **kwargs)
    engine.brain.write_node(node)
    return node


def _rank(monkeypatch, ids):
    monkeypatch.setattr("graph_engine.retrieval.retrieve",
                        lambda *a, **kw: [(nid, 1.0) for nid in ids])


def test_oversized_first_memory_is_packed(engine, monkeypatch):
    from graph_engine.context import build_context, estimate_tokens
    _write(engine, "huge", "memory " * 2000, "main")
    _rank(monkeypatch, ["huge"])
    result = build_context(engine, "memory", budget=80)
    assert result["nodes"] == ["huge"]
    assert "memory " in result["context"]
    assert result["context"].endswith("… [truncated]")
    assert result["tokens"] == estimate_tokens(result["context"]) <= 80
    assert result["truncated"] and result["memories"][0]["truncated"]


@pytest.mark.parametrize("budget", [0, 1, 5, 15, 30, 100, 500])
def test_tiny_and_empty_budgets_ids_are_exact(engine, monkeypatch, budget):
    import re
    from graph_engine.context import build_context, estimate_tokens
    for tier in ("main", "recall", "archival"):
        _write(engine, tier, "汉字memory " * 100, tier)
    _rank(monkeypatch, ["main", "recall", "archival"])
    result = build_context(engine, "memory", budget=budget)
    assert result["tokens"] == estimate_tokens(result["context"]) <= budget
    assert re.findall(r"\[memory:([^\]]+)\]", result["context"]) == result["nodes"]
    assert [m["id"] for m in result["memories"]] == result["nodes"]
    if budget <= 5:
        assert result["nodes"] == [] and result["context"] == ""
        assert result["omitted"] == 3 and result["truncated"]


def test_sections_follow_storage_tiers_not_rank_slices(engine, monkeypatch):
    from graph_engine.context import build_context, context_stats
    for tier in ("main", "recall", "archival"):
        _write(engine, tier, f"memory in {tier}", tier)
    _rank(monkeypatch, ["archival", "recall", "main"])
    result = build_context(engine, "memory", k=1)
    assert result["nodes"] == ["main", "recall", "archival"]
    for tier in ("main", "recall", "archival"):
        assert f"## {tier.title()} Context\n\n[memory:{tier}]" in result["context"]
        assert result["tiers"][tier]["nodes"] == [tier]
    stats = context_stats(engine, "memory", budget=40)
    assert stats["tokens"] <= 40
    assert stats["tiers"] == build_context(engine, "memory", budget=40)["tiers"]


def test_important_main_selected_without_overlap_bounded(engine, monkeypatch):
    from graph_engine.context import build_context
    _write(engine, "pinned", "Always use German", "main", tier_locked=True)
    _write(engine, "frequent", "Use short answers", "main", recall_count=10)
    _write(engine, "unused", "Old preference", "main")
    _write(engine, "match", "memory match")
    _rank(monkeypatch, ["match"])
    result = build_context(engine, "memory", k=1)
    assert result["nodes"] == ["pinned", "match"]
    assert result["memories"][0]["selection"] == "important_main"
    result = build_context(engine, "memory", k=2)
    assert result["nodes"] == ["pinned", "frequent", "match"]
    assert "unused" not in result["context"]


@pytest.mark.parametrize("crowded_tier", ["main", "recall", "archival"])
@pytest.mark.parametrize("rerank", [False, True])
def test_candidate_and_result_limits_are_per_tier(engine, crowded_tier, rerank):
    from collections import Counter
    from graph_engine.context import build_context
    from graph_engine.embedder import HashEmbedder
    engine.embedder = HashEmbedder()
    for i in range(36):
        _write(engine, f"crowded-{i:02}", f"Project memory note {i}", crowded_tier)
    for tier in ("main", "recall", "archival"):
        if tier != crowded_tier:
            _write(engine, tier, f"Project memory answer in {tier}", tier)

    seen = []

    class ReverseReranker:
        def rerank(self, query, candidates, k):
            seen.extend(nid for nid, _, _ in candidates)
            return list(reversed(candidates))[:k]

    if rerank:
        engine.reranker = ReverseReranker()
    result = build_context(engine, "Project memory", budget=4000, k=2)
    for tier in ("main", "recall", "archival"):
        assert len(result["tiers"][tier]["nodes"]) == (2 if tier == crowded_tier else 1)
    assert result["tokens"] < 4000 and not result["truncated"]
    if rerank:
        tiers = {node.id: node.storage_tier for node in engine.brain.read_nodes()}
        counts = Counter(tiers[nid] for nid in seen)
        assert counts[crowded_tier] == 6  # 3*k candidates per tier, before reranking
        assert set(counts) == {"main", "recall", "archival"}


def test_skip_large_citation_and_try_following_memory(engine, monkeypatch):
    from graph_engine.context import build_context
    _write(engine, "too-big", "memory", source="x" * 1000)
    _write(engine, "small", "useful memory")
    _rank(monkeypatch, ["too-big", "small"])
    result = build_context(engine, "memory", budget=25)
    assert result["nodes"] == ["small"]
    assert result["omitted"] == 1 and result["truncated"]


def test_tombstone_empty_missing_and_duplicate_candidates(engine, monkeypatch):
    from graph_engine.context import build_context
    _write(engine, "gone", "secret memory", "main", status="tombstone", tier_locked=True)
    _write(engine, "empty", "")
    _write(engine, "live", "usable memory")
    _rank(monkeypatch, ["gone", "empty", "missing", "live", "live"])
    result = build_context(engine, "memory")
    assert result["nodes"] == ["live"]
    assert "secret" not in result["context"]


def test_citations_and_only_live_accepted_evidence(engine, monkeypatch):
    from graph_engine.brain import Edge
    from graph_engine.context import build_context
    _write(engine, "fact", "memory fact", source="agent", sources=["user"])
    _write(engine, "other")
    _write(engine, "source", "source evidence")
    _write(engine, "gone", "obsolete", status="tombstone")
    engine.brain.write_edges([
        Edge("fact", "other", "fact", id="accepted", pending=False,
             evidence=[{"node_id": "source", "text": "source evidence"}]),
        Edge("fact", "other", "fact", id="pending", pending=True,
             evidence=[{"node_id": "source", "text": "pending evidence"}]),
        Edge("fact", "other", "fact", id="dead", pending=False,
             evidence=[{"node_id": "gone", "text": "obsolete evidence"}]),
        Edge("fact", "other", "fact", id="rejected", pending=False, rejected=True,
             evidence=[{"node_id": "source", "text": "rejected evidence"}]),
        Edge("fact", "other", "fact", id="expired", pending=False,
             valid_to="2000-01-01T00:00:00+00:00",
             evidence=[{"node_id": "source", "text": "expired evidence"}]),
    ])
    _rank(monkeypatch, ["fact"])
    result = build_context(engine, "memory", include_metadata=False)
    assert "[memory:fact]" in result["context"]
    assert "source: agent; user" in result["context"]
    assert "accepted@source" in result["context"]
    assert result["memories"][0]["evidence"] == [{"edge_id": "accepted", "node_id": "source"}]
    assert not any(word in result["context"] for word in ("obsolete", "dead", "pending", "rejected", "expired"))


def test_context_never_changes_brain_files(tmp_path):
    import subprocess
    from graph_engine.brain_engine import BrainEngine
    from graph_engine.context import build_context, context_stats, context_for_prompt
    from graph_engine.embedder import HashEmbedder
    brain = Brain(str(tmp_path / "git-brain"), mode="git")
    brain.init()
    engine = BrainEngine(brain, HashEmbedder())
    _write(engine, "node", "memory preference")
    brain.commit_and_push("seed", push=False)
    before = {p.relative_to(brain.path): p.read_bytes() for p in brain.path.rglob("*")
              if p.is_file() and ".git" not in p.relative_to(brain.path).parts}
    for fn in (build_context, context_stats, context_for_prompt):
        fn(engine, "memory")
    after = {p.relative_to(brain.path): p.read_bytes() for p in brain.path.rglob("*")
             if p.is_file() and ".git" not in p.relative_to(brain.path).parts}
    assert before == after
    assert not (brain.path / "recalls.jsonl").exists()
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=brain.path) == b""


@pytest.mark.parametrize("kwargs", [{"budget": -1}, {"budget": True}, {"budget": 1.5},
                                    {"k": 0}, {"k": True}, {"query": " "}])
def test_invalid_context_parameters(engine, kwargs):
    from graph_engine.context import build_context
    with pytest.raises(ValueError):
        build_context(engine, **{"query": "memory", **kwargs})


def test_round_up_short_non_cjk_estimate():
    from graph_engine.context import estimate_tokens
    assert estimate_tokens("a") == 1
    assert estimate_tokens("汉a") == 2


def test_cli_budget_not_part_of_query(engine, monkeypatch, capsys):
    import json
    from graph_engine.__main__ import cmd_context
    seen = []

    def retrieve(engine, query, **kwargs):
        seen.append(query)
        return [("note", 1.)]

    _write(engine, "note", "memory preference")
    monkeypatch.setattr("graph_engine.retrieval.retrieve", retrieve)
    cmd_context(engine, ["memory", "preference", "--budget", "50", "--json"])
    result = json.loads(capsys.readouterr().out)
    assert seen == ["memory preference"]
    assert result["budget"] == 50 and result["tokens"] <= 50


def test_budget_counts_escaping_markers_and_separators(engine, monkeypatch):
    from graph_engine.context import build_context, estimate_tokens
    for tier in ("main", "recall", "archival"):
        _write(engine, tier, "<>&|汉 memory " * 50, tier)
    _rank(monkeypatch, ["main", "recall", "archival"])
    full = build_context(engine, "memory", budget=10000)
    assert "\\<\\>\\&\\|" in full["context"]
    assert "\n\n---\n\n" in full["context"]
    assert full["tokens"] == estimate_tokens(full["context"])
    for budget in range(0, full["tokens"] + 1, 7):
        result = build_context(engine, "memory", budget=budget)
        assert result["tokens"] == estimate_tokens(result["context"]) <= budget

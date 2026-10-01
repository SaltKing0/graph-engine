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
            engine.ingest(f"Fact number {i} about memory systems and AI agents")
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

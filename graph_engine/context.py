"""Context window management (Phase 3): smart context assembly.

The engine has hybrid retrieval (BM25 + Dense + RRF) but no way to build
an optimized prompt context. This module adds:

  build_context(engine, query, budget)  — assembles a context window
  hierarchical_context(engine, query)  — main → recall → archival tiers
  estimate_tokens(text)                — rough token estimation

All functions are read-only. They never modify the brain.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .brain import Brain, Node
    from .brain_engine import BrainEngine


def estimate_tokens(text: str) -> int:
    """Rough token estimation (1 token ≈ 4 chars for English, 3 for CJK).

    This is a heuristic, not a real tokenizer. Good enough for budget
    planning without adding a dependency.
    """
    if not text:
        return 0
    # Count CJK characters (roughly 1 token each)
    cjk = len(re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]', text))
    # Count non-CJK characters (roughly 4 chars per token)
    non_cjk = len(text) - cjk
    return cjk + (non_cjk // 4)


def build_context(engine: "BrainEngine", query: str, budget: int = 4000,
                  *, k: int = 5, include_metadata: bool = True) -> dict:
    """Assemble a context window for a given query.

    Returns a dict with:
    - context: the assembled context string
    - tokens: estimated token count
    - nodes: list of included node ids
    - budget: the budget that was used
    - truncated: whether the context was truncated to fit the budget

    The context is built hierarchically:
    1. Main context: top-k most relevant nodes (full text)
    2. Recall context: next tier (snippets only)
    3. Archival context: community summaries (if budget allows)
    """
    from .retrieval import retrieve

    # Get candidates (more than k — we need tiers)
    results = retrieve(engine, query, k=k * 3, track=False)
    if not results:
        return {
            "context": "",
            "tokens": 0,
            "nodes": [],
            "budget": budget,
            "truncated": False,
        }

    # Tier 1: Main context (top-k, full text)
    main_ids = [nid for nid, _ in results[:k]]
    # Tier 2: Recall context (next k, snippets)
    recall_ids = [nid for nid, _ in results[k:k * 2]]
    # Tier 3: Archival context (community summaries)
    archival_ids = [nid for nid, _ in results[k * 2:k * 3]]

    context_parts: list[str] = []
    included_nodes: list[str] = []
    total_tokens = 0
    truncated = False

    # Helper to add a section if it fits the budget
    def add_section(header: str, texts: list[str]) -> bool:
        nonlocal total_tokens, truncated
        section = f"## {header}\n\n" + "\n\n".join(texts)
        section_tokens = estimate_tokens(section)
        if total_tokens + section_tokens > budget:
            truncated = True
            return False
        context_parts.append(section)
        total_tokens += section_tokens
        return True

    # Tier 1: Main context (full text)
    main_texts = []
    for nid in main_ids:
        node = engine.brain.read_node(nid)
        if node is None:
            continue
        text = node.text
        if include_metadata:
            meta = f"[{node.ntype}, {node.status}]"
            text = f"{meta} {text}"
        main_texts.append(text)
        included_nodes.append(nid)
    if main_texts:
        if not add_section("Main Context", main_texts):
            return _assemble(context_parts, included_nodes, budget, truncated)

    # Tier 2: Recall context (snippets)
    recall_texts = []
    for nid in recall_ids:
        node = engine.brain.read_node(nid)
        if node is None:
            continue
        # Snippet: first 200 chars
        snippet = node.text[:200] + ("…" if len(node.text) > 200 else "")
        recall_texts.append(snippet)
        included_nodes.append(nid)
    if recall_texts:
        if not add_section("Recall Context", recall_texts):
            return _assemble(context_parts, included_nodes, budget, truncated)

    # Tier 3: Archival context (community summaries)
    archival_texts = []
    for nid in archival_ids:
        node = engine.brain.read_node(nid)
        if node is None:
            continue
        if "community-summary" in (node.tags or []):
            archival_texts.append(node.text[:300])
            included_nodes.append(nid)
    if archival_texts:
        add_section("Archival Context", archival_texts)

    return _assemble(context_parts, included_nodes, budget, truncated)


def _assemble(parts: list[str], nodes: list[str], budget: int,
               truncated: bool) -> dict:
    """Assemble the final context string."""
    context = "\n\n---\n\n".join(parts)
    return {
        "context": context,
        "tokens": estimate_tokens(context),
        "nodes": nodes,
        "budget": budget,
        "truncated": truncated,
    }


def hierarchical_context(engine: "BrainEngine", query: str) -> dict:
    """Build a hierarchical context (main → recall → archival).

    This is a convenience wrapper around build_context with a default
    budget of 4000 tokens. Returns the same dict as build_context.
    """
    return build_context(engine, query, budget=4000)


def context_for_prompt(engine: "BrainEngine", query: str,
                       max_tokens: int = 2000) -> str:
    """Build a context string ready to be inserted into a prompt.

    This is the simplest interface: query in, context string out.
    """
    result = build_context(engine, query, budget=max_tokens)
    return result["context"]


def context_stats(engine: "BrainEngine", query: str, budget: int = 4000) -> dict:
    """Statistics about what a context build would include.

    Useful for debugging: shows how many nodes fit in each tier,
    how many tokens each tier uses, etc.
    """
    from .retrieval import retrieve

    results = retrieve(engine, query, k=15, track=False)
    if not results:
        return {"query": query, "budget": budget, "tiers": {}}

    tiers = {
        "main": {"nodes": [], "tokens": 0},
        "recall": {"nodes": [], "tokens": 0},
        "archival": {"nodes": [], "tokens": 0},
    }

    for i, (nid, _) in enumerate(results):
        node = engine.brain.read_node(nid)
        if node is None:
            continue
        if i < 5:
            tier = "main"
            text = node.text
        elif i < 10:
            tier = "recall"
            text = node.text[:200]
        else:
            tier = "archival"
            text = node.text[:300] if "community-summary" in (node.tags or []) else ""
        if text:
            tiers[tier]["nodes"].append(nid)
            tiers[tier]["tokens"] += estimate_tokens(text)

    return {"query": query, "budget": budget, "tiers": tiers}

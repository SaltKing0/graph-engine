"""Read-only, citation-bearing prompt context from persisted storage tiers."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .brain import STORAGE_TIERS
from .mcp import format as fmt
from .tiers import MAIN_MIN_RECALLS

if TYPE_CHECKING:
    from .brain import Node
    from .brain_engine import BrainEngine

TOKEN_ESTIMATE = (
    "Approximate: one token per CJK character plus ceil(other characters / 4). "
    "Counts the complete context, including headers, citations, metadata, "
    "truncation markers and separators; excludes the JSON envelope and the "
    "rest of your prompt. This is not an exact tokenizer limit."
)
TRUNCATION = (
    "Recall/archival bodies are capped at 200/300 characters. Bodies are "
    "prefix-truncated further to fit the estimated budget, with … [truncated]. "
    "Entries whose citation and non-empty body cannot fit are omitted. "
    "Source labels and evidence references are capped at five per memory "
    "(labels at 200 characters)."
)
MARKER = "… [truncated]"
SEPARATOR = "\n\n---\n\n"


def estimate_tokens(text: str) -> int:
    """CJK characters cost one each; other characters cost ceil(chars / 4).

    A planning heuristic, never a guarantee about a model's actual tokenizer.
    """
    cjk = len(re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]', text))
    return cjk + (len(text) - cjk + 3) // 4


def _evidence(engine: BrainEngine, live: dict[str, Node]) -> dict[str, list[dict]]:
    """Only accepted, current evidence with visible, non-tombstoned sources."""
    refs: dict[str, list[dict]] = {}
    for edge in sorted(engine.brain.read_edges(), key=lambda e: e.id):
        if (edge.pending or edge.rejected or not edge.is_current
                or edge.source not in live or edge.target not in live):
            continue
        evidence_ids = [item.get("node_id") for item in edge.evidence]
        if any(nid not in live for nid in evidence_ids):
            continue
        for nid in dict.fromkeys((edge.source, edge.target)):
            items = refs.setdefault(nid, [])
            for source_id in dict.fromkeys(evidence_ids):
                ref = {"edge_id": edge.id, "node_id": source_id}
                if ref not in items and len(items) < 5:
                    items.append(ref)
    return refs


def build_context(engine: BrainEngine, query: str, budget: int = 4000,
                  *, k: int = 5, include_metadata: bool = True) -> dict:
    """Pack at most k memories per persisted tier, main → recall → archival.

    Select up to k important main memories even without query overlap:
    manually pinned first, then recall_count >= MAIN_MIN_RECALLS, sorted by
    descending recall count and stable ID. Fill remaining slots with hybrid
    hits in retrieval order (candidate pool: 3*k). All selection uses the
    caller's visible live nodes. Retrieval never persists vectors or recalls.

    `nodes` identifies exactly the non-empty memory bodies included in
    `context`. `memories` records their tiers, selection, evidence references
    and truncation. Mandatory stable IDs and provenance remain present even
    when optional type/status metadata is disabled. `tokens` estimates the
    entire rendered context, not the response envelope or surrounding prompt.
    """
    from .retrieval import retrieve

    if type(budget) is not int or budget < 0:
        raise ValueError("budget must be a non-negative integer")
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")

    live = {n.id: n for n in engine.brain.read_nodes()
            if n.status != "tombstone" and n.text.strip()}
    important = sorted(
        (n for n in live.values() if n.storage_tier == "main"
         and (n.tier_locked or n.recall_count >= MAIN_MIN_RECALLS)),
        key=lambda n: (not n.tier_locked, -n.recall_count, n.id))[:k]
    hits = retrieve(engine, query, k=k * 3, rerank_k=max(30, k * 3),
                    persist=False, track=False)
    tiers: dict[str, list[tuple[Node, str]]] = {t: [] for t in STORAGE_TIERS}
    selected = set()
    for node in important:
        tiers["main"].append((node, "important_main"))
        selected.add(node.id)
    for nid, _ in hits:
        node = live.get(nid)
        if node is None or nid in selected or len(tiers[node.storage_tier]) >= k:
            continue
        tiers[node.storage_tier].append((node, "query"))
        selected.add(nid)
    refs = _evidence(engine, live) if selected and budget else {}
    parts: list[str] = []
    memories: list[dict] = []
    omitted = 0
    tier_stats = {t: {"nodes": [], "tokens": 0} for t in STORAGE_TIERS}

    for tier, candidates in tiers.items():
        entries: list[str] = []

        def render(entry: str) -> str:
            section = f"## {tier.title()} Context\n\n" + "\n\n".join([*entries, entry])
            return SEPARATOR.join([*parts, section])

        for node, selection in candidates:
            evidence = refs.get(node.id, [])
            sources = [fmt.snippet(s, 200) for s in
                       dict.fromkeys([node.source, *node.sources]) if s][:5]
            citation = f"[memory:{node.id}]"
            if include_metadata:
                citation += f" [{node.ntype}, {node.status}]"
            if sources:
                citation += " source: " + "; ".join(sources)
            if evidence:
                citation += " evidence: " + ", ".join(
                    f"{r['edge_id']}@{r['node_id']}" for r in evidence)
            prefix = citation + "\n"
            cap = len(node.text) if tier == "main" else 200 if tier == "recall" else 300
            body = node.text[:cap]
            clipped = len(body) < len(node.text)

            def entry_for(length: int) -> str:
                # Escape after truncation, exactly as the MCP formatting helpers.
                return prefix + fmt._escape(body[:length]) + (
                    MARKER if clipped or length < len(body) else "")

            length = len(body)
            if estimate_tokens(render(entry_for(length))) > budget:
                # Search the longest prefix that fits, including its marker.
                low, high = 0, len(body) - 1
                while low < high:
                    mid = (low + high + 1) // 2
                    if estimate_tokens(render(entry_for(mid))) <= budget:
                        low = mid
                    else:
                        high = mid - 1
                length = low
                clipped = True
            if (not body[:length].strip()
                    or estimate_tokens(render(entry_for(length))) > budget):
                omitted += 1
                continue  # a shorter following memory may still fit
            entries.append(entry_for(length))
            memories.append({"id": node.id, "storage_tier": tier,
                             "selection": selection, "truncated": clipped,
                             "sources": sources, "evidence": evidence})
        if entries:
            section = f"## {tier.title()} Context\n\n" + "\n\n".join(entries)
            parts.append(section)
            tier_stats[tier] = {"nodes": [m["id"] for m in memories
                                          if m["storage_tier"] == tier],
                                "tokens": estimate_tokens(section)}

    context = SEPARATOR.join(parts)
    return {"context": context, "tokens": estimate_tokens(context),
            "nodes": [m["id"] for m in memories], "budget": budget,
            "truncated": bool(omitted or any(m["truncated"] for m in memories)),
            "memories": memories, "omitted": omitted, "tiers": tier_stats,
            "token_estimate": TOKEN_ESTIMATE, "truncation": TRUNCATION}


def hierarchical_context(engine: BrainEngine, query: str) -> dict:
    """Convenience wrapper using the default estimated budget of 4000."""
    return build_context(engine, query, budget=4000)


def context_for_prompt(engine: BrainEngine, query: str, max_tokens: int = 2000) -> str:
    """Return just the assembled context for insertion into a model prompt."""
    return build_context(engine, query, budget=max_tokens)["context"]


def context_stats(engine: BrainEngine, query: str, budget: int = 4000) -> dict:
    """Report included memories by persisted tier using the same packing path.

    The top-level token estimate includes every section separator. Tier token
    counts cover each complete rendered section, so they exclude separators.
    """
    result = build_context(engine, query, budget)
    return {"query": query, "budget": budget,
            "tiers": result["tiers"] if result["memories"] else {},
            "tokens": result["tokens"], "truncated": result["truncated"]}

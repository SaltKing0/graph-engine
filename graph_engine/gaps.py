"""Coverage and gap analysis over the brain.

Classifies each node against a topic taxonomy (area → keywords),
counts coverage per area and identifies underrepresented areas (gaps).
This steers targeted research instead of broad search.

The taxonomy is generic and swappable via a JSON file
(format: {"area": ["keyword", ...]}); DEFAULT_TAXONOMY is a sensible
LLM/agent default. Nothing on the brain is modified (read-only).
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .brain import Brain

# Default taxonomy (LLM/agent research) — generic, no personal data.
DEFAULT_TAXONOMY: dict[str, list[str]] = {
    "Agent-Harness & Orchestrierung": [
        "harness", "orchestrierung", "agent-runtime", "supervisor", "handoff",
        "loop-kontrolle", "startup", "kontext-injektion", "resilienz",
        "circuit-breaker", "durable", "plan-and-execute", "agent-loop",
        "workflow", "subagent", "fanout", "delegation",
    ],
    "Coding-Agents & Code": [
        "code", "programmier", "coding", "software", "repo", "debug",
        "test-generierung", "code-review", "refactor", "swe-bench", "human-eval",
        "legacy", "api-generierung", "sql",
    ],
    "Multi-Agent-Systeme": [
        "multi-agent", "verhandlung", "auktion", "konsens", "voting",
        "kooperation", "konkurrenz", "spieltheorie", "mechanism-design",
        "incentive", "marktplatz", "interoperabilitaet", "blackboard",
        "agenten-routing", "schwarm", "peer-to-peer",
    ],
    "LLM-Architektur & Interna": [
        "attention", "transformer", "token", "embedding", "kv-cache", "position",
        "rope", "mamba", "ssm", "mixture", "moe", "architektur", "logits",
        "softmax", "layernorm", "tokenisierung", "bpe", "neuron",
    ],
    "Training & Alignment": [
        "rlhf", "dpo", "grpo", "ppo", "alignment", "fine-tuning", "finetuning",
        "lora", "peft", "qlora", "sft", "reward", "preference", "synthetic",
        "curriculum", "gradient", "loss", "optimizer", "adamw", "training",
    ],
    "Evals & Benchmarks": [
        "eval", "benchmark", "metrik", "leaderboard", "mmlu", "gsm8k", "judge",
        "kontamination", "golden", "oracle", "pass@k", "halluzination-messung",
        "test", "verifikation",
    ],
    "Retrieval & RAG": [
        "retrieval", "rag", "rerank", "bm25", "dense", "vector",
        "embedding-search", "chunk", "index", "graph-rag", "hybrid",
        "semantische-suche", "cross-encoder", "late-chunking",
    ],
    "Memory & Kontext": [
        "memory", "gedaechtnis", "kontext", "working-memory", "episodic",
        "context-engineering", "token-budget", "context-window", "scratchpad",
        "langzeit", "hierarchisches", "summarization", "kontext-kompression",
    ],
    "Serving & Inferenz": [
        "serving", "inferenz", "vllm", "batching", "prefill", "decode",
        "throughput", "latenz", "quantisierung", "gpu", "inference",
        "speculative", "disaggregated", "ttft", "pagedattention",
    ],
    "Sicherheit & Governance": [
        "sicherheit", "security", "jailbreak", "injection", "sandbox",
        "governance", "privacy", "datenschutz", "ethik", "regulierung", "audit",
        "compliance", "exfiltration", "autorisierung", "trust", "verantwortung",
    ],
    "Multimodal": [
        "multimodal", "vision", "bild", "audio", "speech", "tts", "video",
        "clip", "image", "sprach-synthese", "geste", "cross-modal",
        "text-to-image",
    ],
    "Konversations-KI": [
        "konversation", "dialog", "chatbot", "persona", "intent", "slot",
        "multi-turn", "chat", "gespraech", "engagement", "turn-qualitaet",
        "empathie",
    ],
    "Interpretability & Mechanistik": [
        "interpretab", "mechanistic", "sae", "sparse autoencoder", "activation",
        "circuit", "logit-lens", "probing", "attribution", "causal", "ablation",
        "steering", "transparenz", "erklaer",
    ],
    "Anwendungen": [
        "industr", "fertigung", "medizin", "biologie", "chemie", "physik",
        "bildung", "tutor", "lern", "content", "marketing", "journalismus",
        "recht", "finanz", "gesundheit", "wissenschaft", "astronomie", "ocean",
        "klima",
    ],
    "Oekonomie & Gesellschaft": [
        "oekonomie", "kosten", "open-source", "closed", "arbeitsmarkt", "umwelt",
        "gesellschaft", "wirtschaft", "markt", "lizenz", "urheber",
    ],
}


def normalize(text: str) -> str:
    """Lowercase + umlaut normalization (ä→ae etc.)."""
    s = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return s


def _node_text(node: Any) -> str:
    """Node body without frontmatter.

    Audit #25: the blind parts[2] lost everything after an internal
    `---` horizontal rule in the body. Frontmatter end is the FIRST
    `---` line alone — everything after that is the complete body.
    """
    t = getattr(node, "text", "") or ""
    m = re.match(r"^---\n.*?\n---\n\n?(.*)$", t, re.DOTALL)
    if m:
        return m.group(1).strip()
    return t.strip()


@dataclass
class AreaStat:
    name: str
    count: int = 0
    examples: list[dict] = field(default_factory=list)


@dataclass
class CoverageResult:
    total: int
    areas: list[AreaStat]  # sorted by count descending
    unclassified: int
    taxonomy: dict[str, list[str]]


def analyze_coverage(brain: Brain, taxonomy: dict[str, list[str]] | None = None) -> CoverageResult:
    """Classifies all nodes against the taxonomy and counts coverage per area.

    A node can belong to multiple areas (keyword overlap).
    Read-only — does not modify the brain.
    """
    tax = taxonomy or DEFAULT_TAXONOMY
    count: Counter = Counter()
    examples: dict[str, list] = defaultdict(list)
    nodes = brain.read_nodes()
    # Tombstones are append-only history, not live knowledge: they must not
    # count toward coverage (they would inflate UNCLASSIFIED and every area).
    nodes = [n for n in nodes if n.status != "tombstone"]
    unclassified = 0
    # Audit #60: substring matching let "test" match "latest" — keywords now
    # match with word boundaries (umlauts are ASCII-shaped by normalize()).
    kw_res = {area: [re.compile(rf"\b{re.escape(k)}\b") for k in kws]
              for area, kws in tax.items()}
    for node in nodes:
        b = normalize(_node_text(node))
        matched = [area for area, patterns in kw_res.items()
                   if any(p.search(b) for p in patterns)]
        if not matched:
            unclassified += 1
        for m in matched:
            count[m] += 1
            if len(examples[m]) < 5:
                examples[m].append({"id": node.id, "text": _node_text(node)[:72]})
    areas = [AreaStat(name=a, count=count[a], examples=examples[a]) for a in tax]
    areas.sort(key=lambda s: s.count, reverse=True)
    return CoverageResult(total=len(nodes), areas=areas, unclassified=unclassified, taxonomy=tax)


def find_gaps(coverage: CoverageResult, threshold: int) -> list[AreaStat]:
    """Areas below the threshold, ascending by coverage (thinnest first)."""
    return [a for a in sorted(coverage.areas, key=lambda s: s.count) if a.count < threshold]


def render(coverage: CoverageResult, threshold: int) -> str:
    """Textual coverage/gap report."""
    lines = [
        f"Coverage ({coverage.total} nodes, {len(coverage.areas)} areas):",
        f"{'Nodes':>5}  {'Area':<40}  Coverage",
        "-----  " + "-" * 40 + "  ---------",
    ]
    maxc = max((a.count for a in coverage.areas), default=1)
    # Audit #24: a brain without hits (all counts 0) must not crash with
    # ZeroDivisionError — maxc at least 1.
    maxc = max(maxc, 1)
    for a in coverage.areas:
        bar = "#" * int(a.count / maxc * 30)
        gap = "  ← GAP" if a.count < threshold else ""
        lines.append(f"{a.count:>5}  {a.name:<40}  {bar}{gap}")
    lines.append(f"{coverage.unclassified:>5}  {'UNCLASSIFIED':<40}")
    gaps = find_gaps(coverage, threshold)
    if gaps:
        lines.append("")
        lines.append(f"GAPS (< {threshold} nodes) — next research targets (thinnest first):")
        for a in gaps:
            lines.append(f"  {a.count:>3}  {a.name}")
    return "\n".join(lines)


def load_taxonomy(path: str) -> dict[str, list[str]]:
    """Loads a taxonomy from a JSON file ({"area": ["kw", ...]})."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not all(isinstance(v, list) for v in data.values()):
        raise ValueError("Taxonomy must be a JSON object: {\"area\": [\"kw\", ...]}")
    return data

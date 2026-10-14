"""Episodic → semantic extraction, separate from dual-buffer deduplication.

Selection is deterministic: recall count, observation age, then eligible pool
size. Original events stay intact; provenance links make repeated passes safe.
The default extractor preserves the evidence verbatim, just like `ig extract`.
The legacy text extractor can refine it or return None. A separate opt-in JSON
protocol produces labelled, searchable proposals with pending evidence links.
"""

from __future__ import annotations

from contextlib import nullcontext

import datetime
import json
import math
from dataclasses import asdict, dataclass
from typing import Callable

from .brain import Brain, Edge, Node, _atomic_write
from .consolidation_protocol import PROPOSAL_PREFIX, PROPOSAL_TAG, validate_consolidation

CURSOR_FILE = "consolidation-cursor.json"
PUBLICATION_POLICY = "searchable labelled proposals; pending/rejected evidence does not hide nodes"


def _claim(node: Node) -> str:
    if PROPOSAL_TAG in node.tags and node.text.startswith(PROPOSAL_PREFIX):
        return node.text[len(PROPOSAL_PREFIX):]
    return node.text


def _suppressed_claims(nodes: dict[str, Node], edges: list[Edge]) -> set[str]:
    """Respect forgetting and structured review decisions in every protocol."""
    forgotten = {_key(_claim(n)) for n in nodes.values()
                 if n.ntype == "semantic" and n.status == "tombstone"}
    blocked_ids = {e.source for e in edges if e.origin == "consolidator" and e.evidence
                   and (e.rejected or e.is_invalidated)}
    return forgotten | {_key(_claim(nodes[nid])) for nid in blocked_ids if nid in nodes}


def _structured_batch(nodes: dict[str, Node], edges: list[Edge], facts: list[dict],
                      result: dict, source_ids: list[str]) -> tuple[dict[str, Node], list[Edge]]:
    """Plan proposals without changing existing records or review decisions."""
    suppressed = _suppressed_claims(nodes, edges)
    matches = {}
    for edge in edges:
        node = nodes.get(edge.source)
        if (node and node.derived_from and node.ntype == "semantic" and node.status != "tombstone" and PROPOSAL_TAG in node.tags
                and edge.origin == "consolidator" and edge.extracted_validity is not None):
            matches[(_key(_claim(node)), edge.extracted_validity["valid_from"],
                     edge.extracted_validity["valid_to"])] = node
    writes, links = {}, []
    linked = {(e.source, e.target) for e in edges if e.origin == "consolidator"}
    for item in facts:
        key = _key(item["text"])
        if key in suppressed:
            result["skipped"] += 1
            continue
        identity = (key, item["valid_from"], item["valid_to"])
        fact = matches.get(identity)
        if fact is None:
            fact = Node(text=PROPOSAL_PREFIX + item["text"], source="consolidator",
                        tags=["episodic-extraction", PROPOSAL_TAG], ntype="semantic",
                        status="probation")
            writes[fact.id] = fact
            matches[identity] = fact
            result["created"] += 1
        else:
            result["reused"] += 1
        # The model saw the entire batch, not just the quotes it selected.
        fact.derived_from = sorted(set(fact.derived_from) | set(source_ids))
        writes[fact.id] = fact
        # One reviewable assertion edge per source, carrying all that source's quotes.
        for nid in dict.fromkeys(ref["node_id"] for ref in item["evidence"]):
            if (fact.id, nid) in linked:
                planned = next((e for e in links if e.source == fact.id and e.target == nid), None)
                if planned is not None:
                    for ref in item["evidence"]:
                        if ref["node_id"] == nid and ref not in planned.evidence:
                            planned.evidence.append(ref)
                continue
            links.append(Edge(source=fact.id, target=nid, kind="extends", pending=True,
                              origin="consolidator", evidence=[ref for ref in item["evidence"]
                                                               if ref["node_id"] == nid],
                              valid_from=item["valid_from"], valid_to=item["valid_to"],
                              extracted_validity={"valid_from": item["valid_from"],
                                                  "valid_to": item["valid_to"]}))
            linked.add((fact.id, nid))
        result["proposals"].append({"node_id": fact.id, **item})
    result["pending_proposals"] = len(links)
    return writes, links


@dataclass(frozen=True)
class ConsolidationConfig:
    threshold: int = 1
    min_age_days: float = 1.0
    min_count: int = 1
    limit: int = 50

    def __post_init__(self) -> None:
        for key, minimum in (("threshold", 0), ("min_count", 1), ("limit", 1)):
            value = getattr(self, key)
            if not isinstance(value, int) or value < minimum:
                raise ValueError(f"{key} must be an integer >= {minimum}")
        if not math.isfinite(self.min_age_days) or self.min_age_days < 0:
            raise ValueError("min_age_days must be finite and >= 0")


def _key(text: str) -> str:
    return " ".join(text.casefold().split())


def _timestamp(node: Node) -> datetime.datetime | None:
    try:
        stamp = datetime.datetime.fromisoformat(
            (node.observed_at or node.created).replace("Z", "+00:00"))
        return stamp.replace(tzinfo=datetime.timezone.utc) if stamp.tzinfo is None else stamp
    except (ValueError, TypeError):
        return None


def _read_cursor(brain: Brain) -> tuple[datetime.datetime, str] | None:
    """Resume after the last examined event, including events that were skipped."""
    brain.authorize("admin")
    try:
        data = json.loads((brain.path / CURSOR_FILE).read_text(encoding="utf-8"))
        stamp = datetime.datetime.fromisoformat(data["observed_at"])
        nid = data["id"]
        if stamp.tzinfo is not None and isinstance(nid, str):
            return stamp, nid
    except (FileNotFoundError, ValueError, TypeError, KeyError):
        pass
    return None


def consolidation_plan(brain: Brain, *, config: ConsolidationConfig | None = None,
                       now: datetime.datetime | None = None) -> dict:
    """Read-only gates and source IDs; no sync, cache writes, or extractor calls."""
    if config is None:
        from .brain_engine import consolidation_config_from_env
        config = consolidation_config_from_env()
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    nodes = {n.id: n for n in brain.read_nodes()}
    # Keep reviewed/forgotten extractions processed too: a scheduled pass must
    # not undo a user's rejection or resurrect an explicitly forgotten fact.
    # Community summaries are not per-event fact extractions.
    processed = {e.target for e in brain.read_edges(include_rejected=True)
                 if e.origin == "consolidator" and e.kind == "extends"
                 and e.source in nodes and nodes[e.source].ntype == "semantic"
                 and "community-summary" not in nodes[e.source].tags}
    episodic = [n for n in nodes.values()
                if n.ntype == "episodic" and n.status != "tombstone"]
    eligible: list[tuple[datetime.datetime, str]] = []
    for node in episodic:
        if node.id in processed or not node.text.strip():
            continue
        stamp = _timestamp(node)
        if stamp is None:
            continue
        age = (now - stamp).total_seconds() / 86400
        if age >= config.min_age_days and node.recall_count >= config.threshold:
            eligible.append((stamp, node.id))
    eligible.sort()
    cursor = _read_cursor(brain)
    if cursor is not None:
        # Walk the chronological queue in rounds. A decline remains retryable,
        # but cannot consume the first slot of every bounded pass forever.
        eligible = ([item for item in eligible if item > cursor]
                    + [item for item in eligible if item <= cursor])
    triggered = len(eligible) >= config.min_count
    proposal_edges = [e for e in brain.read_edges(include_rejected=True)
                      if e.origin == "consolidator" and e.evidence
                      and e.source in nodes and PROPOSAL_TAG in nodes[e.source].tags]
    return {"publication_policy": PUBLICATION_POLICY,
            "review": {"pending": sum(e.pending and not e.rejected for e in proposal_edges),
                       "rejected": sum(e.rejected for e in proposal_edges),
                       "accepted": sum(not e.pending and not e.rejected and not e.is_invalidated
                                       for e in proposal_edges)},
            "episodic": len(episodic),
            "processed": sum(n.id in processed for n in episodic),
            "eligible": len(eligible), "triggered": triggered,
            "candidates": [nid for _, nid in eligible[:config.limit]] if triggered else [],
            "gates": asdict(config)}


def consolidate(brain: Brain, *, config: ConsolidationConfig | None = None,
                extractor: Callable[[str], str | None] | None = None,
                structured_extractor: Callable[[list[dict]], dict] | None = None,
                dry_run: bool = False, commit: bool = True,
                now: datetime.datetime | None = None, pending_evidence: bool = False,
                sync: bool = True) -> dict:
    """One bounded pass, one commit. Validate all extraction before writing.

    Copy/legacy modes reuse exact normalized semantic matches. Structured mode
    reuses labelled proposals with the same validity window. New facts enter
    probation; tombstoned matches are never revived.
    Dry runs report source candidates, not model-dependent output counts.
    Background workers use pending_evidence=True for copy provenance; the
    interactive command keeps its existing publication policy by default.
    With sync=False the caller must hold the guard over an already ready and
    pulled corpus. The pass still commits and pushes its changes.
    """
    brain.authorize("admin")
    if extractor is not None and structured_extractor is not None:
        raise ValueError("legacy and structured consolidation are mutually exclusive")
    from .brain_engine import consolidation_config_from_env
    config = config or consolidation_config_from_env()
    with nullcontext() if dry_run else brain.write_guard():
        if not dry_run and sync:
            brain.ensure_ready()
            brain.pull()
        plan = consolidation_plan(brain, config=config, now=now)
        result = {**plan, "created": 0, "reused": 0, "edges": 0,
                  "skipped": 0, "dry_run": dry_run,
                  "used_llm": extractor is not None or structured_extractor is not None,
                  "protocol": "structured-v1" if structured_extractor is not None else
                              "legacy-text" if extractor is not None else "copy",
                  "extraction_ran": False, "proposals": [], "pending_proposals": 0}
        if dry_run or not plan["candidates"]:
            return result

        nodes = {n.id: n for n in brain.read_nodes()}
        edges = brain.read_edges(include_rejected=True)
        if structured_extractor is not None:
            events = [{"node_id": nid, "text": nodes[nid].text,
                       "observed_at": nodes[nid].observed_at or nodes[nid].created}
                      for nid in plan["candidates"]]
            facts = validate_consolidation(structured_extractor(events), events)
            changed, links = _structured_batch(nodes, edges, facts, result, plan["candidates"])
            result["abstained"] = not facts
            result["extraction_ran"] = True
        else:
            changed, links = _copy_batch(nodes, edges, plan, extractor, result,
                                         pending_evidence=pending_evidence)
            result["extraction_ran"] = True

        # No file writes until the complete extraction batch has been validated.
        for fact in changed.values():
            brain.write_node(fact)
        if links:
            brain.write_edges(brain.read_edges(include_rejected=True) + links)
            brain.rebuild_index()
        cursor_changed = False
        if plan["eligible"] > len(plan["candidates"]):
            last_id = plan["candidates"][-1]
            stamp = _timestamp(nodes[last_id])
            if (stamp, last_id) != _read_cursor(brain):
                _atomic_write(brain.path / CURSOR_FILE, json.dumps(
                    {"observed_at": stamp.isoformat(), "id": last_id}) + "\n")
                cursor_changed = True
        if commit and (links or cursor_changed):
            brain.commit_and_push(
                f"consolidate episodic ({result['protocol']}): {result['created']} facts, "
                f"{result['reused']} reused, {len(links)} provenance edges")
        result["edges"] = len(links)
        return result


def _copy_batch(nodes: dict[str, Node], edges: list[Edge], plan: dict, extractor: Callable | None,
                result: dict, *, pending_evidence: bool = False) -> tuple[dict[str, Node], list[Edge]]:
    """Compatible deterministic and legacy extraction planning."""
    semantic: dict[str, Node] = {}
    suppressed = _suppressed_claims(nodes, edges)
    for node in sorted(nodes.values(), key=lambda n: n.id):
        if (node.ntype == "semantic" and node.status != "tombstone"
                and "community-summary" not in node.tags and PROPOSAL_TAG not in node.tags):
            semantic.setdefault(_key(node.text), node)
    changed: dict[str, Node] = {}
    links: list[Edge] = []
    for nid in plan["candidates"]:
        event = nodes[nid]
        text = extractor(event.text) if extractor is not None else event.text
        if text is not None and not isinstance(text, str):
            raise ValueError("consolidation extractor must return text or None")
        if text is None or not text.strip() or _key(text) in suppressed:
            result["skipped"] += 1
            continue
        text = text.strip()
        key = _key(text)
        fact = semantic.get(key)
        if fact is None:
            # Node identity must survive edits/merges independently of its
            # text. Exact reuse is handled by `semantic`, not a content ID.
            fact = Node(text=text, source="consolidator",
                        tags=["episodic-extraction"], ntype="semantic",
                        status="probation")
            semantic[key] = fact
            nodes[fact.id] = fact
            changed[fact.id] = fact
            result["created"] += 1
        else:
            result["reused"] += 1
            if "consolidator" not in fact.sources:
                fact.sources.append("consolidator")
                changed[fact.id] = fact
        fact.derived_from = sorted(set(fact.derived_from) | {nid} |
            {e.target for e in edges if e.origin == "consolidator" and e.kind == "extends" and e.source == fact.id})
        changed[fact.id] = fact
        links.append(Edge(source=fact.id, target=nid, kind="extends",
                          pending=pending_evidence, origin="consolidator"))

    result["pending_proposals"] = sum(e.pending for e in links)

    return changed, links

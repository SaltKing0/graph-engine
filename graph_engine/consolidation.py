"""Episodic → semantic extraction, separate from dual-buffer deduplication.

Selection is deterministic: recall count, observation age, then eligible pool
size. Original events stay intact; provenance links make repeated passes safe.
The default extractor preserves the evidence verbatim, just like `ig extract`.
An optional extractor can refine it or return None to decline extraction.
"""

from __future__ import annotations

import datetime
import json
import math
from dataclasses import asdict, dataclass
from typing import Callable

from .brain import Brain, Edge, Node, _atomic_write

CURSOR_FILE = "consolidation-cursor.json"


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
    return {"episodic": len(episodic),
            "processed": sum(n.id in processed for n in episodic),
            "eligible": len(eligible), "triggered": triggered,
            "candidates": [nid for _, nid in eligible[:config.limit]] if triggered else [],
            "gates": asdict(config)}


def consolidate(brain: Brain, *, config: ConsolidationConfig | None = None,
                extractor: Callable[[str], str | None] | None = None,
                dry_run: bool = False, commit: bool = True,
                now: datetime.datetime | None = None) -> dict:
    """One bounded pass, one commit. Validate all extraction before writing.

    New facts enter probation. Exact normalized semantic matches are reused
    (never episodic/procedural nodes); tombstoned matches are never revived.
    Dry runs report source candidates, not model-dependent output counts.
    """
    from .brain_engine import BRAIN_LOCK, consolidation_config_from_env
    config = config or consolidation_config_from_env()
    with BRAIN_LOCK:
        if not dry_run:
            brain.ensure_ready()
            brain.pull()
        plan = consolidation_plan(brain, config=config, now=now)
        result = {**plan, "created": 0, "reused": 0, "edges": 0,
                  "skipped": 0, "dry_run": dry_run,
                  "used_llm": extractor is not None}
        if dry_run or not plan["candidates"]:
            return result

        nodes = {n.id: n for n in brain.read_nodes()}
        semantic: dict[str, Node] = {}
        forgotten = {_key(n.text) for n in nodes.values()
                     if n.ntype == "semantic" and n.status == "tombstone"}
        for node in sorted(nodes.values(), key=lambda n: n.id):
            if (node.ntype == "semantic" and node.status != "tombstone"
                    and "community-summary" not in node.tags):
                semantic.setdefault(_key(node.text), node)
        changed: dict[str, Node] = {}
        links: list[Edge] = []
        for nid in plan["candidates"]:
            event = nodes[nid]
            text = extractor(event.text) if extractor is not None else event.text
            if text is not None and not isinstance(text, str):
                raise ValueError("consolidation extractor must return text or None")
            if text is None or not text.strip() or _key(text) in forgotten:
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
            links.append(Edge(source=fact.id, target=nid, kind="extends",
                              pending=False, origin="consolidator"))

        # No file writes happen until every extractor result has been validated.
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
                f"consolidate episodic: {result['created']} facts, "
                f"{result['reused']} reused, {len(links)} provenance edges")
        result["edges"] = len(links)
        return result

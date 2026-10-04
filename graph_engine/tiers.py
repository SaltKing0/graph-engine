"""Storage priority, independent of node type and lifecycle status.

Tier changes are persisted by maintenance, never by retrieval. Files remain at
stable nodes/<id>.md paths: tiers are logical storage classes, not moves.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .brain import Brain, Node, STORAGE_TIERS

if TYPE_CHECKING:
    from .brain_engine import BrainEngine

MAIN_MIN_RECALLS = 3
MAIN_RECENT_DAYS = 7
MAIN_IDLE_DAYS = 30
ARCHIVE_IDLE_DAYS = 90


def _age_days(value: str | None, now: datetime) -> float | None:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return max(0.0, (now - stamp).total_seconds() / 86400)
    except (ValueError, TypeError, AttributeError):
        return None


def recommended_tier(node: Node, *, now: datetime | None = None) -> str:
    """Keep manual choices; promote used memories and demote idle ones."""
    if node.tier_locked or node.status == "tombstone":
        return node.storage_tier
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age = _age_days(node.last_recalled or node.created, now)
    if age is None:
        return node.storage_tier  # unknown age must not trigger a demotion
    if age >= ARCHIVE_IDLE_DAYS:
        return "archival"
    if (node.last_recalled and age <= MAIN_RECENT_DAYS
            and node.recall_count >= MAIN_MIN_RECALLS):
        return "main"
    if node.storage_tier == "main" and age < MAIN_IDLE_DAYS:
        return "main"  # hysteresis avoids oscillation at the promotion boundary
    return "recall"


def rebalance(brain: Brain, *, dry_run: bool = False, commit: bool = True,
              now: datetime | None = None) -> list[dict]:
    """Apply automatic tier policy during maintenance (including idle brains)."""
    from .brain_engine import BRAIN_LOCK
    getattr(brain, "authorize", lambda **_: None)(action="admin")
    with BRAIN_LOCK:
        changes = []
        for node in brain.read_nodes():
            target = recommended_tier(node, now=now)
            if target == node.storage_tier:
                continue
            changes.append({"node_id": node.id, "from": node.storage_tier, "to": target})
            if not dry_run:
                node.storage_tier = target
                brain.write_node(node)
        if changes and not dry_run and commit:
            brain.commit_and_push(f"tiers: rebalance {len(changes)} memories")
        return changes


def set_tier(brain: Brain, node_id: str, tier: str | None, *,
             commit: bool = True) -> Node:
    """A manual tier is pinned until reset with tier=None (automatic policy)."""
    if tier is not None and tier not in STORAGE_TIERS:
        raise ValueError(f"Unknown storage tier: {tier!r}")
    from .brain_engine import BRAIN_LOCK
    with BRAIN_LOCK:
        getattr(brain, "authorize", lambda **_: None)(action="write", node_id=node_id)
        brain.ensure_ready()
        brain.pull()
        node = brain.read_node(node_id)
        if node is None:
            raise ValueError(f"No node with id {node_id!r}.")
        node.tier_locked = tier is not None
        node.storage_tier = tier if tier is not None else recommended_tier(node)
        brain.write_node(node)
        if commit:
            brain.commit_and_push(f"tier: {node_id} -> {node.storage_tier}")
        return node


def order_by_tier(hits: list[tuple[str, float]], tiers: dict[str, str]) -> list[tuple[str, float]]:
    """Stable priority order; preserve relevance/reranker order within a tier."""
    priority = {tier: index for index, tier in enumerate(STORAGE_TIERS)}
    return sorted(hits, key=lambda hit: priority.get(tiers.get(hit[0], "recall"), 1))


def cmd_tier(engine: BrainEngine, args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="ig tier")
    parser.add_argument("node_id", nargs="?")
    parser.add_argument("tier", nargs="?", choices=(*STORAGE_TIERS, "auto"))
    parser.add_argument("--rebalance", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    opts = parser.parse_args(args)
    if opts.rebalance and (opts.node_id or opts.tier):
        parser.error("--rebalance cannot be combined with a node")
    if opts.dry_run and not opts.rebalance:
        parser.error("--dry-run requires --rebalance")
    if not opts.rebalance and not opts.node_id:
        parser.error("provide a node ID or --rebalance")
    try:
        if opts.rebalance:
            getattr(engine.brain, "authorize", lambda **_: None)(action="admin")
            if not opts.dry_run:
                engine.brain.ensure_ready()
                engine.brain.pull()
            result = {"changes": rebalance(engine.brain, dry_run=opts.dry_run),
                      "dry_run": opts.dry_run}
        else:
            node = (set_tier(engine.brain, opts.node_id,
                             None if opts.tier == "auto" else opts.tier)
                    if opts.tier else engine.brain.read_node(opts.node_id))
            if node is None:
                raise ValueError(f"No node with id {opts.node_id!r}.")
            result = {"node_id": node.id, "storage_tier": node.storage_tier,
                      "tier_locked": node.tier_locked}
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2) if opts.json or opts.rebalance else
          f"{result['node_id']}  {result['storage_tier']}  "
          f"({'manual' if result['tier_locked'] else 'automatic'})")

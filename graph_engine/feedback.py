"""Deterministic retrieval learning from explicit user relevance judgments.

The tracked feedback.json file keeps the latest judgment per normalized
(query, node), avoiding repeated votes and allowing corrections. Channel rank
observations train bounded RRF weights; successful queries expand similar
queries with a small set of terms from currently visible, live target nodes.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .brain import Brain, Node, _atomic_write, _now_iso

if TYPE_CHECKING:
    from .brain_engine import BrainEngine

FEEDBACK_FILE = "feedback.json"
MAX_EXPANSION_TERMS = 5
STOP_WORDS = frozenset("a an and are as at be by for from in is it of on or that the this to was with".split())


def normalize(query: str) -> str:
    return " ".join(query.lower().split())


def _terms(text: str) -> list[str]:
    return [word for word in re.findall(r"\w+", text.lower())
            if len(word) > 2 and word not in STOP_WORDS]


def _read_feedback(brain: Brain) -> list[dict]:
    """Read valid rows; trusted RMW preserves judgments outside caller scope."""
    path = brain.path / FEEDBACK_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("judgments"), list):
            raise ValueError("unsupported feedback format")
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Cannot read {FEEDBACK_FILE}: {exc}") from exc
    rows = []
    for row in data["judgments"]:
        if (not isinstance(row, dict) or not isinstance(row.get("query"), str)
                or not normalize(row["query"]) or not isinstance(row.get("node_id"), str)
                or row.get("label") not in ("relevant", "irrelevant")):
            continue
        rows.append(row)
    return rows


def read_feedback(brain: Brain) -> list[dict]:
    """Read judgments only for currently visible, live nodes."""
    getattr(brain, "authorize", lambda **_: None)(action="read")
    visible = {node.id for node in brain.read_nodes() if node.status != "tombstone"}
    return [row for row in _read_feedback(brain) if row["node_id"] in visible]


@dataclass
class LearningProfile:
    query: str
    dense_weight: float = 1.0
    bm25_weight: float = 1.0
    expansion_terms: list[str] = field(default_factory=list)
    adjustments: dict[str, float] = field(default_factory=dict)

    @property
    def expanded_query(self) -> str:
        return " ".join([self.query, *self.expansion_terms])


def learning_profile(brain: Brain, query: str, nodes: list[Node]) -> LearningProfile:
    profile = LearningProfile(query)
    visible = {node.id: node for node in nodes if node.status != "tombstone"}
    # Latest row wins even in hand-edited files; a judgment cannot multiply votes.
    getattr(brain, "authorize", lambda **_: None)(action="read")
    judgments = {(normalize(row["query"]), row["node_id"]): row
                 for row in _read_feedback(brain) if row["node_id"] in visible}
    if not judgments:
        return profile
    dense_utility = bm25_utility = 0.0
    expansions: Counter[str] = Counter()
    query_terms = set(_terms(query))
    for (prior_query, nid), row in judgments.items():
        sign = 1 if row["label"] == "relevant" else -1
        def utility(channel: str) -> float:
            rank = row.get(channel + "_rank")
            return 1.0 / rank if isinstance(rank, int) and not isinstance(rank, bool) and rank > 0 else 0.0
        dense_utility += sign * utility("dense")
        bm25_utility += sign * utility("bm25")
        if prior_query == normalize(query):
            profile.adjustments[nid] = sign / 60.0
        prior_terms = set(_terms(prior_query))
        similarity = len(query_terms & prior_terms) / max(1, len(query_terms | prior_terms))
        if sign > 0 and similarity >= 0.5:
            expansions.update(set(_terms(visible[nid].text)) - query_terms)
    # Bounded update with a neutral prior: many duplicate votes cannot overpower
    # the other channel, and no-feedback behavior is exactly the existing RRF.
    delta = max(-0.5, min(0.5, (dense_utility - bm25_utility) / (2 + len(judgments))))
    profile.dense_weight = 1.0 + delta
    profile.bm25_weight = 1.0 - delta
    profile.expansion_terms = sorted(expansions, key=lambda t: (-expansions[t], t))[:MAX_EXPANSION_TERMS]
    return profile


def record_feedback(engine: BrainEngine, query: str, node_id: str, label: str, *,
                    commit: bool = True) -> dict:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be non-empty")
    if label not in ("relevant", "irrelevant"):
        raise ValueError("label must be relevant or irrelevant")
    from .brain_engine import BRAIN_LOCK
    from .retrieval import _retrieve_trace
    brain = engine.brain
    with BRAIN_LOCK:
        getattr(brain, "authorize", lambda **_: None)(action="write", node_id=node_id)
        brain.ensure_ready()
        brain.pull()
        node = brain.read_node(node_id)
        if node is None or node.status == "tombstone":
            raise ValueError(f"No live node with id {node_id!r}.")
        # Measure the baseline channels, not our own previous learned boost.
        trace = _retrieve_trace(engine, query, 30, persist=False, learn=False)
        rows = _read_feedback(brain)
        key = (normalize(query), node_id)
        rows = [row for row in rows if (normalize(row["query"]), row["node_id"]) != key]
        row = {"query": key[0], "node_id": node_id, "label": label, "at": _now_iso(),
               "dense_rank": trace.dense_ranks.get(node_id),
               "bm25_rank": trace.bm25_ranks.get(node_id)}
        rows.append(row)
        _atomic_write(brain.path / FEEDBACK_FILE,
                      json.dumps({"version": 1, "judgments": rows}, ensure_ascii=False, indent=2) + "\n")
        if commit:
            brain.commit_and_push(f"feedback: {label} for {node_id}")
        return row


def cmd_feedback(engine: BrainEngine, args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="ig feedback")
    parser.add_argument("query")
    parser.add_argument("node_id")
    parser.add_argument("label", choices=("relevant", "irrelevant"))
    parser.add_argument("--json", action="store_true")
    opts = parser.parse_args(args)
    try:
        result = record_feedback(engine, opts.query, opts.node_id, opts.label)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2) if opts.json else
          f"Recorded {opts.label} feedback for {opts.node_id}.")

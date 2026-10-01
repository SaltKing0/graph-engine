"""Recall tracking: what the memory is actually asked for.

A memory system that does not know which of its entries are ever retrieved
cannot decide what to keep, promote, or let decay — OpenClaw's dreaming
promotes a candidate only when it passed `minRecallCount` / `minUniqueQueries`,
and GraphEngine had no such signal at all (every node was equally "fresh"
forever, all 2120 stuck in `probation`).

Two halves, deliberately split so the READ path stays cheap and git-clean:

  * `record(brain, query, node_ids)` — append ONE line to the local ledger
    `<brain>/recalls.jsonl` (gitignored). No read-modify-write of node files,
    no commit per search: a search must not dirty the brain.
  * `aggregate(brain)` — folds the ledger into the derived counters on the
    nodes (`recall_count`, `recall_queries`, `last_recalled`) and writes them
    back in ONE pass. Called by the dream pass / `ig recall --aggregate`.

The counters are DERIVED data, like INDEX.md: the ledger is the source of
truth, the node fields are the queryable projection.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
from collections import Counter

from .brain import Brain, Node

LEDGER_NAME = "recalls.jsonl"
# Distinct query fingerprints kept per node: enough for "was this asked for in
# many different ways?" (OpenClaw's query-diversity gate) without unbounded
# frontmatter growth.
MAX_QUERY_FINGERPRINTS = 25


def ledger_path(brain: Brain) -> pathlib.Path:
    return pathlib.Path(brain.path) / LEDGER_NAME


def fingerprint(query: str) -> str:
    norm = " ".join(query.lower().split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]


def record(brain: Brain, query: str, node_ids: list[str], ts: str | None = None) -> int:
    """Append one recall event. Returns the number of node ids recorded."""
    ids = [nid for nid in node_ids if nid]
    if not ids:
        return 0
    entry = {"ts": ts or _now(), "q": fingerprint(query), "ids": ids}
    with open(ledger_path(brain), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return len(ids)


def read_ledger(brain: Brain) -> list[dict]:
    path = ledger_path(brain)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def aggregate(brain: Brain, *, dry_run: bool = False, commit: bool = True) -> dict:
    """Fold the recall ledger into the node counters (one pass, one commit).

    Per node: `recall_count` += occurrences, `recall_queries` = distinct query
    fingerprints (capped), `last_recalled` = newest ledger timestamp. The ledger
    is then MOVED to `<ledger>.processed` (audit trail) and truncated, so a
    second run is idempotent instead of double-counting.
    """
    entries = read_ledger(brain)
    if not entries:
        return {"nodes": 0, "recalls": 0, "ledger_entries": 0, "dry_run": dry_run}

    counts: Counter = Counter()
    queries: dict[str, set[str]] = {}
    last: dict[str, str] = {}
    for entry in entries:
        ts, fp = entry.get("ts"), entry.get("q")
        for nid in entry.get("ids", []):
            counts[nid] += 1
            if fp:
                queries.setdefault(nid, set()).add(fp)
            if ts and ts > last.get(nid, ""):
                last[nid] = ts

    nodes = {n.id: n for n in brain.read_nodes()}
    touched = 0
    for nid, increment in counts.items():
        node = nodes.get(nid)
        if node is None:
            continue  # recalled node was deleted/merged away since the ledger write
        node.recall_count = getattr(node, "recall_count", 0) + increment
        seen = list(getattr(node, "recall_queries", []))
        for fp in sorted(queries.get(nid, set())):
            if fp not in seen:
                seen.append(fp)
        node.recall_queries = seen[:MAX_QUERY_FINGERPRINTS]
        node.last_recalled = max(filter(None, [getattr(node, "last_recalled", None),
                                               last.get(nid)]), default=None)
        if not dry_run:
            brain.write_node(node)
        touched += 1

    if not dry_run:
        # Move the ledger, THEN optionally commit. The move is bookkeeping that
        # must happen whenever the counters were written — tying it to `commit`
        # was a real bug (found live 2026-09-18): `dream.refresh()` batches the
        # commit with `commit=False`, so the source entries stayed in place and
        # EVERY pass folded them again (recall_count 1 -> 2 on a single real
        # ledger line), inflating exactly the signal the promotion gates read.
        path = ledger_path(brain)
        processed = pathlib.Path(brain.path) / (LEDGER_NAME + ".processed")
        with open(processed, "a", encoding="utf-8") as fh:
            fh.write(path.read_text(encoding="utf-8"))
        path.write_text("", encoding="utf-8")
        if commit:
            brain.commit_and_push(
                f"recall: aggregate {sum(counts.values())} recalls into {touched} nodes")
    return {"nodes": touched, "recalls": sum(counts.values()),
            "ledger_entries": len(entries), "dry_run": dry_run}


def top(brain: Brain, n: int = 10) -> list[tuple[str, int]]:
    """Most-recalled nodes (derived counters, no aggregation)."""
    counts = Counter()
    for node in brain.read_nodes():
        if getattr(node, "recall_count", 0):
            counts[node.id] = node.recall_count
    return counts.most_common(n)


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def tracking_enabled(env: dict[str, str] | None = None) -> bool:
    """Recall tracking is on unless explicitly disabled (`IG_NO_RECALL_TRACKING=1`)."""
    raw = (env or {}).get("IG_NO_RECALL_TRACKING",
                          os.environ.get("IG_NO_RECALL_TRACKING", ""))
    return str(raw).lower() not in ("1", "true", "yes")
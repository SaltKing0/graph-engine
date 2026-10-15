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

from .write_guard import write_operation

import hashlib
import json
import os
import pathlib
from collections import Counter

from .brain import Brain, _atomic_write

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


@write_operation
def record(brain: Brain, query: str, node_ids: list[str], ts: str | None = None) -> int:
    """Append one recall event. Returns the number of node ids recorded."""
    brain.authorize("read")
    ids = [nid for nid in node_ids if nid and brain.can_access("write", nid)]
    if not ids:
        return 0
    entry = {"ts": ts or _now(), "q": fingerprint(query), "ids": ids}
    with open(ledger_path(brain), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return len(ids)


def _read_entries(brain: Brain, path: pathlib.Path) -> list[dict]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Unlocked readers can race a generation rotation or cleanup.
        return []
    out = []
    for line in raw.splitlines():
        if line.strip():
            try:
                entry = json.loads(line)
                entry["ids"] = [nid for nid in entry.get("ids", []) if brain.can_access("read", nid)]
                if entry["ids"]:
                    out.append(entry)
            except json.JSONDecodeError:
                continue
    return out


def read_ledger(brain: Brain) -> list[dict]:
    """Include a generation awaiting recovery as well as newly recorded events."""
    brain.authorize("read")
    pending = pathlib.Path(brain.path) / ".recall" / "pending.jsonl"
    return _read_entries(brain, pending) + _read_entries(brain, ledger_path(brain))


def _projection(brain: Brain, entries: list[dict]) -> dict:
    """Capture absolute targets BEFORE the first counter write."""
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

    targets = {}
    for node in brain.read_nodes():
        if node.id not in counts:
            continue
        seen = list(node.recall_queries)
        for fp in sorted(queries.get(node.id, set())):
            if fp not in seen:
                seen.append(fp)
        targets[node.id] = {
            "recall_count": node.recall_count + counts[node.id],
            "recall_queries": seen[:MAX_QUERY_FINGERPRINTS],
            "last_recalled": max(filter(None, [node.last_recalled, last.get(node.id)]),
                                 default=None),
        }
    return {"targets": targets, "recalls": sum(counts.values()),
            "ledger_entries": len(entries), "applied": False}


def _archive_generation(processed: pathlib.Path, pending: pathlib.Path, offset: int) -> None:
    """Resume even a partial append without duplicating any audit bytes.

    Writers hold the brain guard. Only this generation may extend the archive
    until its journal is cleared; an unexpected suffix requires inspection.
    """
    source = pending.read_bytes()
    with processed.open("a+b") as fh:
        fh.seek(0, os.SEEK_END)
        if fh.tell() < offset:
            raise RuntimeError("Recall archive shrank during aggregation; preserve .recall for recovery")
        fh.seek(offset)
        suffix = fh.read()
        if not source.startswith(suffix):
            raise RuntimeError("Recall archive changed during aggregation; preserve .recall for recovery")
        fh.write(source[len(suffix):])
        fh.flush()
        os.fsync(fh.fileno())


def _finish_generation(brain: Brain, state: pathlib.Path, plan: dict, *,
                       commit: bool, recovering: bool) -> None:
    from .tiers import rebalance
    journal, pending = state / "projection.json", state / "pending.jsonl"
    if not plan["applied"]:
        for nid, values in plan["targets"].items():
            # Read afresh: a retry must preserve edits to text/tags/tier, and
            # must not resurrect a node deleted since the interrupted pass.
            node = brain.read_node(nid)
            if node is None:
                continue
            if all(getattr(node, key) == value for key, value in values.items()):
                continue
            for key, value in values.items():
                setattr(node, key, value)
            brain.write_node(node)
        _archive_generation(pathlib.Path(brain.path) / (LEDGER_NAME + ".processed"),
                            pending, plan["archive_offset"])
        # Checkpoint BEFORE removing the source. Once applied, recovery only
        # retries cleanup/tier maintenance/sync, never stale counter targets.
        plan["applied"] = True
        _atomic_write(journal, json.dumps(plan))
    pending.unlink(missing_ok=True)
    if commit and recovering:
        brain.pull()  # restore a coherent local projection before any merge
    rebalance(brain, commit=False)
    if commit:
        brain.commit_and_push(
            f"recall: aggregate {plan['recalls']} recalls into {len(plan['targets'])} nodes",
            sync_pending=True)
    journal.unlink()


@write_operation
def aggregate(brain: Brain, *, dry_run: bool = False, commit: bool = True) -> dict:
    """Fold local recall events exactly once across interrupted retries.

    Rotate a ledger generation, durably journal its absolute counter targets,
    then project/archive it. The journal survives through tier maintenance and
    optional sync. Recovery replays assignments, not increments. The original
    JSONL bytes (including legacy events without IDs) are archived unchanged.
    """
    from .tiers import rebalance
    brain.authorize("admin")
    if dry_run:
        plan = _projection(brain, read_ledger(brain))
        if not plan["ledger_entries"]:
            rebalance(brain, dry_run=True, commit=commit)
        return {"nodes": len(plan["targets"]), "recalls": plan["recalls"],
                "ledger_entries": plan["ledger_entries"], "dry_run": True}

    if commit:
        brain.ensure_ready()
    state = pathlib.Path(brain.path) / ".recall"
    journal, pending = state / "projection.json", state / "pending.jsonl"
    touched: set[str] = set()
    recalls = ledger_entries = 0
    recovering = journal.exists() or pending.exists()
    while True:
        if journal.exists():
            plan = json.loads(journal.read_text(encoding="utf-8"))
        else:
            if not pending.exists() and not _read_entries(brain, ledger_path(brain)):
                break
            if commit:
                brain.pull()
            if not pending.exists():
                state.mkdir(exist_ok=True)
                # Keep recovery metadata local even in brains using `git add -A`.
                _atomic_write(state / ".gitignore", "*\n")
                os.replace(ledger_path(brain), pending)
            ledger_path(brain).touch(exist_ok=True)
            plan = _projection(brain, _read_entries(brain, pending))
            processed = pathlib.Path(brain.path) / (LEDGER_NAME + ".processed")
            plan["archive_offset"] = processed.stat().st_size if processed.exists() else 0
            _atomic_write(journal, json.dumps(plan))
        _finish_generation(brain, state, plan, commit=commit, recovering=recovering)
        touched.update(plan["targets"])
        recalls += plan["recalls"]
        ledger_entries += plan["ledger_entries"]
        recovering = False
    if not ledger_entries:
        rebalance(brain, commit=commit)
    return {"nodes": len(touched), "recalls": recalls,
            "ledger_entries": ledger_entries, "dry_run": False}


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

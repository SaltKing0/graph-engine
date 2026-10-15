"""Read committed brain records directly from Git's object database.

No checkout, temporary brain, vector cache, recall ledger or sync is involved.
Historical records are untrusted input; incompatible schemas fail explicitly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Callable
import os
from pathlib import Path
import re
import subprocess
from typing import TYPE_CHECKING

from .brain import Brain, Edge, Node, VALID_STATUS, STORAGE_TIERS

if TYPE_CHECKING:
    from .brain_engine import BrainEngine


def _timestamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=timezone.utc)


class SnapshotError(ValueError):
    """The requested revision or its storage schema cannot be read safely."""


def _git(brain: Brain, *args: str, data: bytes | None = None) -> bytes:
    # Do not let ambient Git overrides select a different repository/index.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    env["GIT_NO_LAZY_FETCH"] = "1"
    try:
        result = subprocess.run(["git", "-C", str(brain.path), *args],
                                input=data, capture_output=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SnapshotError("Snapshot Git read unavailable or timed out") from exc
    if result.returncode:
        raise SnapshotError("Snapshot revision unavailable in the brain repository")
    return result.stdout


def _records(brain: Brain, revision: str) -> tuple[str, str, dict[str, str]]:
    if brain.mode != "git":
        raise SnapshotError("Git snapshots require a Git-mode brain with committed history")
    if (not isinstance(revision, str) or len(revision) > 200
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*(?:[~^][0-9]{0,4}){0,4}", revision)
            or ".." in revision or "//" in revision):
        raise SnapshotError("Invalid snapshot revision: use a commit/ref with optional ~N or ^N")
    root = _git(brain, "rev-parse", "--show-toplevel").decode().strip()
    if Path(root).resolve() != brain.path:
        raise SnapshotError("Brain path must be the Git repository root")
    sha = _git(brain, "rev-parse", "--verify", "--end-of-options",
               revision + "^{commit}").decode().strip()
    committed_at = _git(brain, "show", "-s", "--format=%cI", sha).decode().strip()
    entries = _git(brain, "ls-tree", "-r", "-l", "-z", sha, "--", "nodes", "edges.jsonl")
    blobs: list[tuple[str, str, int]] = []
    try:
        for entry in entries.split(b"\0"):
            if not entry:
                continue
            metadata, name = entry.split(b"\t", 1)
            path = name.decode("utf-8")
            if path != "edges.jsonl" and not re.fullmatch(r"nodes/[^/]+\.md", path):
                raise ValueError("unsupported record path")
            mode, kind, oid, size = metadata.split()
            if mode not in (b"100644", b"100755") or kind != b"blob":
                raise ValueError("records must be regular files")
            blobs.append((path, oid.decode("ascii"), int(size)))
        if "edges.jsonl" not in {path for path, _, _ in blobs}:
            raise ValueError("missing edges.jsonl")
        if len(blobs) > 50000 or sum(size for _, _, size in blobs) > 64 * 1024 * 1024:
            raise ValueError("snapshot exceeds 50,000 records or 64 MiB")
        output = _git(brain, "cat-file", "--batch",
                      data="".join(oid + "\n" for _, oid, _ in blobs).encode("ascii"))
        records = {}
        offset = 0
        for path, oid, size in blobs:
            end = output.index(b"\n", offset)
            if output[offset:end] != f"{oid} blob {size}".encode("ascii"):
                raise ValueError("unexpected Git object")
            start = end + 1
            records[path] = output[start:start + size].decode("utf-8")
            offset = start + size + 1
        return sha, committed_at, records
    except (ValueError, UnicodeError) as exc:
        raise SnapshotError(f"Incompatible historical schema: {exc}") from exc


_NODE_KEYS = {"id", "created", "source", "type", "status", "storage_tier", "tier_locked",
              "sources", "tags", "capture", "document", "derived_from", "entity_name", "entity_type",
              "aliases", "observed_at", "context", "recalls", "recall_queries", "last_recalled"}
_EDGE_KEYS = {"id", "source", "target", "kind", "pending", "valid_from", "valid_to",
              "confidence", "invalidated_by", "rejected", "origin", "predicate", "evidence",
              "extracted_validity", "invalidated_at", "replacement", "superseded_by",
              "reviewed_at", "reviewed_by"}


def _parse_edge(row: dict, *, decision_record: bool = False) -> Edge:
    if (not isinstance(row, dict) or set(row) - _EDGE_KEYS
            or not all(isinstance(row.get(k), str) and row[k]
                       for k in ("id", "source", "target", "kind"))
            or "valid_from" not in row
            or any(type(row.get(k, False)) is not bool for k in ("pending", "rejected"))):
        raise ValueError("unsupported edge metadata")
    evidence = row.get("evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("unsupported evidence metadata")
    for item in evidence:
        if (not isinstance(item, dict) or not isinstance(item.get("node_id"), str)
                or set(item) not in ({"node_id", "text"}, {"node_id", "quote"})
                or not isinstance(item.get("text", item.get("quote")), str)):
            raise ValueError("unsupported evidence metadata")
    validity = row.get("extracted_validity")
    if validity is not None:
        if not isinstance(validity, dict) or set(validity) != {"valid_from", "valid_to"}:
            raise ValueError("unsupported extracted validity")
        for value in validity.values():
            if value is not None:
                _timestamp(value)
    # Avoid manufacturing a query-time date via Edge's legacy defaults.
    if row["valid_from"] is None and not (
            row.get("origin") == "consolidator" and evidence and validity is not None):
        raise ValueError("missing edge validity start")
    for key in ("valid_from", "valid_to", "invalidated_at", "reviewed_at"):
        if row.get(key) is not None:
            _timestamp(row[key])
    meta = row.get("replacement")
    if decision_record and (row["kind"] != "fact" or meta is not None):
        raise ValueError("unsupported replacement decision record")
    if row["kind"] == "fact_replacement" or meta is not None:
        if (row["kind"] != "fact_replacement" or not isinstance(meta, dict)
                or set(meta) - {"old_fact_id", "new_fact_id", "reason", "basis", "effective_at", "decision"}
                or not all(isinstance(meta.get(k), str) for k in
                           ("old_fact_id", "new_fact_id", "reason", "basis"))):
            raise ValueError("unsupported replacement metadata")
        if meta.get("effective_at") is not None:
            _timestamp(meta["effective_at"])
        if "decision" in meta:
            decision = meta["decision"]
            if not isinstance(decision, dict) or set(decision) != {"before", "after"}:
                raise ValueError("unsupported replacement decision")
            for rows in decision.values():
                if not isinstance(rows, list) or len(rows) != 2:
                    raise ValueError("unsupported replacement decision")
                for record in rows:
                    _parse_edge(record, decision_record=True)
    return Edge(**{"pending": False, **row})


def _parse_records(records: dict[str, str]) -> tuple[dict[str, Node], list[Edge]]:
    import json
    nodes = {}
    try:
        for path, text in records.items():
            if path == "edges.jsonl":
                continue
            match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
            if not match:
                raise ValueError("missing node frontmatter")
            meta = dict(line.split(":", 1) for line in match[1].splitlines() if ":" in line)
            meta = {k.strip(): v.strip() for k, v in meta.items()}
            if (set(meta) - _NODE_KEYS or not meta.get("created")
                    or meta.get("status", "probation") not in VALID_STATUS
                    or meta.get("type", "semantic") not in ("semantic", "episodic", "procedural", "entity")
                    or meta.get("tier_locked", "false") not in ("true", "false")
                    or meta.get("storage_tier", "recall") not in STORAGE_TIERS):
                raise ValueError("unsupported node metadata")
            datetime.fromisoformat(meta["created"].replace("Z", "+00:00"))
            int(meta.get("recalls", "0"))
            node = Node.from_markdown(text)
            if (node.id.startswith(".") or "\\" in node.id or "\x00" in node.id
                    or len(node.id) > 200):
                raise ValueError("invalid node ID")
            if path != f"nodes/{node.id}.md" or not node.id or node.id in nodes:
                raise ValueError("node ID/path mismatch")
            nodes[node.id] = node
        edges = []
        ids = set()
        for line in records["edges.jsonl"].splitlines():
            if not line.strip():
                continue
            edge = _parse_edge(json.loads(line))
            if edge.id in ids:
                raise ValueError("duplicate edge ID")
            if len(nodes) + len(edges) >= 50000:
                raise ValueError("snapshot exceeds 50,000 records")
            ids.add(edge.id)
            edges.append(edge)
        return nodes, edges
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SnapshotError("Incompatible historical schema: invalid node or edge record") from exc


def snapshot(brain: Brain, revision: str, *, fact_valid_at: str | None = None) -> dict:
    """Read tracked state at a commit, authorized by the CURRENT access policy.

    Without a validity filter, retain snapshot tombstones and pending/rejected
    decisions. With a filter, expose only live nodes and accepted valid edges.
    """
    brain.authorize("read")
    stamp = None
    if fact_valid_at is not None:
        try:
            stamp = _timestamp(fact_valid_at)
        except (ValueError, TypeError, AttributeError) as exc:
            raise SnapshotError("Invalid fact-validity timestamp") from exc
    sha, committed_at, records = _records(brain, revision)
    nodes, edges = _parse_records(records)

    from .access import SecuredBrain, derivation_parents, provenance_allowed
    current_view = brain._access_view() if isinstance(brain, SecuredBrain) else None
    historical_parents = derivation_parents(nodes, edges) if current_view is not None else {}

    def allowed(nid: str) -> bool:
        if current_view is not None:
            # Historical text must satisfy historical lineage AND today's lineage/ACLs.
            return provenance_allowed(nid, nodes, historical_parents,
                lambda source: brain.can_access("read", source, _view=current_view))
        # Both the historical AND current copy-parent chain must be readable.
        # Removed IDs still use their current explicit ACL/graph membership.
        seen = set()
        while nid not in seen and nid in nodes and brain.can_access("read", nid):
            seen.add(nid)
            node = nodes[nid]
            if not node.capture or not node.capture["duplicate"]:
                return True
            nid = node.capture["node_id"]
        return False

    readable = {nid for nid in nodes if allowed(nid)}
    visible = {nid for nid in readable if stamp is None or (
        nodes[nid].status != "tombstone" and
        _timestamp(nodes[nid].created) <= stamp)}
    # Reuse the storage ACL boundary for replacement records and their embedded
    # undo evidence. It checks current permissions against historical fact IDs.

    class SnapshotAccess:
        _edge_allowed = SecuredBrain._edge_allowed

        def can_access(self, action: str, node_id: str) -> bool:
            return node_id in readable

    checker = SnapshotAccess()
    by_id = {edge.id: edge for edge in edges}
    result_edges = []
    for edge in edges:
        if (edge.source not in visible or edge.target not in visible
                or any(e["node_id"] not in visible for e in edge.evidence)):
            continue
        try:
            if not checker._edge_allowed(edge, "read", edges_by_id=by_id):
                continue
        except (KeyError, TypeError, AttributeError) as exc:
            raise SnapshotError("Incompatible historical schema: invalid review evidence") from exc
        if stamp is not None and (edge.pending or edge.rejected or not edge.is_valid_at(stamp)):
            continue
        result_edges.append(edge)
    return {"revision": sha, "commit_time": committed_at, "fact_valid_at": fact_valid_at,
            "nodes": [nodes[nid] for nid in sorted(visible)], "edges": result_edges}


class _SnapshotStore:
    """Only the in-memory read contract required by hybrid retrieval."""

    def __init__(self, nodes: list[Node]) -> None:
        self.nodes = nodes

    def read_nodes(self) -> list[Node]:
        return self.nodes

    def vectors_for(self, node_ids: set[str], embed_fn: Callable[[str], list[float]],
                    **kwargs: object) -> dict[str, list[float]]:
        from .vector_cache import normalize_text
        return {node.id: embed_fn(normalize_text(node.text))
                for node in self.nodes if node.id in node_ids}


def snapshot_query(engine: BrainEngine, revision: str, query: str, *, k: int = 5,
                   fact_valid_at: str | None = None) -> dict:
    """Rank historical text; no current feedback, vectors, graph expansion or recall."""
    if not isinstance(query, str) or not query.strip() or len(query) > 4000:
        raise SnapshotError("Snapshot query must contain 1 to 4000 characters")
    if type(k) is not int or not 1 <= k <= 100:
        raise SnapshotError("Snapshot k must be an integer between 1 and 100")
    from .brain_engine import BrainEngine
    from .retrieval import _retrieve_trace, _finish_retrieval
    result = snapshot(engine.brain, revision, fact_valid_at=fact_valid_at)
    view = BrainEngine(_SnapshotStore(result["nodes"]), embedder=engine.embedder,
                       reranker=engine.reranker, search_cache_enabled=False)
    trace = _retrieve_trace(view, query, max(30, k), persist=False, learn=False)
    hits = _finish_retrieval(view, query, k, trace, track=False)
    result["hits"] = hits
    hit_ids = {nid for nid, _ in hits}
    by_id = {node.id: node for node in result["nodes"]}
    result["nodes"] = [by_id[nid] for nid, _ in hits]
    result["edges"] = [e for e in result["edges"] if e.source in hit_ids and e.target in hit_ids]
    result["query"] = query
    result["score_kind"] = "rrf"
    return result

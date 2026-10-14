"""Opt-in application access control for trusted CLI/MCP and bearer-auth HTTP.

The OS account, policy file and Python caller remain trusted. This does not
sandbox Python or encrypt a brain against someone who can read its files.
"""
from __future__ import annotations

from .write_guard import write_operation

from contextvars import ContextVar
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path

from .brain import Brain, Edge, Node

request_principal: ContextVar[str | None] = ContextVar("ig_principal", default=None)


def policy_path() -> str:
    return os.environ.get("IG_ACCESS_POLICY", "")


def load_policy() -> dict:
    try:
        data = json.loads(Path(policy_path()).expanduser().read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("graphs"), dict):
            raise ValueError("missing graphs object")
        for config in data["graphs"].values():
            if not isinstance(config, dict) or not isinstance(config.get("roles"), dict):
                raise ValueError("missing roles object")
            if any(r not in ("admin", "editor", "viewer") for r in config["roles"].values()):
                raise ValueError("unknown role")
            for acl in config.get("nodes", {}).values():
                if not isinstance(acl, dict) or set(acl) - {"read", "write"}:
                    raise ValueError("invalid node ACL")
                if any(not isinstance(v, list) or any(not isinstance(p, str) for p in v)
                       for v in acl.values()):
                    raise ValueError("ACL must contain principal lists")
        return data
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise PermissionError("Access policy unavailable or invalid") from exc


def principal() -> str:
    return request_principal.get() if request_principal.get() is not None else os.environ.get("IG_PRINCIPAL", "")


def token_principal(authorization: str) -> str:
    if not authorization.startswith("Bearer "):
        raise PermissionError("Bearer authentication required")
    digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
    identity = load_policy().get("tokens", {}).get(digest)
    if not isinstance(identity, str) or not identity:
        raise PermissionError("Invalid bearer token")
    return identity


def audit(graph: str, identity: str, action: str, allowed: bool,
          node_id: str | None = None) -> None:
    # A separate file beside the trusted policy avoids exporting security logs
    # with a brain git push. Failure to append fails the operation closed.
    row = {"ts": datetime.now(timezone.utc).isoformat(), "principal": identity,
           "graph": graph, "action": action, "allowed": allowed, "node_id": node_id}
    path = Path(policy_path()).expanduser().with_suffix(".audit.jsonl")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def permitted(graph: str, identity: str, action: str, node_id: str | None = None) -> bool:
    policy = load_policy()
    config = policy["graphs"].get(graph, {})
    role = config.get("roles", {}).get(identity)
    if not identity or role not in ("admin", "editor", "viewer"):
        return False
    if role == "admin":
        return True
    if action == "admin" or (action == "write" and role != "editor"):
        return False
    if action not in ("read", "write"):
        return False
    acl = config.get("nodes", {}).get(node_id, {})
    readers = acl.get("read")
    if readers is not None and identity not in readers and "*" not in readers:
        return False
    users = acl.get(action)
    return users is None or identity in users or "*" in users


def require(graph: str, identity: str, action: str, node_id: str | None = None) -> None:
    allowed = permitted(graph, identity, action, node_id)
    audit(graph, identity, action, allowed, node_id)
    if not allowed:
        raise PermissionError("Access denied")


def derivation_parents(nodes: dict[str, Node], edges: list[Edge]) -> dict[str, set[str]]:
    """Recorded dependencies, including conservative legacy lineage recovery."""
    parents: dict[str, set[str]] = {}
    for edge in edges:
        if edge.origin == "consolidator" and edge.kind == "extends":
            parents.setdefault(edge.source, set()).add(edge.target)
        elif edge.origin == "entity-extractor" and edge.kind == "mentions":
            parents.setdefault(edge.target, set()).add(edge.source)
    for node in nodes.values():
        parents.setdefault(node.id, set()).update(node.derived_from)
        parents[node.id].update(re.findall(
            r"\[consolidated from ([^/\\\r\n\]\x00]+?) on ", node.text))
        if not node.derived_from:
            # Old summaries/proposals omit model inputs beyond their cited edges.
            if "community-summary" in node.tags or "consolidation-proposal" in node.tags:
                parents[node.id].add("")
            if (node.source in ("consolidator", "entity-extractor")
                    or "episodic-extraction" in node.tags) and not parents[node.id]:
                parents[node.id].add("")
        if node.capture and node.capture["duplicate"]:
            parents[node.id].add(node.capture["node_id"])
    return parents


def provenance_allowed(node_id: str, nodes: dict[str, Node], parents: dict[str, set[str]],
                       check: Callable[[str], bool], *, allow_new: bool = False) -> bool:
    """Iterative DFS: allow shared ancestors; deny missing sources and cycles."""
    active, complete = set(), set()
    stack = [(node_id, False)]
    while stack:
        nid, leaving = stack.pop()
        if leaving:
            active.remove(nid)
            complete.add(nid)
            continue
        if nid in complete:
            continue
        if nid in active or not check(nid):
            return False
        if nid not in nodes:
            return allow_new and nid == node_id and not active
        active.add(nid)
        stack.append((nid, True))
        stack.extend((parent, False) for parent in sorted(parents.get(nid, set()), reverse=True))
    return True


class SecuredBrain(Brain):
    """Filter reads and authorize mutations at the shared storage boundary."""

    def __init__(self, *args, graph_name: str, identity: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.graph_name, self.identity = graph_name, identity
        self._raw = Brain(str(self.path), self.remote, self.mode)
        self.authorize("read")

    def authorize(self, action: str, node_id: str | None = None) -> None:
        allowed = self.can_access(action, node_id)
        audit(self.graph_name, self.identity, action, allowed, node_id)
        if not allowed:
            raise PermissionError("Access denied")

    def _access_view(self) -> tuple[dict[str, Node], dict[str, set[str]]]:
        """Operation-local provenance snapshot; never cache permissions across reads."""
        nodes = {n.id: n for n in self._raw.read_nodes()}
        # Compatibility for copies/extractions predating persisted provenance.
        # Review state does not remove a dependency on embedded source text.
        parents = derivation_parents(nodes, self._raw.read_edges(include_rejected=True))
        return nodes, parents

    def can_access(self, action: str, node_id: str | None = None, *,
                   _view: tuple[dict[str, Node], dict[str, set[str]]] | None = None) -> bool:
        if node_id is None:
            return permitted(self.graph_name, self.identity, action)
        nodes, parents = _view or self._access_view()
        # New root IDs are permitted for writes; missing sources fail closed.
        return provenance_allowed(node_id, nodes, parents,
            lambda nid: permitted(self.graph_name, self.identity, action, nid), allow_new=True)

    def read_nodes(self) -> list[Node]:
        self.authorize("read")
        view = self._access_view()
        return [n for n in view[0].values() if self.can_access("read", n.id, _view=view)]

    def read_node(self, node_id: str) -> Node | None:
        self.authorize("read", node_id)
        return self._raw.read_node(node_id)

    @write_operation
    def write_node(self, node: Node) -> None:
        self.authorize("write", node.id)
        node._validate_derivation()
        nodes, parents = self._access_view()
        # A normal rewrite must not silently publish previously private text.
        # Keep historical dependencies even if edges or capture metadata change.
        inherited = parents.get(node.id, set())
        node.derived_from = sorted(set(node.derived_from) | inherited)
        proposed = set(node.derived_from)
        if node.capture and node.capture["duplicate"]:
            proposed.add(node.capture["node_id"])
        nodes[node.id], parents[node.id] = node, proposed
        if not self.can_access("write", node.id, _view=(nodes, parents)):
            audit(self.graph_name, self.identity, "write", False, node.id)
            raise PermissionError("Derived source unavailable or access denied")
        self._raw.write_node(node)

    def capture_receipts(self, node_id: str) -> list[Node]:
        # Discover all copies before a forget, including copies with tighter
        # ACLs than their survivor. Fail before returning or changing any data.
        self.authorize("write", node_id)
        receipts = self._raw.capture_receipts(node_id)
        for node in receipts:
            self.authorize("write", node.id)
        return receipts

    def _edge_allowed(self, edge: Edge, action: str, *,
                      edges_by_id: dict[str, Edge] | None = None,
                      _view: tuple[dict[str, Node], dict[str, set[str]]] | None = None) -> bool:
        # Evidence is embedded text: hiding only the endpoints would leak it.
        ids = [edge.source, edge.target] + [e.get("node_id") for e in edge.evidence]
        if edge.kind == "fact_replacement":
            meta = edge.replacement or {}
            records = (edges_by_id if edges_by_id is not None else
                       {e.id: e for e in self._raw.read_edges(include_rejected=True)})
            for key in ("old_fact_id", "new_fact_id"):
                fact = records.get(meta.get(key))
                if fact is None or fact.kind != "fact" or not self._edge_allowed(fact, action, _view=_view):
                    return False
            # Undo snapshots contain embedded quotes too; their permissions
            # remain mandatory even if the current fact later loses support.
            for rows in meta.get("decision", {}).values():
                for row in rows:
                    ids.extend([row["source"], row["target"],
                                *(e.get("node_id") for e in row.get("evidence", []))])
        return all(isinstance(nid, str) and (
            self.can_access(action, nid, _view=_view) if _view is not None else
            self.can_access(action, nid)) for nid in ids)

    def read_edges(self, include_rejected: bool = False) -> list[Edge]:
        self.authorize("read")
        view = self._access_view()
        return [e for e in self._raw.read_edges(include_rejected)
                if self._edge_allowed(e, "read", _view=view)]

    @write_operation
    def write_edges(self, edges: list[Edge]) -> None:
        self.authorize("write")
        with self._lock:
            view = self._access_view()
            old = {e.id: e for e in self._raw.read_edges(include_rejected=True)}
            new = {e.id: e for e in edges}
            # Complete the proposed view before checking references. Hidden
            # records survive bulk rewrites regardless of validation order.
            for eid in old.keys() - new.keys():
                if not self._edge_allowed(old[eid], "read", edges_by_id=old, _view=view):
                    new[eid] = old[eid]
            for eid in old.keys() | new.keys():
                before, after = old.get(eid), new.get(eid)
                if before and after and before.to_dict() == after.to_dict():
                    continue
                # Check the saved record against saved facts and the proposed
                # record against facts in this same atomic write.
                for edge, records in ((before, old), (after, new)):
                    if edge is not None and not self._edge_allowed(edge, "write", edges_by_id=records, _view=view):
                        audit(self.graph_name, self.identity, "write_edge", False)
                        raise PermissionError("Access denied")
            # Persist legacy dependencies before their evidence is removed or
            # redirected. A crash can leave extra restrictions, never publication.
            affected = set()
            for eid, edge in old.items():
                if eid in new and edge.to_dict() == new[eid].to_dict():
                    continue
                if edge.origin == "consolidator" and edge.kind == "extends":
                    affected.add(edge.source)
                elif edge.origin == "entity-extractor" and edge.kind == "mentions":
                    affected.add(edge.target)
            for nid in sorted(affected):
                node = view[0].get(nid)
                if node is not None and view[1].get(nid, set()) - set(node.derived_from):
                    self.write_node(node)
            self._raw.write_edges(list(new.values()))

    def read_vectors(self) -> dict[str, list[float]]:
        self.authorize("read")
        view = self._access_view()
        return {nid: v for nid, v in self._raw.read_vectors().items()
                if nid in view[0] and self.can_access("read", nid, _view=view)}

    @write_operation
    def write_vectors(self, vectors: dict[str, list[float]]) -> None:
        self.authorize("write")
        old = self._raw.read_vectors()
        view = self._access_view()
        for nid, vector in vectors.items():
            if old.get(nid) != vector:
                self.authorize("write", nid)
        # Preserve vectors outside the caller's view, including node ACLs.
        preserved = {nid: v for nid, v in old.items() if not self.can_access("read", nid, _view=view)}
        for nid in old.keys() - vectors.keys() - preserved.keys():
            self.authorize("write", nid)
        self._raw.write_vectors({**preserved, **vectors})

    def vectors_for(self, node_ids: set[str], embed_fn, batch_fn=None,
                    persist: bool = True) -> dict[str, list[float]]:
        # Do not use the global unscoped memo or persist search side effects.
        nodes = {n.id: n for n in self.read_nodes() if n.id in node_ids}
        cached = self.read_vectors()
        missing = sorted(nodes.keys() - cached.keys())
        values = batch_fn([nodes[n].text for n in missing]) if batch_fn and missing else [embed_fn(nodes[n].text) for n in missing]
        cached.update(zip(missing, values))
        return {nid: cached[nid] for nid in nodes if nid in cached}

    @write_operation
    def ensure_ready(self) -> None:
        self.authorize("write")
        self._raw.ensure_ready()

    @write_operation
    def init(self, remote: str | None = None, commit: bool = True) -> None:
        self.authorize("admin")
        self._raw.init(remote, commit)

    @write_operation
    def clone_if_missing(self) -> None:
        self.authorize("admin")
        self._raw.clone_if_missing()

    @write_operation
    def pull(self) -> None:
        self.authorize("write")
        self._raw.pull()

    @write_operation
    def commit_and_push(self, message: str, push: bool = True, *, sync_pending: bool = False) -> None:
        self.authorize("write")
        self._raw.commit_and_push(message, push, sync_pending=sync_pending)

    @write_operation
    def rebuild_index(self) -> None:
        self.authorize("write")
        # Generate complete internal derived state, not a filtered INDEX that
        # would erase other users' entries. INDEX is never served by HTTP/MCP.
        self._raw.rebuild_index()

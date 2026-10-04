"""Opt-in application access control for trusted CLI/MCP and bearer-auth HTTP.

The OS account, policy file and Python caller remain trusted. This does not
sandbox Python or encrypt a brain against someone who can read its files.
"""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
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


class SecuredBrain(Brain):
    """Filter reads and authorize mutations at the shared storage boundary."""

    def __init__(self, *args, graph_name: str, identity: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.graph_name, self.identity = graph_name, identity
        self._raw = Brain(str(self.path), self.remote, self.mode)
        self.authorize("read")

    def authorize(self, action: str, node_id: str | None = None) -> None:
        require(self.graph_name, self.identity, action, node_id)

    def can_access(self, action: str, node_id: str | None = None) -> bool:
        return permitted(self.graph_name, self.identity, action, node_id)

    def read_nodes(self) -> list[Node]:
        self.authorize("read")
        return [n for n in self._raw.read_nodes() if self.can_access("read", n.id)]

    def read_node(self, node_id: str) -> Node | None:
        self.authorize("read", node_id)
        return self._raw.read_node(node_id)

    def write_node(self, node: Node) -> None:
        self.authorize("write", node.id)
        self._raw.write_node(node)

    def _edge_allowed(self, edge: Edge, action: str) -> bool:
        # Evidence is embedded text: hiding only the endpoints would leak it.
        ids = [edge.source, edge.target] + [e.get("node_id") for e in edge.evidence]
        return all(isinstance(nid, str) and self.can_access(action, nid) for nid in ids)

    def read_edges(self, include_rejected: bool = False) -> list[Edge]:
        self.authorize("read")
        return [e for e in self._raw.read_edges(include_rejected) if self._edge_allowed(e, "read")]

    def write_edges(self, edges: list[Edge]) -> None:
        self.authorize("write")
        with self._lock:
            old = {e.id: e for e in self._raw.read_edges(include_rejected=True)}
            new = {e.id: e for e in edges}
            for eid in old.keys() | new.keys():
                before, after = old.get(eid), new.get(eid)
                if before and after and before.to_dict() == after.to_dict():
                    continue
                if before and after is None and not self._edge_allowed(before, "read"):
                    new[eid] = before  # bulk rewrites must preserve hidden records
                    continue
                for edge in (before, after):
                    if edge is not None and not self._edge_allowed(edge, "write"):
                        audit(self.graph_name, self.identity, "write_edge", False)
                        raise PermissionError("Access denied")
            self._raw.write_edges(list(new.values()))

    def read_vectors(self) -> dict[str, list[float]]:
        self.authorize("read")
        return {nid: v for nid, v in self._raw.read_vectors().items() if self.can_access("read", nid)}

    def write_vectors(self, vectors: dict[str, list[float]]) -> None:
        self.authorize("write")
        old = self._raw.read_vectors()
        for nid, vector in vectors.items():
            if old.get(nid) != vector:
                self.authorize("write", nid)
        # Preserve vectors outside the caller's view, including node ACLs.
        preserved = {nid: v for nid, v in old.items() if not self.can_access("read", nid)}
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

    def ensure_ready(self) -> None:
        self.authorize("write")
        self._raw.ensure_ready()

    def init(self, remote: str | None = None, commit: bool = True) -> None:
        self.authorize("admin")
        self._raw.init(remote, commit)

    def clone_if_missing(self) -> None:
        self.authorize("admin")
        self._raw.clone_if_missing()

    def pull(self) -> None:
        self.authorize("write")
        self._raw.pull()

    def commit_and_push(self, message: str, push: bool = True) -> None:
        self.authorize("write")
        self._raw.commit_and_push(message, push)

    def rebuild_index(self) -> None:
        self.authorize("write")
        # Generate complete internal derived state, not a filtered INDEX that
        # would erase other users' entries. INDEX is never served by HTTP/MCP.
        self._raw.rebuild_index()

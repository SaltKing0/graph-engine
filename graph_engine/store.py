"""JSONL store: one JSON line per object. No DB overhead."""

from __future__ import annotations

import json
from pathlib import Path

from .model import Node, Edge


class Store:
    """Holds nodes and edges as JSONL (separate files)."""

    def __init__(self, path: str | Path = "data.jsonl"):
        self.path = Path(path)
        self.edges_path = self.path.with_suffix(".edges.jsonl")
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.nodes.append(Node.from_dict(json.loads(line)))
        if self.edges_path.exists():
            for line in self.edges_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.edges.append(Edge.from_dict(json.loads(line)))

    def add_node(self, node: Node) -> None:
        self.nodes.append(node)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(node.to_dict(), ensure_ascii=False) + "\n")

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)
        with self.edges_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(edge.to_dict(), ensure_ascii=False) + "\n")

    def resolve_edge(self, edge_id: str, accept: bool) -> Edge | None:
        """Accept a pending edge (pending=False) or discard it (remove)."""
        edge = next((e for e in self.edges if e.id == edge_id), None)
        if edge is None or not edge.pending:
            return None
        if accept:
            edge.pending = False
            self._rewrite_edges()
            return edge
        self.edges.remove(edge)
        self._rewrite_edges()
        return edge

    def _rewrite_edges(self) -> None:
        with self.edges_path.open("w", encoding="utf-8") as f:
            for e in self.edges:
                f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")

    def graph_state(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

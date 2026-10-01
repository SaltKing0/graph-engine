"""Core data model: nodes (ideas) and typed edges.

Edges carry a type: "similar", "contradicts", "extends".
Pending edges are suggestions from the growth loop and wait for a
human-in-the-loop decision (accept/discard).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict

EDGE_TYPES = ("similar", "contradicts", "extends")


def _now() -> float:
    return time.time()


@dataclass
class Node:
    text: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        return cls(text=d["text"], id=d["id"], created=d.get("created", 0.0))


@dataclass
class Edge:
    source: str          # node ID (new idea)
    target: str          # node ID (existing idea)
    kind: str            # one of EDGE_TYPES
    pending: bool = True  # suggestion until accepted/discarded
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Edge":
        return cls(
            source=d["source"],
            target=d["target"],
            kind=d["kind"],
            pending=d.get("pending", False),
            id=d["id"],
            created=d.get("created", 0.0),
        )

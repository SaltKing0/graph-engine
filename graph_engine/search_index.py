"""Disposable process-local search snapshots. Canonical files remain authoritative."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .brain import Node


def file_stamp(path: Path) -> tuple | None:
    try:
        stat = path.stat()
        return (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except FileNotFoundError:
        return None


def corpus_stamp(path: Path) -> tuple:
    """Scan on every request: adds/removes, atomic replacement, edits and pulls.

    This detects completed local writes, not a transactional read snapshot.
    Like ordinary reads, a concurrent writer may change files during a query.
    """
    return (str(path.resolve()),
            tuple((file.name, file_stamp(file)) for file in sorted((path / "nodes").glob("*.md"))),
            file_stamp(path / "vectors.jsonl"))


@dataclass(frozen=True, eq=False)
class _Identity:
    value: Any

    def __hash__(self) -> int:
        return id(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Identity) and self.value is other.value


def embedder_stamp(embedder: Any) -> tuple:
    """Retain objects to prevent ID reuse; support unhashable custom adapters.

    Custom mutable adapters must change cache_key when their model changes.
    """
    from .vector_cache import model_identity, model_key
    return (_Identity(embedder), model_key(None, model_identity(embedder)),
            _Identity(getattr(embedder, "_model", None)))


@dataclass(frozen=True)
class SearchIndex:
    key: tuple
    nodes: list[Node]
    dense_ids: list[str]
    matrix: np.ndarray
    bm25: Any
    dimension: int

    def valid(self) -> bool:
        # No on-disk index to deserialize. Discard a malformed memory entry.
        try:
            return (isinstance(self.matrix, np.ndarray) and self.matrix.ndim == 2
                    and self.matrix.shape == (len(self.dense_ids), self.dimension)
                    and self.bm25.N == len(self.nodes))
        except (AttributeError, TypeError):
            return False

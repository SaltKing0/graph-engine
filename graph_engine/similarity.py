"""Similarity: cosine similarity + k nearest neighbors."""

from __future__ import annotations

import math


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. Audit #8: mismatched dimensions are a data error
    (e.g. 384-dim ST vector vs. 64-dim hash vector in one brain) — a silent
    truncation to the shorter length produces plausible-looking scores and can
    trigger a wrong auto-merge at the dedup threshold. Therefore: hard fail."""
    if len(a) != len(b):
        raise ValueError(
            f"cosine: dimension mismatch ({len(a)} vs {len(b)}) — "
            "inhomogeneous embedders in the same brain? Vectors are not comparable.")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def knn(query: list[float], candidates: dict[str, list[float]], k: int = 3) -> list[tuple[str, float]]:
    """Returns the k nearest neighbors as (id, similarity), sorted descending.

    Audit #8 follow-up (fix wave 2): foreign-dimension candidates are
    skipped instead of crashing the whole query — the same two-level
    decision as in _find_duplicate: the primitive cosine() is strict,
    the call sites are tolerant. A brain with a few legacy vectors of the
    wrong dimension (e.g. after an embedder switch) degrades cleanly to the
    compatible neighbors.
    Audit #60: k<=0 returns [] instead of all items (k=0) or the last one
    being dropped (k=-1) — a limit means limit."""
    if k <= 0:
        return []
    query_dim = len(query)
    scored = [(nid, cosine(query, vec)) for nid, vec in candidates.items()
              if vec and len(vec) == query_dim]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:k]

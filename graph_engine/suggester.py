"""Edge suggestions: the k nearest neighbors become typed suggestions.

Rules (V2#3 — confidence bands instead of bare thresholds):
- sim >= 0.95            → "similar", AUTO-ACCEPT (pending=False), confidence=sim
- 0.75 <= sim < 0.95     → "similar", pending
- 0.45 <= sim < 0.75     → "extends", pending
- sim < 0.45             → no suggestion

Every suggestion carries a confidence (the cosine similarity). The caller
(BrainEngine) decides from the band + env override whether it stays pending.

"same_as" is never suggested automatically — it is created manually
(CLI `link`, cockpit) for translation/alias pairs.
"""

from __future__ import annotations

from dataclasses import dataclass

from .similarity import knn

THRESHOLD_SIMILAR = 0.75
THRESHOLD_EXTEND = 0.45
AUTO_ACCEPT_CONFIDENCE = 0.95


@dataclass
class Suggestion:
    source: str
    target: str
    kind: str
    confidence: float = 0.0


def suggest(source_id: str, query_vec: list[float],
            candidates: dict[str, list[float]], k: int = 3) -> list[Suggestion]:
    out: list[Suggestion] = []
    seen: set[str] = set()
    for nid, sim in knn(query_vec, candidates, k):
        if nid == source_id or nid in seen:
            continue
        if sim >= THRESHOLD_SIMILAR:
            kind = "similar"
        elif sim >= THRESHOLD_EXTEND:
            kind = "extends"
        else:
            continue
        seen.add(nid)
        out.append(Suggestion(source=source_id, target=nid, kind=kind, confidence=sim))
    return out


def is_auto_accept(confidence: float) -> bool:
    """Confidence band: >=0.95 is accepted without HITL."""
    return confidence >= AUTO_ACCEPT_CONFIDENCE


# Backwards-compatible for the JSONL engine (v0.0.1)
def suggest_edges(source_id: str, query_vec: list[float],
                  candidates: dict[str, list[float]], k: int = 3):
    from .model import Edge
    return [Edge(source=s.source, target=s.target, kind=s.kind, pending=True)
            for s in suggest(source_id, query_vec, candidates, k)]

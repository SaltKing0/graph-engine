"""Cross-encoder reranking (roadmap V2#1) — optional second retrieval pass.

Hybrid (dense+BM25, RRF) delivers the top-K candidates. A cross-encoder
scores each (query, candidate) pair JOINTLY — instead of cosine on separate
embeddings — and re-sorts the top-K down to the top-N. Per the roadmap this
is the single largest measured add-on (minus one third of residual failures).

No new mandatory dependency: the default is `None`/identity, so behavior is
unchanged. A real model is loaded only when requested (`IDEAGRAPH_RERANKER=st`
for a sentence-transformers CrossEncoder, or a model name/path as the value).
`ReverseReranker` is a deterministic test stub proving that the rerank pass
determines the final ranking.
"""

from __future__ import annotations

import os


class Reranker:
    """Protocol: re-sorts (query, candidates) down to the top-k."""

    def rerank(self, query: str, candidates, k: int):
        # candidates: list[(node_id, text, rrf_score)]
        # returns:    list[(node_id, text, rrf_score)] — top-k in rerank order
        raise NotImplementedError


class ReverseReranker(Reranker):
    """Deterministic test stub: reverses the candidate order.

    Purpose: prove that the rerank pass determines the final ranking
    (pipeline integration) — not that the model is qualitatively better.
    """

    def rerank(self, query: str, candidates, k: int):
        return list(reversed(candidates))[:k]


class CrossEncoderReranker(Reranker):
    """Real cross-encoder model (sentence-transformers), loaded on demand."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "IDEAGRAPH_RERANKER=st requires 'sentence-transformers' "
                "(pip install sentence-transformers)."
            ) from exc
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, candidates, k: int):
        pairs = [(query, text) for _, text, _ in candidates]
        scores = self.model.predict(pairs, show_progress_bar=False)
        scored = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
        return [cand for cand, _ in scored][:k]


def get_reranker():
    """Factory from IDEAGRAPH_RERANKER: 'none' (default) | 'st' | model name/path."""
    mode = os.environ.get("IDEAGRAPH_RERANKER", "none").strip().lower()
    if not mode or mode == "none":
        return None
    if mode == "st":
        return CrossEncoderReranker()
    return CrossEncoderReranker(model_name=mode)

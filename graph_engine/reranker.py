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

Candidate = tuple[str, str, float]


class Reranker:
    """Protocol: re-sorts (query, candidates) down to the top-k."""

    def rerank(self, query: str, candidates: list[Candidate], k: int) -> list[Candidate]:
        # candidates: list[(node_id, text, rrf_score)]
        # returns:    list[(node_id, text, rrf_score)] — top-k in rerank order
        raise NotImplementedError

    def rerank_with_scores(self, query: str, candidates: list[Candidate],
                           k: int) -> tuple[list[Candidate], dict[str, float]]:
        """Return ordered hits and any model predictions, separately from RRF.

        Ordering-only rerankers have no model scores to expose.
        """
        return self.rerank(query, candidates, k), {}


class ReverseReranker(Reranker):
    """Deterministic test stub: reverses the candidate order.

    Purpose: prove that the rerank pass determines the final ranking
    (pipeline integration) — not that the model is qualitatively better.
    """

    def rerank(self, query: str, candidates: list[Candidate], k: int) -> list[Candidate]:
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

    def rerank(self, query: str, candidates: list[Candidate], k: int) -> list[Candidate]:
        # Preserve the public search contract: scores in hits remain RRF.
        return self.rerank_with_scores(query, candidates, k)[0]

    def rerank_with_scores(self, query: str, candidates: list[Candidate],
                           k: int) -> tuple[list[Candidate], dict[str, float]]:
        if not candidates:
            return [], {}
        pairs = [(query, text) for _, text, _ in candidates]
        scores = self.model.predict(pairs, show_progress_bar=False)
        scored = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
        # Include predictions for candidates excluded by the final top-k too.
        return ([cand for cand, _ in scored][:k],
                {cand[0]: float(score) for cand, score in scored})


def get_reranker():
    """Factory from IDEAGRAPH_RERANKER: 'none' (default) | 'st' | model name/path."""
    mode = os.environ.get("IDEAGRAPH_RERANKER", "none").strip().lower()
    if not mode or mode == "none":
        return None
    if mode == "st":
        return CrossEncoderReranker()
    return CrossEncoderReranker(model_name=mode)

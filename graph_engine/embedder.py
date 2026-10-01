"""Embeddings: local via sentence-transformers (default: all-MiniLM-L6-v2).

HashEmbedder is the deterministic test embedder — no model download.
Audit #60: embedders expose embed_batch() so cold caches embed N nodes in
ONE model call instead of N sequential calls (sentence-transformers
encode() accepts lists natively).
"""

from __future__ import annotations

import hashlib


class Embedder:
    """Loads sentence-transformers lazily — only on the first real embedding."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._ensure_model()
        return model.encode(text).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        return model.encode(texts).tolist()


class HashEmbedder:
    """Deterministic test embedder: bag-of-words projection onto a fixed dim.

    No model, no network — same text → same vector,
    similar text (word overlap) → similar vector.
    """

    DIM = 64

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.DIM
        for word in text.lower().split():
            h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
            idx = h % self.DIM
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def get_embedder(name: str = "st", model: str | None = None) -> Embedder | HashEmbedder:
    """Audit #60: model override is honored (default: all-MiniLM-L6-v2).

    'st' degrades gracefully when sentence-transformers is not installed
    (the [st] extra is optional): falls back to HashEmbedder with a clear
    notice instead of crashing the CLI/server on a light install.
    """
    if name == "hash":
        return HashEmbedder()
    try:
        import sentence_transformers  # noqa: F401 — availability probe only
    except ImportError:
        # stderr, not stdout: a stdio MCP server's stdout IS the JSON-RPC
        # transport, and even for plain CLI users informational notices
        # must never corrupt piped output (e.g. `ig search --json`).
        import sys
        print(
            "NOTE: sentence-transformers is not installed — falling back to the "
            "deterministic HashEmbedder (64-dim, lower quality). Install the "
            "real embedder with: pip install 'graph-engine[st]'",
            file=sys.stderr,
        )
        return HashEmbedder()
    return Embedder(model or "all-MiniLM-L6-v2")

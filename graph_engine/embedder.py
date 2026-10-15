"""Embeddings: local via sentence-transformers (default: all-MiniLM-L6-v2).

HashEmbedder is the deterministic test embedder — no model download.
Audit #60: embedders expose embed_batch() so cold caches embed N nodes in
ONE model call instead of N sequential calls (sentence-transformers
encode() accepts lists natively).
"""

from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
import re
from pathlib import Path
from threading import RLock
from typing import Any


def local_model_digest(model_name: str) -> str | None:
    """Content identity for local weights, tokenizer and module configuration."""
    path = Path(model_name)
    if not path.is_dir():
        return None
    digest = hashlib.sha256()
    for file in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(str(file.relative_to(path)).encode())
        digest.update(b"\0")
        with file.open("rb") as stream:
            digest.update(hashlib.file_digest(stream, "sha256").digest())
    return digest.hexdigest()


class Embedder:
    """Loads sentence-transformers lazily — only on the first real embedding."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", *, revision: str | None = None):
        self.model_name = model_name
        self.revision = revision
        self._model = None
        self._model_lock = RLock()

    def _ensure_model(self) -> Any:
        with self._model_lock:
            return self._load_model()

    def matches_source(self, model_name: str, revision: str | None, digest: str | None) -> bool:
        """Check loaded provenance before reusing a lazily created adapter."""
        with self._model_lock:
            requested = (model_name, revision)
            return ((self.model_name, self.revision) == requested
                    and (self._model is None or
                         (self._loaded_source == requested and self._loaded_digest == digest)))

    def _load_model(self) -> Any:
        requested = (self.model_name, self.revision)
        if self._model is None or getattr(self, "_loaded_source", requested) != requested:
            from sentence_transformers import SentenceTransformer
            # Capture local source identity at load time, rather than blessing
            # already-loaded weights with files replaced after loading.
            digest = local_model_digest(self.model_name)
            options = {"revision": self.revision} if self.revision is not None else {}
            self._model = SentenceTransformer(self.model_name, trust_remote_code=False, **options)
            self._loaded_source = requested
            self._loaded_digest = digest
        return self._model

    def vector_cache_key(self) -> dict:
        """Identify loaded local files or the complete ST repository revision.

        A base transformer's commit need not identify ST pooling/tokenizers.
        Models without a resolved root revision fail closed to the instance.
        Model loading retains the trust_remote_code=False encode policy.
        """
        from .vector_cache import opaque_identity
        model = self._ensure_model()
        digest = getattr(self, "_loaded_digest", None)
        card = getattr(model, "model_card_data", None)
        repository = getattr(card, "base_model", None)
        revision = self.revision
        if revision is None and repository in {self.model_name, f"sentence-transformers/{self.model_name}"}:
            # ST records the revision inferred from its root modules.json
            # snapshot, which covers pooling and tokenizers as well as weights.
            revision = getattr(card, "base_model_revision", None)
        immutable = revision and re.fullmatch(r"[0-9a-fA-F]{40,64}", revision)
        resolved = digest or (revision if immutable else opaque_identity(model))
        try:
            library_version = version("sentence-transformers")
        except PackageNotFoundError:
            library_version = None
        return dict(model=self.model_name, revision=self.revision, resolved=resolved,
                    library_version=library_version,
                    prompts=getattr(model, "prompts", None),
                    default_prompt_name=getattr(model, "default_prompt_name", None),
                    max_seq_length=getattr(model, "max_seq_length", None),
                    truncate_dim=getattr(model, "truncate_dim", None), normalization=1)

    def embed(self, text: str) -> list[float]:
        with self._model_lock:
            model = self._ensure_model()
            return model.encode(text).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        with self._model_lock:
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


def get_embedder(name: str = "st", model: str | None = None, *,
                 revision: str | None = None) -> Embedder | HashEmbedder:
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
            "real embedder with: pip install 'graph-engine-memory[st]'",
            file=sys.stderr,
        )
        return HashEmbedder()
    return Embedder(model or "all-MiniLM-L6-v2", revision=revision)

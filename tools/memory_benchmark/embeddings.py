"""Offline hash default and explicitly selected, content-pinned local models."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any, Protocol

from graph_engine.embedder import HashEmbedder

from .dataset import sha256


class Embeddings(Protocol):
    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbeddings:
    def __init__(self, path: Path, seed: int) -> None:
        if not path.is_dir() or not (path / "modules.json").is_file():
            raise ValueError("embedding model must be an existing SentenceTransformer directory")
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ValueError("local semantic models require the optional [st] extra") from exc
        manifest = {}
        for file in sorted(path.rglob("*")):
            if file.is_file():
                with file.open("rb") as stream:
                    manifest[str(file.relative_to(path))] = hashlib.file_digest(stream, "sha256").hexdigest()
        torch.manual_seed(seed)
        self.model = SentenceTransformer(str(path.resolve()), device="cpu", local_files_only=True,
                                         trust_remote_code=False, prompts={"query": "", "document": ""},
                                         default_prompt_name=None)
        self.metadata = {"name": "SentenceTransformer", "path": str(path.resolve()),
                         "model_files_sha256": sha256(json.dumps(manifest, sort_keys=True).encode()),
                         "model_file_manifest": manifest, "device": "cpu",
                         "local_files_only": True, "trust_remote_code": False,
                         "semantic_model": True, "seed": seed,
                         "sentence_transformers_version": importlib.metadata.version("sentence-transformers"),
                         "torch_version": torch.__version__,
                         "dimension": self.model.get_embedding_dimension(),
                         "encode_prompt": ""}

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text, prompt="", normalize_embeddings=True,
                                 show_progress_bar=False).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, prompt="", normalize_embeddings=True,
                                 show_progress_bar=False).tolist()


def select_embeddings(path: Path | None, seed: int) -> tuple[Embeddings, dict[str, Any]]:
    if path is not None:
        embedder = LocalEmbeddings(path, seed)
        return embedder, embedder.metadata
    return HashEmbedder(), {"name": "HashEmbedder", "dimension": HashEmbedder.DIM,
                            "semantic_model": False, "projection": "sha256-bag-of-words-v1"}

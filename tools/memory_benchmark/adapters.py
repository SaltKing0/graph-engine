"""Source-only retrieval adapters. No references or evidence labels are accepted."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from graph_engine.brain import Brain, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.retrieval import BM25, retrieve, tokenize
from graph_engine.similarity import cosine

from .embeddings import Embeddings

ADAPTERS = ("graph-engine", "lexical", "vector")


class Adapter(Protocol):
    def ingest(self, documents: list[dict[str, str]]) -> None: ...
    def retrieve(self, query: str, k: int) -> list[tuple[str, float]]: ...


class GraphAdapter:
    def __init__(self, path: Path, embedder: Embeddings) -> None:
        self.brain = Brain(str(path), mode="local")
        self.engine = BrainEngine(self.brain, embedder=embedder, reranker=False)
        # Bypass the ambient reranker factory, then select no reranking.
        self.engine.reranker = None

    def ingest(self, documents: list[dict[str, str]]) -> None:
        for document in documents:
            self.brain.write_node(Node(document["text"], id=document["id"],
                                       created="2000-01-01T00:00:00Z", source="benchmark",
                                       status="active", storage_tier="recall"))
        self.brain.write_vectors(dict(zip(
            [doc["id"] for doc in documents],
            self.engine.embedder.embed_batch([doc["text"] for doc in documents]))))

    def retrieve(self, query: str, k: int) -> list[tuple[str, float]]:
        return retrieve(self.engine, query, k=k, rerank_k=max(30, k),
                        persist=False, track=False)


class BaselineAdapter:
    def __init__(self, kind: str, embedder: Embeddings) -> None:
        self.kind = kind
        self.embedder = embedder
        self.documents: list[dict[str, str]] = []
        self.vectors: list[list[float]] = []
        self.bm25 = BM25([])

    def ingest(self, documents: list[dict[str, str]]) -> None:
        self.documents = documents
        if self.kind == "lexical":
            self.bm25 = BM25([doc["text"] for doc in documents])
        else:
            self.vectors = self.embedder.embed_batch([doc["text"] for doc in documents])

    def retrieve(self, query: str, k: int) -> list[tuple[str, float]]:
        if self.kind == "lexical":
            scores = self.bm25.scores(tokenize(query))
        else:
            vector = self.embedder.embed(query)
            scores = [cosine(vector, other) for other in self.vectors]
        return sorted([(doc["id"], score) for doc, score in zip(self.documents, scores)
                       if score > 0], key=lambda hit: (-hit[1], hit[0]))[:k]


def create_adapter(kind: str, path: Path, embedder: Embeddings) -> Adapter:
    if kind == "graph-engine":
        return GraphAdapter(path, embedder)
    if kind not in ADAPTERS:
        raise ValueError(f"unknown adapter: {kind}")
    return BaselineAdapter(kind, embedder)

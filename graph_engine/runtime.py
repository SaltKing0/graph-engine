"""Shared brain/engine construction for the CLI, the FastAPI server and (future)
process-shaped surfaces such as the MCP server.

Before this module the CLI (`__main__.py`) and the server (`server.py`) each
rolled their own Brain/BrainEngine construction — same env contract, two
copies that could drift (the server adds a process-wide engine cache, the
CLI does not). One factory, one source of truth.

Env contract (identical for every consumer):
  IG_BRAIN_PATH          — brain location (default ~/graph-engine-brain, ~ expanded,
                           also for explicitly set values — Audit #33)
  IG_BRAIN_REMOTE        — clone URL for FIRST setup only (no personal default)
  IG_BRAIN_MODE          — "git" (real repo) or "local" (FS only, tests)
  IDEAGRAPH_EMBEDDER     — "st" (sentence-transformers) or "hash"
  IDEAGRAPH_EMBEDDER_MODEL — model override (Audit #60)
  IDEAGRAPH_EMBEDDER_REVISION — optional model revision (commit SHA recommended)
  IDEAGRAPH_RERANKER_REVISION — optional cross-encoder revision
"""

from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import Callable
from threading import RLock
from typing import TypeVar

from .brain import Brain
from . import access, namespaces
from .brain_engine import BrainEngine, model_revisions_from_env
from .embedder import Embedder, HashEmbedder, get_embedder, local_model_digest
from .reranker import Reranker, get_reranker

# Model adapters contain no brain, identity, corpus or query-result state.
# Keep them independent of the unprotected engine/corpus cache (issue #55).
# Eviction releases cache references; in-flight requests retain their resources.
_CACHE_LIMIT = 8
_CACHE_LOCK = RLock()
_ENGINES: OrderedDict[tuple, BrainEngine] = OrderedDict()
_EMBEDDERS: OrderedDict[tuple, Embedder | HashEmbedder] = OrderedDict()
_RERANKERS: OrderedDict[tuple, Reranker | None] = OrderedDict()
_T = TypeVar("_T")


def _cached(cache: OrderedDict[tuple, _T], key: tuple, factory: Callable[[], _T]) -> _T:
    """Caller holds _CACHE_LOCK, including construction and reset."""
    if key not in cache:
        cache[key] = factory()
    cache.move_to_end(key)
    while len(cache) > _CACHE_LIMIT:
        cache.popitem(last=False)
    return cache[key]


def brain_path() -> str:
    """Resolved brain path from the env (~ expanded, Audit #33)."""
    return _brain_path(namespaces.selected())


def _brain_path(graph_name: str) -> str:
    """Use the same selection snapshot for the path and its permissions."""
    if namespaces.home() is not None:
        return str(namespaces.graph_path(graph_name))
    return os.path.expanduser(
        os.environ.get("IG_BRAIN_PATH", os.path.expanduser("~/graph-engine-brain")))


def make_brain() -> Brain:
    """A Brain from the env contract. No personal defaults."""
    graph_name = namespaces.selected()
    cls = access.SecuredBrain if access.policy_path() else Brain
    kwargs = {"graph_name": graph_name, "identity": access.principal()} if access.policy_path() else {}
    return cls(
        **kwargs,
        path=_brain_path(graph_name),
        remote=(os.environ.get("IG_BRAIN_REMOTE", "") or None) if namespaces.home() is None else None,
        mode=os.environ.get("IG_BRAIN_MODE", "git"),
    )


def make_engine() -> BrainEngine:
    """Share models, but always build a fresh authorized brain and engine."""
    brain = make_brain()
    embedder_name = os.environ.get("IDEAGRAPH_EMBEDDER", "st")
    model = os.environ.get("IDEAGRAPH_EMBEDDER_MODEL") or "all-MiniLM-L6-v2"
    revision, rerank_revision = model_revisions_from_env()
    rerank_mode = os.environ.get("IDEAGRAPH_RERANKER", "none").strip()
    rerank_model = ("cross-encoder/ms-marco-MiniLM-L-6-v2" if rerank_mode.lower() == "st"
                    else rerank_mode)
    embed_key = (embedder_name, model, revision,
                 local_model_digest(model) if embedder_name != "hash" else None)
    rerank_key = (rerank_model, rerank_revision, local_model_digest(rerank_model)
                  if rerank_model and rerank_model.lower() != "none" else None)
    with _CACHE_LOCK:
        embedder = _cached(_EMBEDDERS, embed_key,
                           lambda: get_embedder(embedder_name, model, revision=revision))
        reranker = _cached(_RERANKERS, rerank_key,
                          lambda: get_reranker(rerank_mode, revision=rerank_revision))

        def build() -> BrainEngine:
            # False explicitly disables the constructor's env-based fallback.
            return BrainEngine(brain, embedder, reranker=reranker if reranker is not None else False)

        if isinstance(brain, access.SecuredBrain):
            # Never retain an authorized corpus snapshot or a request identity.
            return build()
        # A cached engine can outlive an independently evicted adapter. Include
        # adapter identities rather than mutating an engine used by other threads.
        key = (str(brain.path), brain.mode, embed_key, rerank_key, id(embedder), id(reranker))
        return _cached(_ENGINES, key, build)


def reset_engine_cache() -> None:
    """Drop retained engines and model resources; in-flight users stay valid."""
    with _CACHE_LOCK:
        _ENGINES.clear()
        _EMBEDDERS.clear()
        _RERANKERS.clear()

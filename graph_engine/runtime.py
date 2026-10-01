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
"""

from __future__ import annotations

import os

from .brain import Brain
from .brain_engine import BrainEngine
from .embedder import get_embedder

# Audit #16: building a fresh engine per request re-instantiates the
# sentence-transformers model per request (seconds of CPU, memory churn).
# A process-wide cache shares the model + vector cache; write consistency
# is provided by the Brain instance lock (all RMW mutations run under
# brain._lock / BRAIN_LOCK). The cache is keyed on (brain path, embedder):
# a changed env (tests, multi-brain setups) correctly gets a fresh engine
# instead of the foreign instance.
_ENGINES: dict[tuple[str, str], BrainEngine] = {}


def brain_path() -> str:
    """Resolved brain path from the env (~ expanded, Audit #33)."""
    return os.path.expanduser(
        os.environ.get("IG_BRAIN_PATH", os.path.expanduser("~/graph-engine-brain")))


def make_brain() -> Brain:
    """A Brain from the env contract. No personal defaults."""
    return Brain(
        path=brain_path(),
        remote=os.environ.get("IG_BRAIN_REMOTE", "") or None,
        mode=os.environ.get("IG_BRAIN_MODE", "git"),
    )


def make_engine() -> BrainEngine:
    """A BrainEngine from the env contract, process-wide cached."""
    embedder_name = os.environ.get("IDEAGRAPH_EMBEDDER", "st")
    key = (brain_path(), embedder_name)
    eng = _ENGINES.get(key)
    if eng is None:
        model = os.environ.get("IDEAGRAPH_EMBEDDER_MODEL")  # audit #60
        eng = BrainEngine(make_brain(), get_embedder(embedder_name, model))
        _ENGINES[key] = eng
    return eng


def reset_engine_cache() -> None:
    """Drop the process-wide engine cache (tests, env changes)."""
    _ENGINES.clear()

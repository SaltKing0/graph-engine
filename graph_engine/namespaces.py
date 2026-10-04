"""Separate brain directories with an atomic, persisted CLI selection."""
from __future__ import annotations

from contextvars import ContextVar
import os
from pathlib import Path
import re

from .brain import Brain, _atomic_write
from . import access


request_graph: ContextVar[str | None] = ContextVar("ig_graph", default=None)


def home() -> Path | None:
    value = os.environ.get("IG_GRAPH_HOME", "")
    return Path(value).expanduser().resolve() if value else None


def validate_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        raise ValueError("Graph name must contain 1-64 letters, digits, underscores or hyphens")
    return name


def selected() -> str:
    if request_graph.get() is not None:
        return request_graph.get()
    explicit = os.environ.get("IG_GRAPH", "")
    root = home()
    if explicit:
        if root is None:
            raise ValueError("IG_GRAPH requires IG_GRAPH_HOME")
        return validate_name(explicit)
    if root and (root / "selected").exists():
        return validate_name((root / "selected").read_text(encoding="utf-8").strip())
    return "default"


def graph_path(name: str) -> Path:
    root = home()
    if root is None:
        raise ValueError("Set IG_GRAPH_HOME to use named graphs")
    path = root / "graphs" / validate_name(name)
    if path.resolve() != path or (root / "graphs").is_symlink():
        raise ValueError("Graph directories must not be symlinks")
    return path


def list_graphs() -> list[str]:
    root = home()
    if root is None:
        raise ValueError("Set IG_GRAPH_HOME to use named graphs")
    names = sorted(p.name for p in (root / "graphs").glob("*") if p.is_dir() and not p.is_symlink())
    return [n for n in names if not access.policy_path() or access.permitted(n, access.principal(), "read")]


def switch_graph(name: str) -> None:
    path = graph_path(name)
    if access.policy_path():
        access.require(name, access.principal(), "read")
    if not path.is_dir():
        raise ValueError("Graph does not exist; use ig graph create first")
    _atomic_write(home() / "selected", name + "\n")


def create_graph(name: str) -> None:
    path = graph_path(name)
    if access.policy_path():
        # Provision roles in the trusted policy before creating a namespace.
        access.require(name, access.principal(), "admin")
    path.mkdir(parents=True, exist_ok=False)
    Brain(str(path), mode=os.environ.get("IG_BRAIN_MODE", "git")).init()

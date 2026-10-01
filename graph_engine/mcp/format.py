"""Pure response shaping for the MCP tools (report #1 §3.4).

Deliberately SDK-free: every function here is unit-testable without `mcp`
installed — the same split that keeps `evals.py` independent of the server.
All tool payloads flow through these helpers so caps and escaping live in
exactly one place.
"""
from __future__ import annotations

import os

# Caps (report #1 §3.9): measured 745 B for a compact k=5 search payload;
# every cap here exists so a single tool call can never blow a context.
DEFAULT_SNIPPET_CHARS = int(os.environ.get("IG_MCP_MAX_SNIPPET_CHARS", "200"))
DEFAULT_NEIGHBOR_LIMIT = int(os.environ.get("IG_MCP_MAX_NEIGHBORS", "20"))
MAX_NEIGHBOR_LIMIT = 50
DEFAULT_NODE_CHARS = 2000
MAX_NODE_CHARS = 8000

ERROR_HINTS = {
    "brain_missing": "Set IG_BRAIN_PATH to a brain directory (or run `ig init`).",
    "node_not_found": "Use search_brain to find node ids.",
}


def err(code: str, message: str, hint: str | None = None) -> dict:
    """The error envelope: {ok:false, error:{code,message,hint}}."""
    return {"ok": False,
            "error": {"code": code, "message": message,
                      "hint": hint or ERROR_HINTS.get(code)}}


ELLIPSIS = "\u2026"


def _escape(text: str) -> str:
    """Escape the characters that break markdown tables / HTML injection."""
    return (text.replace("|", "\\|")
                .replace("<", "\\<")
                .replace(">", "\\>")
                .replace("&", "\\&"))


def snippet(text: str, limit: int = DEFAULT_SNIPPET_CHARS) -> str:
    """Single-line snippet: newlines collapsed FIRST (a newline in a JSON
    string is legal but destroys table/terminal rendering), then
    TRUNCATE-then-ESCAPE (audit #55 order: a pipe at the cap cannot survive
    unescaped into markdown output)."""
    if not text:
        return ""
    one_line = " ".join(text.split())
    if len(one_line) > limit:
        one_line = one_line[:limit] + ELLIPSIS
    return _escape(one_line)


def node_not_found(node_id: str) -> dict:
    return err("node_not_found", f"No node with id {node_id!r}.")


def invalid(message: str) -> dict:
    return err("invalid_params", message)


def brain_missing(path: str) -> dict:
    return err("brain_missing", f"No brain found at {path!r}.")

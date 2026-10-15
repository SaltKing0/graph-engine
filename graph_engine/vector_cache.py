"""Versioned, disposable vectors tied to normalized input and model identity."""
from __future__ import annotations

import hashlib
import json
import uuid
import weakref
from typing import Any, Callable

SCHEMA_VERSION = 1


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


# Undeclared adapters are deliberately process/object-local. Never guess that
# two arbitrary functions or two same-class adapters produce the same vectors.
_PROCESS = uuid.uuid4().hex
_OPAQUE: dict[int, tuple[weakref.ReferenceType, str]] = {}


def opaque_identity(value: Any) -> str:
    key = id(value)
    entry = _OPAQUE.get(key)
    if entry is not None and entry[0]() is value:
        return entry[1]
    token = f"{_PROCESS}:{uuid.uuid4().hex}"
    try:
        reference = weakref.ref(value, lambda _: _OPAQUE.pop(key, None))
    except TypeError:
        return token  # Non-weakrefable unknown adapters cannot safely be reused.
    _OPAQUE[key] = (reference, token)
    return token


def model_identity(embedder: Any) -> tuple:
    """Stable declared identities survive restart; unknown adapters fail closed.

    Custom adapters must update revision/cache_key for every change in weights,
    tokenizer, preprocessing or encode options. Without a declaration we reuse
    only within that adapter's lifetime.
    """
    from .embedder import Embedder, HashEmbedder
    cls = type(embedder)
    implementation = f"{cls.__module__}.{cls.__qualname__}"
    if cls is HashEmbedder:
        return (implementation, 1, embedder.DIM)
    if cls is Embedder:
        return (implementation, embedder.vector_cache_key())
    declared = {name: getattr(embedder, name, None)
                for name in ("model_name", "revision", "cache_key", "DIM")}
    # A dimension alone does not identify a custom model.
    if not any(declared[name] is not None for name in ("model_name", "revision", "cache_key")):
        declared["adapter"] = opaque_identity(embedder)
    return (implementation, declared)


def model_key(embed_fn: Callable | None, explicit: tuple | None = None) -> str:
    identity = explicit if explicit is not None else model_identity(getattr(embed_fn, "__self__", embed_fn))
    # No repr(): object addresses are not persistent model identities. Custom
    # cache keys must be JSON-compatible; invalid keys must never bless a cache.
    return json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)


def record(nid: str, text: str, vector: list[float], key: str) -> dict:
    return dict(id=nid, vec=vector, version=SCHEMA_VERSION,
                text_hash=text_hash(text), model_key=key)


def compatible(entry: dict, text: str, key: str) -> bool:
    return (type(entry.get("version")) is int and entry["version"] == SCHEMA_VERSION
            and entry.get("text_hash") == text_hash(text)
            and entry.get("model_key") == key)


def refresh(records: dict[str, dict], nodes: dict, node_ids: set[str],
            embed_fn: Callable, batch_fn: Callable | None, key: str) -> dict[str, dict]:
    """Return only requested live IDs; legacy/incompatible entries are rebuilt."""
    result = {nid: records[nid] for nid in node_ids & nodes.keys() & records.keys()
              if compatible(records[nid], nodes[nid].text, key)}
    missing = sorted((node_ids & nodes.keys()) - result.keys())
    texts = [normalize_text(nodes[nid].text) for nid in missing]
    vectors = batch_fn(texts) if texts and batch_fn else [embed_fn(text) for text in texts]
    if len(vectors) != len(missing):
        raise ValueError("Embedding batch returned the wrong number of vectors")
    result.update((nid, record(nid, nodes[nid].text, vec, key))
                  for nid, vec in zip(missing, vectors))
    return result

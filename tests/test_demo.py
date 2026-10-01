"""Tests for the demo seed brain (`ig init --demo`)."""
from __future__ import annotations

import importlib.util
import os

import pytest

from graph_engine.brain import Brain
from graph_engine.brain_engine import BrainEngine
from graph_engine.demo import build_demo_brain
from graph_engine.embedder import HashEmbedder

# The real (semantic) embedder is the optional [st] extra; the default install
# (and the default CI job) has no sentence-transformers. Tests that need it
# skip instead of failing — the "test-st" CI job installs the extra and runs
# them for real.
_HAS_ST = importlib.util.find_spec("sentence_transformers") is not None
_NEEDS_ST = "requires the optional [st] extra (sentence-transformers)"


@pytest.fixture()
def demo_path(tmp_path):
    return str(tmp_path / "demo-brain")


def test_build_demo_brain_creates_graph(demo_path):
    stats = build_demo_brain(demo_path, commit=False)
    assert stats["nodes"] == 13
    assert stats["edges"] == 19
    assert stats["pending"] == 2
    brain = Brain(demo_path, mode="local")
    nodes = brain.read_nodes()
    assert len(nodes) == 13
    edges = brain.read_edges()
    assert len(edges) == 19
    kinds = {e.kind for e in edges}
    # every edge type is represented
    assert {"similar", "extends", "contradicts", "supersedes",
            "same_as"} <= kinds
    assert sum(1 for e in edges if e.pending) == 2


def test_demo_brain_refuses_overwrite(demo_path):
    build_demo_brain(demo_path, commit=False)
    with pytest.raises(FileExistsError):
        build_demo_brain(demo_path, commit=False)


def test_demo_brain_search_works(demo_path):
    """The precomputed vectors must make hybrid search immediately usable."""
    build_demo_brain(demo_path, commit=False)
    from graph_engine.retrieval import retrieve
    engine = BrainEngine(Brain(demo_path, mode="local"), HashEmbedder())
    hits = retrieve(engine, "RAG grounding")
    assert hits, "demo brain should return retrieval hits"
    by_id = {n.id: n.text for n in engine.brain.read_nodes()}
    top_texts = " ".join(by_id.get(h[0], "") for h in hits[:3]).lower()
    assert "retrieval-augmented generation" in top_texts or "rag" in top_texts


def test_demo_brain_hygiene_reports(demo_path):
    """The island demo must actually show up in the connectivity report."""
    from graph_engine.hygiene import connectivity
    build_demo_brain(demo_path, commit=False)
    brain = Brain(demo_path, mode="local")
    conn = connectivity(brain)
    assert len(conn.islands) >= 1, "the consolidation node must be an island"


@pytest.mark.skipif(not _HAS_ST, reason=_NEEDS_ST)
def test_demo_near_dup_pair_is_flagged(demo_path):
    """The near-dup demo pair must show up in the report.

    Measured on the real ST embedder (cos 0.847) — the HashEmbedder of a light
    install puts the pair outside the 0.78-0.92 band, so this skips without
    the [st] extra instead of asserting a property the demo doesn't have there.
    """
    from graph_engine.hygiene import near_dup_pairs
    build_demo_brain(demo_path, commit=False)
    brain = Brain(demo_path, mode="local")
    pairs = near_dup_pairs(brain, lo=0.78, hi=0.92)
    assert len(pairs) >= 1, "the graph-RAG/multi-hop pair must be flagged as near-dup"

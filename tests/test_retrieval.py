"""Unit tests for hybrid retrieval (BM25 + RRF fusion, V2#1)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.retrieval import tokenize, BM25, rrf_fuse


def test_bm25_ranks_shared_terms_higher():
    corpus = [
        "katze hund tier futter",
        "quantenmechanik wellenfunktion schroedinger",
    ]
    bm = BM25(corpus)
    scores = bm.scores(tokenize("katze futter"))
    assert scores[0] > scores[1]


def test_bm25_handles_empty_corpus():
    bm = BM25([])
    assert bm.scores(tokenize("irgendwas")) == []


def test_bm25_term_frequency_boost():
    corpus = ["alpha alpha beta", "gamma delta"]
    bm = BM25(corpus)
    scores = bm.scores(tokenize("alpha"))
    assert scores[0] > scores[1]


def test_rrf_fuses_two_rankings():
    fused = rrf_fuse([
        [("a", 0.9), ("b", 0.1)],
        [("b", 0.9), ("a", 0.1)],
    ])
    ids = [x[0] for x in fused]
    assert "a" in ids and "b" in ids


def test_rrf_empty():
    assert rrf_fuse([[], []]) == []

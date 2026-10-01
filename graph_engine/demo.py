"""graph_engine.demo — a small, generic seed brain for onboarding (`ig init --demo`).

13 nodes over generic LLM/agent topics (no user-specific content), linked with
every edge type (similar, extends, contradicts, supersedes, same_as),
2 pending edges for the HITL review flow, an orphan island to demo `ig status`,
and 1 near-dup pair (0.78-0.92 band) to demo `ig near-dup` + `ig merge`.

Everything is deterministic and public-safe: no private data, no personal
defaults, neutral English texts that avoid the intent-marker vocabulary
(the demo mirrors the marker-free finding style used by the self-evolving
pipeline). Edge KIND values are canonical English (`similar`, `extends`,
`contradicts`, `supersedes`, `continues`, `same_as`) — matching the
engine emission since the v0.5 kind migration.
"""
from __future__ import annotations

import datetime as _dt

from .brain import Brain, Edge, Node

# (text, ntype, tags) — texts reuse each other's vocabulary so the edges are
# semantically honest, not arbitrary. Near-dup pair measured at cos 0.847.
_NODES: list[tuple[str, str, list[str]]] = [
    # 0: RAG hub
    ("Retrieval-Augmented Generation connects a language model to an external"
     " knowledge source: for a query, the retriever fetches relevant passages"
     " from a corpus, and the language model composes the answer grounded on"
     " those passages. RAG complements parametric knowledge with addressable,"
     " updatable knowledge and reduces hallucinations on knowledge-intensive"
     " tasks.", "semantic", ["rag"]),
    # 1: dense retrieval
    ("Dense Retrieval computes dense vectors (embeddings) for queries and"
     " documents and retrieves by cosine similarity. Bi-encoders encode query"
     " and document independently, which allows approximate-nearest-neighbor"
     " indexes over large corpora. Dense Retrieval is the fetch layer that"
     " RAG relies on.", "semantic", ["retrieval"]),
    # 2: BM25
    ("BM25 is a lexical ranking function over inverted indexes: term"
     " frequency, inverse document frequency, and length normalization weight"
     " the matching terms. BM25 complements Dense Retrieval for exact term"
     " matches such as names, identifiers, and code symbols, which vector"
     " similarity can miss.", "semantic", ["retrieval", "bm25"]),
    # 3: hybrid search (near-dup pair with 2)
    ("Hybrid Search combines lexical ranking with Dense Retrieval via"
     " Reciprocal Rank Fusion: each ranker produces a ranked list, and the"
     " fusion merges them without a calibration step. Hybrid Search adds"
     " exact term matching on top of vector similarity and serves as a fetch"
     " layer for RAG.", "semantic", ["retrieval", "hybrid"]),
    # 4: agent memory
    ("Agent Memory stores an agent's experience across sessions in a"
     " persistent store: episodic entries, semantic entries, and procedural"
     " entries. Agent Memory relates to RAG, which reuses the same retrieval"
     " infrastructure for recall.", "semantic", ["memory"]),
    # 5: episodic memory
    ("Episodic Memory records events with timestamp and context: sessions,"
     " decisions, observations. It adds the temporal dimension to semantic"
     " memory and enables consolidation: recurring episodes generalize into"
     " semantic knowledge.", "episodic", ["memory", "episodic"]),
    # 6: semantic memory
    ("Semantic Memory holds generalized knowledge: concepts, facts, rules."
     " It forms through consolidation of episodic entries and serves as the"
     " long-term knowledge base of an agent.",
     "semantic", ["memory", "semantic"]),
    # 7: graph-RAG
    ("Graph-RAG extends RAG with a knowledge graph: entities and relations"
     " are extracted from the corpus, and the retriever traverses the graph"
     " for multi-hop questions. Graph-RAG shows the limit of purely local"
     " retrieval on questions that span several documents.",
     "semantic", ["rag", "graph"]),
    # 8: consolidation (ISLAND — 0 edges, demos `ig status`)
    ("Knowledge graph consolidation merges semantically identical entities"
     " and keeps the graph compact: near-duplicate detection via embedding"
     " similarity, redirection of edges onto the survivor, with full"
     " provenance preserved in the git history.", "semantic", ["hygiene"]),
    # 9: hallucination
    ("Hallucination denotes fluent-sounding, factually unsupported output of"
     " language models. Grounding on retrieved passages reduces"
     " hallucinations, and citing sources makes answers verifiable."
     " Hallucination is the main motivation for RAG.",
     "semantic", ["safety"]),
    # 10: enterprise RAG
    ("Enterprise RAG indexes internal documents such as wikis, manuals, and"
     " tickets, and answers employee questions grounded on those documents"
     " with citations. Enterprise RAG is the most common production use of"
     " RAG.", "semantic", ["rag", "enterprise"]),
    # 11: multi-hop (near-dup pair with 7 — measured cos 0.847 on the demo texts)
    ("Multi-hop questions over a knowledge graph are answered by Graph-RAG"
     " through traversal of extracted entities and relations: find entity A,"
     " then follow the relation from A to B, then on to C. The Graph-RAG"
     " approach traverses the graph for this; pure Dense Retrieval falls"
     " short because a single passage rarely holds the full answer.",
     "semantic", ["rag", "multi-hop"]),
    # 12: same_as demo pair (EN twin of node 0) — demos `ig link` + same_as
    ("Retrieval-Augmented Generation (RAG) verbindet ein Sprachmodell mit"
     " einer externen Wissensquelle: der Retriever holt fuer eine Anfrage"
     " relevante Passagen aus einem Korpus, und das Sprachmodell erzeugt die"
     " Antwort grounding auf diesen Passagen.", "semantic", ["rag", "de"]),
]

# (source_idx, target_idx, kind, pending, confidence)
_EDGES: list[tuple[int, int, str, bool, float | None]] = [
    (1, 0, "extends", False, None),
    (2, 0, "extends", False, None),
    (2, 1, "extends", False, None),   # BM25 complements dense retrieval
    (3, 1, "extends", False, None),   # hybrid search builds on dense retrieval
    (3, 0, "extends", False, None),
    (4, 0, "extends", False, None),
    (9, 0, "extends", False, None),
    (10, 0, "extends", False, None),
    (11, 7, "extends", False, None),
    (4, 5, "extends", False, None),
    (4, 6, "extends", False, None),
    (5, 6, "similar", False, None),
    (7, 0, "supersedes", False, None),        # intent demo: graph-RAG supersedes plain RAG
    (9, 10, "contradicts", False, None),  # intent demo (explicitly labeled demo pair)
    (3, 2, "similar", False, 0.85),         # near-dup demo pair (hybrid ≈ BM25)
    (0, 12, "same_as", False, None),           # EN/DE alias demo
    (9, 12, "extends", False, None),   # hallucination motivates the DE twin too
    # 2 pending edges → the HITL review flow has something to review
    (10, 4, "extends", True, 0.62),
    (11, 3, "extends", True, 0.58),
]


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_demo_brain(path: str, commit: bool = True) -> dict:
    """Create a fresh brain at `path` and fill it with the demo graph.

    Returns a small stats dict for the CLI to print. Aborts if the path
    already contains a brain (never overwrites user data).
    """
    import os
    if os.path.exists(path) and os.listdir(path):
        raise FileExistsError(f"{path} already exists and is not empty.")
    brain = Brain(path, mode="git")
    brain.init(commit=False)  # structure + git init, no commit yet

    nodes = [Node(text=t, source="demo-seed", tags=tags, ntype=nt, status="active")
             for t, nt, tags in _NODES]
    for n in nodes:
        brain.write_node(n)

    for s, t, kind, pending, conf in _EDGES:
        brain.add_edge(Edge(source=nodes[s].id, target=nodes[t].id,
                            kind=kind, pending=pending, confidence=conf,
                            origin="manual" if conf is None else "suggester"))

    # Embedding cache for the demo nodes (so `ig search` works immediately).
    # Route through get_embedder() so a light install (no [st] extra) degrades
    # to the HashEmbedder instead of crashing the demo seed.
    from .embedder import get_embedder
    emb = get_embedder()
    vectors = emb.embed_batch([n.text for n in nodes])
    vectors = {n.id: v for n, v in zip(nodes, vectors)}
    brain.write_vectors(vectors)

    brain.rebuild_index()
    if commit:
        brain.commit_and_push("demo-seed: 13 nodes, 19 edges (example graph)",
                              push=False)
    return {"nodes": len(nodes), "edges": len(_EDGES),
            "pending": sum(1 for e in _EDGES if e[3]), "path": str(brain.path)}

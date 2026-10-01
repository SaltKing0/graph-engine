"""Tests für die Coverage-/Gap-Analyse (`ig gaps`).

Definieren das erwartete Verhalten von analyze_coverage/find_gaps/render,
bevor weitere Engine-Arbeit darauf aufbaut (measure-first).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.brain import Brain, Node
from graph_engine.gaps import (
    DEFAULT_TAXONOMY,
    analyze_coverage,
    find_gaps,
    load_taxonomy,
    normalize,
    render,
)


def _brain(tmp_path) -> Brain:
    return Brain(str(tmp_path / "brain"), mode="local")


def test_normalize_umlauts():
    assert normalize("Ökonomie Übertragung Straße") == "oekonomie uebertragung strasse"


def test_coverage_counts(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Attention und Transformer bilden die Architektur"))
    b.write_node(Node(id="b", text="Multi-Agent-Systeme koordinieren Agenten"))
    b.write_node(Node(id="c", text="Retrieval und RAG nutzen Embeddings"))
    cov = analyze_coverage(b)
    assert cov.total == 3
    by_name = {a.name: a.count for a in cov.areas}
    # 'a' trifft LLM-Architektur (attention/transformer/architektur)
    assert by_name["LLM-Architektur & Interna"] >= 1
    # 'b' trifft Multi-Agent-Systeme
    assert by_name["Multi-Agent-Systeme"] >= 1
    # 'c' trifft Retrieval & RAG
    assert by_name["Retrieval & RAG"] >= 1


def test_unclassified(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="xyzzy unbekanntes fachfremdes wort ohne bezug"))
    cov = analyze_coverage(b)
    assert cov.unclassified == 1


def test_find_gaps_flags_thin_area(tmp_path):
    b = _brain(tmp_path)
    # zwei Nodes in Multi-Agent, viele in Retrieval
    b.write_node(Node(id="a", text="Multi-Agent-Systeme koordinieren Agenten"))
    b.write_node(Node(id="b", text="Multi-Agent-Konsens und Verhandlung"))
    for i in range(8):
        b.write_node(Node(id=f"r{i}", text=f"Retrieval RAG Embedding Chunk Index {i}"))
    cov = analyze_coverage(b)
    gaps = find_gaps(cov, threshold=5)
    names = {a.name for a in gaps}
    # Multi-Agent (2) ist ein Gap; Retrieval (8) nicht
    assert "Multi-Agent-Systeme" in names
    assert "Retrieval & RAG" not in names
    # sorted by coverage ascending (thinnest first)
    counts = [a.count for a in gaps]
    assert counts == sorted(counts)


def test_render_marks_gap(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Multi-Agent-Systeme koordinieren Agenten"))
    b.write_node(Node(id="b", text="Retrieval RAG Embedding Chunk"))
    out = render(analyze_coverage(b), threshold=3)
    assert "GAP" in out and "Multi-Agent-Systeme" in out


def test_load_taxonomy(tmp_path):
    p = tmp_path / "tax.json"
    p.write_text(json.dumps({"Mein Bereich": ["signal", "rauschen"]}), encoding="utf-8")
    tax = load_taxonomy(str(p))
    assert tax == {"Mein Bereich": ["signal", "rauschen"]}


def test_custom_taxonomy_used(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Signalverarbeitung mit Rauschen"))
    b.write_node(Node(id="b", text="ganz anderes thema"))
    tax = {"Mein Bereich": ["signal", "rauschen"]}
    cov = analyze_coverage(b, tax)
    by_name = {a.name: a.count for a in cov.areas}
    assert by_name["Mein Bereich"] == 1
    assert cov.unclassified == 1


def test_default_taxonomy_nonempty():
    assert isinstance(DEFAULT_TAXONOMY, dict) and len(DEFAULT_TAXONOMY) >= 10

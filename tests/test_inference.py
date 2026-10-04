"""Relationship answers must carry reproducible, live graph evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from graph_engine.brain import Brain, Edge, Node
from graph_engine.inference import explain_node, infer


@pytest.fixture
def brain(tmp_path):
    brain = Brain(tmp_path / "brain", mode="local")
    brain.ensure_ready()
    for nid, name in [("a", "Alice"), ("b", "Team"), ("c", "Acme"), ("d", "World")]:
        brain.write_node(Node(id=nid, text=name, ntype="entity", entity_name=name,
                              aliases=["ACME Corp"] if nid == "c" else []))
    return brain


def fact(source, target, predicate, eid, **kwargs):
    return Edge(source=source, target=target, kind="fact", predicate=predicate,
                id=eid, pending=False, **kwargs)


def snapshot(brain):
    return {str(p.relative_to(brain.path)): p.read_bytes()
            for p in brain.path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("query", ["a -> c", "How does Alice relate to Acme?",
                                   "what is the relationship between Alice and Acme?",
                                   "How is Alice related to ACME Corp?",
                                   '"Alice" -> "Acme"'])
def test_transitive_fact_and_actual_evidence(brain, query):
    edges = [fact("a", "b", "part_of", "ab"), fact("b", "c", "part_of", "bc")]
    edges[0].evidence = [{"node_id": "d", "quote": "Alice is part of Team"}]
    brain.write_edges(edges)
    before = snapshot(brain)
    result = infer(brain, query)
    assert result["source"] == "a" and result["target"] == "c"
    assert result["relations"] == [{"source": "a", "target": "c", "relation": "part_of",
                                    "inferred": True, "rule": "transitive_part_of",
                                    "edge_ids": ["ab", "bc"]}]
    assert result["paths"][0]["node_ids"] == ["a", "b", "c"]
    assert result["edges"] == [e.to_dict() for e in edges]
    assert result["contradictions"] == []
    assert "(transitive)" in result["answer"]
    assert snapshot(brain) == before
    json.dumps(result)


def test_transitive_direction_is_preserved(brain):
    brain.write_edges([fact("a", "b", "is_a", "ab"), fact("b", "c", "is_a", "bc")])
    result = infer(brain, "c -> a")
    relation = result["relations"][0]
    assert (relation["source"], relation["target"]) == ("a", "c")
    assert [s["direction"] for s in result["paths"][0]["steps"]] == ["in", "in"]


@pytest.mark.parametrize("kind,predicate", [("similar", None), ("extends", None),
                                            ("contradicts", None), ("fact", "works_at"),
                                            ("fact", "not_part_of"), ("part_of", None)])
def test_arbitrary_connections_never_become_transitive_claims(brain, kind, predicate):
    brain.write_edges([Edge(source=a, target=b, kind=kind, predicate=predicate, pending=False)
                       for a, b in [("a", "b"), ("b", "c")]])
    result = infer(brain, "a -> c")
    assert result["relations"] == []
    assert result["paths"][0]["hops"] == 2
    assert "does not establish" in result["answer"]


def test_mixed_predicates_and_wrong_direction_do_not_compose(brain):
    for edges in [
        [fact("a", "b", "part_of", "ab"), fact("b", "c", "is_a", "bc")],
        [fact("a", "b", "part_of", "ab"), fact("c", "b", "part_of", "bc")],
    ]:
        brain.write_edges(edges)
        assert infer(brain, "a -> c")["relations"] == []


def test_same_as_is_symmetric_and_transitive_with_cycles(brain):
    brain.write_edges([Edge(source=a, target=b, kind="same_as", pending=False, id=eid)
                       for a, b, eid in [("b", "a", "ab"), ("b", "c", "bc"), ("c", "b", "cb")]])
    result = infer(brain, "a -> c")
    assert result["relations"][0]["relation"] == "same_as"
    assert result["relations"][0]["edge_ids"] == ["ab", "bc"]
    assert len(explain_node(brain, "a")["paths"]) == 2


def test_direct_relations_keep_direction_and_origin(brain):
    edge = fact("c", "a", "works_at", "ca", origin="manual")
    brain.write_edges([edge])
    result = infer(brain, "a -> c")
    assert result["relations"][0]["source"] == "c"
    assert result["relations"][0]["inferred"] is False
    assert result["edges"] == [edge.to_dict()]


def test_conflicts_include_transitive_support_but_no_invented_negation(brain):
    brain.write_edges([fact("a", "b", "part_of", "ab"), fact("b", "c", "part_of", "bc"),
                       fact("a", "c", "not_part_of", "acn"),
                       Edge(id="contra", source="a", target="b", kind="contradicts", pending=False)])
    result = infer(brain, "a -> c")
    assert result["contradictions"] == [
        {"kind": "recorded", "source": "a", "target": "b", "edge_ids": ["contra"]},
        {"kind": "opposing_facts", "source": "a", "target": "c", "relation": "part_of",
         "edge_ids": ["ab", "acn", "bc"]},
    ]
    assert "2 recorded contradiction(s)" in result["answer"]
    assert all(r["relation"] != "not_part_of" or not r["inferred"] for r in result["relations"])


@pytest.mark.parametrize("mutations", [
    {"pending": True}, {"rejected": True}, {"valid_to": "2001-01-01T00:00:00Z"},
    {"invalidated_at": "2001-01-01T00:00:00Z"}, {"valid_from": "2999-01-01T00:00:00Z"},
    {"target": "missing"},
])
def test_unusable_edges_never_contribute(brain, mutations):
    edge = fact("a", "b", "part_of", "ab")
    for key, value in mutations.items():
        setattr(edge, key, value)
    brain.write_edges([edge, fact("b", "c", "part_of", "bc")])
    assert infer(brain, "a -> c")["paths"] == []
    assert explain_node(brain, "a")["graph_context"] == []


def test_tombstones_and_dangling_intermediate_nodes_cannot_bridge(brain):
    edges = [fact("a", "b", "part_of", "ab"), fact("b", "c", "part_of", "bc")]
    brain.write_edges(edges)
    brain.write_node(Node("Team", id="b", status="tombstone"))
    assert infer(brain, "a -> c")["paths"] == []
    with pytest.raises(ValueError, match="No live node"):
        infer(brain, "a -> b")
    with pytest.raises(ValueError, match="No live node"):
        explain_node(brain, "b")


def test_deterministic_paths_depth_limit_and_explanation_cap(brain):
    edges = [fact("a", "b", "part_of", "ab"), fact("b", "c", "part_of", "bc"),
             fact("c", "d", "part_of", "cd")]
    brain.write_edges(edges)
    before = snapshot(brain)
    result = explain_node(brain, "a", max_depth=3, limit=1)
    assert result["truncated"] and len(result["paths"]) == 1
    assert result["paths"][0]["node_ids"] == ["a", "b"]
    assert not result["graph_used_for_ranking"]
    assert "context only" in result["explanation"]
    assert snapshot(brain) == before
    assert infer(brain, "a -> d", max_depth=2)["paths"] == []
    full = infer(brain, "a -> d")
    brain.write_edges(list(reversed(edges)))
    assert full == infer(brain, "a -> d")


def test_identity_and_ambiguous_resolution(brain):
    assert infer(brain, "Acme -> ACME Corp")["paths"][0]["hops"] == 0
    brain.write_node(Node(id="duplicate", text="Other", ntype="entity", entity_name="Alice"))
    with pytest.raises(ValueError, match="Ambiguous.*a, duplicate"):
        infer(brain, "Alice -> Acme")
    assert infer(brain, "a -> c")["source"] == "a"


@pytest.mark.parametrize("query", ["", "hello", "a ->", "a -> b -> c", "a -> missing"])
def test_invalid_queries_fail_cleanly(brain, query):
    with pytest.raises(ValueError):
        infer(brain, query)


@pytest.mark.parametrize("depth", [-1, 0, 21])
def test_invalid_bounds(brain, depth):
    with pytest.raises(ValueError):
        infer(brain, "a -> c", max_depth=depth)
    with pytest.raises(ValueError):
        explain_node(brain, "a", max_depth=depth)
    with pytest.raises(ValueError):
        explain_node(brain, "a", limit=0)


def run_cli(brain, args):
    env = {**os.environ, "IG_BRAIN_PATH": str(brain.path), "IG_BRAIN_MODE": "local",
           "IG_BRAIN_REMOTE": "", "IDEAGRAPH_EMBEDDER": "hash"}
    return subprocess.run([sys.executable, "-m", "graph_engine", *args], env=env,
                          text=True, capture_output=True, cwd=Path(__file__).parents[1])


def test_cli_infer_and_no_query_explain_roundtrip(brain):
    brain.write_edges([fact("a", "b", "part_of", "ab"), fact("b", "c", "part_of", "bc")])
    before = snapshot(brain)
    for args in [["infer", "a -> c", "--json"], ["explain", "a", "--json"]]:
        result = run_cli(brain, args)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["paths"][0]["node_ids"][0] == "a"
    result = run_cli(brain, ["infer", "How does Alice relate to Acme?"])
    assert result.returncode == 0 and "--part_of[ab]-->" in result.stdout
    result = run_cli(brain, ["explain", "a"])
    assert result.returncode == 0 and "context only" in result.stdout
    assert snapshot(brain) == before


@pytest.mark.parametrize("args", [["infer"], ["infer", "blah"], ["infer", "a -> c", "--max-depth", "0"],
                                  ["infer", "a -> c", "--max-depth", "bad"],
                                  ["explain", "a", "--limit", "0"]])
def test_cli_errors_are_clean(brain, args):
    result = run_cli(brain, args)
    assert result.returncode != 0 and "Traceback" not in result.stderr

"""Entity extraction, typed identity, evidence and existing graph workflows."""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from graph_engine.brain import Brain, Edge, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder
from graph_engine.entities import command_extractor, extract_entities, rule_extract, validate_extraction


@pytest.fixture
def brain(tmp_path):
    return Brain(tmp_path / "brain", mode="local")


def snapshot(brain):
    return {str(p.relative_to(brain.path)): p.read_bytes()
            for p in brain.path.rglob("*") if p.is_file()}


def extraction(text="Alice works at Acme", **fields):
    fact = dict(subject="Alice", predicate="works_at", object="Acme", evidence=text)
    fact.update(fields)
    return dict(entities=[dict(name="Alice", type="person"), dict(name="Acme", type="org")],
                facts=[fact])


def provider(data):
    return lambda text, known: data


def test_rule_entities_facts_and_unambiguous_coreference():
    result = rule_extract("Alice works at Acme. She uses Python. Acme is based in Berlin.")
    assert [(e["name"], e["type"]) for e in result["entities"]] == [
        ("Alice", "person"), ("Acme", "org"), ("Python", "concept"), ("Berlin", "location")]
    assert [(f["subject"], f["predicate"], f["object"]) for f in result["facts"]] == [
        ("Alice", "works_at", "Acme"), ("Alice", "uses", "Python"), ("Acme", "based_in", "Berlin")]


def test_rule_german_and_alias_declarations():
    result = rule_extract("Alice arbeitet bei International Business Machines (IBM). "
                          "Sie nutzt Python. Berlin ist ein Ort.")
    assert result["entities"][1] == dict(name="International Business Machines", type="org", aliases=["IBM"])
    assert result["entities"][-1]["type"] == "location"
    assert result["facts"][1]["subject"] == "Alice"


@pytest.mark.parametrize("text", [
    "Alice does not work at Acme.", "Alice never works at Acme.",
    "Alice might works at Acme.", "If Alice works at Acme.",
    "Bob says Alice works at Acme.", "Alice works at Acme?",
    "Does Alice works at Acme?", "Maybe Alice works at Acme.",
    "Alice works at Acme and Bob works at Other.", "Alice works at Acme in Berlin.",
    "Alice works at Acme (Not An Alias).", "She works at Acme.",
])
def test_rules_do_not_turn_unsupported_clauses_into_claims(text):
    assert rule_extract(text) == {"entities": [], "facts": []}


def test_ambiguous_pronouns_are_skipped():
    result = rule_extract("Alice works at Acme. Bob works at Acme. She uses Python.")
    assert len(result["facts"]) == 2
    assert "Python" not in {e["name"] for e in result["entities"]}


def test_rule_type_conflict_does_not_leave_partial_entities():
    result = rule_extract("Alice is a person. Alice is based in Berlin.")
    assert result == dict(entities=[dict(name="Alice", type="person", aliases=[])], facts=[])


def test_serialization_preserves_entity_metadata_and_legacy_shapes(brain):
    node = Node(text='A, "B": Ö', ntype="entity", entity_name='A, "B": Ö',
                entity_type="org", aliases=['Ö, Co.', '"ABC"', "A:B"], recall_count=3)
    brain.write_node(node)
    assert brain.read_node(node.id).to_dict() == node.to_dict()
    legacy = Node("old")
    assert "entity_name" not in legacy.to_dict()
    assert "aliases:" not in legacy.to_markdown()
    edge = Edge(node.id, "other", "fact", predicate="works_at", evidence=[dict(node_id="note", text="a quote")])
    brain.write_edges([edge])
    assert brain.read_edges()[0].to_dict() == edge.to_dict()
    assert "predicate" not in Edge("a", "b", "similar").to_dict()


def test_persistence_review_and_live_graph(brain):
    from graph_engine.graph import live_edges
    engine = BrainEngine(brain, HashEmbedder())
    result = engine.entities("Alice works at Acme. She uses Python.")
    assert result["created_entities"] == 3 and result["created_facts"] == 2
    nodes = {n.id: n for n in brain.read_nodes()}
    source = nodes[result["source_node_id"]]
    assert source.ntype == "semantic" and source.text == "Alice works at Acme. She uses Python."
    assert len(live_edges(brain)) == 3  # accepted mentions, pending facts
    for f in result["facts"]:
        assert f["evidence"][0]["node_id"] == source.id
        assert f["evidence"][0]["text"] in source.text
        engine.resolve(f["id"], accept=True)
    assert len(live_edges(brain)) == 5
    assert {e.predicate for e in brain.read_edges() if e.kind == "fact"} == {"works_at", "uses"}


def test_exact_repeat_is_byte_identical_no_commit(brain, monkeypatch):
    text = "Alice works at Acme. She uses Python."
    extract_entities(brain, text)
    before = snapshot(brain)
    monkeypatch.setattr(brain, "commit_and_push", lambda *a: pytest.fail("repeat must not commit"))
    result = extract_entities(brain, text)
    assert not result["changed"]
    assert snapshot(brain) == before


def test_cross_text_alias_linking_and_fact_evidence_aggregation(brain):
    first = extract_entities(brain, "Alice works at International Business Machines (IBM).")
    second = extract_entities(brain, "alice works at IBM.")
    assert second["created_entities"] == 0 and second["created_facts"] == 0
    assert {n["id"] for n in first["entities"]} == {n["id"] for n in second["entities"]}
    assert first["facts"][0]["id"] == second["facts"][0]["id"]
    fact = next(e for e in brain.read_edges() if e.kind == "fact")
    assert len(fact.evidence) == 2
    assert {e["node_id"] for e in fact.evidence} == {first["source_node_id"], second["source_node_id"]}
    assert fact.pending


def test_same_name_different_types_are_distinct(brain):
    first = extract_entities(brain, "Jordan is a person.")
    second = extract_entities(brain, "Jordan is a location.")
    assert first["entities"][0]["id"] != second["entities"][0]["id"]


def test_existing_episodic_source_is_not_modified(brain):
    source = Node("Alice works at Acme.", ntype="episodic", observed_at="2020-01-01T00:00:00Z", context="meeting")
    brain.write_node(source)
    before = brain.node_path(source.id).read_bytes()
    result = extract_entities(brain, node_id=source.id)
    assert result["source_node_id"] == source.id
    assert brain.node_path(source.id).read_bytes() == before
    assert len(brain.read_nodes()) == 3


def test_dry_run_does_not_create_brain_or_write_cache(brain, monkeypatch):
    monkeypatch.setattr(brain, "ensure_ready", lambda: pytest.fail("no init"))
    monkeypatch.setattr(brain, "pull", lambda: pytest.fail("no pull"))
    result = extract_entities(brain, "Alice works at Acme.", dry_run=True)
    assert result["created_facts"] == 1 and result["dry_run"]
    assert not brain.path.exists()


def test_empty_extraction_creates_no_evidence_node(brain):
    assert not extract_entities(brain, "a note about an unsupported topic")["changed"]
    assert snapshot(brain) == {}


@pytest.mark.parametrize("node", [None, Node("secret", id="missing", status="tombstone"),
                                  Node("entity", id="missing", ntype="entity")])
def test_invalid_source_is_rejected_before_extractor(brain, node):
    if node:
        brain.write_node(node)
    before = snapshot(brain)
    with pytest.raises(ValueError, match="source node"):
        extract_entities(brain, node_id="missing", extractor=lambda *a: pytest.fail("no extraction"))
    assert snapshot(brain) == before


def test_ambiguous_aliases_abort_without_partial_writes(brain):
    for name in ("Alex Smith", "Alex Jones"):
        brain.write_node(Node(name, ntype="entity", entity_name=name, entity_type="person", aliases=["Alex"]))
    before = snapshot(brain)
    with pytest.raises(ValueError, match="ambiguous"):
        extract_entities(brain, "Alex works at Acme.", extractor=provider(extraction("Alex works at Acme", subject="Alex") | {
            "entities": [dict(name="Alex", type="person"), dict(name="Acme", type="org")]}))
    assert snapshot(brain) == before


def test_tombstoned_identity_is_not_recreated(brain):
    result = extract_entities(brain, "Alice works at Acme.")
    alice = next(n for n in brain.read_nodes() if n.entity_name == "Alice")
    brain.tombstone_node(alice.id)
    before = snapshot(brain)
    with pytest.raises(ValueError, match="forgotten"):
        extract_entities(brain, "Alice works at Other.")
    assert snapshot(brain) == before


def test_rejected_and_invalidated_facts_are_not_recreated_or_accepted(brain):
    engine = BrainEngine(brain, HashEmbedder())
    result = engine.entities("Alice works at Acme. Alice founded Acme.")
    works = next(f for f in result["facts"] if f["predicate"] == "works_at")
    founded = next(f for f in result["facts"] if f["predicate"] == "founded")
    engine.resolve(works["id"], accept=False)
    brain.invalidate_edge(founded["id"])
    before = snapshot(brain)
    repeated = engine.entities("Alice works at Acme. Alice founded Acme.", accept_facts=True)
    assert not repeated["changed"]
    assert snapshot(brain) == before


def test_accept_override_only_applies_to_new_facts(brain):
    pending = extract_entities(brain, "Alice works at Acme.")
    assert not extract_entities(brain, "Alice works at Acme.", accept_facts=True)["changed"]
    second = extract_entities(brain, "Alice founded Acme.", accept_facts=True)
    assert not second["facts"][0]["pending"]
    assert brain.read_edges()[2].id == pending["facts"][0]["id"]
    assert next(e for e in brain.read_edges() if e.id == pending["facts"][0]["id"]).pending


def test_unknown_entities_do_not_enter_ingest_cosine_dedup(brain):
    engine = BrainEngine(brain, HashEmbedder())
    result = engine.entities("Alice works at Acme.")
    entity = next(n for n in brain.read_nodes() if n.entity_name == "Alice")
    node, _, duplicate = engine.ingest("Alice")
    assert not duplicate and node.id != entity.id
    engine.consolidate()
    assert brain.read_node(entity.id).status != "tombstone"


def test_two_different_predicates_and_direction_survive_note_merge(brain):
    from graph_engine.merge import merge_nodes
    data = extraction() | {"facts": [
        dict(subject="Alice", predicate="works_at", object="Acme", evidence="Alice works at Acme"),
        dict(subject="Alice", predicate="founded", object="Acme", evidence="Alice founded Acme"),
        dict(subject="Acme", predicate="employs", object="Alice", evidence="Acme employs Alice"),
    ]}
    result = extract_entities(brain, "Alice works at Acme. Alice founded Acme. Acme employs Alice.", extractor=provider(data))
    brain.write_node(Node("another source", id="another"))
    merge_nodes(brain, "another", result["source_node_id"])
    assert len([e for e in brain.read_edges() if e.kind == "fact"]) == 3
    entities = [n for n in brain.read_nodes() if n.ntype == "entity"]
    before = snapshot(brain)
    with pytest.raises(ValueError, match="identities"):
        merge_nodes(brain, entities[0].id, entities[1].id)
    assert snapshot(brain) == before


def test_explicit_validity_windows_are_distinct_and_temporal(brain):
    from graph_engine.temporal import valid_at
    for year in (2024, 2025):
        data = extraction(valid_from=f"{year}-01-01", valid_to=f"{year}-06-01")
        extract_entities(brain, "Alice works at Acme", extractor=provider(data), accept_facts=True)
    facts = [e for e in brain.read_edges() if e.kind == "fact"]
    assert len(facts) == 2
    at = valid_at(brain, "2024-03-01T00:00:00Z")
    assert [e.id for e in at["edges"] if e.kind == "fact"] == [facts[0].id]
    assert not [e for e in valid_at(brain, "2024-07-01T00:00:00Z")["edges"] if e.kind == "fact"]
    before = snapshot(brain)
    extract_entities(brain, "Alice works at Acme", extractor=provider(extraction(valid_from="2024-01-01", valid_to="2024-06-01")))
    assert snapshot(brain) == before


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(entities="bad"),
    lambda d: d["entities"][0].update(type="spaceship"),
    lambda d: d["entities"][0].update(aliases="Al"),
    lambda d: d["entities"][0].update(aliases=[4]),
    lambda d: d["entities"][0].update(name="Unmentioned"),
    lambda d: d["entities"].append(dict(name="alice", type="person")),
    lambda d: d["facts"][0].update(subject="Bob"),
    lambda d: d["facts"][0].update(predicate=""),
    lambda d: d["facts"][0].update(evidence="invented quote"),
    lambda d: d["facts"][0].update(confidence=float("nan")),
    lambda d: d["facts"][0].update(confidence=True),
    lambda d: d["facts"][0].update(valid_from="nonsense"),
    lambda d: d["facts"][0].update(valid_to="2020-01-01"),
    lambda d: d["facts"][0].update(valid_from="2025-01-01", valid_to="2020-01-01"),
])
def test_bad_extractor_output_fails_before_any_writes(brain, mutate):
    brain.write_node(Node("keep unchanged", id="old"))
    before = snapshot(brain)
    data = extraction()
    mutate(data)
    with pytest.raises(ValueError):
        extract_entities(brain, "Alice works at Acme", extractor=provider(data))
    assert snapshot(brain) == before


def test_concurrent_extraction_reuses_entities_and_facts(brain):
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: extract_entities(brain, "Alice works at Acme."), range(3)))
    assert sum(r["created_entities"] for r in results) == 2
    assert sum(r["created_facts"] for r in results) == 1
    assert len(brain.read_nodes()) == 3


def test_git_mode_one_commit_and_repeat_no_commit(tmp_path):
    brain = Brain(tmp_path / "git-brain", mode="git")
    extract_entities(brain, "Alice works at Acme.")
    def log():
        return subprocess.check_output(["git", "-C", str(brain.path), "log", "--format=%s"], text=True)
    before = log()
    assert len(before.splitlines()) == 1 and before.startswith("entities:")
    extract_entities(brain, "Alice works at Acme.")
    assert log() == before


def test_command_adapter_passes_schema_and_known_entities(tmp_path):
    import shlex
    script = tmp_path / "extract.py"
    script.write_text("import json, sys\nr=json.load(sys.stdin)\n"
                      "assert r['text'] == 'Alice works at Acme'\n"
                      "assert r['known_entities'][0]['name'] == 'Alice'\n"
                      "assert 'schema' in r and 'instruction' in r\n"
                      "print(json.dumps(" + repr(extraction()) + "))\n")
    result = command_extractor(f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}")(
        "Alice works at Acme", [dict(name="Alice", type="person", aliases=[])])
    assert len(validate_extraction(result, "Alice works at Acme")["facts"]) == 1


@pytest.mark.parametrize("command,exception", [("exit 7", RuntimeError), ("printf invalid", ValueError), ("true", ValueError)])
def test_command_adapter_failure(command, exception):
    with pytest.raises(exception):
        command_extractor(command)("Alice works at Acme", [])


def test_command_timeout_and_missing_configuration(monkeypatch):
    monkeypatch.setenv("IG_ENTITIES_LLM_CMD", "")
    with pytest.raises(ValueError, match="IG_ENTITIES_LLM_CMD"):
        command_extractor()
    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired("test", 300)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        command_extractor("test")("text", [])


def test_single_input_reuses_declared_alias_for_later_pronoun(brain):
    result = extract_entities(brain, "Alice works at International Business Machines (IBM). "
                              "Bob works at IBM. It uses Python.")
    assert result["created_entities"] == 4
    assert result["facts"][-1]["source"] == next(
        e["id"] for e in result["entities"] if e["entity_type"] == "org")


def test_trailing_stdin_whitespace_does_not_break_idempotence(brain):
    extract_entities(brain, "\n Alice works at Acme.\n")
    before = snapshot(brain)
    assert not extract_entities(brain, "\n Alice works at Acme.\n")["changed"]
    assert snapshot(brain) == before


def test_graph_neighbors_include_fact_predicate(brain):
    from graph_engine.graph import neighbors
    result = extract_entities(brain, "Alice works at Acme.", accept_facts=True)
    alice = next(e for e in result["entities"] if e["entity_name"] == "Alice")
    adjacent = neighbors(brain, alice["id"], kinds=["fact"])
    assert len(adjacent) == 1 and adjacent[0].predicate == "works_at"


def test_mcp_preserves_entity_and_fact_metadata(brain, monkeypatch):
    pytest.importorskip("mcp")
    from graph_engine.mcp.server import get_node, neighbors
    monkeypatch.setenv("IG_BRAIN_PATH", str(brain.path))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    result = extract_entities(brain, "Alice works at International Business Machines (IBM).", accept_facts=True)
    org = next(e for e in result["entities"] if e["entity_type"] == "org")
    info = get_node(org["id"])
    assert info["node"]["entity_name"] == org["entity_name"]
    assert info["node"]["aliases"] == ["IBM"]
    fact = next(e for e in info["edges"] if e["kind"] == "fact")
    assert fact["predicate"] == "works_at" and fact["evidence"][0]["node_id"] == result["source_node_id"]
    assert neighbors(org["id"], kinds=["fact"])["neighbors"][0]["predicate"] == "works_at"


def test_ambiguous_known_alias_in_rules_aborts_batch(brain):
    for name in ("Alex Smith", "Alex Jones"):
        brain.write_node(Node(name, ntype="entity", entity_name=name, entity_type="person", aliases=["Alex"]))
    before = snapshot(brain)
    with pytest.raises(ValueError, match="ambiguous"):
        extract_entities(brain, "Alex works at Acme.")
    assert snapshot(brain) == before


def test_corrupt_entity_frontmatter_is_skipped(brain):
    brain.write_node(Node("Alice", id="bad", ntype="entity", entity_name="Alice", entity_type="person"))
    path = brain.node_path("bad")
    path.write_text(path.read_text().replace("aliases: []", "aliases: 42"))
    assert brain.read_node("bad") is None
    assert brain.read_nodes() == []


def test_rule_uses_preserves_declared_product_type():
    data = rule_extract("GraphEngine is a product. Alice uses GraphEngine.")
    assert data["entities"][0]["type"] == "product"
    assert data["facts"][0]["object"] == "GraphEngine"


def test_multiline_model_evidence_survives_round_trip(brain):
    text = "Alice\nworks at Acme"
    result = extract_entities(brain, text, extractor=provider(extraction(text)))
    assert result["created_facts"] == 1
    fact = next(e for e in brain.read_edges() if e.kind == "fact")
    assert fact.evidence[0]["text"] == text

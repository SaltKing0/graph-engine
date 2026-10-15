"""Search snapshot equivalence, freshness and read-only boundaries."""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import numpy as np
import pytest

from graph_engine.brain import Brain, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder
from graph_engine.retrieval import retrieve
from graph_engine import runtime
from graph_engine.reranker import ReverseReranker
from tools.retrieval_benchmark import quality_comparison


@pytest.fixture
def engine(tmp_path):
    brain = Brain(str(tmp_path / "brain"))
    brain.init()
    for nid, text in (("a", "alpha beta"), ("b", "alpha gamma"), ("c", "omega")):
        brain.write_node(Node(text, id=nid, status="active"))
    engine = BrainEngine(brain, HashEmbedder(), reranker=False)
    engine.reranker = None
    return engine


def hits(engine, *, cached=True, persist=False, **kwargs):
    engine.search_cache_enabled = cached
    return retrieve(engine, "alpha", k=5, persist=persist, **kwargs)


def assert_matches(engine):
    cached = hits(engine)
    assert cached == hits(engine, cached=False)
    return cached


def test_warm_reuses_parsing_and_indexes_but_keeps_reranking(engine):
    first = hits(engine)
    index = engine._search_index
    original = engine.brain.read_nodes
    engine.brain.read_nodes = Mock(side_effect=AssertionError("warm parse"))
    assert hits(engine) == first
    assert engine._search_index is index
    engine.reranker = ReverseReranker()
    assert hits(engine) == first[::-1]
    engine.brain.read_nodes = original
    assert_matches(engine)


@pytest.mark.parametrize("mutation", ["add", "edit", "remove", "tombstone", "tier", "vectors", "corrupt-node", "corrupt-vectors"])
def test_completed_internal_and_external_mutations_invalidate(engine, mutation):
    hits(engine)
    index = engine._search_index
    brain = engine.brain
    if mutation == "add":
        brain.write_node(Node("alpha new", id="d", status="active"))
    elif mutation == "remove":
        brain.node_path("a").unlink()
    elif mutation == "edit":
        # Direct external edit, including unchanged length.
        path = brain.node_path("a")
        path.write_text(path.read_text().replace("alpha beta", "omega beta"))
    elif mutation == "tombstone":
        node = brain.read_node("a")
        node.status = "tombstone"
        brain.write_node(node)
    elif mutation == "tier":
        node = brain.read_node("b")
        node.storage_tier = "main"
        brain.write_node(node)
    elif mutation == "vectors":
        brain.write_vectors({"a": [0.] * 64, "b": [1.] * 64})
    elif mutation == "corrupt-node":
        brain.node_path("a").write_text("---\nid: [\n")
    else:
        brain.vectors_file.write_text('{broken\n{"id": "b", "vec": []}\n')
    results = assert_matches(engine)
    assert engine._search_index is not index
    if mutation in ("remove", "tombstone", "corrupt-node"):
        assert "a" not in dict(results)
    if mutation == "tier":
        assert results[0][0] == "b"


def test_vector_memo_invalidates_missing_text_and_completes_partial_entry(engine):
    brain = engine.brain
    Brain._VECTOR_MEMO.clear()
    first = brain.vectors_for({"a"}, engine.embedder.embed, persist=False)
    second = brain.vectors_for({"a", "b"}, engine.embedder.embed, persist=False)
    assert set(second) == {"a", "b"}
    node = brain.read_node("a")
    node.text = "omega"
    brain.write_node(node)
    updated = brain.vectors_for({"a"}, engine.embedder.embed, persist=False)
    assert updated["a"] != first["a"]


def test_model_change_and_brain_switch_invalidate(engine, tmp_path):
    hits(engine)
    old = engine._search_index
    class Other(HashEmbedder):
        DIM = 32
    engine.embedder = Other()
    assert_matches(engine)
    assert engine._search_index is not old
    assert engine._search_index.dimension == 32
    assert engine._search_index.matrix.shape[1] == 32
    other = Brain(str(tmp_path / "other"))
    other.init()
    other.write_node(Node("alpha", id="other"))
    engine.brain = other
    assert set(dict(assert_matches(engine))) == {"other"}


def test_corrupt_memory_entry_recovers_and_no_files_are_written(engine):
    brain = engine.brain
    before = {str(p): p.read_bytes() for p in brain.path.rglob("*") if p.is_file()}
    expected = hits(engine)
    index = engine._search_index
    engine._search_index = replace(index, matrix=np.empty((0, 0)))
    assert hits(engine) == expected
    assert engine._search_index is not index
    engine._search_index = {"corrupt": True}
    assert hits(engine) == expected
    after = {str(p): p.read_bytes() for p in brain.path.rglob("*") if p.is_file()}
    assert after == before
    assert brain.read_vectors() == {}
    # A subsequent opt-in writer must fill vectors even after read-only search.
    hits(engine, persist=True)
    assert set(brain.read_vectors()) == {"a", "b", "c"}


def test_per_tier_mode_rebuilds_without_changing_rank(engine):
    hits(engine)
    old = engine._search_index
    assert hits(engine, per_tier=True) == hits(engine, cached=False, per_tier=True)
    assert engine._search_index is not old


def test_runtime_model_override_is_part_of_engine_key(tmp_path, monkeypatch):
    monkeypatch.delenv("IG_ACCESS_POLICY", raising=False)
    monkeypatch.delenv("IG_GRAPH_HOME", raising=False)
    monkeypatch.setenv("IG_BRAIN_PATH", str(tmp_path))
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    runtime.reset_engine_cache()
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER_MODEL", "first")
    first = runtime.make_engine()
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER_MODEL", "second")
    assert runtime.make_engine() is not first
    runtime.reset_engine_cache()


def test_quality_dataset_order_and_scores_match(tmp_path):
    report = quality_comparison(tmp_path, None, 0)
    assert report["questions"] >= 10
    assert report["mismatches"] == []


def test_unhashable_custom_embedder_and_explicit_model_revision(engine):
    from dataclasses import dataclass
    @dataclass
    class Custom(HashEmbedder):
        cache_key: str = "first"
    engine.embedder = Custom()
    hits(engine)
    old = engine._search_index
    engine.embedder.cache_key = "second"
    assert_matches(engine)
    assert engine._search_index is not old


def test_benchmark_small_run_reports_stages_and_sample_counts(tmp_path):
    from tools.retrieval_benchmark import measure
    report = measure(12, 2, tmp_path / "fixture")
    assert report["correctness_mismatches"] == []
    assert report["search"]["cold"]["n"] == 2
    assert report["ingest"]["cold"]["n"] == 2
    assert report["ingest"]["warm"]["n"] == 2
    assert report["search_stages"]["warm"]["reranking"]["p50_ms"] == 0
    assert "cold:pull" in report["ingest_stages_inclusive"]


def test_external_vector_change_during_build_cannot_publish_old_matrix(engine, monkeypatch):
    original = engine.brain.vectors_for
    def racing_vectors(*args, **kwargs):
        result = original(*args, **kwargs)
        engine.brain.write_vectors({"a": [0.] * 64, "b": [1.] * 64})
        return result
    monkeypatch.setattr(engine.brain, "vectors_for", racing_vectors)
    hits(engine)
    assert not hasattr(engine, "_search_index")
    monkeypatch.setattr(engine.brain, "vectors_for", original)
    assert_matches(engine)
    assert hasattr(engine, "_search_index")


@pytest.mark.parametrize("bad", ["garbage", 42, {}, ["garbage"], [float("nan")], [float("inf")]])
def test_malformed_vector_cache_values_recover_without_writes(engine, bad):
    import json
    brain = engine.brain
    brain.vectors_file.write_text(json.dumps({"id": "a", "vec": bad}) + "\n")
    before = brain.vectors_file.read_bytes()
    assert brain.read_vectors() == {}
    assert_matches(engine)
    assert brain.vectors_file.read_bytes() == before


def test_oversized_orphan_vector_preserves_valid_records_and_search(engine):
    import json
    expected = hits(engine, cached=False)
    brain = engine.brain
    valid = engine.embedder.embed("alpha beta")
    brain.vectors_file.write_text(
        json.dumps({"id": "orphan", "vec": [10**400]}) + "\n"
        + json.dumps({"id": "a", "vec": valid}) + "\n")
    before = brain.vectors_file.read_bytes()

    assert brain.read_vectors() == {"a": valid}
    assert hits(engine) == expected
    assert hits(engine) == expected  # Warm snapshot must also recover.
    assert hits(engine, cached=False) == expected
    assert brain.vectors_file.read_bytes() == before


def test_populated_vectors_follow_external_text_edits_and_dense_scores(engine):
    from graph_engine.retrieval import explain
    brain = engine.brain
    brain.vectors_for({"c"}, engine.embedder.embed, persist=True)
    before = brain.vectors_file.read_bytes()
    assert explain(engine, "c", "omega")["dense"]["score"] == pytest.approx(1)
    path = brain.node_path("c")
    path.write_text(path.read_text().replace("omega", "alpha"))
    for cached in (True, False):
        engine.search_cache_enabled = cached
        assert explain(engine, "c", "omega")["dense"]["score"] == pytest.approx(0)
        assert explain(engine, "c", "alpha")["dense"]["score"] == pytest.approx(1)
    assert brain.vectors_file.read_bytes() == before
    brain.vectors_for({"c"}, engine.embedder.embed, persist=True)
    assert brain.read_vectors()["c"] == engine.embedder.embed("alpha")


def test_populated_vectors_follow_same_dimension_model_revision(engine):
    from graph_engine.retrieval import explain
    class Model:
        model_name = "test-model"
        revision = "first"
        def embed(self, text):
            return [1., 0.] if text == "omega" or self.revision == "first" else [0., 1.]
    model = Model()
    engine.embedder = model
    engine.brain.vectors_for({"a"}, model.embed, persist=True)
    before = engine.brain.vectors_file.read_bytes()
    assert explain(engine, "a", "omega")["dense"]["score"] == pytest.approx(1)
    model.revision = "second"
    for cached in (True, False):
        engine.search_cache_enabled = cached
        assert explain(engine, "a", "omega")["dense"]["score"] == pytest.approx(0)
    assert engine.brain.vectors_file.read_bytes() == before


def test_legacy_vectors_are_recomputed_without_read_side_effects(engine):
    brain = engine.brain
    brain.write_vectors({"c": engine.embedder.embed("alpha")})
    before = brain.vectors_file.read_bytes()
    assert brain.vectors_for({"c"}, engine.embedder.embed, persist=False)["c"] == engine.embedder.embed("omega")
    assert brain.vectors_file.read_bytes() == before


def test_versioned_vectors_survive_new_instances_and_preserve_normalization(engine):
    import json
    from graph_engine.vector_cache import text_hash
    brain = engine.brain
    expected = brain.vectors_for({"a", "b"}, engine.embedder.embed)
    entries = {row["id"]: row for row in map(json.loads, brain.vectors_file.read_text().splitlines())}
    assert entries["a"]["version"] == 1
    assert entries["a"]["text_hash"] == text_hash(" ALPHA\n beta ")
    assert "HashEmbedder" in entries["a"]["model_key"]
    Brain._VECTOR_MEMO.clear()
    fresh = Brain(brain.path)
    embedder = HashEmbedder()
    embedder.embed = Mock(side_effect=AssertionError("valid vector was re-embedded"))
    # Supply a stable model identity while wrapping the bound method.
    from graph_engine.vector_cache import model_identity
    assert fresh.vectors_for({"a", "b"}, embedder.embed, persist=False,
                             embedder_key=model_identity(embedder)) == expected
    node = brain.read_node("a")
    node.text = " ALPHA\n beta "
    brain.write_node(node)
    assert fresh.vectors_for({"a"}, embedder.embed, persist=False,
                             embedder_key=model_identity(embedder)) == {"a": expected["a"]}
    # Legacy maintenance rewrites must retain other records' provenance.
    brain.write_vectors({"a": expected["a"]})
    assert json.loads(brain.vectors_file.read_text()) == entries["a"]


@pytest.mark.parametrize("field,value", [("version", 0), ("version", True),
                                       ("text_hash", "stale"), ("model_key", "old")])
def test_incompatible_metadata_recomputes_in_memory(engine, field, value):
    import json
    brain = engine.brain
    brain.vectors_for({"c"}, engine.embedder.embed)
    entry = json.loads(brain.vectors_file.read_text())
    entry[field] = value
    entry["vec"] = engine.embedder.embed("alpha")
    brain.vectors_file.write_text(json.dumps(entry) + "\n")
    before = brain.vectors_file.read_bytes()
    assert brain.vectors_for({"c"}, engine.embedder.embed, persist=False)["c"] == engine.embedder.embed("omega")
    assert brain.vectors_file.read_bytes() == before


def test_same_dimension_model_name_change_and_partial_memo(engine):
    class Model:
        model_name = "first"
        def embed(self, text):
            return [1., 0.] if self.model_name == "first" else [0., 1.]
    brain, model = engine.brain, Model()
    brain.vectors_for({"a", "b"}, model.embed)
    model.model_name = "second"
    assert brain.vectors_for({"a"}, model.embed, persist=False) == {"a": [0., 1.]}
    assert brain.vectors_for({"a", "b"}, model.embed, persist=False) == {"a": [0., 1.], "b": [0., 1.]}
    brain.vectors_for({"a"}, model.embed)
    # An unrequested old-model record must not enter the new-model memo.
    assert brain.vectors_for({"b"}, model.embed, persist=False) == {"b": [0., 1.]}


def test_anonymous_adapters_do_not_share_vector_provenance(engine):
    brain = engine.brain
    first, second = lambda _: [1., 0.], lambda _: [0., 1.]
    brain.vectors_for({"a"}, first)
    assert brain.vectors_for({"a"}, second, persist=False) == {"a": [0., 1.]}


def test_persisted_model_identity_is_reusable_across_processes(engine):
    import subprocess
    import sys
    engine.brain.vectors_for({'a'}, engine.embedder.embed)
    script = '''
import sys
from graph_engine.brain import Brain
from graph_engine.embedder import HashEmbedder
from graph_engine.vector_cache import model_identity
brain = Brain(sys.argv[1], mode="local")
def unexpected(text):
    raise AssertionError("compatible persisted vector was recomputed")
assert brain.vectors_for({"a"}, unexpected, persist=False,
                         embedder_key=model_identity(HashEmbedder()))["a"] == HashEmbedder().embed("alpha beta")
'''
    subprocess.run([sys.executable, '-c', script, str(engine.brain.path)], check=True)

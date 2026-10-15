"""Evaluation integrity regressions, independent of future DM implementation."""
from __future__ import annotations

import copy
import json
import shutil
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.decision_benchmark.corpus import DATA, canonical, digest, load_bundle, validate, visible_inputs
from tools.decision_benchmark.freeze_sources import freeze, verify_git
from tools.decision_benchmark.runner import dependency_alerts, run
from tools.decision_benchmark.scoring import score


@pytest.mark.parametrize("name", ["project-v1", "controls-v1"])
def test_bundled_bytes_and_complete_pair_labels(name):
    inputs, labels, manifest = load_bundle(DATA / name)
    assert labels["pairs"] and manifest["gates"]["heldout_positive_min"] == 20
    if name == "project-v1":
        assert len(inputs["decisions"]) == 8 and len(inputs["events"]) == 16
        assert {label["outcome"] for label in labels["pairs"].values()} == {"pending"}


def test_frozen_bytes_reject_tampering_and_escaping_paths(tmp_path):
    root = tmp_path / "corpus"
    shutil.copytree(DATA / "controls-v1", root)
    source = root / "sources/comparable-basis.txt"
    source.write_text("different")
    with pytest.raises(ValueError, match="frozen file changed"):
        load_bundle(root)
    manifest = json.loads((root / "freeze.json").read_bytes())
    manifest["files"]["../outside"] = digest(b"oops")
    manifest["sha256"] = digest(canonical(manifest["files"]))
    (root / "freeze.json").write_text(json.dumps(manifest))
    # Restore the earlier bytes so the escaping entry is the first failure.
    shutil.copyfile(DATA / "controls-v1/sources/comparable-basis.txt", source)
    with pytest.raises(ValueError, match="inside the bundle"):
        load_bundle(root)


def test_future_sources_and_other_split_never_reach_ingestion():
    inputs, _, _ = load_bundle(DATA / "project-v1")
    event = inputs["events"][0]
    visible = visible_inputs(inputs, event, DATA / "project-v1")
    ids = {doc["source_id"] for doc in visible["documents"]}
    assert event["source_id"] in ids
    assert inputs["events"][-1]["source_id"] not in ids
    assert all(s["split"] == event["split"] for s in inputs["sources"] if s["id"] in ids)
    encoded = json.dumps(visible)
    assert "draft_rationale" not in encoded and "draft_outcome" not in encoded


@pytest.mark.parametrize("mutation", ["future", "split", "chronology", "missing-label", "self-review"])
def test_invalid_evaluation_inputs_fail_closed(mutation):
    inputs, labels, manifest = load_bundle(DATA / "project-v1")
    if mutation == "future":
        inputs["sources"][0]["available_at"] = "2099-01-01T00:00:00Z"
    elif mutation == "split":
        inputs["decisions"][0]["split"] = "evaluation"
    elif mutation == "chronology":
        inputs["events"].reverse()
    elif mutation == "missing-label":
        labels["pairs"].clear()
    else:
        label = next(iter(labels["pairs"].values()))
        label["outcome"] = "positive"
        label["annotation"].update(status="adjudicated", reviewer="Codex")
    with pytest.raises(ValueError):
        validate(inputs, labels, manifest)


def test_offline_baseline_is_reproducible_without_gold_or_ambient_models(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline evaluation attempted network/model factory")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr("graph_engine.brain_engine.get_embedder", forbidden)
    monkeypatch.setattr("graph_engine.brain_engine.get_reranker", forbidden)
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "st")
    monkeypatch.setenv("IDEAGRAPH_RERANKER", "st")
    root = tmp_path / "corpus"
    shutil.copytree(DATA / "controls-v1", root)
    first = run(root, tmp_path / "first.json", split="all")
    inputs, labels, _ = load_bundle(root)
    for label in labels["pairs"].values():
        label["rationale"] = "SECRET_GOLD_CANARY"
        label["outcome"] = "negative"
        label["valid_paths"] = []
    freeze(root, inputs, labels, (root / "contract.md").read_bytes())
    second = run(root, tmp_path / "second.json", split="all")
    assert first["smoke_passed"] and second["smoke_passed"]
    for left, right in zip(first["results"], second["results"]):
        assert left["baselines"] == right["baselines"]
        assert left["retrieval"]["hits"] == right["retrieval"]["hits"]
        assert left["retrieval"]["prompt_sha256"] == right["retrieval"]["prompt_sha256"]
        assert "SECRET_GOLD_CANARY" not in json.dumps(right["retrieval"]["prompt"])
    assert first["scores"] != second["scores"]
    assert not first["release_readiness"]["passed"]
    assert first["metadata"]["configuration"]["provider_calls"] is False


def test_proposed_and_curated_dependencies_are_separate():
    inputs, _, _ = load_bundle(DATA / "controls-v1")
    event = inputs["events"][0]
    visible = visible_inputs(inputs, event, DATA / "controls-v1")
    curated = dependency_alerts(visible, event, "curated")
    assert len(curated) == 1 and dependency_alerts(visible, event, "proposed") == []
    visible["dependencies"][0]["status"] = "proposed"
    assert dependency_alerts(visible, event, "curated") == []
    assert len(dependency_alerts(visible, event, "proposed")) == 1


def test_errors_unknown_alerts_wrong_paths_and_duplicates_keep_denominators():
    labels = {"pairs": {"e/p": {"outcome": "positive", "valid_paths": [["s", "l", "p"]]},
                         "e/n": {"outcome": "negative", "valid_paths": []},
                         "e/i": {"outcome": "inconclusive", "valid_paths": [["s", "l", "i"]]},
                         "e/u": {"outcome": "unanswerable", "valid_paths": [["s", "l", "u"]]},
                         "e/pending": {"outcome": "pending", "valid_paths": []}}}
    alerts = [{"decision_id": "p", "path": ["wrong"]},
              {"decision_id": "n", "path": [], "uncertainty_reason": "unknown"},
              {"decision_id": "i", "path": ["s", "l", "i"], "uncertainty_reason": "missing host"},
              {"decision_id": "u", "path": ["s", "l", "u"], "uncertainty_reason": "missing result"}]
    rows = [{"event_id": "e", "eligible_decisions": ["p", "n", "i", "u", "pending"], "alerts": alerts}]
    result = score(rows, labels)
    assert result["recall"]["value"] == 0
    assert result["false_alert_rate"]["value"] == 1
    assert result["precision"]["denominator"] == 2
    assert result["inconclusive_handling"]["denominator"] == 1
    assert result["unanswerable_handling"]["value"] == 1
    alerts.append(copy.deepcopy(alerts[1]))
    duplicate = score(rows, labels)
    assert duplicate["false_alert_rate"] == result["false_alert_rate"]
    assert duplicate["counts"]["raw_alerts"] == 5
    alerts[0]["path"] = ["s", "l", "p"]
    rows[0]["error"] = "RuntimeError"
    error = score(rows, labels)
    assert error["miss_rate"]["value"] == 1
    assert error["counts"]["error_pairs"] == 5 and error["counts"]["error_cases"] == 1


def test_failed_retrieval_remains_visible_in_attempted_pairs(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("do not persist raw provider or source error bodies")
    monkeypatch.setattr("tools.decision_benchmark.runner.prepare", fail)
    report = run(DATA / "controls-v1", tmp_path / "errors.json", split="all")
    assert report["status"] == "completed_with_errors" and not report["smoke_passed"]
    assert all(row["error"] == "RuntimeError" for row in report["results"])
    assert report["scores"]["curated"]["miss_rate"]["value"] == 1
    assert report["scores"]["curated"]["counts"]["attempted_pairs"] == 100

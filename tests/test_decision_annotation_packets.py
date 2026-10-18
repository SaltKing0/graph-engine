"""Development export boundaries, exact references and reproducibility."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.decision_benchmark.annotation_packets import (
    BUNDLE, EXPOSURE, prepare_development, validate_packet, validate_quote,
)
from tools.decision_benchmark.corpus import canonical, digest


def test_export_never_reads_labels_or_evaluation_source_bytes(monkeypatch):
    original = Path.read_bytes
    inputs = json.loads(original(BUNDLE / "inputs.json"))
    forbidden = {BUNDLE / "labels.json"} | {
        BUNDLE / s["file"] for s in inputs["sources"] if s["split"] == "evaluation"
    }
    opened = set()

    def guarded(path):
        assert path not in forbidden, f"opened reserved file: {path}"
        opened.add(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    packet, form = prepare_development()
    assert opened and not opened & forbidden
    assert packet["exposure"] == EXPOSURE
    assert len(packet["cases"]) == 8 and len(form["pairs"]) == 27
    assert form["packet_sha256"] == digest(canonical(packet))
    assert form["reviewers"] == [] and form["calibration"]["status"] == "not-started"
    for pair in form["pairs"]:
        assert len(pair["initial_judgments"]) == 2
        assert all(j["outcome"] is None and j["reviewer_id"] is None for j in pair["initial_judgments"])
        assert pair["adjudication"]["disagreements"] is None
    encoded = json.dumps(packet)
    for field in ("draft_rationale", "draft_outcome", "dependencies", "conditions", "valid_paths", "annotation"):
        assert f'"{field}"' not in encoded
    report = validate_packet(packet)
    assert report["eligible_pairs"] == 27 and not report["acceptance_complete"]
    assert report["independently_reviewed_pairs"] is None
    assert sum(report["final_coverage"].values()) == 0


def test_chronological_projection_and_original_lineage_not_lost():
    packet, _ = prepare_development()
    first = packet["cases"][0]
    last_update = packet["cases"][-1]["update_source_id"]
    assert last_update not in {s["id"] for s in first["sources"]}
    assert all(d["family"] in {"graph", "context", "documents", "cache"}
               for case in packet["cases"] for d in case["decisions"])
    reports = [s for case in packet["cases"] for s in case["sources"] if s["id"] == "graph-report"]
    assert reports and "graph-diagnostic-20261012" in reports[0]["measurement_lineages"]
    assert "MIT License" in reports[0]["license_text"]


@pytest.mark.parametrize("mutation", ["future", "duplicate", "hash", "license", "missing", "gold", "split", "order", "identity"])
def test_packet_validation_rejects_broken_boundaries(mutation):
    packet, _ = prepare_development()
    case = packet["cases"][0]
    if mutation == "future":
        case["sources"][0]["available_at"] = "2099-01-01T00:00:00Z"
    elif mutation == "duplicate":
        case["sources"].append(copy.deepcopy(case["sources"][0]))
    elif mutation == "hash":
        case["sources"][0]["text"] += "changed"
    elif mutation == "license":
        case["sources"][0]["license_text"] = "wrong license"
    elif mutation == "missing":
        case["update_source_id"] = "missing"
    elif mutation == "gold":
        case["decisions"][0]["expected_impact"] = True
    elif mutation == "split":
        packet["split"] = "evaluation"
    elif mutation == "order":
        packet["cases"].reverse()
    else:
        source = packet["cases"][-1]["sources"][0]
        source["revision"] = "different-version"
    with pytest.raises(ValueError):
        validate_packet(packet)


def test_source_freeze_tampering_is_rejected_without_opening_labels(monkeypatch):
    original = Path.read_bytes

    def corrupt(path):
        if path == BUNDLE / "inputs.json":
            return original(path) + b" "
        assert path.name != "labels.json"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", corrupt)
    with pytest.raises(ValueError, match="frozen file changed"):
        prepare_development()


@pytest.mark.parametrize("kind", ["family", "lineage"])
def test_export_rejects_cross_split_families_and_duplicate_lineage(monkeypatch, kind):
    original = Path.read_bytes
    inputs = json.loads(original(BUNDLE / "inputs.json"))
    freeze = json.loads(original(BUNDLE / "freeze.json"))
    if kind == "family":
        inputs["decisions"][-1]["family"] = inputs["decisions"][0]["family"]
    else:
        inputs["sources"][-1]["lineage"] = next(
            s["lineage"] for s in inputs["sources"] if s["split"] == "evaluation")
    raw_inputs = canonical(inputs)
    freeze["files"]["inputs.json"] = digest(raw_inputs)
    freeze["sha256"] = digest(canonical(freeze["files"]))

    def modified(path):
        assert path.name != "labels.json"
        if path == BUNDLE / "inputs.json":
            return raw_inputs
        if path == BUNDLE / "freeze.json":
            return canonical(freeze)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", modified)
    with pytest.raises(ValueError, match="family or source lineage crosses split"):
        prepare_development()


@pytest.mark.parametrize("mutation", [None, "quote", "version", "hash", "offset", "boolean", "unicode", "tampered-source"])
def test_quotes_bind_exact_utf8_bytes_and_source_version(mutation):
    packet, _ = prepare_development()
    case = packet["cases"][0]
    source = case["sources"][0]
    reference = {"source_id": source["id"], "revision": source["revision"], "sha256": source["sha256"],
                 "byte_start": 0, "byte_end": len(source["text"].encode("utf-8")), "quote": source["text"]}
    if mutation is None:
        validate_quote(case, reference)
        return
    if mutation == "quote":
        reference["quote"] += "x"
    elif mutation == "version":
        reference["revision"] = "another-version"
    elif mutation == "hash":
        reference["sha256"] = "wrong"
    elif mutation == "offset":
        reference["byte_start"] = -1
    elif mutation == "boolean":
        reference["byte_start"] = False
    elif mutation == "tampered-source":
        source["text"] += "x"
        reference.update(quote=source["text"], byte_end=len(source["text"].encode()))
    else:
        # UTF-8 character offsets cannot masquerade as byte offsets.
        source["text"] = "éx"
        source["sha256"] = digest(source["text"].encode())
        reference.update(sha256=source["sha256"], byte_end=1, quote="é")
    with pytest.raises(ValueError, match="exact source version/byte span"):
        validate_quote(case, reference)


def test_cli_reproducible_hashes_and_refuses_overwriting_reviews(tmp_path):
    directories = [tmp_path / "first", tmp_path / "second"]
    for directory in directories:
        subprocess.run([sys.executable, "-m", "tools.decision_benchmark.annotation_packets",
                        "--output", str(directory)], check=True, capture_output=True)
    first, second = directories
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {p.name: p.read_bytes() for p in second.iterdir()}
    manifest = json.loads((first / "manifest.json").read_bytes())
    assert manifest["sha256"] == digest(canonical(manifest["files"]))
    for name, expected in manifest["files"].items():
        assert digest((first / name).read_bytes()) == expected
    (first / "blank-form.json").write_text("human work must survive")
    result = subprocess.run([sys.executable, "-m", "tools.decision_benchmark.annotation_packets",
                             "--output", str(first)], capture_output=True)
    assert result.returncode != 0
    assert (first / "blank-form.json").read_text() == "human work must survive"

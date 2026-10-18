"""Prepare previously exposed development sources, never final evaluation data.

This is annotation preparation, not an independent-label or release validator.
No label file, provider, Git command or network is used by this module.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .corpus import DATA, canonical, digest, instant, local_file

SCHEMA = "dm.annotation.development/1"
EXPOSURE = "previously-exposed-development-only"
# A future corpus needs a separately authorized custodian workflow. Do not add
# an arbitrary --bundle/--split switch that could disclose reserved sources.
BUNDLE = DATA / "project-v1"
SOURCE_KEYS = (
    "id", "available_at", "repository", "revision", "path", "url", "capture_date",
    "retrieval", "license", "license_revision", "license_sha256", "redistribution",
    "blob_sha256", "blob_oid", "byte_start", "byte_end", "format", "parent_revision",
    "lineage",
)


def _unique(rows: list[dict], key: str = "id") -> dict[str, dict]:
    indexed = {row[key]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"duplicate {key}")
    return indexed


def _blank_judgment() -> dict:
    return {
        "reviewer_id": None, "recorded_at": None, "outcome": None,
        "needs_review": None, "triggering_evidence": [], "conditions": [],
        "comparability": None, "dependency_paths": [], "remaining_support": [],
        "withdrawn_support": [], "uncertainty": None, "rationale": None,
        "failure_modes": [],
    }


def prepare_development() -> tuple[dict, dict]:
    """Read only the fixed development inputs and their chronological bytes."""
    freeze = json.loads((BUNDLE / "freeze.json").read_bytes())
    if (freeze["schema"] != "dm.eval.freeze/1"
            or digest(canonical(freeze["files"])) != freeze["sha256"]):
        raise ValueError("invalid source freeze")

    def read_frozen(name: str) -> bytes:
        raw = local_file(BUNDLE, name).read_bytes()
        if digest(raw) != freeze["files"][name]:
            raise ValueError(f"frozen file changed: {name}")
        return raw

    inputs = json.loads(read_frozen("inputs.json"))
    if inputs["schema"] != "dm.eval.inputs/1" or inputs["version"] != "project-v1.0.0":
        raise ValueError("only the known exposed development bundle is supported")
    sources = _unique(inputs["sources"])
    decisions = _unique(inputs["decisions"])
    _unique(inputs["events"])
    families: dict[str, set[str]] = {}
    lineages: dict[str, set[str]] = {}
    for decision in decisions.values():
        families.setdefault(decision["family"], set()).add(decision["split"])
        if sources[decision["source_id"]]["split"] != decision["split"]:
            raise ValueError("decision source crosses split")
    for source in sources.values():
        for lineage in [source["lineage"], *source.get("measurement_lineages", [])]:
            lineages.setdefault(lineage, set()).add(source["split"])
    if any(len(splits) != 1 for splits in [*families.values(), *lineages.values()]):
        raise ValueError("family or source lineage crosses split")

    cases = []
    pairs = []
    for event in inputs["events"]:
        if event["split"] != "development":
            continue
        cutoff = instant(event["at"])
        for key in ("source_id", "changed_source_id"):
            source = sources[event[key]]
            if source["split"] != "development" or instant(source["available_at"]) > cutoff:
                raise ValueError("event references future or other-split source")
        visible = [source for source in sources.values() if source["split"] == "development"
                   and instant(source["available_at"]) <= cutoff]
        ids = {source["id"] for source in visible}
        inventory = [{key: decision[key] for key in ("id", "family", "source_id", "action", "status")}
                     for decision in decisions.values() if decision["split"] == "development"
                     and decision["source_id"] in ids]
        documents = []
        for source in visible:
            raw = read_frozen(source["file"])
            notice = read_frozen(source["license_file"])
            if digest(notice) != source["license_sha256"]:
                raise ValueError("license hash mismatch")
            documents.append({**{key: source[key] for key in SOURCE_KEYS},
                              "sha256": digest(raw), "text": raw.decode("utf-8"),
                              "measurement_lineages": source.get("measurement_lineages", []),
                              "limitations": source.get("limitations", "not recorded"),
                              "license_text": notice.decode("utf-8")})
        cases.append({"id": event["id"], "at": event["at"],
                      "update_source_id": event["source_id"],
                      "changed_source_id": event["changed_source_id"],
                      "sources": documents, "decisions": inventory})
        for decision in inventory:
            pairs.append({"case_id": event["id"], "decision_id": decision["id"],
                          "initial_judgments": [_blank_judgment(), _blank_judgment()],
                          "adjudication": {"reviewer_id": None, "recorded_at": None,
                                           "disagreements": None, "resolution": None,
                                           "final_outcome": None}})
    packet = {"schema": SCHEMA, "exposure": EXPOSURE, "split": "development",
              "origin_version": inputs["version"], "origin_freeze_sha256": freeze["sha256"],
              "origin_inputs_sha256": freeze["files"]["inputs.json"], "cases": cases}
    form = {"schema": "dm.annotation.form/1", "exposure": EXPOSURE,
            "packet_sha256": digest(canonical(packet)),
            "reviewers": [], "pairs": pairs,
            "calibration": {"status": "not-started", "disagreements": None,
                            "rubric_revision": None, "sign_off": None}}
    validate_packet(packet)
    return packet, form


def _keys(row: dict, keys: set[str]) -> None:
    if set(row) != keys:
        raise ValueError("unexpected or missing packet fields")


def validate_packet(packet: dict) -> dict:
    """Validate development packet structure only; never certify human evidence."""
    _keys(packet, {"schema", "exposure", "split", "origin_version", "origin_freeze_sha256",
                   "origin_inputs_sha256", "cases"})
    if (packet["schema"] != SCHEMA or packet["split"] != "development"
            or packet["exposure"] != EXPOSURE or packet["origin_version"] != "project-v1.0.0"):
        raise ValueError("not a previously exposed development packet")
    _unique(packet["cases"])
    pairs = 0
    previous = None
    seen_sources: dict[str, dict] = {}
    seen_decisions: dict[str, dict] = {}
    for case in packet["cases"]:
        _keys(case, {"id", "at", "update_source_id", "changed_source_id", "sources", "decisions"})
        cutoff = instant(case["at"])
        if previous is not None and cutoff < previous:
            raise ValueError("cases must be chronological")
        previous = cutoff
        sources = _unique(case["sources"])
        for key in ("update_source_id", "changed_source_id"):
            if case[key] not in sources:
                raise ValueError("missing event source")
        for source in sources.values():
            _keys(source, {*SOURCE_KEYS, "sha256", "text", "license_text",
                           "measurement_lineages", "limitations"})
            if instant(source["available_at"]) > cutoff:
                raise ValueError("future source in case")
            if digest(source["text"].encode("utf-8")) != source["sha256"]:
                raise ValueError("source hash mismatch")
            if digest(source["license_text"].encode("utf-8")) != source["license_sha256"]:
                raise ValueError("license hash mismatch")
            if source["id"] in seen_sources and seen_sources[source["id"]] != source:
                raise ValueError("source identity changed between cases")
            seen_sources[source["id"]] = source
        _unique(case["decisions"])
        for decision in case["decisions"]:
            _keys(decision, {"id", "family", "source_id", "action", "status"})
            if decision["source_id"] not in sources:
                raise ValueError("missing decision source")
            if decision["id"] in seen_decisions and seen_decisions[decision["id"]] != decision:
                raise ValueError("decision identity changed between cases")
            seen_decisions[decision["id"]] = decision
        pairs += len(case["decisions"])
    if not packet["cases"] or not pairs:
        raise ValueError("empty development packet")
    return {"schema": "dm.annotation.preparation-report/1", "packet_valid": True,
            "cases": len(packet["cases"]), "eligible_pairs": pairs,
            "independently_reviewed_pairs": None,
            "final_coverage": {"positive_pairs": 0, "negative_pairs": 0, "inconclusive_cases": 0},
            "acceptance_complete": False,
            "blockers": ["Human calibration not recorded", "No successor final sources or labels",
                         "Two independent judgments and adjudication not verified",
                         "No custodian access-control or freeze sign-off"]}


def validate_quote(case: dict, reference: dict) -> None:
    """Check a UTF-8 byte span against the exact packet version, not a substring."""
    _keys(reference, {"source_id", "revision", "sha256", "byte_start", "byte_end", "quote"})
    source = _unique(case["sources"])[reference["source_id"]]
    start, end = reference["byte_start"], reference["byte_end"]
    raw = source["text"].encode("utf-8")
    if (digest(raw) != source["sha256"]
            or reference["revision"] != source["revision"] or reference["sha256"] != source["sha256"]
            or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(raw)
            or raw[start:end] != reference["quote"].encode("utf-8")):
        raise ValueError("quote does not resolve to the exact source version/byte span")


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="NEW directory for development preparation; existing paths are refused")
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(DATA.resolve()):
        parser.error("preparation output must be outside preserved benchmark data")
    packet, form = prepare_development()
    # Fail before writing anything if the directory exists. No overwriting reviews.
    args.output.mkdir(parents=True, exist_ok=False)
    _write(args.output / "packet.json", packet)
    _write(args.output / "blank-form.json", form)
    _write(args.output / "preparation-report.json", validate_packet(packet))
    files = {path.name: digest(path.read_bytes()) for path in sorted(args.output.iterdir())}
    _write(args.output / "manifest.json", {"schema": "dm.annotation.preparation-freeze/1",
                                         "files": files, "sha256": digest(canonical(files)),
                                         "status": "development-preparation-not-successor-freeze"})


if __name__ == "__main__":
    main()

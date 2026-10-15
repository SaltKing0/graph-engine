"""Rebuild v1 from local Git objects only. Never fetch or execute source code.

Run only when intentionally preparing a NEW freeze; normal evaluation only reads
bundled bytes. Draft labels are authored from source scope before baseline runs.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from .corpus import DATA, canonical, digest, instant

REPOSITORY = "https://github.com/SaltKing0/graph-engine"
SNAPSHOT = "3baa0a3"
# Each tuple is one documented action, its exact source section, and two actual
# later changes. This is a reconstruction, not a historical maintainer assessment.
RECIPES = (
    ("graph", "9bf0050", "docs/graph-retrieval.md", "## Evaluation",
     "Keep graph expansion opt-in; synthetic diagnostic results do not establish production answer quality.",
     ("c3df1f5", ".github/workflows/ci.yml"), ("502b2aa", "graph_engine/__main__.py")),
    ("context", "9b41afc", "docs/guide.md", "### Budgeted context and a complete agent turn",
     "Assemble citation-bearing context by persisted tier within an estimated token budget.",
     ("14a6735", "graph_engine/access.py"), ("d2a6bfd", "graph_engine/retrieval.py")),
    ("documents", "d0b4156", "docs/guide.md", "### Local document import",
     "Import local documents with exact source provenance, bounded chunks and retry receipts.",
     ("402f8ae", "graph_engine/document_import.py"), ("c06661d", "graph_engine/document_import.py")),
    ("cache", "0ca70b5", "docs/retrieval-performance.md", None,
     "Use disposable retrieval caches while validating freshness and preserving current authorization.",
     ("5cea9f4", "graph_engine/brain.py"), ("a95f7be", "graph_engine/retrieval.py")),
    ("temporal", "00eb0d5", "docs/guide.md", "### Known limitations",
     "Filter current records by temporal validity; this does not reconstruct historical Git snapshots.",
     ("eebbdc1", "graph_engine/temporal.py"), ("d2a6bfd", "graph_engine/temporal.py")),
    ("models", "e8946a5", "docs/memory-benchmarks.md", "## Optional local semantic embeddings",
     "Use built-in model modules and disable custom Python code in the offline benchmark loader.",
     ("52ba995", "graph_engine/runtime.py"), ("bc533d1", "graph_engine/runtime.py")),
    ("forget", "c504835", "README.md", "### Agent memory: `ig mcp --write` (opt-in)",
     "Forget by tombstoning and invalidating; keep forgotten memories out of live views.",
     ("b182b7e", "graph_engine/dream.py"), ("e58853c", "graph_engine/dream.py")),
    ("writer", "4df4cb4", "docs/guide.md", "## Local writer coordination",
     "Serialize cooperating local brain writes using a shared writer guard.",
     ("3c819f4", "graph_engine/maintenance.py"), ("7e10ef7", "graph_engine/maintenance.py")),
)


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def section(raw: bytes, heading: str | None) -> tuple[int, int]:
    if heading is None:
        return 0, len(raw)
    token = heading.encode() + b"\n"
    start = raw.index(token)
    level = len(heading) - len(heading.lstrip("#"))
    match = re.search(rb"(?m)^#{1," + str(level).encode() + rb"} ", raw[start + len(token):])
    return start, start + len(token) + match.start() if match else len(raw)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def freeze(root: Path, inputs: dict, labels: dict, contract: bytes, *,
           task_version: str = "decision-review-offline/1") -> None:
    write_json(root / "inputs.json", inputs)
    write_json(root / "labels.json", labels)
    (root / "contract.md").write_bytes(contract)
    files = {str(p.relative_to(root)): digest(p.read_bytes()) for p in sorted(root.rglob("*"))
             if p.is_file() and p.name != "freeze.json"}
    write_json(root / "freeze.json", {"schema": "dm.eval.freeze/1", "files": files,
               "sha256": digest(canonical(files)),
               "gates": {"false_alert_rate_max": 0.05, "miss_rate_max": 0.05,
                         "provenance_correctness_min": 1, "inconclusive_handling_min": 1,
                         "unsupported_conclusions_max": 0, "heldout_positive_min": 20,
                         "heldout_negative_min": 20, "heldout_inconclusive_min": 10,
                         "integrity_pass_min": 1, "median_review_time_reduction_min": 0.2},
               "split_policy": "whole decision families; no event from a family crosses splits",
               "task_version": task_version, "k": 5, "budget": 4000})


def build_real(repository: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    snapshot = git(repository, "rev-parse", SNAPSHOT).decode().strip()
    capture = "2026-10-15"  # capture day, not observation or publication time
    license_raw = git(repository, "show", f"{snapshot}:LICENSE")
    (output / "LICENSE").write_bytes(license_raw)
    inputs: dict = {"schema": "dm.eval.inputs/1", "kind": "real", "version": "project-v1.0.0",
                    "snapshot": snapshot, "sources": [], "decisions": [], "events": [], "dependencies": []}
    labels: dict = {"schema": "dm.eval.labels/1", "pairs": {}, "claims": [],
                    "annotation_protocol": "docs/decision-evaluation.md#annotation-protocol",
                    "author": "Codex source-only draft; not independent human gold",
                    "reviewer": None, "disagreements": None}

    def add_source(sid: str, rev: str, path: str, split: str, heading: str | None = None,
                   patch: bool = False) -> dict:
        revision = git(repository, "rev-parse", rev).decode().strip()
        at = instant(git(repository, "show", "-s", "--format=%cI", revision).decode().strip()).isoformat()
        raw = git(repository, "show", f"{revision}:{path}")
        if git(repository, "show", f"{revision}:LICENSE") != license_raw:
            raise ValueError("source revision needs a separate redistribution notice")
        start, end = section(raw, heading)
        if patch:
            content = git(repository, "diff", "--no-ext-diff", "--no-textconv", "--binary",
                          revision + "^", revision, "--", path)
            if not content:
                raise ValueError(f"empty update {revision}:{path}")
        else:
            content = raw[start:end]
        file = f"sources/{sid}.txt"
        (output / "sources").mkdir(exist_ok=True)
        (output / file).write_bytes(content)
        source = {"id": sid, "file": file, "split": split, "available_at": at,
                  "repository": REPOSITORY, "revision": revision, "path": path,
                  "url": f"{REPOSITORY}/blob/{revision}/{path}",
                  "capture_date": capture, "retrieval": "local Git object; no network",
                  "license": "MIT", "license_file": "LICENSE", "license_sha256": digest(license_raw),
                  "license_revision": revision, "redistribution": "retain MIT notice",
                  "blob_sha256": digest(raw), "blob_oid": git(repository, "rev-parse", f"{revision}:{path}").decode().strip(),
                  "byte_start": None if patch else start, "byte_end": None if patch else end,
                  "format": "git-first-parent-diff" if patch else "exact-utf8-excerpt",
                  "parent_revision": git(repository, "rev-parse", revision + "^").decode().strip() if patch else None,
                  "lineage": f"git:{revision}:{path}", "conditions": {"code_revision": revision,
                  "environment": "unknown", "workload": "repository implementation; not a benchmark run"}}
        inputs["sources"].append(source)
        return source

    for index, (family, rev, path, heading, action, *updates) in enumerate(RECIPES):
        split = "development" if index < 4 else "evaluation"
        source = add_source(f"{family}-basis", rev, path, split, heading)
        did = f"decision-{family}"
        inputs["decisions"].append({"id": did, "family": family, "split": split,
                                    "source_id": source["id"], "action": action,
                                    "status": "documented-action-reconstruction; historical review unavailable"})
        inputs["dependencies"].append({"id": f"dependency-{family}", "source_id": source["id"],
                                        "decision_id": did, "status": "curated", "available_at": source["available_at"],
                                        "provenance": "Codex draft source attribution; independent review pending"})
        labels["claims"].append({"decision_id": did, "claim": action, "supporting_source_ids": [source["id"]],
                                  "opposing_source_ids": [], "irrelevant_source_ids": [],
                                  "context": source["conditions"], "epistemic_status": "unassessed",
                                  "annotation_status": "draft; not independently reviewed"})
        for number, (update_rev, update_path) in enumerate(updates, 1):
            change = add_source(f"{family}-update-{number}", update_rev, update_path, split, patch=True)
            inputs["events"].append({"id": f"event-{family}-{number}", "at": change["available_at"],
                                     "source_id": change["id"], "changed_source_id": source["id"],
                                     "changed_path": update_path, "split": split,
                                     "attachment": "manual draft topic mapping; not an accepted runtime DM link"})
    # Preserve complete original benchmark artifacts/conditions, with original
    # dirty code metadata. They are sources, never independent repeated results.
    for sid, path in (("graph-report", "docs/graph-retrieval-benchmark.json"),
                      ("graph-protocol", "docs/memory-benchmarks.md"),
                      ("graph-fixture", "tools/memory_benchmark/data/graph_expansion_v1.json")):
        source = add_source(sid, "9bf0050", path, "development")
        source["measurement_lineages"] = (["graph-diagnostic-20261012", "original-diagnostic-20261012"]
                                           if sid != "graph-fixture" else [])
        source["limitations"] = "Original synthetic retrieval diagnostic; no new run; no measured answer quality. Prose and report are not independent measurements."
    inputs["events"].sort(key=lambda event: (instant(event["at"]), event["id"]))
    for event in inputs["events"]:
        for decision in inputs["decisions"]:
            basis = next(s for s in inputs["sources"] if s["id"] == decision["source_id"])
            if decision["split"] != event["split"] or instant(basis["available_at"]) > instant(event["at"]):
                continue
            same = event["changed_source_id"] == decision["source_id"]
            labels["pairs"][f"{event['id']}/{decision['id']}"] = {
                "outcome": "pending", "draft_outcome": "inconclusive" if same else "negative",
                "draft_rationale": ("Implementation topic changed; independent review must establish whether this changes the decision basis. "
                                    "A code fix does not demonstrate measured performance or opposition." if same else
                                    "No declared direct dependency; reviewer must check indirect scope before a negative label."),
                "valid_paths": [], "annotation": {"status": "draft", "annotator": "Codex",
                "reviewer": None, "disagreements": None, "reviewed_at": None}}
    freeze(output, inputs, labels, git(repository, "show", f"{snapshot}:docs/decision-memory-v1.md"))


def verify_git(repository: Path, root: Path, inputs: dict) -> None:
    """Optional source inspection requiring full local history, never a fetch."""
    for source in inputs["sources"]:
        rev, path = source["revision"], source["path"]
        raw = git(repository, "show", f"{rev}:{path}")
        if digest(raw) != source["blob_sha256"]:
            raise ValueError("Git blob hash mismatch")
        if source["format"] == "git-first-parent-diff":
            expected = git(repository, "diff", "--no-ext-diff", "--no-textconv", "--binary",
                           source["parent_revision"], rev, "--", path)
        else:
            expected = raw[source["byte_start"]:source["byte_end"]]
        if expected != (root / source["file"]).read_bytes():
            raise ValueError("Git source bytes mismatch")
        if instant(git(repository, "show", "-s", "--format=%cI", rev).decode().strip()) != instant(source["available_at"]):
            raise ValueError("Git timestamp mismatch")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_real(args.repository, args.output)

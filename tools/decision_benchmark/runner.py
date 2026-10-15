"""Reproducible offline baselines, with gold held outside the execution boundary."""
from __future__ import annotations

import json
import math
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from graph_engine.context import build_context
from graph_engine.embedder import HashEmbedder
from tools.memory_benchmark.adapters import GraphAdapter
from tools.memory_benchmark.runner import checkpoint, source_metadata

from .corpus import canonical, digest, load_bundle, visible_inputs
from .scoring import score

TASK = ("Which documented decisions need review after this update to {path}? "
        "Explain exact source evidence, conditions, surviving support and uncertainty. "
        "A candidate requests review; it does not reverse a decision. Return decision IDs, "
        "source IDs and an explicit inconclusive reason when information is missing.")
SYSTEM = "Use only the supplied sources and declared dependencies. Do not execute code or fetch sources."


def dependency_alerts(visible: dict, event: dict, mode: str) -> list[dict]:
    """Simple explicit-dependency baseline: alert on every directly changed basis.

    Deliberately no semantic opposition, comparability or remaining-support analysis.
    Uses source inputs only; never accepts labels or expected decisions.
    """
    return [{"decision_id": link["decision_id"], "path": [event["source_id"], event["changed_source_id"],
             link["id"], link["decision_id"]], "reason": "declared source dependency changed",
             "uncertainty_reason": None}
            for link in visible["dependencies"] if link["status"] == mode
            and link["source_id"] == event["changed_source_id"]]


def prepare(visible: dict, event: dict, path: Path, k: int, budget: int) -> dict:
    documents = [{"id": doc["id"], "text": doc["text"]} for doc in visible["documents"]]
    adapter = GraphAdapter(path, HashEmbedder(), graph=False)
    adapter.ingest(documents)
    task = TASK.format(path=event["changed_path"])
    start = time.perf_counter()
    hits = adapter.retrieve(task, k)
    retrieval_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    # Use the actual current agent-context implementation, including its own
    # per-tier retrieval and documented 200-character recall-body truncation.
    context = build_context(adapter.engine, task, budget, k=k)
    context_ms = (time.perf_counter() - start) * 1000
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content":
                task + "\nDecision inventory:\n" + json.dumps(visible["decisions"], sort_keys=True)
                + "\nUpdate source: " + event["source_id"] + "\n" + context["context"]}]
    return {"hits": [{"id": nid, "score": value} for nid, value in hits],
            "context": context, "prompt": messages, "prompt_sha256": digest(canonical(messages)),
            "latency_ms": {"retrieval": retrieval_ms, "context": context_ms},
            "graph": {"selected": False, "used_for_ranking": False, "relationships_ingested": 0}}


def percentile(values: list[float], fraction: float) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def run(root: Path, output: Path, *, split: str = "development") -> dict:
    inputs, labels, freeze = load_bundle(root)
    repository = Path(__file__).resolve().parents[2]
    metadata = source_metadata(repository)
    paths = sorted([*repository.glob("tools/decision_benchmark/*.py"),
                    *repository.glob("tools/memory_benchmark/*.py"),
                    *repository.glob("graph_engine/**/*.py")])
    manifest = {str(p.relative_to(repository)): digest(p.read_bytes()) for p in paths}
    metadata.update({"code_manifest": manifest, "code_sha256": digest(canonical(manifest)),
                     "captured_at": datetime.now(timezone.utc).isoformat(),
                     "corpus_version": inputs["version"], "kind": inputs["kind"],
                     "freeze_sha256": digest((root / "freeze.json").read_bytes()),
                     "frozen_files": freeze["files"], "configuration": {
                         "k": freeze["k"], "context_budget_estimated_tokens": freeze["budget"],
                         "task_version": freeze["task_version"], "task_template": TASK,
                         "system_prompt": SYSTEM, "graph_expansion": False,
                         "context_assembly": "graph_engine.context.build_context",
                         "source_chunk_chars": 800, "split": split, "embedder": "HashEmbedder",
                         "embedder_dimension": HashEmbedder.DIM, "reranker": None,
                         "provider_calls": False, "answer_model": None,
                         "dependency_profiles": ["curated", "proposed"],
                         "extraction_quality_measured": False}})
    report: dict = {"schema": "dm.eval.report/1", "status": "running", "metadata": metadata,
                    "results": [], "scores": {}, "limitations": [
                        "Real labels await independent annotation; draft labels are not scored.",
                        "Synthetic controls are scored separately and cannot establish product readiness.",
                        "No model, answer-quality, rationale judgment, user time or human effort measurement.",
                        "Curated/proposed dependencies are supplied inputs, not measured extraction quality."]}
    checkpoint(output, report)
    events = [e for e in inputs["events"] if split == "all" or e["split"] == split]
    with tempfile.TemporaryDirectory(prefix="decision-evaluation-") as temp:
        for event in events:
            visible = visible_inputs(inputs, event, root)
            dids = [d["id"] for d in visible["decisions"]]
            start = time.perf_counter()
            row: dict = {"event_id": event["id"], "split": event["split"],
                         "eligible_decisions": dids, "available_source_ids": sorted({d["source_id"] for d in visible["documents"]}),
                         "visible_inputs_sha256": digest(canonical(visible)), "error": None}
            try:
                row["retrieval"] = prepare(visible, event, Path(temp) / event["id"], freeze["k"], freeze["budget"])
                row["baselines"] = {mode: dependency_alerts(visible, event, mode) for mode in ("curated", "proposed")}
            except Exception as exc:
                row["error"] = type(exc).__name__
                row["baselines"] = {"curated": [], "proposed": []}
            row["latency_ms"] = (time.perf_counter() - start) * 1000
            row["reference_integrity"] = {
                "retrieval_ids_resolve": all(hit["id"] in {d["id"] for d in visible["documents"]}
                                             for hit in row.get("retrieval", {}).get("hits", [])),
                "context_ids_resolve": set(row.get("retrieval", {}).get("context", {}).get("nodes", []))
                                       <= {d["id"] for d in visible["documents"]}}
            report["results"].append(row)
            checkpoint(output, report)
    for mode in ("curated", "proposed"):
        report["scores"][mode] = score([{**row, "alerts": row["baselines"][mode]}
                                       for row in report["results"]], labels)
    latencies = [row["latency_ms"] for row in report["results"]]
    report["latency_ms"] = {"p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95), "n": len(latencies)}
    report["cost_effort"] = {"provider_calls": 0, "provider_cost": 0, "currency": None,
                              "wall_ms": sum(latencies), "human_annotation_minutes": None,
                              "human_review_minutes": None}
    report["retrieval_scores"] = None  # No independently reviewed evidence gold yet.
    report["release_readiness"] = {"passed": False, "frozen_thresholds": freeze["gates"],
                                    "reason": "Independent held-out labels, minimum strata and integrity/statement/user studies are incomplete."}
    report["status"] = "completed_with_errors" if any(r["error"] for r in report["results"]) else "complete"
    report["smoke_passed"] = bool(events) and report["status"] == "complete" and all(
        row["retrieval"]["context"]["tokens"] <= freeze["budget"]
        and all(row["reference_integrity"].values()) for row in report["results"])
    checkpoint(output, report)
    return report

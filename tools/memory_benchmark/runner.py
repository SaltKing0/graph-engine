"""Inspectable, checkpointed experiments with separate pipeline timings."""
from __future__ import annotations

import importlib.metadata
import json
import platform
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from graph_engine.context import estimate_tokens

from .adapters import ADAPTERS, create_adapter
from .answers import HTTPAnswers, PROMPT_VERSION, ReplayAnswers, build_prompt, prompt_hash
from .dataset import DEFAULT_DATASET, load_dataset, sha256, source_documents
from .scoring import answer_metrics, retrieval_metrics
from .embeddings import select_embeddings

SMOKE_IDS = ("en-preference", "de-preference", "en-unanswerable", "de-unanswerable")


def assemble_context(hits: list[tuple[str, float]], documents: list[dict[str, str]],
                     budget: int) -> dict[str, Any]:
    """Shared whole-turn packing; ids count only when text actually fits."""
    by_id = {doc["id"]: doc["text"] for doc in documents}
    parts, included, skipped = [], [], []
    for nid, _ in hits:
        part = f"[{nid}] {by_id[nid]}"
        candidate = "\n\n".join([*parts, part])
        if estimate_tokens(candidate) > budget:
            skipped.append(nid)
            continue
        parts.append(part)
        included.append(nid)
    text = "\n\n".join(parts)
    return {"text": text, "node_ids": included, "skipped_node_ids": skipped,
            "estimated_tokens": estimate_tokens(text), "budget": budget,
            "sha256": sha256(text.encode())}


def source_metadata(root: Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    # Pin the actual runner/engine bytes as well as HEAD, including local edits.
    paths = sorted([*root.glob("tools/memory_benchmark/**/*.py"),
                    *root.glob("graph_engine/**/*.py")])
    manifest = {str(path.relative_to(root)): sha256(path.read_bytes()) for path in paths}
    return {"source_commit": git("rev-parse", "HEAD"),
            "source_dirty": bool(git("status", "--porcelain", "--untracked-files=all")),
            "code_sha256": sha256(json.dumps(manifest, sort_keys=True).encode()),
            "code_manifest": manifest,
            "python": platform.python_version(), "platform": platform.platform(),
            "dependencies": {name: importlib.metadata.version(name)
                             for name in ("graph-engine-memory", "numpy", "httpx")}}


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Macro means with explicit denominators; unknown metrics stay null."""
    keys = ("recall_at_k", "mrr", "evidence_coverage", "answer_correct_exact",
            "abstention_correct", "false_memory_detected")
    summaries: dict[str, Any] = {}
    for adapter in sorted({row["adapter"] for row in results}):
        rows = [row for row in results if row["adapter"] == adapter]
        summary: dict[str, Any] = {"questions": len(rows)}
        for key in keys:
            values = [row["metrics"][key] for row in rows if row["metrics"][key] is not None]
            summary[key] = {"mean": sum(values) / len(values) if values else None,
                            "n": len(values)}
        summary["errors"] = sum(row.get("error") is not None for row in rows)
        summary["latency_ms_mean"] = {
            stage: sum(row["latency_ms"][stage] for row in rows) / len(rows)
            for stage in ("retrieval", "context", "generation", "scoring")}
        summary["estimated_tokens"] = {
            key: sum(row["tokens"][key] for row in rows)
            for key in ("context", "prompt", "completion")}
        summary["actual_tokens"] = {}
        for key in ("prompt_tokens", "completion_tokens"):
            values = [row["tokens"]["actual"].get(key) for row in rows
                      if row["tokens"]["actual"] is not None]
            values = [value for value in values if value is not None]
            summary["actual_tokens"][key] = {"total": sum(values) if values else None,
                                             "n": len(values)}
        summaries[adapter] = summary
    return summaries


def checkpoint(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def run(*, dataset_path: Path = DEFAULT_DATASET, output: Path,
        adapters: tuple[str, ...] = ADAPTERS, k: int = 5, budget: int = 256,
        seed: int = 0, smoke: bool = False, question_ids: tuple[str, ...] = (),
        predictions: Path | None = None, answerer: HTTPAnswers | None = None,
        check: bool = False, embedding_model_path: Path | None = None) -> dict[str, Any]:
    if k < 1 or budget < 1 or not adapters or len(set(adapters)) != len(adapters):
        raise ValueError("positive k/budget and unique nonempty adapters are required")
    if any(adapter not in ADAPTERS for adapter in adapters):
        raise ValueError("unknown adapter")
    if predictions and answerer:
        raise ValueError("select either replay or HTTP generation")
    if check and (not smoke or predictions or answerer or embedding_model_path):
        raise ValueError("--check is an offline smoke retrieval/evidence gate only")
    dataset, dataset_hash = load_dataset(dataset_path)
    selected = SMOKE_IDS if smoke else question_ids
    questions = [q for q in dataset["questions"] if not selected or q["id"] in selected]
    if selected and set(selected) != {q["id"] for q in questions}:
        raise ValueError("unknown requested question id (smoke requires the custom v1 dataset)")
    if not questions:
        raise ValueError("no questions selected")
    generator = answerer or (ReplayAnswers(predictions, dataset_hash) if predictions else None)
    embedder, embedding_metadata = select_embeddings(embedding_model_path, seed)
    root = Path(__file__).resolve().parents[2]
    report: dict[str, Any] = {
        "report_schema_version": 1, "status": "prepared",
        "metadata": {**source_metadata(root), "dataset_version": dataset["version"],
                     "dataset_sha256": dataset_hash,
                     "dataset_provenance": dataset.get("provenance"),
                     "embedder": embedding_metadata,
                     "reranker": None, "answer_model": generator.metadata if generator else None,
                     "configuration": {"adapters": list(adapters), "k": k,
                                       "context_budget_estimated_tokens": budget, "seed": seed,
                                       "questions": [q["id"] for q in questions],
                                       "ingestion": "whole dated turns, no extraction/dedup/edges",
                                       "graph_used_for_ranking": False,
                                       "context_policy": "ranked-whole-turn-packing-v1",
                                       "prompt_version": PROMPT_VERSION,
                                       "scoring": "normalized-exact-and-proxy-v1"},
                     "token_estimator": "graph_engine.context.estimate_tokens; not tokenizer usage"},
        "ingestion": [], "results": [], "summary": {},
    }
    planned: list[tuple[dict[str, Any], dict[str, Any]]] = []
    by_id = {c["id"]: c for c in dataset["conversations"]}
    with tempfile.TemporaryDirectory(prefix="graph-memory-benchmark-") as temporary:
        for kind in adapters:
            for cid in dict.fromkeys(q["conversation_id"] for q in questions):
                documents = source_documents(by_id[cid])
                start = time.perf_counter()
                adapter = create_adapter(kind, Path(temporary) / kind / cid, embedder)
                adapter.ingest(documents)
                report["ingestion"].append({"adapter": kind, "conversation_id": cid,
                                            "documents": len(documents),
                                            "latency_ms": (time.perf_counter() - start) * 1000})
                for question in (q for q in questions if q["conversation_id"] == cid):
                    start = time.perf_counter()
                    hits = adapter.retrieve(question["question"], k)
                    retrieval_ms = (time.perf_counter() - start) * 1000
                    start = time.perf_counter()
                    context = assemble_context(hits, documents, budget)
                    context_ms = (time.perf_counter() - start) * 1000
                    messages = build_prompt(question["question"], context["text"],
                                            question.get("question_date"))
                    row = {"adapter": kind, "question_id": question["id"],
                           "conversation_id": cid, "language": question["language"],
                           "category": question["category"], "question": question["question"],
                           "reference_answers": question["answers"],
                           "forbidden_answers": question.get("forbidden_answers", []),
                           "expected_evidence_ids": question["evidence_ids"],
                           "unanswerable": question["unanswerable"],
                           "retrieved": [{"node_id": nid, "score": score, "rank": rank,
                                          "text": next(doc["text"] for doc in documents if doc["id"] == nid)}
                                         for rank, (nid, score) in enumerate(hits, 1)],
                           "context": context, "prompt": messages,
                           "prompt_sha256": prompt_hash(messages), "answer": None,
                           "tokens": {"context": context["estimated_tokens"],
                                      "prompt": estimate_tokens(json.dumps(messages, ensure_ascii=False)),
                                      "completion": 0, "actual": None},
                           "latency_ms": {"retrieval": retrieval_ms, "context": context_ms,
                                          "generation": 0.0, "scoring": 0.0}}
                    planned.append((question, row))
    # Verify the entire call/token plan and replay bindings before any paid call.
    if answerer:
        answerer.preflight([row["tokens"]["prompt"] for _, row in planned])
    if isinstance(generator, ReplayAnswers):
        for _, row in planned:
            generator.generate(row["adapter"], row["question_id"], row["prompt"])
    report["status"] = "running"
    checkpoint(output, report)
    for question, row in planned:
        start = time.perf_counter()
        if generator:
            try:
                row["answer"] = generator.generate(row["adapter"], row["question_id"], row["prompt"])
                if row["answer"].get("error"):
                    row["error"] = row["answer"]["error"]
            except Exception as exc:
                # Preserve completed results, never persist credentials or response bodies.
                row["error"] = type(exc).__name__
            row["latency_ms"]["generation"] = (time.perf_counter() - start) * 1000
        answer = row["answer"]
        if answer:
            row["tokens"]["completion"] = estimate_tokens(answer.get("raw_content", answer.get("text", "")))
            row["tokens"]["actual"] = answer.get("usage")
        start = time.perf_counter()
        row["metrics"] = {
            **retrieval_metrics(question["evidence_ids"],
                                [hit["node_id"] for hit in row["retrieved"]], row["context"]["node_ids"]),
            **answer_metrics(question, None if row.get("error") else answer, row["context"]["node_ids"]),
        }
        row["latency_ms"]["scoring"] = (time.perf_counter() - start) * 1000
        report["results"].append(row)
        report["summary"] = summarize(report["results"])
        checkpoint(output, report)
    errors = any(row.get("error") for row in report["results"])
    report["status"] = "completed_with_errors" if errors else "complete"
    if check:
        report["smoke_passed"] = all(
            row["metrics"]["recall_at_k"] == 1 and row["metrics"]["evidence_coverage"] == 1
            for row in report["results"] if not row["unanswerable"])
    checkpoint(output, report)
    return report

"""Opt-in local retrieval/ingest measurements; no large timing CI gate."""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import resource
import statistics
import tempfile
import time
import tracemalloc
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Callable

from graph_engine.brain import Brain, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.retrieval import retrieve
from tools.memory_benchmark.dataset import DEFAULT_DATASET, load_dataset
from tools.memory_benchmark.embeddings import select_embeddings
from tools.memory_benchmark.adapters import GraphAdapter
from tools.memory_benchmark.dataset import source_documents


def distribution(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {"n": len(values), "p50_ms": statistics.median(values),
            "p95_ms": ordered[max(0, math.ceil(len(ordered) * .95) - 1)]}


def clear(engine: BrainEngine) -> None:
    engine.clear_search_cache()
    Brain._VECTOR_MEMO.clear()


def search(engine: BrainEngine, query: str, *, cached: bool) -> tuple[list, float, dict]:
    engine.search_cache_enabled = cached
    engine.retrieval_timings = {"reranking": 0.0}
    start = time.perf_counter()
    hits = retrieve(engine, query, persist=False)
    return hits, (time.perf_counter() - start) * 1000, dict(engine.retrieval_timings)


def quality_comparison(root: Path, model_path: Path | None, seed: int) -> dict[str, Any]:
    dataset, digest = load_dataset(DEFAULT_DATASET)
    embedder, _ = select_embeddings(model_path, seed)
    mismatches = []
    count = 0
    for conversation in dataset["conversations"]:
        adapter = GraphAdapter(root / conversation["id"], embedder)
        adapter.ingest(source_documents(conversation), conversation.get("relationships", []))
        for question in dataset["questions"]:
            if question["conversation_id"] != conversation["id"]:
                continue
            engine = adapter.engine
            oracle, _, _ = search(engine, question["question"], cached=False)
            clear(engine)
            cold, _, _ = search(engine, question["question"], cached=True)
            warm, _, _ = search(engine, question["question"], cached=True)
            count += 1
            if oracle != cold or oracle != warm:
                mismatches.append(question["id"])
    return {"dataset_version": dataset["version"], "dataset_sha256": digest,
            "questions": count, "mismatches": mismatches,
            "comparison": "exact ordered (ID, score) pairs; same embedding and reranking settings"}


@contextmanager
def ingest_costs(engine: BrainEngine, timings: dict[str, float]) -> Iterator[None]:
    """Inclusive stage timings: rebuild_index also includes its nested reads."""
    targets = {name: engine.brain for name in
               ("pull", "commit_and_push", "read_nodes", "read_vectors", "rebuild_index")}
    targets.update({name: engine.embedder for name in ("embed", "embed_batch")})
    originals = {name: getattr(target, name) for name, target in targets.items()}
    def wrapper(name: str) -> Callable:
        def call(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return originals[name](*args, **kwargs)
            finally:
                timings[name] = timings.get(name, 0.0) + (time.perf_counter() - start) * 1000
        return call
    try:
        for name in originals:
            setattr(targets[name], name, wrapper(name))
        yield
    finally:
        for name, method in originals.items():
            setattr(targets[name], name, method)


def measure(size: int, samples: int, root: Path, *, model_path: Path | None = None,
            mode: str = "local", seed: int = 0) -> dict[str, Any]:
    start = time.perf_counter()
    embedder, model = select_embeddings(model_path, seed)
    # LocalEmbeddings loads eagerly; HashEmbedder has no model to load.
    model_load_ms = (time.perf_counter() - start) * 1000
    brain = Brain(str(root), mode=mode)
    brain.init()
    texts = [f"Memory record {i}: project topic{i % 97} user preference language{i % 7} "
             f"meeting decision evidence reference archive {i} weekly progress and planning notes."
             for i in range(size)]
    start = time.perf_counter()
    for i, text in enumerate(texts):
        brain.write_node(Node(text, id=f"record-{i:07}", status="active"))
    from graph_engine.vector_cache import model_identity, normalize_text
    brain.cache_vectors(dict(zip([f"record-{i:07}" for i in range(size)],
                                 embedder.embed_batch([normalize_text(t) for t in texts]))),
                        embedder_key=model_identity(embedder))
    brain.commit_and_push("Seed performance fixture", push=False)
    setup_ms = (time.perf_counter() - start) * 1000
    engine = BrainEngine(brain, embedder, dedupe_threshold=1.1, reranker=False)
    engine.reranker = None
    rows: dict[str, list[float]] = {name: [] for name in ("uncached", "cold", "warm")}
    stages: dict[str, dict[str, list[float]]] = {name: {} for name in rows}
    mismatches = []
    for sample in range(samples):
        query = f"project topic{sample % 97} preference language{sample % 7}"
        clear(engine)
        oracle, ms, timings = search(engine, query, cached=False)
        rows["uncached"].append(ms)
        for stage, value in timings.items():
            stages["uncached"].setdefault(stage, []).append(value)
        clear(engine)
        for name in ("cold", "warm"):
            hits, ms, timings = search(engine, query, cached=True)
            rows[name].append(ms)
            for stage, value in timings.items():
                stages[name].setdefault(stage, []).append(value)
            if hits != oracle:
                mismatches.append({"sample": sample, "path": name})
    # Memory probe separate from latency samples: tracemalloc changes timings.
    clear(engine)
    tracemalloc.start()
    search(engine, "project topic1", cached=True)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    ingest: dict[str, list[float]] = {"cold": [], "warm": []}
    sync: dict[str, list[float]] = {}
    for sample in range(samples):
        clear(engine)
        for name in ("cold", "warm"):
            timings = {}
            start = time.perf_counter()
            with ingest_costs(engine, timings):
                # Explicit duplicate allowance guarantees a new observation.
                engine.ingest(f"Benchmark observation {sample} {name}: topic{sample % 97} "
                              f"new preference memory at size {size}.", allow_duplicates=True)
            ingest[name].append((time.perf_counter() - start) * 1000)
            for stage, value in timings.items():
                sync.setdefault(name + ":" + stage, []).append(value)
    return {"nodes": size, "ingest_added_nodes": samples * 2, "fixture_setup_ms": setup_ms, "model_load_ms": model_load_ms,
            "embedder": model, "search": {name: distribution(values) for name, values in rows.items()},
            "search_stages": {name: {stage: distribution(values) for stage, values in parts.items()}
                              for name, parts in stages.items()},
            "ingest": {name: distribution(values) for name, values in ingest.items() if values},
            "ingest_stages_inclusive": {name: distribution(values) for name, values in sync.items()},
            "memory": {"python_and_numpy_traced_retained_bytes": current,
                       "python_and_numpy_traced_peak_bytes": peak,
                       "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss *
                           (1 if platform.system() == "Darwin" else 1024)},
            "correctness_mismatches": mismatches}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000])
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--mode", choices=["local", "git"], default="local")
    parser.add_argument("--embedding-model-path", type=Path)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 2 or any(size < 1 for size in args.sizes):
        parser.error("positive sizes and at least two samples are required")
    root = Path(__file__).resolve().parents[1]
    from tools.memory_benchmark.runner import source_metadata
    source = source_metadata(root)
    # source_metadata pins quality-runner and engine; also pin this harness.
    from tools.memory_benchmark.dataset import sha256
    source["performance_harness_sha256"] = sha256(Path(__file__).read_bytes())
    report = {"schema_version": 1, "environment": {
        **source,
        "cpu_count": os.cpu_count(), "processor": platform.processor(), "machine": platform.machine(), "mode": args.mode, "seed": args.seed,
        "numpy_version": __import__("numpy").__version__,
        "blas_threads": {key: os.environ.get(key) for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")},
        "reranker": None, "remote": None,
        "cold_definition": "application indexes/memo cleared; OS page cache not flushed",
        "warm_definition": "immediate second query or ingest after cold operation",
        "fixture": "synthetic-v1; deterministic topic/language terms, 19-word records, 64-dimensional hash default",
        "ingestion": "normal ingest, allow_duplicates=True; cold/warm pairs add two nodes, source corpus grows",
        "model_cost": "explicit local model loaded separately; document embedding occurs during fixture setup",
        "git_cost": "local mode calls are no-ops; git mode includes local commits, no remote/network",
        "reranking_cost": "disabled (zero); configured production rerankers require their own measurement",
        "rss_definition": "process high-water mark, cumulative across sizes",}, "results": []}
    with tempfile.TemporaryDirectory(prefix="ig-retrieval-benchmark-") as temporary:
        path = Path(temporary)
        for size in args.sizes:
            report["results"].append(measure(size, args.samples, path / str(size),
                                            model_path=args.embedding_model_path,
                                            mode=args.mode, seed=args.seed))
        report["quality"] = quality_comparison(path / "quality", args.embedding_model_path, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    if report["quality"]["mismatches"] or any(row["correctness_mismatches"] for row in report["results"]):
        raise SystemExit("cached/uncached correctness mismatch")


if __name__ == "__main__":
    main()

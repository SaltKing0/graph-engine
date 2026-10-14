"""Offline experiment checks, separate from engine state/golden-set oracles."""
from __future__ import annotations

import copy
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.context import estimate_tokens
from tools.memory_benchmark.answers import HTTPAnswers, ReplayAnswers, build_prompt
from tools.memory_benchmark.dataset import DEFAULT_DATASET, import_longmemeval, load_dataset, validate_dataset
from tools.memory_benchmark.runner import assemble_context, run
from tools.memory_benchmark.scoring import answer_metrics, retrieval_metrics, validate_answer


def test_checkpoint_is_utf8_with_ascii_locale(tmp_path):
    script = r'''
import json
import sys
from pathlib import Path
from tools.memory_benchmark.runner import checkpoint

output = Path(sys.argv[1])
report = {"text": "gr\u00fcner Tee \U0001f375"}
checkpoint(output, report)
assert json.loads(output.read_bytes()) == report
'''
    env = {**os.environ, "LC_ALL": "C", "LANG": "C",
           "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path / "report.json")],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_smoke_is_offline_and_ignores_ambient_models(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline experiment attempted network or model factory")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr("graph_engine.brain_engine.get_embedder", forbidden)
    monkeypatch.setattr("graph_engine.brain_engine.get_reranker", forbidden)
    monkeypatch.setenv("IDEAGRAPH_RERANKER", "st")
    report = run(output=tmp_path / "report.json", smoke=True, check=True)
    assert report["status"] == "complete" and report["smoke_passed"]
    assert len(report["results"]) == 12
    assert {row["language"] for row in report["results"]} == {"de", "en"}
    assert len(report["ingestion"]) == 6
    for row in report["results"]:
        assert row["context"]["estimated_tokens"] <= 256
        assert row["metrics"]["answer_correct_exact"] is None
        assert row["metrics"]["false_memory_detected"] is None
        assert row["tokens"]["actual"] is None
        if row["unanswerable"]:
            assert row["metrics"]["recall_at_k"] is None
        else:
            assert set(row["expected_evidence_ids"]) <= set(row["context"]["node_ids"])
    metadata = report["metadata"]
    assert len(metadata["source_commit"]) == 40
    assert len(metadata["dataset_sha256"]) == 64
    assert metadata["reranker"] is None
    assert metadata["configuration"]["graph_used_for_ranking"] is False


def test_retrieval_reproducible_and_gold_does_not_leak(tmp_path):
    first = run(output=tmp_path / "one.json")
    dataset, _ = load_dataset(DEFAULT_DATASET)
    mutated = copy.deepcopy(dataset)
    for question in mutated["questions"]:
        if not question["unanswerable"]:
            question["answers"] = ["SECRET_GOLD_CANARY"]
            question["evidence_ids"] = [mutated["conversations"][0 if question["language"] == "en" else 1]["turns"][-1]["id"]]
    path = tmp_path / "mutated.json"
    path.write_text(json.dumps(mutated))
    second = run(dataset_path=path, output=tmp_path / "two.json")
    assert len(first["results"]) == 36
    for left, right in zip(first["results"], second["results"]):
        assert left["retrieved"] == right["retrieved"]
        assert left["context"] == right["context"]
        assert left["prompt_sha256"] == right["prompt_sha256"]
        assert "SECRET_GOLD_CANARY" not in json.dumps(right["prompt"])


def test_context_budget_counts_only_included_evidence():
    documents = [{"id": "large", "text": "x" * 100}, {"id": "small", "text": "short"}]
    context = assemble_context([("large", 1), ("small", .5)], documents, budget=5)
    assert context["node_ids"] == ["small"]
    assert context["skipped_node_ids"] == ["large"]
    assert estimate_tokens(context["text"]) <= 5
    metrics = retrieval_metrics(["large", "small"], ["large", "small"], context["node_ids"])
    assert metrics == {"recall_at_k": 1, "mrr": 1, "evidence_coverage": .5}
    assert retrieval_metrics(["small"], ["large", "small"], ["small"])["mrr"] == .5
    assert all(value is None for value in retrieval_metrics([], ["large"], ["large"]).values())


def test_answer_scoring_distinguishes_wrong_abstention_and_false_memory():
    dataset, _ = load_dataset(DEFAULT_DATASET)
    temporal = next(q for q in dataset["questions"] if q["id"] == "en-temporal")
    unsupported = next(q for q in dataset["questions"] if q["id"] == "en-unanswerable")
    answer = {"text": "BERLIN!", "abstained": False, "citations": ["en-t03"]}
    assert answer_metrics(temporal, answer, ["en-t03"])["answer_correct_exact"]
    answer["text"] = "Hamburg"
    assert answer_metrics(temporal, answer, ["en-t03"])["false_memory_detected"]
    answer["text"] = "A long paraphrase that needs human review"
    metrics = answer_metrics(temporal, answer, ["en-t03"])
    assert not metrics["answer_correct_exact"] and not metrics["false_memory_detected"]
    answer["citations"] = ["imaginary"]
    assert answer_metrics(temporal, answer, ["en-t03"])["invalid_citations"] == ["imaginary"]
    abstention = {"text": "", "abstained": True, "citations": []}
    assert answer_metrics(unsupported, abstention, [])["answer_correct_exact"]
    assert not answer_metrics(temporal, abstention, [])["abstention_correct"]
    assert answer_metrics(unsupported, answer, [])["false_memory_detected"]
    with pytest.raises(ValueError):
        validate_answer({"text": "fabricated fact", "abstained": True, "citations": []})


def test_replay_binds_each_prediction_to_dataset_and_prompt(tmp_path):
    prepared = run(output=tmp_path / "prepared.json", adapters=("graph-engine",), smoke=True)
    records = [{"adapter": row["adapter"], "question_id": row["question_id"],
                "prompt_sha256": row["prompt_sha256"], "text": "", "abstained": True,
                "citations": [], "usage": {"prompt_tokens": 12, "completion_tokens": 3}}
               for row in prepared["results"]]
    payload = {"dataset_sha256": prepared["metadata"]["dataset_sha256"],
               "model": "test-answerer-revision-1", "predictions": records}
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps(payload))
    replay = run(output=tmp_path / "replay.json", adapters=("graph-engine",), smoke=True,
                 predictions=path)
    summary = replay["summary"]["graph-engine"]
    assert summary["answer_correct_exact"] == {"mean": .5, "n": 4}
    assert summary["actual_tokens"]["prompt_tokens"] == {"total": 48, "n": 4}
    # A changed context cannot accidentally reuse answers from another budget.
    with pytest.raises(ValueError, match="prompt hash mismatch"):
        run(output=tmp_path / "different.json", adapters=("graph-engine",), smoke=True,
            budget=1, predictions=path)
    payload["dataset_sha256"] = "wrong"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="matching dataset"):
        ReplayAnswers(path, prepared["metadata"]["dataset_sha256"])


def test_longmemeval_import_preserves_history_and_turn_evidence(tmp_path):
    sample = {"question_id": "q1", "question_type": "knowledge-update", "question": "Where now?",
              "answer": "Berlin", "question_date": "2026-02-12",
              "haystack_session_ids": ["s1", "s2"], "haystack_dates": ["January", "February"],
              "haystack_sessions": [[{"role": "user", "content": "Hamburg"}],
                                    [{"role": "user", "content": "Berlin", "has_answer": True},
                                     {"role": "assistant", "content": "Noted", "has_answer": False}]],
              "answer_session_ids": ["s2"]}
    missing = copy.deepcopy(sample)
    missing["question_id"] = "q2"
    for session in missing["haystack_sessions"]:
        for turn in session:
            turn.pop("has_answer", None)
    abstention = copy.deepcopy(sample)
    abstention["question_id"] = "q3_abs"
    path = tmp_path / "upstream.json"
    path.write_text(json.dumps([sample, missing, abstention]))
    imported = import_longmemeval(path, "upstream-pinned-revision")
    assert imported["questions"][0]["evidence_ids"] == ["lme-0-s1-t0"]
    assert imported["questions"][1]["evidence_ids"] is None
    assert imported["questions"][2]["unanswerable"]
    assert imported["questions"][2]["evidence_ids"] == []
    assert len(imported["conversations"][0]["turns"]) == 3
    assert imported["questions"][0]["upstream_answer_session_ids"] == ["s2"]
    local = tmp_path / "imported.json"
    local.write_text(json.dumps(imported))
    report = run(dataset_path=local, adapters=("lexical",), output=tmp_path / "report.json")
    assert report["results"][1]["metrics"]["recall_at_k"] is None
    assert report["metadata"]["dataset_provenance"]["source_sha256"]


@pytest.mark.parametrize("mutation", ["duplicate", "unknown_evidence", "unsafe_id", "false_unanswerable"])
def test_bad_dataset_rejected(mutation):
    dataset, _ = load_dataset(DEFAULT_DATASET)
    if mutation == "duplicate":
        dataset["questions"].append(dataset["questions"][0])
    elif mutation == "unknown_evidence":
        dataset["questions"][0]["evidence_ids"] = ["absent"]
    elif mutation == "unsafe_id":
        dataset["conversations"][0]["id"] = "../../escape"
    else:
        dataset["questions"][0]["unanswerable"] = True
    with pytest.raises(ValueError):
        validate_dataset(dataset)


def test_real_call_limits_refuse_before_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("preflight must precede network")
    monkeypatch.setattr(httpx.Client, "post", forbidden)
    answerer = HTTPAnswers("http://localhost:8000/v1/chat/completions", "pinned-v1", 0, 128, 1, 8192, 1)
    with pytest.raises(ValueError, match="max-requests"):
        run(output=tmp_path / "refused.json", smoke=True, answerer=answerer)
    assert answerer.calls == 0
    answerer.max_requests = 12
    answerer.max_total_estimated_tokens = 1
    with pytest.raises(ValueError, match="max-total-estimated-tokens"):
        run(output=tmp_path / "refused.json", smoke=True, answerer=answerer)
    assert answerer.calls == 0


def test_http_answers_record_raw_output_usage_and_model_without_gold(tmp_path, monkeypatch):
    bodies = []
    monkeypatch.setenv("MEMORY_BENCHMARK_API_KEY", "secret-do-not-log")
    def post(client, url, *, headers, json):
        bodies.append(json)
        assert headers["Authorization"] == "Bearer secret-do-not-log"
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "model": "actual-snapshot", "system_fingerprint": "fp-test",
            "choices": [{"finish_reason": "stop", "message": {"content":
                '{"text":"green tea without sugar","abstained":false,"citations":["en-t00"]}'}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 20}})
    monkeypatch.setattr(httpx.Client, "post", post)
    answerer = HTTPAnswers("http://localhost:8000/v1/chat/completions", "pinned-v1", 3, 128, 1, 8192, 1)
    output = tmp_path / "http.json"
    report = run(output=output, adapters=("lexical",), question_ids=("en-preference",), answerer=answerer)
    row = report["results"][0]
    assert row["answer"]["returned_model"] == "actual-snapshot"
    assert row["answer"]["raw_content"]
    assert row["metrics"]["answer_correct_exact"]
    assert row["tokens"]["actual"] == {"prompt_tokens": 40, "completion_tokens": 20}
    assert bodies[0]["seed"] == 3 and bodies[0]["max_tokens"] == 128
    assert "reference_answers" not in str(bodies[0])
    assert "secret-do-not-log" not in output.read_text()
    with pytest.raises(ValueError, match="request limit"):
        answerer.generate("lexical", "other", build_prompt("Question", ""))


def test_model_errors_are_checkpointed_with_unknown_answer_scores(tmp_path, monkeypatch):
    def post(client, url, **kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "model": "pinned", "choices": [{"finish_reason": "length", "message": {"content": "{broken"}}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 128}})
    monkeypatch.setattr(httpx.Client, "post", post)
    answerer = HTTPAnswers("http://localhost:8000/v1/chat/completions", "pinned", 0, 128, 1, 8192, 1)
    output = tmp_path / "error.json"
    report = run(output=output, adapters=("lexical",), question_ids=("en-preference",), answerer=answerer)
    assert report["status"] == "completed_with_errors"
    assert report["results"][0]["answer"]["raw_content"] == "{broken"
    assert report["results"][0]["metrics"]["answer_correct_exact"] is None
    assert report["summary"]["lexical"]["actual_tokens"]["completion_tokens"]["total"] == 128
    assert json.loads(output.read_text())["status"] == "completed_with_errors"


def test_cli_requires_explicit_model_opt_in(tmp_path):
    result = subprocess.run([sys.executable, "-m", "tools.memory_benchmark", "--output",
                             str(tmp_path / "never.json"), "--model", "pinned-v1"],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "--allow-model-calls" in result.stderr
    assert not (tmp_path / "never.json").exists()


def test_local_semantic_model_requires_existing_path_and_is_not_allowed_in_gate(tmp_path):
    from tools.memory_benchmark.embeddings import select_embeddings
    with pytest.raises(ValueError, match="existing SentenceTransformer"):
        select_embeddings(tmp_path / "no-download", 0)
    with pytest.raises(ValueError, match="offline smoke"):
        run(output=tmp_path / "never.json", smoke=True, check=True, embedding_model_path=tmp_path)


def test_local_model_pins_bytes_and_blocks_downloads(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import numpy as np
    from graph_engine.embedder import HashEmbedder
    from tools.memory_benchmark.embeddings import select_embeddings

    model_path = tmp_path / "model"
    model_path.mkdir()
    (model_path / "modules.json").write_text("[]")
    (model_path / "weights.bin").write_bytes(b"revision-one")
    options = []
    class Model:
        def __init__(self, path, **kwargs):
            options.append(kwargs)
        def get_embedding_dimension(self):
            return 64
        def encode(self, texts, **kwargs):
            assert kwargs["prompt"] == ""
            embedder = HashEmbedder()
            return np.asarray(embedder.embed(texts) if isinstance(texts, str) else embedder.embed_batch(texts))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(manual_seed=lambda seed: None, __version__="test"))
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=Model))
    real_version = __import__("importlib.metadata", fromlist=["version"]).version
    monkeypatch.setattr("tools.memory_benchmark.embeddings.importlib.metadata.version",
                        lambda name: "test" if name == "sentence-transformers" else real_version(name))
    embedder, metadata = select_embeddings(model_path, 0)
    assert options[0]["local_files_only"] is True and options[0]["trust_remote_code"] is False
    assert len(embedder.embed("Ada")) == 64
    (model_path / "weights.bin").write_bytes(b"revision-two")
    _, changed = select_embeddings(model_path, 0)
    assert metadata["model_files_sha256"] != changed["model_files_sha256"]
    report = run(output=tmp_path / "semantic.json", embedding_model_path=model_path, smoke=True)
    assert report["metadata"]["embedder"]["semantic_model"]
    assert {row["adapter"] for row in report["results"]} == {"graph-engine", "lexical", "vector"}


def test_graph_adapter_compares_identical_sources_and_records_paths(tmp_path):
    dataset_path = DEFAULT_DATASET.with_name('graph_expansion_v1.json')
    report = run(dataset_path=dataset_path, output=tmp_path / 'graph.json',
                 adapters=('graph-engine', 'graph-engine-expanded', 'lexical'))
    assert report['summary']['graph-engine']['recall_at_k']['mean'] == 0
    assert report['summary']['lexical']['recall_at_k']['mean'] == 0
    assert report['summary']['graph-engine-expanded']['recall_at_k']['mean'] == 1
    assert report['metadata']['configuration']['graph_expansion_enabled']
    assert report['metadata']['configuration']['graph_used_for_ranking']
    for row in report['results']:
        assert row['latency_ms']['retrieval'] >= 0
        assert row['metrics']['answer_correct_exact'] is None
        if row['adapter'] == 'graph-engine-expanded' and not row['unanswerable']:
            assert row['graph']['graph_used_for_ranking']
            assert row['graph']['options']['hops'] == 2
            assert any(path['hops'] == 2 for paths in row['graph']['evidence'].values() for path in paths)


def test_graph_benchmark_gold_annotations_do_not_affect_ranking(tmp_path):
    dataset_path = DEFAULT_DATASET.with_name('graph_expansion_v1.json')
    dataset, _ = load_dataset(dataset_path)
    first = run(dataset_path=dataset_path, output=tmp_path / 'one.json',
                 adapters=('graph-engine-expanded',))
    for question in dataset['questions']:
        if not question['unanswerable']:
            question['answers'] = ['gold-only-canary']
            question['evidence_ids'] = [f"{question['language']}-4"]
    changed = tmp_path / 'changed.json'; changed.write_text(json.dumps(dataset))
    second = run(dataset_path=changed, output=tmp_path / 'two.json',
                 adapters=('graph-engine-expanded',))
    for left, right in zip(first['results'], second['results']):
        assert left['retrieved'] == right['retrieved']
        assert left['prompt_sha256'] == right['prompt_sha256']


def test_source_relationships_reject_unknown_evidence(tmp_path):
    dataset, _ = load_dataset(DEFAULT_DATASET.with_name('graph_expansion_v1.json'))
    dataset['conversations'][0]['relationships'][0]['evidence_ids'] = ['missing']
    with pytest.raises(ValueError, match='relationship evidence'):
        validate_dataset(dataset)

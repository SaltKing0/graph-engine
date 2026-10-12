"""Opt-in capture/extraction contract across engine, CLI, HTTP and MCP."""
import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from graph_engine import runtime
from graph_engine.agent_memory import forget, remember
from graph_engine.brain import Brain, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder
from graph_engine.server import app


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.delenv("IG_ACCESS_POLICY", raising=False)
    monkeypatch.delenv("IG_GRAPH_HOME", raising=False)
    monkeypatch.delenv("IG_ENTITIES_LLM_CMD", raising=False)
    monkeypatch.setenv("IG_BRAIN_PATH", str(tmp_path / "brain"))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    runtime.reset_engine_cache()
    return runtime.make_engine()


def snapshot(brain):
    return {p.relative_to(brain.path): p.read_bytes()
            for p in brain.path.rglob("*") if p.is_file() and ".git" not in p.parts}


def test_default_capture_and_remember_are_compatible(engine):
    node, edges, duplicate, extraction = engine.capture(" Alice works at Acme. ")
    assert not duplicate and extraction is None
    assert node.text == "Alice works at Acme." and node.capture is None
    result = remember(engine, node.text)
    assert result["duplicate"] and "extraction" not in result
    assert len(engine.brain.read_nodes()) == 1
    assert not any(e.kind == "fact" for e in engine.brain.read_edges())


@pytest.mark.parametrize("allow_duplicates", [False, True])
def test_exact_input_and_idempotent_retry(engine, allow_duplicates):
    text = " \nAlice works at Acme.\r\n\t\u2028"
    node, _, duplicate, first = engine.capture(text, extraction="rules",
                                              allow_duplicates=allow_duplicates)
    assert not duplicate and first["status"] == "complete"
    assert first["created_entities"] == 2 and first["created_facts"] == 1
    assert first["pending_facts"] == 1 and first["source_node_id"] == node.id
    assert engine.brain.read_node(node.id).capture["input"] == text
    before = snapshot(engine.brain)
    repeated, _, _, second = engine.capture(text, extraction="rules",
                                           allow_duplicates=allow_duplicates)
    assert repeated.id == node.id and second["retried"]
    assert second["created_entities"] == second["created_facts"] == 0
    assert second["reused_entities"] == 2 and second["reused_facts"] == 1
    assert snapshot(engine.brain) == before


class SameVector(HashEmbedder):
    def embed(self, text):
        return [1., 0.]

    def embed_batch(self, texts):
        return [self.embed(t) for t in texts]


def test_cosine_dedup_keeps_new_claim_as_separate_evidence(engine):
    engine.embedder = SameVector()
    old, _, _ = engine.ingest("Alice works at Acme.")
    text = "\nAlice works for Other.\n"
    node, _, duplicate, result = engine.capture(text, extraction="rules")
    assert duplicate and node.id == old.id
    assert result["source_node_id"] != old.id
    evidence = engine.brain.read_node(result["source_node_id"])
    assert evidence.capture["input"] == text
    fact = next(e for e in engine.brain.read_edges() if e.kind == "fact")
    assert fact.evidence == [{"node_id": evidence.id, "text": "Alice works for Other"}]
    assert engine.brain.read_node(old.id).text == "Alice works at Acme."
    before = snapshot(engine.brain)
    assert engine.capture(text, extraction="rules")[3]["reused_facts"] == 1
    assert snapshot(engine.brain) == before


def test_zero_entities_still_captures_source(engine):
    node, _, _, result = engine.capture("ambiguous prose", extraction="rules")
    assert result["status"] == "complete" and result["source_node_id"] == node.id
    assert result["created_entities"] == result["pending_facts"] == 0


@pytest.mark.parametrize("duplicate", [False, True])
def test_forget_remembered_capture_removes_receipts_and_fact_support(engine, duplicate, monkeypatch):
    from graph_engine.retrieval import retrieve

    text = "Alice works at Acme."
    if duplicate:
        engine.ingest(text)
    result = remember(engine, text, extraction="rules", accept_facts=True)
    assert result["duplicate"] is duplicate
    receipt = result["extraction"]["source_node_id"]
    commits = []
    monkeypatch.setattr(engine.brain, "commit_and_push",
                        lambda message, push=True: commits.append(message))
    forgotten = forget(engine.brain, result["node_id"], reason="Remove this observation")
    assert forgotten["forgotten"] and forgotten["edges_invalidated"] == 3
    assert engine.brain.read_node(receipt).status == "tombstone"
    assert engine.brain.read_node(result["node_id"]).status == "tombstone"
    assert not {receipt, result["node_id"]} & {nid for nid, _ in retrieve(engine, text, k=20)}
    assert all(e.is_invalidated for e in engine.brain.read_edges() if e.origin == "entity-extractor")
    assert forget(engine.brain, result["node_id"], reason="retry")["already"]
    assert len(commits) == 1


def test_forget_cleans_legacy_receipt_chains_below_a_tombstone(engine):
    brain = engine.brain
    brain.write_node(Node("old note", id="survivor", status="tombstone"))
    brain.write_node(Node("old copy", id="copy", status="tombstone",
                         capture=dict(input="old copy", node_id="survivor", duplicate=True, source="human")))
    brain.write_node(Node("live copy", id="child",
                         capture=dict(input="live copy", node_id="copy", duplicate=True, source="human")))
    assert forget(brain, "survivor", reason="finish previous forget")["forgotten"]
    assert brain.read_node("child").status == "tombstone"


@pytest.mark.parametrize("survivor_active", [False, True])
def test_consolidation_preserves_duplicate_capture_and_retry(engine, survivor_active):
    from graph_engine.context import _evidence

    text = "Alice works at Acme."
    survivor = engine.ingest(text)[0]
    if survivor_active:
        engine.brain.promote_node(survivor.id)
    first = engine.capture(text, extraction="rules", accept_facts=True)[3]
    receipt_id = first["source_node_id"]
    live = lambda: {n.id: n for n in engine.brain.read_nodes() if n.status != "tombstone"}
    refs = _evidence(engine, live())
    assert any(refs.values())
    assert engine.consolidate()["merged"] == 0
    assert engine.brain.read_node(survivor.id).status == "active"
    assert engine.brain.read_node(receipt_id).status == "active"
    assert _evidence(engine, live()) == refs
    before = snapshot(engine.brain)
    retried = engine.capture(text, extraction="rules")[3]
    assert retried["retried"] and retried["source_node_id"] == receipt_id
    assert snapshot(engine.brain) == before


def test_consolidation_preserves_independent_exact_input_receipts(engine):
    text = "Alice works at Acme."
    first = engine.capture(text, source="first", extraction="rules", allow_duplicates=True)[0]
    second = engine.capture(text, source="second", extraction="rules", allow_duplicates=True)[0]
    assert first.id != second.id
    assert engine.consolidate() == {"promoted": 2, "merged": 0}
    for source, node in (("first", first), ("second", second)):
        retried = engine.capture(text, source=source, extraction="rules")[3]
        assert retried["retried"] and retried["source_node_id"] == node.id


def test_later_ingests_never_deduplicate_into_an_evidence_copy(engine):
    text = "Alice works at Acme."
    engine.brain.write_node(Node(text, id="z-survivor"))
    engine.brain.write_node(Node(text, id="a-evidence",
        capture=dict(input=text, node_id="z-survivor", duplicate=True, source="human")))
    assert engine.ingest(text)[0].id == "z-survivor"


def test_remember_retry_does_not_report_a_new_note_write(engine):
    first = remember(engine, "Alice works at Acme.", extraction="rules")
    second = remember(engine, "Alice works at Acme.", extraction="rules")
    assert first["written"] and not second["written"]
    assert second["node_id"] == first["node_id"] and second["extraction"]["retried"]


@pytest.mark.parametrize("failure", ["malformed", "invalid_schema", "timeout", "exit"])
def test_model_failure_retains_capture_and_retry_does_not_duplicate(engine, monkeypatch, failure):
    monkeypatch.setenv("IG_ENTITIES_LLM_CMD", "configured-adapter")
    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("configured-adapter", 300)
        output = "not json" if failure == "malformed" else '{"entities": 42, "facts": []}'
        return SimpleNamespace(returncode=7 if failure == "exit" else 0,
                               stdout=output, stderr="private provider diagnostic")
    monkeypatch.setattr(subprocess, "run", run)
    text = "Alice works at Acme."
    node, _, _, failed = engine.capture(text, extraction="model")
    assert failed["status"] == "failed" and failed["captured"]
    assert failed["retryable"] and failed["created_entities"] is None
    assert "private provider" not in json.dumps(failed)
    assert len(engine.brain.read_nodes()) == 1 and not engine.brain.read_edges()
    repeated, _, _, again = engine.capture(text, extraction="model")
    assert repeated.id == node.id and again["retried"] and again["status"] == "failed"
    # Operator can repair the command, or resume with dependency-free rules.
    recovered = engine.capture(text, extraction="rules")[3]
    assert recovered["status"] == "complete" and recovered["created_entities"] == 2
    assert len(engine.brain.read_nodes()) == 3


def test_config_and_option_errors_precede_capture(engine):
    for options in ({"extraction": "bogus"}, {"accept_facts": True}, {"extraction": "model"}):
        with pytest.raises(ValueError):
            engine.capture("Alice works at Acme.", **options)
    assert not engine.brain.path.exists()


def test_review_decisions_and_tombstones_survive_capture_retries(engine):
    text = "Alice works at Acme."
    engine.capture(text, extraction="rules")
    fact = next(e for e in engine.brain.read_edges() if e.kind == "fact")
    engine.resolve(fact.id, accept=False)
    retried = engine.capture(text, extraction="rules", accept_facts=True)[3]
    assert retried["created_facts"] == retried["pending_facts"] == 0
    assert next(e for e in engine.brain.read_edges(True) if e.id == fact.id).rejected
    alice = next(n for n in engine.brain.read_nodes() if n.entity_name == "Alice")
    engine.brain.tombstone_node(alice.id)
    failed = engine.capture("Alice works at Other.", extraction="rules")[3]
    assert failed["status"] == "failed"
    assert engine.brain.read_node(alice.id).status == "tombstone"
    assert not any(n.entity_name == "Other" for n in engine.brain.read_nodes())


def test_facts_require_explicit_acceptance_not_ingest_env(engine, monkeypatch):
    monkeypatch.setenv("IDEAGRAPH_AUTO_ACCEPT", "1")
    engine.capture("Alice works at Acme.", extraction="rules")
    engine.capture("Alice founded Acme.", extraction="rules", accept_facts=True)
    facts = {e.predicate: e for e in engine.brain.read_edges() if e.kind == "fact"}
    assert facts["works_at"].pending and not facts["founded"].pending


@pytest.mark.parametrize("after_commit", [False, True])
def test_git_two_commits_and_retry_after_extraction_sync_failure(tmp_path, monkeypatch, after_commit):
    brain = Brain(tmp_path / "git-brain", mode="git")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    brain.ensure_ready()
    subprocess.run(["git", "-C", str(brain.path), "remote", "add", "origin", str(remote)], check=True)
    brain.commit_and_push("seed remote brain")
    engine = BrainEngine(brain, HashEmbedder())
    commit = brain.commit_and_push
    def fail_after_commit(message, push=True, *, sync_pending=False):
        if message.startswith("capture entities:") and not after_commit:
            raise RuntimeError("simulated commit failure")
        commit(message, push=not message.startswith("capture entities:") and push,
               sync_pending=sync_pending)
        if message.startswith("capture entities:"):
            raise RuntimeError("simulated remote sync failure")
    monkeypatch.setattr(brain, "commit_and_push", fail_after_commit)
    failed = engine.capture("Alice works at Acme.", extraction="rules")[3]
    assert failed["status"] == "failed"
    def log():
        return subprocess.check_output(["git", "-C", str(brain.path), "log", "--format=%s"], text=True)
    before = log()
    assert len(before.splitlines()) == (3 if after_commit else 2)
    monkeypatch.setattr(brain, "commit_and_push", commit)
    result = engine.capture("Alice works at Acme.", extraction="rules")[3]
    assert result["status"] == "complete" and result["created_facts"] == 0
    assert len(brain.read_nodes()) == 3 and len(log().splitlines()) == 3
    if after_commit:
        assert log() == before
    finished = log()
    engine.capture("Alice works at Acme.", extraction="rules")
    assert log() == finished
    remote_log = subprocess.check_output(["git", "-C", str(remote), "log", "main", "--format=%s"], text=True)
    assert remote_log == finished  # no-op retries must sync already-local commits


def test_cli_stdin_json_and_failure_exit(engine, monkeypatch, capsys):
    import io
    from graph_engine.__main__ import cmd_ingest
    monkeypatch.setattr("sys.stdin", io.StringIO("\nAlice works at Acme.\n"))
    cmd_ingest(engine, ["-", "--extract-entities", "--json"])
    result = json.loads(capsys.readouterr().out)
    assert result["extraction"]["status"] == "complete"
    assert result["node"]["capture"]["input"] == "\nAlice works at Acme.\n"
    monkeypatch.setenv("IG_ENTITIES_LLM_CMD", "printf invalid")
    with pytest.raises(SystemExit) as exc:
        cmd_ingest(engine, ["Bob works at Other.", "--extract-model", "--json"])
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["extraction"]["status"] == "failed"


def test_http_contract_and_partial_failure(engine, monkeypatch):
    with TestClient(app) as client:
        plain = client.post("/api/ingest", json={"text": "plain note"}).json()
        assert set(plain) == {"node", "suggested", "duplicate"}
        data = {"text": "Alice works at Acme.", "extraction": "rules"}
        first = client.post("/api/ingest", json=data)
        assert first.status_code == 200 and first.json()["extraction"]["pending_facts"] == 1
        retry = client.post("/api/ingest", json=data).json()
        assert retry["node"]["id"] == first.json()["node"]["id"]
        assert retry["extraction"]["retried"] and retry["extraction"]["created_facts"] == 0
        assert client.post("/api/ingest", json=data | {"extraction": "invalid"}).status_code == 400
        monkeypatch.setenv("IG_ENTITIES_LLM_CMD", "printf invalid")
        failed = client.post("/api/ingest", json=data | {"extraction": "model"})
        assert failed.status_code == 502 and failed.json()["extraction"]["captured"]


def test_mcp_contract_keeps_write_guard_and_original_input(engine, monkeypatch):
    pytest.importorskip("mcp")
    from graph_engine.mcp import server
    engine.brain.init()
    monkeypatch.setenv("IG_MCP_WRITE", "0")
    denied = server.remember("Alice works at Acme.", extraction="rules")
    assert not denied["ok"] and not engine.brain.read_nodes()
    monkeypatch.setenv("IG_MCP_WRITE", "1")
    text = " \nAlice works at Acme.\n"
    result = server.remember(text, extraction="rules")
    assert result["ok"] and result["extraction"]["status"] == "complete"
    assert engine.brain.read_node(result["node_id"]).source == "agent"
    assert engine.brain.read_node(result["node_id"]).capture["input"] == text
    monkeypatch.setenv("IG_ENTITIES_LLM_CMD", "printf invalid")
    failed = server.remember(text, extraction="model")
    assert not failed["ok"] and failed["extraction"]["captured"]
    assert failed["node_id"] == result["node_id"]


def test_new_wording_adds_support_without_replacing_fact_decision(engine):
    engine.embedder = SameVector()
    first = engine.capture("Alice works at International Business Machines (IBM).", extraction="rules")[3]
    second = engine.capture("Alice works for IBM.", extraction="rules")[3]
    assert second["created_entities"] == second["created_facts"] == 0
    assert second["reused_entities"] == 2 and second["reused_facts"] == 1
    fact = next(e for e in engine.brain.read_edges() if e.kind == "fact")
    assert fact.pending and {s["node_id"] for s in fact.evidence} == {
        first["source_node_id"], second["source_node_id"]}
    before = snapshot(engine.brain)
    engine.capture("Alice works for IBM.", extraction="rules", accept_facts=True)
    assert snapshot(engine.brain) == before


def test_model_validity_windows_survive_capture_and_retry(engine, monkeypatch):
    data = {"entities": [{"name": "Alice", "type": "person"}, {"name": "Acme", "type": "org"}],
            "facts": [{"subject": "Alice", "predicate": "works_at", "object": "Acme",
                       "evidence": "Alice works at Acme", "valid_from": "2024-01-01",
                       "valid_to": "2024-06-01", "confidence": .8}]}
    monkeypatch.setenv("IG_ENTITIES_LLM_CMD", "configured-adapter")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps(data), stderr=""))
    first = engine.capture("Alice works at Acme", extraction="model")[3]
    assert first["status"] == "complete"
    fact = next(e for e in engine.brain.read_edges() if e.kind == "fact")
    assert fact.extracted_validity == {"valid_from": "2024-01-01T00:00:00Z", "valid_to": "2024-06-01T00:00:00Z"}
    engine.brain.invalidate_edge(fact.id)
    before = snapshot(engine.brain)
    retry = engine.capture("Alice works at Acme", extraction="model", accept_facts=True)[3]
    assert retry["created_facts"] == retry["pending_facts"] == 0
    assert snapshot(engine.brain) == before

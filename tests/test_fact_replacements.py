"""Replacement review never infers exclusivity, event dates or permission."""
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from graph_engine.access import SecuredBrain
from graph_engine.agent_memory import forget
from graph_engine.brain import Brain, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder
from graph_engine.entities import extract_entities, rule_extract, validate_extraction
from graph_engine.graph import live_edges
from graph_engine.review import accept_pending


@pytest.fixture
def brain(tmp_path):
    return Brain(tmp_path / "brain", mode="local")


def facts(brain):
    return {e.id: e for e in brain.read_edges(include_rejected=True)}


def setup_change(brain, date=None, **kwargs):
    initial = extract_entities(brain, "Alice works at Acme.", accept_facts=True)
    text = "Alice now works at Globex instead of Acme" + (f" as of {date}" if date else "") + "."
    change = extract_entities(brain, text, **kwargs)
    return initial["facts"][0], change, text


def test_explicit_change_is_a_pending_evidence_backed_proposal(brain):
    old, change, text = setup_change(brain, accept_facts=True)
    saved = facts(brain)
    assert saved[old["id"]].to_dict() == old
    assert len(change["proposals"]) == 1
    proposal = change["proposals"][0]
    assert proposal["pending"] and proposal["replacement"]["effective_at"] is None
    assert proposal["replacement"]["reason"] == text[:-1]
    assert {e["node_id"] for e in proposal["evidence"]} == {
        old["evidence"][0]["node_id"], change["source_node_id"]}
    assert change["facts"][0]["pending"]  # even with --accept-facts
    assert proposal["id"] not in {e.id for e in live_edges(brain, include_pending=True)}
    assert next(e for e in brain.graph_state()["edges"] if e["id"] == proposal["id"])["current"] is False
    before = brain.edges_file.read_bytes()
    assert not extract_entities(brain, text, accept_facts=True)["changed"]
    assert brain.edges_file.read_bytes() == before


@pytest.mark.parametrize("text", ["Alice works at Globex.", "Alice might work at Globex instead of Acme.",
                                   "Alice now works at Globex instead of Acme?", "She now works at Globex instead of Acme."])
def test_simultaneous_and_ambiguous_employers_never_imply_replacement(brain, text):
    extract_entities(brain, "Alice works at Acme.", accept_facts=True)
    result = extract_entities(brain, text)
    assert result["proposals"] == []
    assert all(not e.is_invalidated for e in facts(brain).values())


def test_declared_exclusivity_is_opt_in(brain):
    extract_entities(brain, "Alice works at Acme.", accept_facts=True)
    result = extract_entities(brain, "Alice works at Globex.", exclusive_predicates=("works_at",))
    assert result["proposals"][0]["replacement"]["basis"] == "declared exclusive predicate"


@pytest.mark.parametrize("date", [None, "2025-01-01", "2998-01-01"])
def test_accept_and_undo_restore_exact_original_dates(brain, date):
    old, change, text = setup_change(brain, date)
    pid = change["proposals"][0]["id"]
    new = change["facts"][0]
    engine = BrainEngine(brain, HashEmbedder())
    assert engine.resolve(pid, True)
    saved = facts(brain)
    assert saved[old["id"]].extracted_validity == old["extracted_validity"]
    assert saved[old["id"]].superseded_by == pid
    assert saved[old["id"]].reviewed_at
    if date:
        assert saved[old["id"]].valid_to == date + "T00:00:00Z"
        assert saved[old["id"]].invalidated_at is None
        assert saved[old["id"]].is_current == (date == "2998-01-01")
    else:
        assert saved[old["id"]].valid_to is None
        assert saved[old["id"]].invalidated_at
    assert not saved[new["id"]].pending
    assert engine.undo(old["id"]) is None
    assert engine.undo(new["id"]) is None
    assert engine.resolve(pid, True) is None
    assert not extract_entities(brain, text, accept_facts=True)["changed"]
    assert engine.undo(pid).pending
    saved = facts(brain)
    assert saved[old["id"]].to_dict() == old
    assert saved[new["id"]].to_dict() == new
    assert engine.resolve(pid, True)


def test_reject_changes_neither_fact_and_retry_preserves_decision(brain):
    old, change, text = setup_change(brain)
    pid = change["proposals"][0]["id"]
    engine = BrainEngine(brain, HashEmbedder())
    assert engine.resolve(pid, False).rejected
    saved = facts(brain)
    assert saved[old["id"]].to_dict() == old
    assert saved[change["facts"][0]["id"]].to_dict() == change["facts"][0]
    before = brain.edges_file.read_bytes()
    assert not extract_entities(brain, text, accept_facts=True)["changed"]
    assert brain.edges_file.read_bytes() == before
    assert engine.undo(pid).pending


@pytest.mark.parametrize("which", ["old", "new", "old_evidence", "new_evidence"])
@pytest.mark.parametrize("accepted", [False, True])
def test_forget_blocks_accept_and_undo_without_resurrection(brain, which, accepted):
    old, change, _ = setup_change(brain)
    new = change["facts"][0]
    pid = change["proposals"][0]["id"]
    engine = BrainEngine(brain, HashEmbedder())
    if accepted:
        engine.resolve(pid, True)
    nid = {"old": old["target"], "new": new["target"],
           "old_evidence": old["evidence"][0]["node_id"],
           "new_evidence": change["source_node_id"]}[which]
    forget(brain, nid, reason="test", commit=False)
    before = brain.edges_file.read_bytes()
    assert engine.undo(pid) is None
    assert engine.resolve(pid, True) is None
    assert brain.edges_file.read_bytes() == before


def test_later_evidence_prevents_undo_from_discarding_it(brain):
    _, change, _ = setup_change(brain)
    engine = BrainEngine(brain, HashEmbedder())
    pid = change["proposals"][0]["id"]
    engine.resolve(pid, True)
    extract_entities(brain, "Alice works at Globex. Another observation.")
    assert engine.undo(pid) is None


def test_bulk_review_holds_replacements_and_their_new_facts(brain):
    _, change, _ = setup_change(brain)
    result = accept_pending(brain, commit=False)
    assert set(result["held"]) == {change["facts"][0]["id"], change["proposals"][0]["id"]}
    assert not result["accepted"]


@pytest.mark.parametrize("which", ["old", "new", "old_evidence", "new_evidence", "late_evidence"])
@pytest.mark.parametrize("readable", [False, True])
def test_every_endpoint_and_evidence_node_controls_review(brain, tmp_path, monkeypatch, which, readable):
    old, change, _ = setup_change(brain)
    new = change["facts"][0]
    pid = change["proposals"][0]["id"]
    extra = Node("late private support")
    brain.write_node(extra)
    rows = list(facts(brain).values())
    next(e for e in rows if e.id == old["id"]).evidence.append(dict(node_id=extra.id, text=extra.text))
    brain.write_edges(rows)
    nid = {"old": old["target"], "new": new["target"],
           "old_evidence": old["evidence"][0]["node_id"],
           "new_evidence": change["source_node_id"], "late_evidence": extra.id}[which]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"graphs": {"default": {"roles": {"user": "editor"},
        "nodes": {nid: {"write": [], **({} if readable else {"read": []})}}}}}))
    monkeypatch.setenv("IG_ACCESS_POLICY", str(path))
    secured = SecuredBrain(brain.path, mode="local", graph_name="default", identity="user")
    before = brain.edges_file.read_bytes()
    if readable:
        assert pid in {e.id for e in secured.read_edges()}
        with pytest.raises(PermissionError):
            secured.resolve_edge(pid, True)
        with pytest.raises(PermissionError):
            secured.resolve_edge(pid, False)
    else:
        assert pid not in {e.id for e in secured.read_edges()}
        assert secured.resolve_edge(pid, True) is None
        assert pid not in {e["id"] for e in secured.graph_state()["edges"]}
    assert brain.edges_file.read_bytes() == before


def test_model_replacement_metadata_requires_explicit_evidence():
    data = rule_extract("Alice works at Globex instead of Acme.")
    data["facts"][0]["evidence"] = "Alice works at Globex and Acme"
    with pytest.raises(ValueError, match="explicit replacement"):
        validate_extraction(data, "Alice works at Globex and Acme")


def test_http_and_cli_review_details_and_undo(brain, monkeypatch, capsys):
    from graph_engine.__main__ import cmd_pending, cmd_undo
    from graph_engine.server import app
    old, change, _ = setup_change(brain)
    pid = change["proposals"][0]["id"]
    engine = BrainEngine(brain, HashEmbedder())
    cmd_pending(engine, [])
    printed = capsys.readouterr().out
    for word in (old["id"], change["facts"][0]["id"], "Acme", "Globex", "effective: unknown", "evidence"):
        assert word in printed
    monkeypatch.setenv("IG_BRAIN_PATH", str(brain.path))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    with TestClient(app) as client:
        assert client.post(f"/api/edge/{pid}/accept").status_code == 200
        assert client.post(f"/api/edge/{pid}/undo").status_code == 200
        assert client.post(f"/api/edge/{pid}/reject").status_code == 200
    cmd_undo(engine, [pid])
    assert facts(brain)[pid].pending


def test_git_accept_and_undo_each_commit_both_facts_and_provenance(tmp_path):
    brain = Brain(tmp_path / "git", mode="git")
    old, change, _ = setup_change(brain)
    pid = change["proposals"][0]["id"]
    engine = BrainEngine(brain, HashEmbedder())
    def commits():
        return subprocess.check_output(["git", "-C", str(brain.path), "rev-list", "--count", "HEAD"], text=True)
    before = int(commits())
    engine.resolve(pid, True)
    assert int(commits()) == before + 1
    committed = subprocess.check_output(["git", "-C", str(brain.path), "show", "HEAD:edges.jsonl"], text=True)
    rows = {row["id"]: row for row in map(json.loads, committed.splitlines())}
    assert rows[old["id"]]["superseded_by"] == pid
    assert not rows[change["facts"][0]["id"]]["pending"]
    assert rows[pid]["replacement"]["decision"]
    engine.undo(pid)
    assert int(commits()) == before + 2
    assert facts(brain)[old["id"]].to_dict() == old


@pytest.mark.parametrize("start,end,date", [
    ("2020-01-01", "2021-01-01", "2025-01-01"),
    ("2026-01-01", None, "2025-01-01"),
])
def test_nonoverlapping_or_backwards_windows_are_not_replacements(brain, start, end, date):
    data = rule_extract("Alice works at Acme.")
    data["facts"][0].update(valid_from=start, valid_to=end)
    old = extract_entities(brain, "Alice works at Acme.", extractor=lambda *_: data, accept_facts=True)
    result = extract_entities(brain, f"Alice works at Globex instead of Acme as of {date}.")
    assert result["proposals"] == []
    assert facts(brain)[old["facts"][0]["id"]].valid_to == old["facts"][0]["valid_to"]


def test_model_explicit_negation_can_propose_a_replacement(brain):
    extract_entities(brain, "Alice works at Acme.", accept_facts=True)
    quote = "Alice no longer works at Acme and now works at Globex"
    data = rule_extract("Alice works at Globex instead of Acme.")
    data["facts"][0]["evidence"] = quote
    result = extract_entities(brain, quote, extractor=lambda *_: data)
    assert result["proposals"][0]["replacement"]["effective_at"] is None


def test_forget_authorizes_referenced_facts_before_any_tombstone(brain, tmp_path, monkeypatch):
    old, change, _ = setup_change(brain)
    readonly = change["facts"][0]["target"]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"graphs": {"default": {"roles": {"user": "editor"},
        "nodes": {readonly: {"write": []}}}}}))
    monkeypatch.setenv("IG_ACCESS_POLICY", str(path))
    secured = SecuredBrain(brain.path, mode="local", graph_name="default", identity="user")
    before = brain.edges_file.read_bytes()
    with pytest.raises(PermissionError):
        forget(secured, old["target"], reason="test", commit=False)
    assert brain.read_node(old["target"]).status != "tombstone"
    assert brain.edges_file.read_bytes() == before


def test_same_second_decisions_cannot_undo_another_replacement(brain, monkeypatch):
    import graph_engine.replacements as replacements
    monkeypatch.setattr(replacements, "_now_iso", lambda: "2026-10-12T00:00:00Z")
    extract_entities(brain, "Alice works at Acme. Alice works at Other.", accept_facts=True)
    change = extract_entities(brain, "Alice works at Globex.", exclusive_predicates=("works_at",))
    p1, p2 = [p["id"] for p in change["proposals"]]
    engine = BrainEngine(brain, HashEmbedder())
    assert engine.resolve(p1, True)
    assert engine.resolve(p2, True)
    assert engine.undo(p1) is None
    assert engine.undo(p2)
    assert engine.undo(p1)


def test_changed_claim_cannot_accept_a_stale_proposal(brain):
    old, change, _ = setup_change(brain)
    rows = list(facts(brain).values())
    next(e for e in rows if e.id == old["id"]).predicate = "founded"
    brain.write_edges(rows)
    before = brain.edges_file.read_bytes()
    assert BrainEngine(brain, HashEmbedder()).resolve(change["proposals"][0]["id"], True) is None
    assert brain.edges_file.read_bytes() == before


def test_bounded_old_fact_restores_its_original_end_on_undo(brain):
    data = rule_extract("Alice works at Acme.")
    data["facts"][0].update(valid_from="2020-01-01", valid_to="2030-01-01")
    initial = extract_entities(brain, "Alice works at Acme.", extractor=lambda *_: data, accept_facts=True)
    old = initial["facts"][0]
    change = extract_entities(brain, "Alice works at Globex instead of Acme as of 2027-01-01.")
    pid = change["proposals"][0]["id"]
    engine = BrainEngine(brain, HashEmbedder())
    assert engine.resolve(pid, True)
    saved = facts(brain)[old["id"]]
    assert saved.valid_to == "2027-01-01T00:00:00Z"
    assert saved.extracted_validity["valid_to"] == "2030-01-01T00:00:00Z"
    assert saved.invalidated_at is None
    assert engine.undo(pid)
    assert facts(brain)[old["id"]].to_dict() == old


def test_dry_run_proposal_does_not_mutate_the_brain(brain):
    extract_entities(brain, "Alice works at Acme.", accept_facts=True)
    before = {str(p): p.read_bytes() for p in brain.path.rglob("*") if p.is_file()}
    result = extract_entities(brain, "Alice works at Globex instead of Acme.", dry_run=True)
    assert result["proposals"][0]["pending"]
    assert {str(p): p.read_bytes() for p in brain.path.rglob("*") if p.is_file()} == before

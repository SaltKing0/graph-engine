"""Grounded proposals: publication, review, atomic failures and command bounds."""
import datetime
import json
import shlex
import subprocess
import sys

import pytest

from graph_engine.brain import Brain, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.consolidation import ConsolidationConfig, consolidate, consolidation_plan
from graph_engine.consolidation_protocol import (
    PROPOSAL_PREFIX, PROPOSAL_TAG, command_extractor, validate_consolidation,
)
from graph_engine.dream import lifecycle_plan, plan
from graph_engine.embedder import HashEmbedder
from graph_engine.retrieval import retrieve
from graph_engine.review import accept_pending

OPEN = ConsolidationConfig(threshold=0, min_age_days=0)
NOW = datetime.datetime(2026, 10, 12, tzinfo=datetime.timezone.utc)


def seed(brain: Brain, nid: str = "event", text: str = "Alice works at Acme. Alice lives in Berlin.") -> Node:
    node = Node(id=nid, text=text, ntype="episodic", created="2026-09-01T00:00:00Z")
    brain.write_node(node)
    return node


def fact(text: str = "Alice works at Acme.", quote: str | None = None, nid: str = "event", **dates) -> dict:
    return dict(text=text, evidence=[dict(node_id=nid, quote=quote or text)], **dates)


def batch(*facts: dict) -> dict:
    return dict(version=1, abstain=not facts, facts=list(facts))


def run(brain: Brain, data: dict, **kwargs) -> dict:
    return consolidate(brain, config=OPEN, now=NOW, structured_extractor=lambda events: data, **kwargs)


def snapshot(brain: Brain) -> dict:
    return {str(p.relative_to(brain.path)): p.read_bytes()
            for p in brain.path.rglob("*") if p.is_file() and ".git" not in p.parts}


def shell(code: str) -> str:
    return shlex.join([sys.executable, "-c", code])


def test_multi_fact_provenance_publication_review_and_repeat(tmp_path):
    brain = Brain(tmp_path / "brain", mode="local")
    seed(brain)
    before_event = brain.node_path("event").read_bytes()
    result = run(brain, batch(fact(), fact("Alice lives in Berlin.")))
    assert result["created"] == result["edges"] == result["pending_proposals"] == 2
    assert result["protocol"] == "structured-v1" and result["extraction_ran"]
    assert brain.node_path("event").read_bytes() == before_event
    nodes = [n for n in brain.read_nodes() if PROPOSAL_TAG in n.tags]
    assert len(nodes) == 2
    assert all(n.status == "probation" and n.text.startswith(PROPOSAL_PREFIX) for n in nodes)
    edges = brain.read_edges()
    assert all(e.pending and e.valid_from is None and e.evidence for e in edges)
    engine = BrainEngine(brain, embedder=HashEmbedder())
    # Pending links, and even rejected links, do not remove semantic nodes from search.
    ids = {nid for nid, _ in retrieve(engine, "Alice", k=10, persist=False)}
    assert {n.id for n in nodes} <= ids
    before = snapshot(brain)
    assert accept_pending(brain, commit=False)["held"] == sorted(e.id for e in edges)
    assert snapshot(brain) == before
    accepted = brain.resolve_edge(edges[0].id, True)
    assert accepted.reviewed_at and accepted.reviewed_by == "local"
    rejected = brain.resolve_edge(edges[1].id, False)
    assert rejected.rejected and rejected.reviewed_at
    assert edges[1].source in {nid for nid, _ in retrieve(engine, "Alice", k=10, persist=False)}
    before = snapshot(brain)
    assert run(brain, batch())["candidates"] == []
    assert snapshot(brain) == before
    review = consolidation_plan(brain, config=OPEN, now=NOW)["review"]
    assert review == dict(pending=0, accepted=1, rejected=1)
    restored = brain.restore_edge(edges[1].id)
    assert restored.pending and not restored.rejected and restored.reviewed_at is None


def test_supported_quotes_do_not_prove_added_claim_or_pronoun_resolution(tmp_path):
    brain = Brain(tmp_path / "brain", mode="local")
    seed(brain, text="Alice met Bob. He uses Python.")
    # Exact quote checking is deliberately not an entailment oracle.
    result = run(brain, batch(fact("Bob is an expert Python developer.", "He uses Python.")))
    assert result["created"] == 1
    assert brain.read_edges()[0].pending
    assert brain.read_node(result["proposals"][0]["node_id"]).text.startswith(PROPOSAL_PREFIX)
    assert "Selection eligibility only" in plan(brain, consolidation_config=OPEN).render()


@pytest.mark.parametrize("bad", [
    batch(fact(quote="Alice founded Acme.")),  # unsupported quote
    batch(fact(nid="other")),  # a real source outside the selected batch is still invalid
    batch(fact(valid_from="yesterday")),
    batch(fact(valid_to="2026-01-01")),
    batch(fact(valid_from="2026-02-01", valid_to="2026-01-01")),
    batch(fact(valid_from="2026-01-01", valid_to="2026-01-01")),
    batch(dict(text="x", evidence=[])),
    batch(dict(text="x", evidence=[dict(node_id="event", quote="Alice", extra=True)])),
    batch(dict(text="x", evidence=[dict(node_id="event", quote="Alice")], confidence=0.99)),
    batch(fact(text="x" * 4001, quote="Alice")),
    batch(*[fact() for _ in range(33)]),
    dict(version=True, abstain=False, facts=[fact()]),
    dict(version=1, abstain=True, facts=[fact()]),
    dict(version=1, abstain=False, facts=[]),
    dict(version=2, abstain=True, facts=[]),
    "not an object",
])
def test_invalid_batch_leaves_nodes_edges_and_cursor_unwritten(tmp_path, bad):
    brain = Brain(tmp_path / "brain", mode="local")
    seed(brain)
    seed(brain, "other")
    before = snapshot(brain)
    # First fact is good: failure later must not publish the first one.
    if isinstance(bad, dict) and isinstance(bad.get("facts"), list) and bad["facts"]:
        bad = {**bad, "facts": [fact(), *bad["facts"]]}
    with pytest.raises(ValueError):
        consolidate(brain, config=ConsolidationConfig(threshold=0, min_age_days=0, limit=1),
                    now=NOW, structured_extractor=lambda events: bad)
    assert snapshot(brain) == before


def test_abstention_dry_run_and_protocol_exclusivity(tmp_path, monkeypatch):
    brain = Brain(tmp_path / "brain", mode="local")
    seed(brain)
    before = snapshot(brain)
    result = run(brain, batch())
    assert result["abstained"] and result["created"] == result["edges"] == 0
    assert snapshot(brain) == before
    def forbidden(*args):
        pytest.fail("dry run invoked command or mutation")
    for method in ("ensure_ready", "pull", "write_node", "write_edges", "commit_and_push"):
        monkeypatch.setattr(brain, method, forbidden)
    result = consolidate(brain, config=OPEN, now=NOW, dry_run=True, structured_extractor=forbidden)
    assert not result["extraction_ran"] and result["protocol"] == "structured-v1"
    with pytest.raises(ValueError, match="mutually exclusive"):
        consolidate(brain, extractor=lambda text: text, structured_extractor=forbidden)


@pytest.mark.parametrize("decision", ["reject", "forget", "invalidate"])
def test_later_matching_event_cannot_recreate_forgotten_or_rejected_fact(tmp_path, decision):
    brain = Brain(tmp_path / "brain", mode="local")
    seed(brain)
    first = run(brain, batch(fact()))
    nid = first["proposals"][0]["node_id"]
    edge = brain.read_edges()[0]
    if decision == "reject":
        brain.resolve_edge(edge.id, False)
    elif decision == "invalidate":
        brain.invalidate_edge(edge.id)
    else:
        brain.tombstone_node(nid)
    seed(brain, "later")
    before = snapshot(brain)
    result = run(brain, batch(fact(nid="later")))
    assert result["skipped"] == 1 and result["created"] == result["edges"] == 0
    assert snapshot(brain) == before


def test_exact_reuse_dates_and_multiple_event_links(tmp_path):
    brain = Brain(tmp_path / "brain", mode="local")
    seed(brain)
    seed(brain, "second")
    data = batch(dict(text="Alice works at Acme.", evidence=[
        dict(node_id="event", quote="Alice works at Acme."),
        dict(node_id="second", quote="Alice works at Acme.")],
        valid_from="2026-01-01T01:00:00+01:00", valid_to="2027-01-01"))
    first = run(brain, data)
    assert first["created"] == 1 and first["edges"] == 2
    edges = brain.read_edges()
    assert {e.target for e in edges} == {"event", "second"}
    assert all(e.extracted_validity["valid_from"] == "2026-01-01T00:00:00Z" for e in edges)
    seed(brain, "third")
    again = run(brain, batch(fact(nid="third", valid_from="2026-01-01", valid_to="2027-01-01")))
    assert again["created"] == 0 and again["reused"] == 1 and again["edges"] == 1
    assert again["proposals"][0]["node_id"] == first["proposals"][0]["node_id"]
    seed(brain, "fourth")
    assert run(brain, batch(fact(nid="fourth", valid_from="2025-01-01")))["created"] == 1


def test_proposals_do_not_get_promoted_merged_or_reused_as_ingest_survivors(tmp_path):
    brain = Brain(tmp_path / "brain", mode="local")
    seed(brain)
    result = run(brain, batch(fact()))
    nid = result["proposals"][0]["node_id"]
    node = brain.read_node(nid)
    node.recall_count = 10
    brain.write_node(node)
    assert nid not in lifecycle_plan(brain, min_degree=0)["promote"]
    engine = BrainEngine(brain, embedder=HashEmbedder(), dedupe_threshold=0)
    engine.consolidate()
    assert brain.read_node(nid).status == "probation"
    assert engine._find_duplicate(engine.embedder.embed(node.text)).id != nid


def test_git_batch_one_commit_failure_and_repeat_do_not_commit(tmp_path):
    brain = Brain(tmp_path / "brain", mode="git")
    brain.ensure_ready()
    seed(brain)
    brain.commit_and_push("seed")
    def head():
        return subprocess.check_output(["git", "-C", str(brain.path), "rev-parse", "HEAD"])
    before = head()
    with pytest.raises(ValueError):
        run(brain, batch(fact(), fact(quote="made up")))
    assert head() == before
    run(brain, batch(fact(), fact("Alice lives in Berlin.")))
    after = head()
    assert after != before
    assert subprocess.check_output(["git", "-C", str(brain.path), "rev-parse", "HEAD~1"]) == before
    run(brain, batch())
    assert head() == after
    assert subprocess.check_output(["git", "-C", str(brain.path), "status", "--porcelain"]) == b""


def test_command_protocol_and_whitespace_exactness(tmp_path):
    command = shell('import sys,json; r=json.load(sys.stdin); e=r["events"][0]; '
                    'print(json.dumps({"version":1,"abstain":False,"facts":['
                    '{"text":"Alice uses Python.","evidence":[{"node_id":e["node_id"],"quote":e["text"]}]}]}))')
    events = [dict(node_id="event", text="  Alice uses Python.  ")]
    facts = validate_consolidation(command_extractor(command)(events), events)
    assert facts[0]["evidence"][0]["quote"] == events[0]["text"]


@pytest.mark.parametrize("code,error", [
    ('print("no JSON")', ValueError),
    ('print(\'{"version":1,"version":1,"abstain":true,"facts":[]}\')', ValueError),
    ('import sys; sys.exit(2)', RuntimeError),
    ('print("x" * 131073)', ValueError),
    ('import sys; sys.stderr.write("x" * 131073)', ValueError),
    ('import time; time.sleep(5)', RuntimeError),
])
def test_command_errors_leave_batch_unwritten(tmp_path, code, error):
    brain = Brain(tmp_path / "brain", mode="local")
    seed(brain)
    before = snapshot(brain)
    with pytest.raises(error):
        consolidate(brain, config=OPEN, now=NOW,
                    structured_extractor=command_extractor(shell(code), timeout=0.2))
    assert snapshot(brain) == before


def test_large_input_is_rejected_before_launching_command():
    with pytest.raises(ValueError, match="input exceeds"):
        command_extractor(shell('raise AssertionError("must not run")'))([
            dict(node_id="event", text="x" * 262144)])

"""Git snapshots restore committed records without mutating the active brain."""
from __future__ import annotations

import json
import subprocess

import pytest

from graph_engine.brain import Brain, Node, Edge
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder
from graph_engine.snapshots import SnapshotError, snapshot


def git(brain, *args):
    return subprocess.check_output(['git', '-C', str(brain.path), *args], text=True).strip()


def commit(brain):
    brain.commit_and_push('test revision', push=False)
    return git(brain, 'rev-parse', 'HEAD')


@pytest.fixture
def saved(tmp_path):
    brain = Brain(str(tmp_path / 'brain'), mode='git')
    brain.init()
    a = Node('Alice used Python in the original note', id='alice', status='active',
             created='2020-01-01T00:00:00Z')
    b = Node('Python language', id='python', status='active', created=a.created)
    evidence = Node('Alice uses Python', id='evidence', status='active', created=a.created)
    for n in (a, b, evidence):
        brain.write_node(n)
    fact = Edge(a.id, b.id, 'fact', pending=True, id='fact', origin='consolidator',
                valid_from='2021-01-01T00:00:00Z', valid_to='2022-01-01T00:00:00Z',
                extracted_validity={'valid_from': '2021-01-01T00:00:00Z',
                                    'valid_to': '2022-01-01T00:00:00Z'},
                evidence=[{'node_id': evidence.id, 'text': evidence.text}])
    brain.write_edges([fact])
    pending = commit(brain)
    fact.pending = False
    fact.reviewed_by = 'reviewer'
    fact.reviewed_at = '2023-01-01T00:00:00Z'
    brain.write_edges([fact])
    accepted = commit(brain)
    a.text = 'Alice now uses Rust'
    brain.write_node(a)
    brain.tombstone_node(b.id)
    fact.rejected = True
    brain.write_edges([fact])
    latest = commit(brain)
    return brain, pending, accepted, latest


def state(brain):
    return (git(brain, 'rev-parse', 'HEAD'), git(brain, 'status', '--porcelain=v1'),
            (brain.path / '.git/index').read_bytes(),
            {str(p.relative_to(brain.path)): p.read_bytes() for p in brain.path.rglob('*')
             if p.is_file() and '.git' not in p.relative_to(brain.path).parts})


def test_restores_text_tombstone_and_review_decisions(saved):
    brain, pending, accepted, latest = saved
    result = snapshot(brain, pending)
    assert result['revision'] == pending
    assert result['commit_time']
    assert result['fact_valid_at'] is None
    assert {n.id: n.text for n in result['nodes']}['alice'].endswith('original note')
    assert result['edges'][0].pending
    result = snapshot(brain, accepted)
    assert not result['edges'][0].pending
    assert not result['edges'][0].rejected
    assert result['edges'][0].reviewed_by == 'reviewer'
    assert {n.id: n.status for n in result['nodes']}['python'] == 'active'
    current = snapshot(brain, latest)
    assert {n.id: n.status for n in current['nodes']}['python'] == 'tombstone'
    assert current['edges'][0].rejected
    assert snapshot(brain, 'HEAD~1')['revision'] == accepted


def test_snapshot_query_normalizes_both_document_and_query(saved):
    class CasedAdapter:
        def embed(self, text):
            return [1., 0.] if text in {"nasa launched a satellite", "space agency"} else [0., 1.]

    brain, _, _, _ = saved
    brain.write_node(Node("NASA launched a satellite", id="nasa", status="active"))
    revision = commit(brain)
    engine = BrainEngine(brain, CasedAdapter(), reranker=False)
    engine.reranker = None
    before = state(brain)
    result = engine.snapshot_query(revision, "Space   agency")
    assert result["hits"] == [("nasa", pytest.approx(1 / 61))]
    assert result["query"] == "Space   agency"
    assert state(brain) == before


def test_live_views_hide_tombstones_but_snapshots_use_current_authorization(saved, tmp_path, monkeypatch):
    from graph_engine.access import SecuredBrain
    brain, _, accepted, latest = saved
    assert 'python' not in {n['id'] for n in brain.graph_state()['nodes']}
    assert brain.graph_state()['edges'] == []
    assert brain.read_node('python').status == 'tombstone'
    policy = tmp_path / 'policy.json'
    config = {'roles': {'reader': 'viewer'}}
    policy.write_text(json.dumps({'graphs': {'default': config}}))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(policy))
    secured = SecuredBrain(str(brain.path), mode='git', graph_name='default', identity='reader')
    assert 'python' in {n.id for n in snapshot(secured, accepted)['nodes']}
    assert {n.id: n.status for n in snapshot(secured, latest)['nodes']}['python'] == 'tombstone'
    config['nodes'] = {'python': {'read': ['owner']}}
    policy.write_text(json.dumps({'graphs': {'default': config}}))
    assert 'python' not in {n.id for n in snapshot(secured, accepted)['nodes']}
    assert 'python' not in {n.id for n in snapshot(secured, latest)['nodes']}


def test_validity_is_independent_of_commit_time(saved):
    brain, pending, accepted, latest = saved
    assert snapshot(brain, pending, fact_valid_at='2021-06-01T00:00:00Z')['edges'] == []
    result = snapshot(brain, accepted, fact_valid_at='2021-01-01T01:00:00+01:00')
    assert [e.id for e in result['edges']] == ['fact']
    assert result['edges'][0].reviewed_at.startswith('2023')
    assert snapshot(brain, accepted, fact_valid_at='2022-01-01')['edges'] == []
    assert snapshot(brain, accepted, fact_valid_at='2020-12-31T23:59:59Z')['edges'] == []
    assert snapshot(brain, latest, fact_valid_at='2021-06-01')['edges'] == []
    assert snapshot(brain, accepted, fact_valid_at='2019-01-01')['nodes'] == []


def test_search_old_text_and_all_files_unchanged(saved, monkeypatch):
    brain, pending, accepted, latest = saved
    # Preserve dirty edits, ignored recall ledger and untracked records too.
    (brain.path / 'recalls.jsonl').write_text('ledger sentinel\n')
    (brain.path / 'notes.txt').write_text('untracked sentinel\n')
    brain.write_node(Node('dirty active note', id='dirty'))
    engine = BrainEngine(brain, HashEmbedder())
    monkeypatch.setenv('IG_RECALL_TRACKING', '1')
    for name in ('ensure_ready', 'pull', 'commit_and_push', 'write_vectors', 'vectors_for'):
        monkeypatch.setattr(brain, name, lambda *a, **k: pytest.fail('active brain mutation/cache'))
    import graph_engine.recall
    monkeypatch.setattr(graph_engine.recall, 'record', lambda *a, **k: pytest.fail('recall write'))
    before = state(brain)
    result = engine.snapshot_query(accepted, 'original note')
    assert result['hits'][0][0] == 'alice'
    assert result['nodes'][0].text.endswith('original note')
    assert engine.snapshot_query(latest, 'original note')['hits'] == []
    assert state(brain) == before


def secure(brain, tmp_path, monkeypatch):
    from graph_engine.access import SecuredBrain
    path = tmp_path / 'policy.json'
    policy = {'graphs': {'default': {'roles': {'viewer': 'viewer'}, 'nodes': {}}}}
    path.write_text(json.dumps(policy))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    return SecuredBrain(str(brain.path), mode='git', graph_name='default', identity='viewer'), path, policy


def test_current_revocation_hides_ids_and_evidence(saved, tmp_path, monkeypatch):
    brain, _, accepted, _ = saved
    secured, path, policy = secure(brain, tmp_path, monkeypatch)
    assert len(snapshot(secured, accepted)['edges']) == 1
    policy['graphs']['default']['nodes']['evidence'] = {'read': ['someone-else']}
    path.write_text(json.dumps(policy))
    result = snapshot(secured, accepted)
    assert 'evidence' not in {n.id for n in result['nodes']}
    assert result['edges'] == []
    policy['graphs']['default']['nodes']['alice'] = {'read': []}
    path.write_text(json.dumps(policy))
    engine = BrainEngine(secured, HashEmbedder())
    assert engine.snapshot_query(accepted, 'original note')['hits'] == []
    policy['graphs']['default']['roles'] = {}
    path.write_text(json.dumps(policy))
    with pytest.raises(PermissionError):
        snapshot(secured, accepted)


def test_derived_snapshot_text_respects_historical_and_current_lineage(saved, tmp_path, monkeypatch):
    brain, _, _, _ = saved
    brain.write_node(Node('historically private text', id='derived', derived_from=['evidence']))
    historical = commit(brain)
    # A trusted local rewrite cannot publish the older committed text.
    brain.write_node(Node('now public text', id='derived'))
    secured, path, policy = secure(brain, tmp_path, monkeypatch)
    policy['graphs']['default']['nodes']['evidence'] = {'read': ['owner']}
    path.write_text(json.dumps(policy))
    assert 'derived' not in {n.id for n in snapshot(secured, historical)['nodes']}
    assert BrainEngine(secured, HashEmbedder()).snapshot_query(historical, 'historically private')['hits'] == []
    policy['graphs']['default']['nodes'].clear()
    path.write_text(json.dumps(policy))
    assert 'derived' in {n.id for n in snapshot(secured, historical)['nodes']}
    # Present lineage remains mandatory even when the old record had no sources.
    public_revision = commit(brain)
    brain.write_node(Node('now derived text', id='derived', derived_from=['evidence']))
    policy['graphs']['default']['nodes']['evidence'] = {'read': ['owner']}
    path.write_text(json.dumps(policy))
    assert 'derived' not in {n.id for n in snapshot(secured, public_revision)['nodes']}


def test_snapshot_missing_or_cyclic_derivation_is_hidden(saved, tmp_path, monkeypatch):
    brain, _, _, _ = saved
    brain.write_node(Node('orphan text', id='orphan', derived_from=['absent']))
    brain.write_node(Node('cycle text', id='cycle', derived_from=['cycle']))
    revision = commit(brain)
    secured, _, _ = secure(brain, tmp_path, monkeypatch)
    assert {'orphan', 'cycle'}.isdisjoint(n.id for n in snapshot(secured, revision)['nodes'])


def test_historical_copy_cannot_bypass_current_parent_revocation(saved, tmp_path, monkeypatch):
    brain, _, _, _ = saved
    copy = Node('secret copy', id='copy', capture={
        'input': 'secret copy', 'node_id': 'alice', 'duplicate': True, 'source': 'human'})
    brain.write_node(copy)
    old = commit(brain)
    # The current copy no longer declares a parent. Its historical parent ACL
    # remains mandatory because the snapshot still includes that copied text.
    copy.capture = None
    brain.write_node(copy)
    commit(brain)
    secured, path, policy = secure(brain, tmp_path, monkeypatch)
    policy['graphs']['default']['nodes']['alice'] = {'read': []}
    path.write_text(json.dumps(policy))
    assert 'copy' not in {n.id for n in snapshot(secured, old)['nodes']}


@pytest.mark.parametrize('ref', ['', '--all', '../main', 'HEAD@{yesterday}', 'HEAD:edges.jsonl',
                               'HEAD^{tree}', 'HEAD~99999', 'bad ref', 'a' * 201, 'missing'])
def test_bad_refs_explicit_error(saved, ref):
    brain, *_ = saved
    with pytest.raises(SnapshotError):
        snapshot(brain, ref)


def test_local_no_history_parent_repo_and_noncommit(tmp_path):
    b = Brain(str(tmp_path / 'brain'))
    b.init()
    with pytest.raises(SnapshotError, match='Git-mode'):
        snapshot(b, 'HEAD')
    b.mode = 'git'
    with pytest.raises(SnapshotError):
        snapshot(b, 'HEAD')
    b.init(commit=False)
    with pytest.raises(SnapshotError):
        snapshot(b, 'HEAD')
    sha = commit(b)
    child = Brain(str(b.path / 'nodes'), mode='git')
    with pytest.raises(SnapshotError, match='repository root'):
        snapshot(child, sha)
    oid = git(b, 'rev-parse', 'HEAD:edges.jsonl')
    with pytest.raises(SnapshotError):
        snapshot(b, oid)


@pytest.mark.parametrize('bad', ['status: unknown', 'type: future-type', 'future_schema: 2', 'recalls: invalid'])
def test_unknown_node_schema_fails(saved, bad):
    brain, *_ = saved
    path = brain.path / 'nodes/alice.md'
    text = path.read_text()
    text = text.replace('status: active', bad)
    path.write_text(text)
    commit(brain)
    with pytest.raises(SnapshotError, match='Incompatible historical schema'):
        snapshot(brain, 'HEAD')


def test_corrupt_edge_and_symlink_fail(saved):
    brain, *_ = saved
    brain.edges_file.write_text('{"future_schema": 2}\n')
    commit(brain)
    with pytest.raises(SnapshotError, match='Incompatible historical schema'):
        snapshot(brain, 'HEAD')
    brain.edges_file.unlink()
    brain.edges_file.symlink_to('/etc/passwd')
    commit(brain)
    with pytest.raises(SnapshotError, match='regular files'):
        snapshot(brain, 'HEAD')


def test_cli_json_uses_historical_text(saved, capsys):
    from graph_engine.__main__ import cmd_snapshot
    brain, _, accepted, _ = saved
    engine = BrainEngine(brain, HashEmbedder())
    before = state(brain)
    cmd_snapshot(engine, [accepted, 'original note', '--json'])
    result = json.loads(capsys.readouterr().out)
    assert result['revision'] == accepted
    assert result['nodes'][0]['text'].endswith('original note')
    assert state(brain) == before
    cmd_snapshot(engine, [accepted, '--valid-at', '2021-06-01'])
    assert 'Fact validity at' in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        cmd_snapshot(engine, ['--', '--all'])
    assert exc.value.code == 1


@pytest.mark.parametrize('query,k', [('', 5), ('x'*4001, 5), ('text', 0), ('text', 101)])
def test_query_bounds(saved, query, k):
    brain, _, accepted, _ = saved
    with pytest.raises(SnapshotError):
        BrainEngine(brain, HashEmbedder()).snapshot_query(accepted, query, k=k)


def test_invalid_validity(saved):
    brain, *_ = saved
    with pytest.raises(SnapshotError, match='timestamp'):
        snapshot(brain, 'HEAD', fact_valid_at='invalid')


def test_current_copy_parent_chain_also_applies(saved, tmp_path, monkeypatch):
    brain, *_ = saved
    copy = Node('formerly independent', id='copy')
    brain.write_node(copy)
    old = commit(brain)
    copy.capture = {'input': 'new text', 'node_id': 'alice', 'duplicate': True, 'source': 'human'}
    brain.write_node(copy)
    commit(brain)
    secured, path, policy = secure(brain, tmp_path, monkeypatch)
    policy['graphs']['default']['nodes']['alice'] = {'read': []}
    path.write_text(json.dumps(policy))
    assert 'copy' not in {n.id for n in snapshot(secured, old)['nodes']}


def test_deleted_id_keeps_current_acl(saved, tmp_path, monkeypatch):
    brain, _, accepted, _ = saved
    (brain.path / 'nodes/alice.md').unlink()
    commit(brain)
    secured, path, policy = secure(brain, tmp_path, monkeypatch)
    policy['graphs']['default']['nodes']['alice'] = {'read': []}
    path.write_text(json.dumps(policy))
    assert 'alice' not in {n.id for n in snapshot(secured, accepted)['nodes']}


def test_undo_evidence_inherits_current_acl(saved, tmp_path, monkeypatch):
    brain, _, accepted, _ = saved
    # The present supporting records lost an older quote, but the saved review
    # decision still carries it. That older quote must remain access checked.
    old = Edge('alice', 'python', 'fact', pending=False, id='old',
               valid_from='2020-01-01T00:00:00Z')
    new = Edge('alice', 'python', 'fact', pending=False, id='new',
               valid_from=old.valid_from)
    before = old.to_dict()
    before['evidence'] = [{'node_id': 'evidence', 'text': 'private old quote'}]
    proposal = Edge('alice', 'python', 'fact_replacement', pending=False,
                    replacement={'old_fact_id': old.id, 'new_fact_id': new.id,
                                 'reason': 'replacement', 'basis': 'explicit evidence',
                                 'effective_at': None,
                                 'decision': {'before': [before, new.to_dict()],
                                              'after': [old.to_dict(), new.to_dict()]}})
    brain.write_edges([old, new, proposal])
    sha = commit(brain)
    secured, path, policy = secure(brain, tmp_path, monkeypatch)
    assert proposal.id in {e.id for e in snapshot(secured, sha)['edges']}
    policy['graphs']['default']['nodes']['evidence'] = {'read': []}
    path.write_text(json.dumps(policy))
    result = snapshot(secured, sha)
    assert {e.id for e in result['edges']} == {'old', 'new'}


def test_valid_at_and_when_still_filter_current_records(saved):
    brain, _, accepted, _ = saved
    engine = BrainEngine(brain, HashEmbedder())
    assert engine.snapshot_query(accepted, 'original note')['hits']
    assert engine.when('original note', '2099-01-01T00:00:00Z') == []
    assert engine.valid_at('2021-06-01T00:00:00Z')['edges'] == []
    assert all(n.id != 'python' for n in engine.valid_at('2021-06-01T00:00:00Z')['nodes'])


def test_structured_consolidation_quote_schema(saved):
    brain, *_ = saved
    edge = Edge('alice', 'evidence', 'extends', id='structured', origin='consolidator',
                evidence=[{'node_id': 'evidence', 'quote': 'Alice uses Python'}],
                valid_from=None, extracted_validity={'valid_from': None, 'valid_to': None})
    brain.write_edges([edge])
    sha = commit(brain)
    result = snapshot(brain, sha)
    assert result['edges'][0].valid_from is None
    assert result['edges'][0].evidence == edge.evidence
    assert result['edges'][0].pending


@pytest.mark.parametrize("timestamp", ["2021-01-01", "2021-01-01T00:00:00",
                                       "2021-01-01T00:00:00Z", "2020-12-31T19:00:00-05:00"])
def test_snapshot_validity_normalizes_legacy_timestamps(saved, timestamp):
    brain, _, _, _ = saved
    brain.write_node(Node("legacy alpha", id="legacy-a", created="2020-01-01"))
    brain.write_node(Node("legacy beta", id="legacy-b", created="2020-01-01T01:00:00+01:00"))
    brain.write_edges([Edge("legacy-a", "legacy-b", "fact", id="legacy-fact", pending=False,
                           valid_from="2021-01-01T00:00:00", valid_to="2022-01-01")])
    revision = commit(brain)
    before = state(brain)
    result = snapshot(brain, revision, fact_valid_at=timestamp)
    assert [e.id for e in result["edges"]] == ["legacy-fact"]
    assert state(brain) == before

"""Shared bounded review projections and optimistic review concurrency (#80)."""
import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from graph_engine import decision_schema as s, runtime
from graph_engine.access import SecuredBrain
from graph_engine.decision_service import DecisionService
from test_decision_memory import content_basis, files, check_record
from test_decision_service import save, review
from test_decision_impact import (service, scenario, commit, change_source, comparison,
                                  finding_envelope, link, evidence)


def queue(service, **kwargs):
    return service.read('review-queue', kwargs)


def detail(service, entry):
    return service.read('review-detail', {'reference': entry['reference']} if entry['kind'] == 'finding' else
                        dict(comparison=entry['comparison'], candidate_id=entry['candidate']['candidate_id']))


def changed(service):
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    return refs, comparison(before, after)


def test_pending_history_acknowledgment_resolution_and_material_successor(service):
    refs, comp = changed(service)
    entry, = queue(service, comparison=comp)['items']
    assert entry['kind'] == 'candidate'
    assert entry['comparison'] == comp
    candidate = entry['candidate']
    finding, = service.record_finding(finding_envelope(service, comp, candidate), commit=False)['receipt']['refs']
    pending, = queue(service, comparison=comp)['items']
    assert pending['kind'] == 'finding' and pending['reference'] == finding
    result = detail(service, pending)
    assert result['preview'] == service.preview()
    assert refs['claim']['id'] in {i['record']['id'] for i in result['records']}
    review(service, finding, axis='finding_workflow', after='acknowledged')
    assert queue(service, comparison=comp)['items'] == []
    old, = queue(service, history=True)['items']
    assert old['item']['state']['finding_workflow'] == 'acknowledged'
    review(service, refs['decision'], axis='decision_conclusion', after='needs_investigation', basis=[content_basis(refs['claim'])])
    decision_event = service.inspect(refs['decision'])['events'][-1]
    check, = save(service, check_record())
    review(service, finding, axis='finding_workflow', after='resolved', basis=[
        {'type':'event_ref', 'event_id':decision_event['event_id']}, content_basis(check)])
    assert queue(service)['items'] == []
    history, = queue(service, history=True)['items']
    assert history['item']['state']['finding_workflow'] == 'resolved'
    change_source(service, 'Materially new result')
    latest = commit(service)
    new = queue(service, comparison=comparison(comp['before'], latest))
    assert any(e['kind'] == 'candidate' and e['candidate']['candidate_id'] != candidate['candidate_id'] for e in new['items'])
    assert service.inspect(finding)['state']['finding_workflow'] == 'resolved'


def test_detail_keeps_current_and_previous_claims_support_opposition_and_unresolved_scope(service):
    refs = scenario(service)
    before = commit(service)
    original = service.inspect(refs['claim'])['record']
    from test_decision_memory import draft
    updated, = save(service, draft('claim', dict(original['payload'], text='Updated claim'),
        identity=original['id'], anchor=original['anchor_node_id'], previous=refs['claim']))
    _, counter = evidence(service, refs['profile'], node='counter', text='<img src=x onerror=attack()>')
    link(service, 'opposes', counter, updated, None, accepted=False)
    after = commit(service)
    entries = queue(service, comparison=comparison(before, after))['items']
    result = detail(service, entries[0])
    keys = {s.key(i['record']) for i in result['records']}
    assert s.key(refs['claim']) in keys and s.key(updated) in keys
    assert any(i['record']['kind'] == 'relationship' and i['record']['payload']['kind'] == 'opposes' for i in result['records'])
    assert any(i['record']['payload'].get('text') == '<img src=x onerror=attack()>\n' for i in result['records'])
    assert any(c['status'] == 'unknown' for e in entries for c in e['candidate']['comparison'])


def test_queue_detail_readonly_bounds(service, monkeypatch):
    refs, comp = changed(service)
    entry, = queue(service, comparison=comp)['items']
    before = files(service.brain)
    for name in ('ensure_ready','write_node','write_vectors','commit_and_push','pull'):
        monkeypatch.setattr(service.brain, name, lambda *a, **kw: pytest.fail('Review read mutation'))
    assert detail(service, entry)['records']
    import graph_engine.decision_review as module
    monkeypatch.setattr(module, 'QUEUE_LIMIT', 0)
    assert queue(service, comparison=comp)['truncated']
    monkeypatch.setattr(module, 'DETAIL_LIMIT', 2)
    tiny = detail(service, entry)
    assert tiny['truncated'] and len(tiny['records']) <= 2
    assert files(service.brain) == before


def test_review_reads_fail_closed_on_revocation_and_forgetting(service, tmp_path, monkeypatch):
    refs, comp = changed(service)
    entry, = queue(service, comparison=comp)['items']
    finding, = service.record_finding(finding_envelope(service, comp, entry['candidate']), commit=False)['receipt']['refs']
    policy = tmp_path / 'policy.json'
    policy.write_text(json.dumps({'graphs':{'default':{'roles':{'reader':'viewer'},'nodes':{'source':{'read':[]}}}},'tokens':{}}))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(policy))
    secured = DecisionService(SecuredBrain(str(service.brain.path), mode='git', graph_name='default',identity='reader'))
    response = queue(secured, comparison=comp, history=True)
    assert response['items'] == []
    assert 'Local observation' not in json.dumps(response)
    with pytest.raises(s.RecordConflict): detail(secured, entry)
    with pytest.raises(PermissionError):
        secured.read('review-detail', dict(reference=finding))
    monkeypatch.delenv('IG_ACCESS_POLICY')
    service.brain.tombstone_node('source')
    assert queue(service, history=True)['items'] == []
    with pytest.raises(s.RecordConflict): detail(service, entry)


def test_http_and_cli_share_review_reads_and_headers(service, monkeypatch):
    _, comp = changed(service)
    from graph_engine.server import app
    monkeypatch.setattr(runtime, 'make_brain', lambda: service.brain)
    client = TestClient(app)
    response = client.post('/api/decision-memory/read/review-queue', json={'comparison':comp})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json() == queue(service, comparison=comp)
    entry, = response.json()['items']
    body = dict(comparison=entry['comparison'],candidate_id=entry['candidate']['candidate_id'])
    assert client.post('/api/decision-memory/read/review-detail', json=body).json() == detail(service, entry)
    assert client.post('/api/decision-memory/read/review-queue', json={'history':'yes'}).status_code == 400
    import os
    env = dict(os.environ, IG_BRAIN_PATH=str(service.brain.path), IG_BRAIN_MODE='git', IDEAGRAPH_EMBEDDER='hash')
    proc = subprocess.run([sys.executable,'-m','graph_engine','decision','review-queue','-'],
        input=json.dumps({'comparison':comp}),text=True,capture_output=True,env=env)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == response.json()


def test_mcp_shares_review_reads(service, monkeypatch):
    pytest.importorskip('mcp', reason='requires optional [mcp] extra')
    from graph_engine.mcp import server as mcp
    _, comp = changed(service)
    monkeypatch.setattr(runtime, 'make_brain', lambda: service.brain)
    expected = queue(service, comparison=comp)
    entry, = expected['items']
    body = dict(comparison=entry['comparison'], candidate_id=entry['candidate']['candidate_id'])
    assert mcp.decision_review_queue({'comparison':comp}) == dict(ok=True, **expected)
    assert mcp.decision_review_detail(body) == dict(ok=True, **detail(service, entry))


def test_projection_detects_concurrent_evidence_change(service, monkeypatch):
    _, comp = changed(service)
    original = service.compare
    def race(envelope):
        result = original(envelope)
        change_source(service, 'Concurrent evidence')
        return result
    monkeypatch.setattr(service, 'compare', race)
    with pytest.raises(s.RecordConflict, match='changed'):
        queue(service, comparison=comp)


def test_empty_local_review_does_not_initialize_brain(tmp_path, monkeypatch):
    from graph_engine.brain import Brain
    brain = Brain(str(tmp_path / 'unused'), mode='local')
    service = DecisionService(brain)
    monkeypatch.setattr(runtime, 'make_engine', lambda: pytest.fail('Model engine constructed'))
    result = queue(service)
    assert result['items'] == [] and not result['truncated']
    assert result['preview']['generation'] == 0
    assert not brain.path.exists()


def test_detail_retains_intermediate_decision_versions_and_review_history(service):
    from test_decision_memory import draft
    refs, comp = changed(service)
    entry, = queue(service, comparison=comp)['items']
    original = service.inspect(refs['decision'])['record']
    second, = save(service, draft('decision', dict(original['payload'], rationale='Second rationale'),
        identity=original['id'], anchor=original['anchor_node_id'], previous=refs['decision']))
    review(service, second, axis='decision_conclusion', after='revise', basis=[content_basis(refs['claim'])])
    third, = save(service, draft('decision', dict(original['payload'], rationale='Third rationale'),
        identity=original['id'], anchor=original['anchor_node_id'], previous=second))
    result = detail(service, entry)
    decisions = [item for item in result['records'] if item['record']['kind'] == 'decision']
    assert {s.key(item['record']) for item in decisions} == {s.key(refs['decision']), s.key(second), s.key(third)}
    middle = next(item for item in decisions if s.key(item['record']) == s.key(second))
    assert middle['events'][-1]['to'] == 'revise'


def test_detail_neighborhood_depth_is_explicitly_incomplete(service, monkeypatch):
    refs, comp = changed(service)
    entry, = queue(service, comparison=comp)['items']
    _, ev = evidence(service, refs['profile'], node='additional', text='Additional opposition')
    link(service, 'opposes', ev, refs['claim'], None, accepted=False)
    import graph_engine.decision_review as module
    monkeypatch.setattr(module, 'DETAIL_DEPTH', 0)
    result = detail(service, entry)
    assert result['truncated']
    assert ev['id'] not in {i['record']['id'] for i in result['records']}

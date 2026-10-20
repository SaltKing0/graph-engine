"""Fresh finding review pins the successor's existing reviews and their inputs."""
from pathlib import Path
from uuid import uuid4

import pytest

from graph_engine.brain import Brain
from graph_engine.decision_service import DecisionService
from tools.decision_benchmark.reviewed_development import journal
from tools.decision_benchmark.support_paths import capture, prepare, review


@pytest.fixture
def refreshed(tmp_path):
    sources, case, packet = prepare()
    path = tmp_path / 'brain'
    replay = capture(path, sources, case, packet)
    service = DecisionService(Brain(str(path), mode='git'))
    comp = dict(schema='dm.compare/1', before=replay['initial']['revision'], after=replay['final']['revision'])
    candidate = next(c for c in service.compare(comp)['candidates'] if 'support_withdrawn' in c['reasons'])
    return service, replay, comp, candidate


def confirm(service, comp, candidate):
    preview = service.preview()
    return service.record_finding(dict(schema='dm.finding-review/1', idempotency_key=str(uuid4()),
        expected_generation=preview['generation'], expected_heads=preview['heads'], comparison=comp,
        candidate_id=candidate['candidate_id'], disposition='confirmed',
        reason='Scripted development regression; no independent human review or activation.'),
        commit=False)['receipt']['refs'][0]


def test_successor_reviews_are_pinned_and_finding_history_survives(refreshed):
    service, replay, comp, candidate = refreshed
    refs = replay['references']
    successor_events = {e['event_id'] for e in service.inspect(refs['claim'])['events']}
    assert successor_events <= set(candidate['basis_event_ids'])
    assert refs['claim'] in candidate['basis_refs']
    assert refs['support'] in candidate['basis_refs']
    assert refs['sources']['controls-v2/surviving-support-update'] in candidate['basis_refs']
    before = journal(Path(service.brain.path))
    finding = confirm(service, comp, candidate)
    item = service.inspect(finding)
    assert finding['id'] == refs['finding']['id'] and item['record']['previous'] == refs['finding']
    assert not item['basis_changed']
    assert item['state'] == dict(finding_disposition='confirmed', finding_workflow='open')
    assert service.inspect(refs['finding'])['state']['finding_workflow'] == 'acknowledged'
    after = journal(Path(service.brain.path))
    assert after['versions'][:len(before['versions'])] == before['versions']
    assert after['events'][:len(before['events'])] == before['events']
    assert service.inspect(refs['decision'])['state']['decision'] == 'proposed'
    assert service.inspect(refs['dependency'])['state']['workflow'] == 'proposed'


@pytest.mark.parametrize('changed', ['assessment', 'source', 'support'])
def test_fresh_review_stales_on_current_head_review_or_basis_change(refreshed, changed):
    service, replay, comp, candidate = refreshed
    refs = replay['references']
    finding = confirm(service, comp, candidate)
    if changed == 'assessment':
        review(service, refs['claim'], 'epistemic', 'inconclusive',
               [dict(type='content_ref', ref=refs['evidence']['Y1'])],
               'Changed synthetic assessment; old finding must need refresh.')
    elif changed == 'support':
        review(service, refs['support'], 'availability', 'withdrawn',
               [dict(type='content_ref', ref=refs['evidence']['Y1'])],
               'Synthetic support withdrawal; no independent new case.')
    else:
        node = service.brain.read_node('surviving-support-update')
        node.text += '\nScratch provenance-change regression; frozen development source remains unchanged.\n'
        service.brain.write_node(node)
    assert service.inspect(finding)['basis_changed']
    assert service.inspect(refs['decision'])['state']['decision'] == 'proposed'

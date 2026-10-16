"""Whole production workflow and honest evaluation-boundary regressions (#81)."""
from __future__ import annotations

from copy import deepcopy
import json
import socket

import pytest

from tools.decision_benchmark.corpus import DATA, load_bundle, visible_inputs
from tools.decision_benchmark.production import execute
from tools.decision_benchmark.readiness import assess
from tools.decision_benchmark.scoring import score


def test_complete_workflow_without_network_or_models_preserves_legacy_and_forgetting(tmp_path, monkeypatch):
    from examples.decision_workflow import run

    def forbidden(*args, **kwargs):
        pytest.fail('Offline walkthrough attempted network or model initialization')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr('graph_engine.runtime.make_engine', forbidden)
    monkeypatch.setenv('IDEAGRAPH_EMBEDDER', 'st')
    result = run(tmp_path / 'brain', tmp_path / 'report.json')
    assert result['status'] == 'complete', result.get('error')
    assert len(result['checks']) == 7 and all(result['checks'].values())
    assert result['cost_effort']['human_review_minutes'] is None
    stages = {row['name'] for row in result['stages']}
    assert {'import', 'proposal', 'scripted_review', 'impact', 'agent_context', 'review_history',
            'historical_reconstruction', 'review_detail'} <= stages
    assert not result['release_ready']
    before = (tmp_path / 'brain' / 'nodes' / 'legacy-memory.md').read_bytes()
    with pytest.raises(ValueError, match='empty dedicated'):
        run(tmp_path / 'brain', tmp_path / 'second.json')
    assert (tmp_path / 'brain' / 'nodes' / 'legacy-memory.md').read_bytes() == before


def small_case():
    inputs, labels, freeze = load_bundle(DATA / 'controls-v2')
    event = inputs['events'][0]
    visible = visible_inputs(inputs, event, DATA / 'controls-v2')
    visible['dependencies'] = visible['dependencies'][:1]
    decision_id = visible['dependencies'][0]['decision_id']
    visible['decisions'] = [d for d in visible['decisions'] if d['id'] == decision_id]
    return inputs, labels, freeze, event, visible


def test_production_alerts_require_exact_accepted_path_and_keep_unknown_scope(tmp_path, monkeypatch):
    _, _, _, event, visible = small_case()
    monkeypatch.setattr(socket.socket, 'connect', lambda *args: pytest.fail('Network requested'))
    result = execute(visible, event, tmp_path / 'curated', 'curated', budget=4000, k=5)
    alert, = result['alerts']
    dep, = visible['dependencies']
    assert alert['path'] == [event['source_id'], event['changed_source_id'], dep['id'], dep['decision_id']]
    assert alert['uncertainty_reason']
    assert result['complete'] and result['context_within_budget']
    # Proposed dependencies cannot acquire acceptance simply by selecting a profile.
    proposed = deepcopy(visible)
    proposed['dependencies'][0]['status'] = 'proposed'
    result = execute(proposed, event, tmp_path / 'proposed', 'proposed', budget=1, k=5)
    assert result['alerts'] == [] and result['context_within_budget']
    assert any(row['stage'] == 'context' and row['output']['omitted'] for row in result['raw_outputs'])


def test_missing_update_retains_partial_failure_outputs(tmp_path):
    _, _, _, event, visible = small_case()
    trace = {}
    missing = dict(visible, documents=[d for d in visible['documents'] if d['source_id'] != event['source_id']])
    with pytest.raises(ValueError, match='no visible source'):
        execute(missing, event, tmp_path / 'error', 'curated', budget=4000, k=5, trace=trace)
    assert trace['raw_outputs'] and trace['latency_ms']


def test_unmeasured_pending_and_synthetic_coverage_cannot_pass_release_gates():
    _, _, freeze, _, _ = small_case()
    pending = score([dict(event_id='e', eligible_decisions=['d'], alerts=[], error='failure')],
                    {'pairs': {'e/d': {'outcome': 'pending'}}})
    assessment = assess(pending, freeze['gates'], independent=True)
    assert assessment['gates']['false_alerts']['status'] == 'unmeasured'
    assert assessment['gates']['heldout_positive']['status'] == 'fail'
    assert assessment['gates']['median_review_time_reduction']['observed'] is None
    assert pending['counts']['error_pairs'] == 1
    positive = score([dict(event_id='e', eligible_decisions=['d'], alerts=[dict(decision_id='d', path=['p'])])],
                     {'pairs': {'e/d': {'outcome': 'positive', 'valid_paths': [['p']]}}})
    assessment = assess(positive, freeze['gates'], independent=False)
    assert assessment['gates']['heldout_positive']['observed'] == 0
    assert not assessment['passed']


def test_changed_gold_cannot_change_production_paths_or_source_inputs(tmp_path):
    import shutil
    from tools.decision_benchmark.freeze_sources import freeze
    from tools.decision_benchmark.production import run

    root = tmp_path / 'corpus'
    shutil.copytree(DATA / 'controls-v2', root)
    inputs, labels, _ = load_bundle(root)
    event = inputs['events'][0]
    dep = inputs['dependencies'][0]
    inputs['events'] = [event]
    inputs['decisions'] = [d for d in inputs['decisions'] if d['id'] == dep['decision_id']]
    inputs['dependencies'] = [dep]
    pair = event['id'] + '/' + dep['decision_id']
    labels['pairs'] = {pair: labels['pairs'][pair]}
    contract = (root / 'contract.md').read_bytes()
    freeze(root, inputs, labels, contract)
    first = run(root, tmp_path / 'first.json', split='all')
    labels['pairs'][pair].update(outcome='negative', valid_paths=[], rationale='SECRET_GOLD_CANARY')
    freeze(root, inputs, labels, contract)
    second = run(root, tmp_path / 'second.json', split='all')
    assert first['smoke_passed'] and second['smoke_passed']
    assert first['scores'] != second['scores']
    left, right = first['results'][0], second['results'][0]
    assert left['visible_inputs_sha256'] == right['visible_inputs_sha256']
    for mode in ('curated', 'proposed'):
        def normalized(row: dict) -> list[dict]:
            return [{k: v for k, v in alert.items() if k != 'candidate_id'} for alert in row['profiles'][mode]['alerts']]
        assert normalized(left) == normalized(right)
        assert 'SECRET_GOLD_CANARY' not in json.dumps(right['profiles'][mode]['raw_outputs'])

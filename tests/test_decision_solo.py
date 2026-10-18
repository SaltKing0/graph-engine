"""No hidden-data access, no oracle inputs and no invented independent quality."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from tools.decision_benchmark import solo
from tools.decision_benchmark.annotation_packets import BUNDLE, prepare_development
from tools.decision_benchmark.corpus import visible_inputs


def test_solo_runtime_matches_frozen_development_allowlist_without_labels(monkeypatch):
    original = Path.read_bytes
    metadata = json.loads(original(BUNDLE / 'inputs.json'))
    forbidden = {BUNDLE / 'labels.json', solo.NOTES} | {
        BUNDLE / source['file'] for source in metadata['sources'] if source['split'] == 'evaluation'}

    def guarded(path):
        assert path not in forbidden, f'Forbidden evaluation/annotation access: {path}'
        return original(path)

    monkeypatch.setattr(Path, 'read_bytes', guarded)
    packet, _ = prepare_development()
    for case in packet['cases']:
        runtime, event = solo.runtime_inputs(case)
        frozen = next(e for e in metadata['events'] if e['id'] == event['id'])
        assert runtime == visible_inputs(metadata, frozen, BUNDLE)
        assert event['split'] == 'development'
        assert set(runtime) == {'documents', 'decisions', 'dependencies'}


def test_changed_engineering_judgments_never_enter_runtime_or_become_independent_scores(tmp_path, monkeypatch):
    notes = json.loads(solo.NOTES.read_bytes())
    for pair in notes['pairs']:
        pair['rationale'] = pair['uncertainty'] = 'SOLO_EXPECTATION_CANARY'
    path = tmp_path / 'notes.json'
    path.write_text(json.dumps(notes))
    monkeypatch.setattr(solo, 'NOTES', path)
    calls = []

    def fake(visible, event, path, mode, **kwargs):
        assert 'SOLO_EXPECTATION_CANARY' not in json.dumps([visible, event])
        calls.append((event['id'], mode))
        return dict(alerts=[], complete=True, context_within_budget=True)

    report = solo.run(tmp_path / 'report.json', executor=fake)
    assert report['status'] == 'complete' and len(calls) == 16
    assert report['attempted_pairs_per_profile'] == 27
    assert report['semantic_quality'] is report['human_calibration'] is report['human_review_time'] is None
    assert not report['release_ready'] and sum(report['independent_final_coverage'].values()) == 0
    assert 'scores' not in report


@pytest.mark.parametrize('damage', ['quote', 'duplicate', 'missing', 'independence', 'invented-path',
                                   'wrong-role', 'wrong-revision', 'wrong-count'])
def test_solo_notes_reject_bad_refs_missing_denominators_and_false_independence(damage):
    packet, _ = prepare_development()
    notes = json.loads(solo.NOTES.read_bytes())
    if damage == 'quote':
        notes['pairs'][0]['evidence'][0]['quote'] += 'invented'
    elif damage == 'duplicate':
        notes['pairs'].append(deepcopy(notes['pairs'][0]))
    elif damage == 'missing':
        notes['pairs'].pop()
    elif damage == 'independence':
        notes['independent'] = True
    elif damage == 'invented-path':
        notes['pairs'][0]['accepted_historical_path'] = ['invented', 'accepted', 'path']
    elif damage == 'wrong-role':
        notes['pairs'][0]['evidence'] = [deepcopy(notes['pairs'][0]['evidence'][0])] * 2
    elif damage == 'wrong-revision':
        notes['pairs'][0]['conditions']['code_revision'] = 'wrong'
    else:
        notes['pair_count'] = 0
    with pytest.raises(ValueError):
        solo.validate_notes(packet, notes)


def test_failed_profile_is_visible_and_existing_reports_are_never_overwritten(tmp_path):
    def fail(*args, **kwargs):
        raise RuntimeError('source/proposal preparation failed')

    path = tmp_path / 'report.json'
    report = solo.run(path, executor=fail)
    assert report['status'] == 'completed_with_errors'
    assert len(report['results']) == 8 and report['attempted_pairs_per_profile'] == 27
    assert all(p['error']['type'] == 'RuntimeError' for r in report['results'] for p in r['profiles'].values())
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        solo.run(path, executor=fail)
    assert path.read_bytes() == original

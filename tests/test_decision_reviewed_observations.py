"""Known development field review and conservative source preparation."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tools.decision_benchmark.corpus import canonical, digest
from tools.decision_benchmark.production import execute, source_update
from tools.decision_benchmark.reviewed_development import REVIEWS, check_report_fields, review_inputs
from tools.decision_benchmark.reviewed_observations import AUTHOR, assess
from tools.decision_benchmark.structured_development import TRANSCRIPTIONS, development_inputs


@pytest.fixture
def prepared():
    sources, cases = development_inputs()
    packet = json.loads(TRANSCRIPTIONS.read_bytes())
    reviews = review_inputs(sources, packet, json.loads(REVIEWS.read_bytes()))
    return sources, cases, packet, reviews


def inputs(prepared, family):
    sources, cases, _, reviews = prepared
    case = next(c for c in cases if c['id'] == 'controls-v2/event-' + family)
    keys = ['controls-v2/' + case['event'][k] for k in ('changed_source_id', 'source_id')]
    review = dict(schema='dm.development.field-review/1', author=AUTHOR,
                  sources=deepcopy([reviews[k] for k in keys]))
    update = source_update(case['runtime']['documents'], case['event'])
    for side, key in zip(('old', 'new'), keys):
        update[side]['text'] = sources[key]['text']
    return case, review, update


@pytest.mark.parametrize('family,retained,status', [
    ('comparable', False, 'changed_value_or_sample'), ('changed-conditions', True, 'different_conditions'),
    ('time-only', True, 'same_value'), ('duplicate-citation', True, 'same_recorded_measurement'),
    ('surviving-support', False, 'unknown')])
def test_reviewed_known_sources(prepared, family, retained, status):
    case, review, update = inputs(prepared, family)
    result = assess(review, update, available_at=case['event']['at'])
    assert result['retain_basis'] is retained
    assert result['facts'][0]['status'] == status
    assert not result['independent_acceptance'] and not result['author']['human']
    missing = assess(None, update, available_at=case['event']['at'])
    assert not missing['retain_basis'] and missing['author'] is None


@pytest.mark.parametrize('mutation', ['unit', 'dimension', 'metric', 'sample', 'namespace', 'complete',
                                     'root', 'subject', 'empty'])
def test_ambiguity_retains_basis_change(prepared, mutation):
    family = 'duplicate-citation' if mutation in ('root', 'subject') else 'time-only'
    case, review, update = inputs(prepared, family)
    row = review['sources'][1]
    fact = row['observations']['facts'][0]
    if mutation == 'unit': fact['metric']['unit'] = None
    if mutation == 'dimension': fact['conditions']['environment'] = None
    if mutation == 'metric': fact['metric']['name'] = fact['subject']
    if mutation == 'sample': fact['metric']['sample_count'] = fact['metric']['value']
    if mutation == 'namespace': row['namespace'] = 'another-experiment'
    if mutation == 'complete': row['complete'] = False
    if mutation == 'root': fact['measurement_lineage'] = None
    if mutation == 'subject': fact['subject'] = fact['measurement_lineage']
    if mutation == 'empty': row['observations']['facts'] = []
    # Re-signing is a new developer interpretation, never original review proof.
    row['facts_sha256'] = digest(canonical(row['observations']['facts']))
    if mutation == 'sample':
        with pytest.raises(ValueError): assess(review, update, available_at=case['event']['at'])
    else:
        assert not assess(review, update, available_at=case['event']['at'])['retain_basis']


@pytest.mark.parametrize('mutation', ['hash', 'facts', 'text', 'role', 'extra', 'duplicate', 'incomplete_chunks'])
def test_invalid_review_rejected(prepared, mutation):
    case, review, update = inputs(prepared, 'time-only')
    if mutation == 'hash': review['sources'][0]['text_sha256'] = '0' * 64
    if mutation == 'facts': review['sources'][0]['observations']['facts'][0]['metric']['unit'] = None
    if mutation == 'text': update['new']['text'] = update['new']['text'].replace('0.8', '0.2')
    if mutation == 'role': review['author'] = {**AUTHOR, 'independent': True}
    if mutation == 'extra': review['expected_impact'] = False
    if mutation == 'duplicate': review['sources'][1] = review['sources'][0]
    if mutation == 'incomplete_chunks': update['new']['well_formed_task_chunks'] = False
    with pytest.raises(ValueError): assess(review, update, available_at=case['event']['at'])


@pytest.mark.parametrize('family,alerts', [('comparable', 1), ('changed-conditions', 0),
    ('time-only', 0), ('duplicate-citation', 0), ('surviving-support', 1)])
def test_actual_production_preparation_preserves_updates_and_reviews(prepared, tmp_path, family, alerts):
    case, review, _ = inputs(prepared, family)
    result = execute(deepcopy(case['runtime']), case['event'], tmp_path / family, 'curated',
                     budget=4000, k=5, observation_review=review)
    assert len(result['alerts']) == alerts
    assert result['complete'] and result['context_within_budget']
    assert result['source_update']['captured_update_refs']
    assert bool(result['source_update']['retained_basis_refs']) == (alerts == 0)
    # Impact output itself contains no candidates; no normalized alert filtering.
    comparison = next(o['output'] for o in result['raw_outputs'] if o['stage'] == 'impact')
    assert len(comparison['candidates']) == alerts
    events = [o['output'] for o in result['raw_outputs'] if o['stage'] == 'scripted_review']
    assert len(events) == 1  # Only original curated dependency wiring acceptance.
    from tools.decision_benchmark.reviewed_development import journal
    from graph_engine.decision_schema import hash_record
    snapshot = journal(tmp_path / family)
    assert snapshot['versions'] and snapshot['events']
    assert all(hash_record(record) == record['version_id'] for record in snapshot['versions'])
    assert all(event['axis'] == 'workflow' and event['to'] == 'accepted' for event in snapshot['events'])
    by_ref = {(v['id'], v['version_id']): v for v in snapshot['versions']}
    for ref in result['source_update']['captured_update_refs']:
        assert by_ref[(ref['id'], ref['version_id'])]['kind'] == 'source'
    for ref in result['source_update']['retained_basis_refs']:
        assert by_ref[(ref['id'], ref['version_id'])]['previous'] is None


def test_report_paths_and_unknown_units(prepared):
    sources, _, packet, _ = prepared
    row = next(r for r in packet['sources'] if r['source_id'] == 'project-v1/graph-report')
    checked = check_report_fields(sources[row['source_id']], row)
    assert len(checked) == 12
    assert [r['n'] for r in checked] == [2] * 6 + [10] * 6
    assert all(r['unit'] is None and r['measurement_root'] is None for r in checked)
    damaged = deepcopy(row)
    damaged['facts'][0]['subject']['value'] = 'graph-engine-expanded'
    with pytest.raises(ValueError): check_report_fields(sources[row['source_id']], damaged)


def test_no_reserved_sources_or_labels(prepared, monkeypatch):
    from tools.decision_benchmark.corpus import DATA
    forbidden = set()
    for bundle in ('controls-v2', 'project-v1'):
        root = DATA / bundle
        metadata = json.loads((root / 'inputs.json').read_bytes())
        forbidden.add(root / 'labels.json')
        forbidden.update(root / s['file'] for s in metadata['sources'] if s['split'] == 'evaluation')
    real_text, real_bytes = Path.read_text, Path.read_bytes
    def guard(path):
        assert path not in forbidden, f'Forbidden read: {path}'
    def read_text(path, *args, **kwargs):
        guard(path); return real_text(path, *args, **kwargs)
    def read_bytes(path, *args, **kwargs):
        guard(path); return real_bytes(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read_text)
    monkeypatch.setattr(Path, 'read_bytes', read_bytes)
    sources, _ = development_inputs()
    review_inputs(sources, json.loads(TRANSCRIPTIONS.read_bytes()), json.loads(REVIEWS.read_bytes()))


def test_equal_lexemes_cannot_replace_json_field_identity(prepared):
    sources, _, packet, _ = prepared
    row = next(r for r in packet['sources'] if r['source_id'] == 'project-v1/graph-report')
    damaged = deepcopy(row)
    damaged['facts'][0]['metric']['value'] = deepcopy(row['facts'][1]['metric']['value'])
    with pytest.raises(ValueError, match='different JSON field'):
        check_report_fields(sources[row['source_id']], damaged)
    damaged = deepcopy(row)
    damaged['facts'][0]['subject'] = deepcopy(row['facts'][6]['subject'])
    with pytest.raises(ValueError, match='different JSON field'):
        check_report_fields(sources[row['source_id']], damaged)


@pytest.mark.parametrize('text', ['{"a":1,"a":2}', '{"a":}', '[1,]', '{"a" 1}',
                                 '{"a":1} trailing', '{"a":NaN}'])
def test_json_field_locator_rejects_ambiguous_or_invalid_json(text):
    from tools.decision_benchmark.json_source_fields import spans
    with pytest.raises(ValueError): spans(text)


def test_every_old_measurement_and_every_new_statement_matters(prepared):
    case, review, update = inputs(prepared, 'time-only')
    old = review['sources'][0]
    another = deepcopy(old['observations']['facts'][0])
    another['id'] = 'additional-incomplete-measurement'
    another['metric']['unit'] = None
    old['observations']['facts'].append(another)
    old['facts_sha256'] = digest(canonical(old['observations']['facts']))
    assert not assess(review, update, available_at=case['event']['at'])['retain_basis']
    case, review, update = inputs(prepared, 'time-only')
    new = review['sources'][1]
    another = deepcopy(new['observations']['facts'][0])
    another['id'] = 'additional-incomplete-update'
    another['metric']['unit'] = None
    new['observations']['facts'].append(another)
    new['facts_sha256'] = digest(canonical(new['observations']['facts']))
    assert not assess(review, update, available_at=case['event']['at'])['retain_basis']


def test_runner_keeps_all_attempts_errors_and_missing_acceptance(tmp_path, monkeypatch):
    from tools.decision_benchmark import reviewed_development as runner
    calls = []
    def fake(visible, event, path, mode, **kwargs):
        assert set(visible) == {'documents', 'decisions', 'dependencies'}
        calls.append((event['id'], mode, kwargs['observation_review']))
        if len(calls) == 1:
            raise RuntimeError('deliberate development execution failure')
        return dict(alerts=[], complete=True, context_within_budget=True)
    monkeypatch.setattr(runner, 'execute', fake)
    monkeypatch.setattr(runner, 'journal', lambda path: dict(versions=[], events=[]))
    output = tmp_path / 'new'
    report = runner.run(output)
    assert len(calls) == 26 and report['status'] == 'completed_with_errors'
    assert sum(review is not None for _, _, review in calls) == 10
    assert report['results'][0]['profiles']['curated']['error']['type'] == 'RuntimeError'
    assert report['semantic_scores'] is report['human_review'] is report['user_sessions'] is None
    assert not report['independent_acceptance'] and not report['release_ready']
    assert sum(report['independent_final_coverage'].values()) == 0
    with pytest.raises(FileExistsError): runner.run(output)


def test_root_annotation_cannot_override_changed_value(prepared):
    case, review, update = inputs(prepared, 'comparable')
    # A root assertion cannot override actual measurement kind/value. Reuse an
    # existing exact source-bound subject as the token; it is not the old root.
    new = review['sources'][1]
    new['observations']['facts'][0]['measurement_lineage'] = deepcopy(
        new['observations']['facts'][0]['subject'])
    new['facts_sha256'] = digest(canonical(new['observations']['facts']))
    result = assess(review, update, available_at=case['event']['at'])
    assert not result['retain_basis']
    assert result['facts'][0]['status'] == 'changed_value_or_sample'

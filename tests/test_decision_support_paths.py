"""Source-bound withdrawal paths, fresh successor review and retained history."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from graph_engine import decision_schema as s
from graph_engine.brain import Brain
from graph_engine.decision_service import DecisionService
from tools.decision_benchmark.corpus import DATA, digest
from tools.decision_benchmark.support_paths import assess_source, capture, prepare, run


@pytest.fixture(scope='module')
def prepared():
    return prepare()


@pytest.fixture(scope='module')
def captured(prepared, tmp_path_factory):
    path = tmp_path_factory.mktemp('support-paths') / 'brain'
    sources, case, packet = prepared
    return path, capture(path, sources, case, packet)


def test_withdrawal_explains_two_distinct_paths_without_independence(captured):
    _, result = captured
    refs = result['references']
    candidate = next(c for c in result['comparison']['candidates'] if 'support_withdrawn' in c['reasons'])
    assert candidate['target'] == refs['old_decision']
    assert 'comparability_unknown' not in candidate['reasons']
    assert [x['evidence'] for x in candidate['support']['removed']] == [refs['evidence']['X1']]
    assert [x['evidence'] for x in candidate['support']['remaining']] == [refs['evidence']['Y1']]
    removed, remaining = candidate['support']['removed'][0], candidate['support']['remaining'][0]
    assert removed['sources'] == remaining['sources']
    assert removed['lineage_ids'] == remaining['lineage_ids']
    assert len(removed['lineage_ids']) == 1
    assert removed['lineage_ids'][0].startswith('document-sha256:')
    assert removed['independence'] == remaining['independence'] == 'not inferred'
    assert removed['status'] == 'withdrawn_or_stale' and remaining['status'] == 'available'
    assert candidate['paths']
    assert any(step['relationship'] == refs['old_supports']['X1']
               for path in candidate['paths'] for step in path)


def test_successor_has_new_basis_and_fresh_reviews(captured):
    _, result = captured
    refs, proposal, final = result['references'], result['proposal'], result['final']
    assert proposal['claim']['record']['previous'] == refs['old_claim']
    assert proposal['claim']['state']['epistemic'] == 'unassessed'
    assert proposal['claim']['state']['workflow'] == 'proposed'
    assert proposal['claim']['events'] == []
    assert proposal['support']['state']['workflow'] == 'proposed'
    assert final['claim']['state']['epistemic'] == 'supported'
    assert final['claim']['effective_assessment'] == 'supported'
    assert not final['claim']['basis_changed']
    assert final['claim']['record']['provenance']['inputs'] == [refs['evidence']['Y1'],
        refs['sources']['controls-v2/surviving-support-update']]
    assert final['support']['record']['payload']['source'] == refs['evidence']['Y1']
    assert final['support']['record']['payload']['target'] == refs['claim']
    old_events = {e['event_id'] for e in result['initial']['journal']['events']}
    for item in (final['claim'], final['support']):
        assert item['events']
        assert all(e['event_id'] not in old_events and 'Scripted synthetic developer' in e['reason']
                   for e in item['events'])
        for e in item['events']:
            assert refs['evidence']['X1'] not in s.content_refs(e['basis'])
    assert result['assessment']['threshold'] == '0.7'
    assert result['assessment']['value'] == '0.8'
    assert result['assessment']['statistical_sufficiency'] is None


def test_old_records_and_judgments_remain_exact(captured):
    path, result = captured
    initial, final, refs = result['initial'], result['final'], result['references']
    assert final['journal']['versions'][:len(initial['journal']['versions'])] == initial['journal']['versions']
    assert final['journal']['events'][:len(initial['journal']['events'])] == initial['journal']['events']
    assert final['old_claim']['record'] == initial['claim']['record']
    assert final['old_claim']['events'] == initial['claim']['events']
    assert final['old_claim']['basis_changed']
    assert final['old_claim']['effective_assessment'] == 'inconclusive'
    assert final['historical_claim']['record'] == initial['claim']['record']
    assert final['decision']['record']['previous'] == refs['old_decision']
    assert final['decision']['state']['decision'] == 'proposed'
    assert final['decision']['events'] == []
    assert final['dependency']['state']['workflow'] == 'proposed'
    assert final['old_decision']['state']['decision'] == 'current'
    assert final['old_decision']['state']['decision_conclusion'] == 'needs_investigation'
    assert final['finding']['state']['finding_workflow'] == 'acknowledged'
    fresh = DecisionService(Brain(str(path), mode='git'))
    assert fresh.inspect(refs['evidence']['X1'])['state']['availability'] == 'withdrawn'
    assert fresh.inspect(refs['evidence']['Y1'])['state']['availability'] == 'available'
    assert all(s.hash_record(v) == v['version_id'] for v in final['journal']['versions'])


@pytest.mark.parametrize('mutation', ['hash', 'unit', 'value', 'threshold', 'value-from-X1',
    'condition', 'condition-role', 'root', 'subject', 'human', 'independent', 'gold', 'unit-role'])
def test_invalid_source_roles_rejected_before_writes(prepared, tmp_path, mutation):
    sources, case, original = prepared
    packet = deepcopy(original)
    if mutation == 'hash': packet['sources'][packet['rule']['source_id']]['text_sha256'] = '0' * 64
    if mutation == 'unit': packet['rule']['unit'] = None
    if mutation == 'value': packet['remaining']['value']['value'] = '0.9'
    if mutation == 'threshold': packet['rule']['threshold'] = packet['remaining']['value']
    if mutation == 'value-from-X1':
        from tools.decision_benchmark.observations import binding
        packet['remaining']['value'] = binding(sources[packet['rule']['source_id']]['text'], '0.8', kind='decimal')
    if mutation == 'condition': packet['remaining']['conditions']['environment'] = None
    if mutation == 'condition-role': packet['remaining']['conditions']['environment'] = packet['remaining']['conditions']['workload']
    if mutation == 'root': packet['remaining']['measurement_root'] = packet['withdrawn']['measurement_root']
    if mutation == 'subject': packet['update']['remaining_subject'] = packet['update']['withdrawn_subject']
    if mutation == 'human': packet['author']['human'] = True
    if mutation == 'independent': packet['author']['independent'] = True
    if mutation == 'gold': packet['expected_impact'] = False
    if mutation == 'unit-role': packet['rule']['unit'] = packet['rule']['action']
    path = tmp_path / 'must-not-exist'
    with pytest.raises(ValueError): capture(path, sources, case, packet)
    assert not path.exists()


def test_source_identity_and_citations(prepared, captured):
    sources, _, packet = prepared
    _, result = captured
    refs = result['references']
    records = {s.key(v): v for v in result['final']['journal']['versions']}
    for name, ref in refs['sources'].items():
        payload = records[s.key(ref)]['payload']
        assert payload['artifact']['sha256'] == digest(sources[name]['text'].encode())
        assert payload['text'] == sources[name]['text'] + '\n'  # Exact Node serialization.
    for subject, ref in refs['evidence'].items():
        ev = records[s.key(ref)]['payload']
        assert ev['lineage_ids'] == []
        assert json.loads(ev['interpretation'])['source_declared_root'] == 'run-' + subject
        for citation in ev['sources']:
            p = citation['passage']
            assert records[s.key(citation['ref'])]['payload']['text'][p['start']:p['end']] == p['quote']
    assert not any(v['kind'] == 'result' for v in records.values())  # No invented runs.
    assert assess_source(packet, sources, prepared[1])['independently_reviewed_measurement_independence'] is None


def test_no_reserved_reads_or_output_overwrite(monkeypatch, tmp_path):
    forbidden = set()
    for bundle in ('controls-v2', 'project-v1'):
        root = DATA / bundle
        metadata = json.loads((root / 'inputs.json').read_bytes())
        forbidden.add(root / 'labels.json')
        forbidden.update(root / row['file'] for row in metadata['sources'] if row['split'] == 'evaluation')
    raw, text = Path.read_bytes, Path.read_text
    def read_bytes(path):
        assert path not in forbidden
        return raw(path)
    def read_text(path, *args, **kwargs):
        assert path not in forbidden
        return text(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_bytes', read_bytes)
    monkeypatch.setattr(Path, 'read_text', read_text)
    sources, case, packet = prepare()
    assert packet['case_id'] == case['id']
    nonempty = tmp_path / 'existing'
    nonempty.mkdir()
    (nonempty / 'keep').write_text('foreign work')
    with pytest.raises(ValueError): capture(nonempty, sources, case, packet)
    with pytest.raises(FileExistsError): run(nonempty)
    with pytest.raises(ValueError): run(DATA / 'never-write')
    assert (nonempty / 'keep').read_text() == 'foreign work'

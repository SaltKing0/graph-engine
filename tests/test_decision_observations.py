"""Source-bound development proposals cannot become gold or silence warnings."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from graph_engine.brain import Brain
from graph_engine.decision_service import DecisionService
from tools.decision_benchmark import observations as o, structured_development as d
from tools.decision_benchmark.annotation_packets import BUNDLE
from tools.decision_benchmark.corpus import DATA


def prepared():
    sources, cases = d.development_inputs()
    packet = json.loads(d.TRANSCRIPTIONS.read_bytes())
    o.validate(packet, sources)
    return sources, cases, packet


def rows(packet):
    return {r['source_id']: r for r in packet['sources']}


def test_only_known_development_sources_are_opened_without_labels_or_reserved_bytes(monkeypatch):
    forbidden = set()
    for bundle in (DATA / 'controls-v2', BUNDLE):
        metadata = json.loads((bundle / 'inputs.json').read_bytes())
        forbidden.add(bundle / 'labels.json')
        forbidden.update(bundle / s['file'] for s in metadata['sources'] if s['split'] == 'evaluation')
    read_bytes, read_text = Path.read_bytes, Path.read_text

    def guarded_bytes(path):
        assert path not in forbidden, f'Forbidden read: {path}'
        return read_bytes(path)

    def guarded_text(path, *a, **kw):
        assert path not in forbidden, f'Forbidden read: {path}'
        return read_text(path, *a, **kw)

    monkeypatch.setattr(Path, 'read_bytes', guarded_bytes)
    monkeypatch.setattr(Path, 'read_text', guarded_text)
    sources, cases, packet = prepared()
    assert len(sources) == 30 and len(cases) == 13
    assert all(c['event']['split'] == 'development' for c in cases)
    assert sum(len(r['facts']) for r in packet['sources']) == 24


@pytest.mark.parametrize('damage', ['source-hash','missing-source','duplicate-source','invented-source',
    'quote','numeric-value','position','dimension-type','missing-dimension','duplicate-fact','missing-metric',
    'extra-gold','extra-path','reviewer','independence','future-date','wrong-unit-type','numeric-reviewer','missing-subject'])
def test_invalid_provenance_values_inventories_and_gold_fields_are_rejected(damage):
    sources, _, packet = prepared()
    row = packet['sources'][0]
    fact = row['facts'][0]
    if damage == 'source-hash': row['text_sha256'] = '0' * 64
    elif damage == 'missing-source': packet['sources'].pop()
    elif damage == 'duplicate-source': packet['sources'][-1] = deepcopy(row)
    elif damage == 'invented-source': row['source_id'] = 'invented'
    elif damage == 'quote': fact['metric']['value']['quote'] = '0.2'
    elif damage == 'numeric-value': fact['metric']['value']['value'] = '0.2'
    elif damage == 'position': fact['metric']['value']['start'] += 1
    elif damage == 'dimension-type': fact['conditions']['code']['type'] = 'decimal'
    elif damage == 'missing-dimension': del fact['conditions']['code']
    elif damage == 'duplicate-fact': row['facts'].append(deepcopy(fact))
    elif damage == 'missing-metric': fact['metric'] = None
    elif damage == 'extra-gold': fact['expected_outcome'] = 'negative'
    elif damage == 'extra-path': fact['valid_paths'] = [['gold']]
    elif damage == 'reviewer': packet['author']['human'] = True
    elif damage == 'independence': packet['author']['independent'] = True
    elif damage == 'numeric-reviewer': packet['author']['human'] = 0
    elif damage == 'missing-subject': fact['subject'] = None
    elif damage == 'future-date':
        row = next(r for r in packet['sources'] if r['source_id']=='controls-v2/time-only-update')
        sources[row['source_id']]['available_at'] = '2026-01-01T00:00:00Z'
    else: fact['metric']['unit']['type'] = 'decimal'
    with pytest.raises((ValueError,KeyError)):
        o.validate(packet,sources)


def test_known_declared_conditions_equal_values_and_copies_remain_structural_only():
    _, _, packet = prepared(); by = rows(packet)
    expected = {'comparable':'changed_declared_value', 'changed-conditions':'different_declared_conditions',
                'time-only':'same_declared_value'}
    for family, status in expected.items():
        result = o.compare(by[f'controls-v2/{family}-basis'],by[f'controls-v2/{family}-update'])
        assert result['measurements'][0]['status']==status
        assert result['semantic_review']=='pending' and result['warning_action']=='retain_original_runtime_output'
    copy = o.compare(by['controls-v2/duplicate-citation-basis'],by['controls-v2/duplicate-citation-update'])
    assert copy['citation_lineage']==[dict(fact_id='citation-X1',root='run-X1',status='shared_recorded_root',independence='not inferred')]
    withdrawal = o.compare(by['controls-v2/surviving-support-basis'],by['controls-v2/surviving-support-update'])
    assert {v['recorded_status'] for v in withdrawal['availability']}=={'available','withdrawn'}
    assert [v['recorded_basis_roots'] for v in withdrawal['availability']]==[['run-X1'],['run-Y1']]
    assert not any(v['applied_to_runtime'] for v in withdrawal['availability'])


@pytest.mark.parametrize('change', ['unit','missing-unit','missing-condition','metric','lineage'])
def test_unknown_conditions_units_and_roots_do_not_become_no_impact(change):
    _, _, packet = prepared(); by = rows(packet)
    a,b=by['controls-v2/time-only-basis'],by['controls-v2/time-only-update']
    if change=='unit': b['facts'][0]['metric']['unit']['value']='percent'
    elif change=='missing-unit': b['facts'][0]['metric']['unit']=None
    elif change=='missing-condition': b['facts'][0]['conditions']['environment']=None
    elif change=='metric': b['facts'][0]['metric']['name']['value']='other-metric'
    else:
        a,b=by['controls-v2/duplicate-citation-basis'],by['controls-v2/duplicate-citation-update']
        b['facts'][0]['measurement_lineage']['value']='new-root'
        assert o.compare(a,b)['citation_lineage'][0]['status']=='unknown'
        return
    result=o.compare(a,b)
    assert result['measurements'][0]['status']=='unknown'
    assert result['warning_action']=='retain_original_runtime_output'


def test_real_report_preserves_missing_units_environment_lineage_and_absent_answer_scores():
    _, _, packet=prepared(); by=rows(packet)
    facts=by['project-v1/graph-report']['facts']
    assert len(facts)==12
    assert all(f['metric']['unit'] is None and f['conditions']['environment'] is None
               and f['measurement_lineage'] is None for f in facts)
    assert all(o.value(f['metric']['name'])!='answer_correct_exact' for f in facts)
    assert [o.value(f['metric']['sample_count']) for f in facts]==['2']*6+['10']*6


def test_production_capture_keeps_all_proposals_unreviewed_with_exact_source_quotes(tmp_path):
    sources,_,packet=prepared();by=rows(packet)
    selected=[sources['controls-v2/duplicate-citation-'+suffix] for suffix in ('basis','update')]
    result=d._capture(tmp_path/'brain',selected,by)
    assert result['review_events']==0 and result['proposed_evidence']==2
    assert result['official_comparability']['status']=='unknown'
    service=DecisionService(Brain(str(tmp_path/'brain'),mode='git'))
    assert service.inspect(result['profile'])['state']['workflow']=='proposed'
    for item in result['inspected']:
        assert not item['events'] and item['state']['workflow']=='proposed'
        if item['record']['kind']=='evidence':
            assert item['state']['epistemic']=='unassessed'
            assert item['source_lineage'] and all(r['lineage_ids']==['run-X1'] for r in item['source_lineage'])
            for citation in item['record']['payload']['sources']:
                source=service.inspect(citation['ref'])['record']['payload']['text'];p=citation['passage']
                assert source[p['start']:p['end']]==p['quote']


def test_real_multi_chunk_report_capture_preserves_reported_values_and_unknown_units(tmp_path):
    sources,_,packet=prepared();by=rows(packet)
    result=d._capture(tmp_path/'brain',[sources['project-v1/graph-report']],by)
    assert result['proposed_evidence']==12 and result['review_events']==0
    assert all(item['state']['workflow']=='proposed' for item in result['inspected'])
    metrics=[json.loads(item['record']['payload']['interpretation'])['metric']
             for item in result['inspected'] if item['record']['kind']=='evidence']
    assert all(m['unit'] is None for m in metrics)
    assert [m['sample_count'] for m in metrics]==['2']*6+['10']*6
    assert all(not s['lineage_ids'] for item in result['inspected'] for s in item['source_lineage'])


def test_replay_keeps_runtime_inputs_and_errors_and_never_scores_transcriptions(tmp_path,monkeypatch):
    calls=[]
    def fake(visible,event,path,mode,**kw):
        assert set(visible)=={'documents','decisions','dependencies'}
        assert not any(k in json.dumps(visible) for k in ('semantic_review','expected_outcome','measurement_lineage'))
        calls.append((event['id'],mode))
        if len(calls)==1: raise RuntimeError('failed diagnostic')
        return dict(alerts=[dict(reason='original')],complete=True,context_within_budget=True)
    monkeypatch.setattr(d,'execute',fake)
    monkeypatch.setattr(d,'_capture',lambda *a:dict(review_events=0))
    output=tmp_path/'new'
    result=d.run(output,capture=True)
    assert len(calls)==26 and result['status']=='completed_with_errors'
    assert result['results'][0]['profiles']['curated']['error']['type']=='RuntimeError'
    assert result['human_review'] is result['semantic_quality'] is None
    assert not result['independent_acceptance'] and 'scores' not in result
    with pytest.raises(FileExistsError): d.run(output)
    with pytest.raises(ValueError): d.run(DATA/'new-observations')

"""Verify source-bound proposals and preserved diagnostics, never final labels."""
from __future__ import annotations
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
sys.path.insert(0,str(ROOT))

from graph_engine import decision_schema as schema
from tools.decision_benchmark.observations import validate, compare
from tools.decision_benchmark.corpus import canonical
from tools.decision_benchmark.structured_development import development_inputs


def read(name: str) -> dict:
    p=HERE/name
    raw=gzip.decompress(p.read_bytes()) if name.endswith('.gz') else p.read_bytes()
    return json.loads(raw)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normalized(profile: dict) -> list[dict]:
    return [{k:v for k,v in a.items() if k!='candidate_id'} for a in profile['alerts']]


def main() -> None:
    manifest=read('manifest.json')
    for name,hashes in manifest['files'].items():
        raw=(HERE/name).read_bytes()
        assert digest(raw)==hashes['sha256'],name
        if name.endswith('.gz'):
            assert digest(gzip.decompress(raw))==hashes['uncompressed_sha256'],name
    code=manifest['source_commit']
    for name,expected in manifest['code_files'].items():
        raw=subprocess.check_output(['git','show',f'{code}:{name}'],cwd=ROOT)
        assert digest(raw)==expected and digest((ROOT/name).read_bytes())==expected,name
    assert not subprocess.check_output(['git','diff','5d42d063a8b7076fec82dbcdd7fb3f806a0d87cd','HEAD',
        '--','tools/decision_benchmark/data'],cwd=ROOT)
    sources,cases=development_inputs()
    packet=read('transcriptions.json');validate(packet,sources)
    assert len(sources)==30 and sum(len(s['facts']) for s in packet['sources'])==24
    report=read('capture-report.json.gz')
    assert digest((HERE/'transcriptions.json').read_bytes())==report['transcriptions_sha256']
    assert digest(canonical(report['code_manifest']))==report['code_sha256']
    for name,expected in report['code_manifest'].items():
        assert digest(subprocess.check_output(['git','show',f'{code}:{name}'],cwd=ROOT))==expected,name
    for notice in report['license_notices'].values():
        assert digest((HERE/notice['path']).read_bytes())==notice['sha256']
    assert set(report['source_manifest'])==set(sources)
    assert all(report['source_manifest'][k]['text_sha256']==digest(v['text'].encode()) for k,v in sources.items())
    case_by_id={case['id']:case for case in cases}
    row_by_source={row['source_id']:row for row in packet['sources']}
    assert report['source_commit']==code and not report['dirty']
    assert report['status']=='complete' and report['capture_requested'] and len(report['results'])==13
    assert {row['case_id'] for row in report['results']}==set(case_by_id)
    assert report['semantic_quality'] is report['human_review'] is None
    assert not report['independent_acceptance'] and not report['release_ready'] and 'scores' not in report
    assert sum(report['independent_final_coverage'].values())==0
    old_control=json.loads(gzip.decompress((HERE.parent/'production-controls.json.gz').read_bytes()))
    old_project=json.loads(gzip.decompress((HERE.parent/'solo-development.json.gz').read_bytes()))
    old={**{'controls-v2/'+r['event_id']:r for r in old_control['results']},
         **{'project-v1/'+r['event_id']:r for r in old_project['results']}}
    source_versions=proposed_evidence=0
    for row in report['results']:
        previous=old[row['case_id']]
        case=case_by_id[row['case_id']];bundle=row['case_id'].split('/')[0]
        assert row['comparison']==compare(row_by_source[bundle+'/'+case['event']['changed_source_id']],
                                         row_by_source[bundle+'/'+case['event']['source_id']])
        assert row['untranscribed_source_ids']==[key for key in case['source_ids'] if not row_by_source[key]['facts']]
        expected=previous.get('visible_inputs_sha256',previous.get('source_inputs_sha256'))
        assert row['source_input_sha256']==expected,row['case_id']
        for mode,profile in row['profiles'].items():
            assert profile['error'] is None and profile['complete'] and profile['context_within_budget']
            assert normalized(profile)==normalized(previous['profiles'][mode]),row['case_id']
        assert row['capture_error'] is None
        capture=row['capture'];assert capture['review_events']==0
        assert capture['official_comparability']['status']=='unknown'
        assert row['comparison']['warning_action']=='retain_original_runtime_output'
        records=[*capture['source_records'],*(i['record'] for i in capture['inspected'])]
        index={(r['id'],r['version_id']):r for r in records}
        for record in records:
            assert schema.hash_record(record)==record['version_id']
            if record['kind']=='source':
                p=record['payload'];assert schema.text_hash(p['text'])==p['source_ref']['text_sha256']
                source_versions+=1
        for item in capture['inspected']:
            assert item['state']['workflow']=='proposed' and not item['events']
            if item['record']['kind']!='evidence':continue
            proposed_evidence+=1
            assert item['state']['epistemic']=='unassessed'
            for citation in item['record']['payload']['sources']:
                r=citation['ref'];source=index[(r['id'],r['version_id'])];span=citation['passage']
                assert source['payload']['text'][span['start']:span['end']]==span['quote']
    assert sum(r['eligible_pairs'] for r in report['results'] if r['case_id'].startswith('controls-v2/'))==50
    assert sum(r['eligible_pairs'] for r in report['results'] if r['case_id'].startswith('project-v1/'))==27
    production=read('production-controls.json.gz')
    assert production['scores']['curated']['false_alert_rate']==dict(value=5/95,numerator=5,denominator=95)
    assert production['gate_assessments']['curated']['gates']['false_alerts']['status']=='fail'
    assert production['scores']['proposed']['miss_rate']['numerator']==3
    assert production['baseline']['saved_reference']['matched']
    matrix=read('integrity/report.json')
    assert matrix['execution_passed'] and matrix['counts']['observed_passed_cells']==41
    assert len(matrix['expected_nodes'])==55 and not matrix['deselected_nodes']
    commands=read('commands.json')
    assert len(commands)==12 and all(c['exit_code']==0 for c in commands)
    checks=read('ci-checks.json')
    assert checks['headRefOid']==code and len(checks['statusCheckRollup'])==15
    assert all(c['status']=='COMPLETED' and c['conclusion']=='SUCCESS' for c in checks['statusCheckRollup'])
    print(json.dumps(dict(saved_files=len(manifest['files']),distinct_sources=30,distinct_facts=24,
        replayed_cases=13,source_versions=source_versions,proposed_evidence=proposed_evidence,
        unchanged_diagnostic_inputs_and_alerts=13,independent_acceptance=False,release_ready=False)))


if __name__=='__main__':main()

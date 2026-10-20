"""Verify bounded development replay and immutable historical evidence."""
from __future__ import annotations
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
# When saved in the repository this is docs/.../false-alert-development-v1/reviewed-v1.
ROOT=HERE.parents[3]
sys.path.insert(0,str(ROOT))
from graph_engine import decision_schema as schema
from graph_engine.decision_memory import event_identity, body
from graph_engine.brain import Node
from tools.decision_benchmark.corpus import canonical,digest
from tools.decision_benchmark.reviewed_observations import assess
from tools.decision_benchmark.reviewed_development import review_inputs,check_report_fields
from tools.decision_benchmark.structured_development import development_inputs,TRANSCRIPTIONS


def read(name: str) -> dict:
    raw=(HERE/name).read_bytes()
    return json.loads(gzip.decompress(raw) if name.endswith('.gz') else raw)


def main() -> None:
    manifest=read('manifest.json')
    inventory={str(p.relative_to(HERE)) for p in HERE.rglob('*') if p.is_file() and p.name!='manifest.json'}
    assert set(manifest['files'])==inventory, 'Artifact inventory changed'
    for name,hashes in manifest['files'].items():
        raw=(HERE/name).read_bytes()
        assert digest(raw)==hashes['sha256'],name
        if name.endswith('.gz'):
            assert digest(gzip.decompress(raw))==hashes['uncompressed_sha256'],name
    code=manifest['source_commit']
    for name,expected in manifest['code_files'].items():
        assert digest(subprocess.check_output(['git','show',f'{code}:{name}'],cwd=ROOT))==expected,name
        assert digest((ROOT/name).read_bytes())==expected,name
    assert not subprocess.check_output(['git','diff','fb2fff2eee39c8d3a57360e934a09613fcab0e33',
        '--','tools/decision_benchmark/data'],cwd=ROOT)
    # Historical reports/verifiers are byte-preserved, including their strict
    # current-code guards. Those were executed on their original report head.
    changed=subprocess.check_output(['git','diff','--name-only','fb2fff2eee39c8d3a57360e934a09613fcab0e33',
        '--','docs/decision-evaluation-results'],cwd=ROOT,text=True).splitlines()
    assert all(p.startswith('docs/decision-evaluation-results/false-alert-development-v1/reviewed-v1/') for p in changed)
    historical=read('historical-commands.json')
    assert len(historical)==4 and all(r['exit_code']==0 and r['source_commit']=='fb2fff2eee39c8d3a57360e934a09613fcab0e33' for r in historical)
    sources,cases=development_inputs()
    packet=json.loads(TRANSCRIPTIONS.read_bytes())
    inventory=read('field-reviews.json')
    reviews=review_inputs(sources,packet,inventory)
    assert len(reviews)==10
    report=read('reviewed-report.json.gz')
    assert report['status']=='complete' and report['source_commit']==code and not report['dirty']
    assert report['review_sha256']==digest((HERE/'field-reviews.json').read_bytes())
    assert report['transcriptions_sha256']==digest(TRANSCRIPTIONS.read_bytes())
    assert digest(canonical(report['code_manifest']))==report['code_sha256']
    for name,expected in report['code_manifest'].items():
        assert digest(subprocess.check_output(['git','show',f'{code}:{name}'],cwd=ROOT))==expected,name
    assert set(report['source_manifest'])==set(sources)
    assert all(report['source_manifest'][k]['text_sha256']==digest(s['text'].encode()) for k,s in sources.items())
    row=next(r for r in packet['sources'] if r['source_id']=='project-v1/graph-report')
    assert report['report_field_checks']==check_report_fields(sources[row['source_id']],row)
    assert len(report['report_field_checks'])==12
    assert not report['independent_acceptance'] and not report['release_ready']
    assert report['semantic_scores'] is report['human_review'] is report['user_sessions'] is None
    assert sum(report['independent_final_coverage'].values())==0 and report['provider_calls']==0
    case_by_id={c['id']:c for c in cases}
    assert {r['case_id'] for r in report['results']}==set(case_by_id) and len(report['results'])==13
    previous=read('../structured-v1/capture-report.json.gz')
    old_by_id={r['case_id']:r for r in previous['results']}
    retained=[]; versions=events=0
    for row in report['results']:
        case=case_by_id[row['case_id']]
        assert row['source_input_sha256']==digest(canonical(case['runtime']))==old_by_id[row['case_id']]['source_input_sha256']
        prefix=case['id'].split('/')[0]+'/'
        for mode,p in row['profiles'].items():
            assert p['error'] is None and p['complete'] and p['context_within_budget']
            update=p['source_update']
            bound={side:dict(update[side],text=sources[prefix+update[side]['source_id']]['text']) for side in ('old','new')}
            expected=assess(row['review'],bound,available_at=case['event']['at'])
            assert p['observation_assessment']==expected
            impact=next(o['output'] for o in p['raw_outputs'] if o['stage']=='impact')
            assert len(impact['candidates'])==len(p['alerts'])
            journal=p['journal']; records=journal['versions']; index={(v['id'],v['version_id']):v for v in records}
            versions+=len(records);events+=len(journal['events'])
            for v in records:
                assert schema.hash_record(v)==v['version_id']
                if v['previous']:
                    assert (v['previous']['id'],v['previous']['version_id']) in index
                if v['kind']=='source':
                    payload=v['payload']
                    assert schema.text_hash(payload['text'])==payload['source_ref']['text_sha256']
                    doc=next(d for d in case['runtime']['documents'] if d['id']==v['anchor_node_id'])
                    assert payload['text']==body(Node(doc['text'],id=doc['id']).to_markdown())
            for e in journal['events']:
                assert e['event_id']==event_identity(e)
                v=index[(e['subject']['id'],e['subject']['version_id'])]
                assert mode=='curated' and v['kind']=='relationship' and v['payload']['kind']=='depends_on'
                assert e['axis']=='workflow' and e['from']=='proposed' and e['to']=='accepted'
            for ref in update['captured_update_refs']:
                assert index[(ref['id'],ref['version_id'])]['kind']=='source'
            for ref in update['retained_basis_refs']:
                v=index[(ref['id'],ref['version_id'])]
                assert v['previous'] is None and sum(x['id']==v['id'] for x in records)==1
            if expected['retain_basis']:
                assert not p['alerts']
                if mode=='curated': retained.append(row['case_id'])
            else:
                normalized=lambda x:[{k:v for k,v in a.items() if k!='candidate_id'} for a in x['alerts']]
                assert normalized(p)==normalized(old_by_id[row['case_id']]['profiles'][mode])
    contexts=[(mode,next(o['output'] for o in p['raw_outputs'] if o['stage']=='context'))
              for row in report['results'] for mode,p in row['profiles'].items()]
    assert sum(bool(c['truncated']) for mode,c in contexts if mode=='curated')==13
    assert sum(bool(c['truncated']) for mode,c in contexts if mode=='proposed')==5
    assert all(c['tokens']<=4000 for mode,c in contexts)
    assert len(retained)==3
    assert sum(len(r['profiles']['curated']['alerts']) for r in report['results'])==10
    assert sum(len(r['profiles']['proposed']['alerts']) for r in report['results'])==0
    assert sum(r['eligible_pairs'] for r in report['results'] if r['case_id'].startswith('controls-v2/'))==50
    assert sum(r['eligible_pairs'] for r in report['results'] if r['case_id'].startswith('project-v1/'))==27
    production=read('production-controls.json.gz')
    assert production['scores']['curated']['false_alert_rate']==dict(value=5/95,numerator=5,denominator=95)
    assert production['gate_assessments']['curated']['gates']['false_alerts']['status']=='fail'
    assert production['scores']['proposed']['miss_rate']['numerator']==3
    assert production['baseline']['saved_reference']['matched']
    matrix=read('integrity/report.json')
    assert matrix['execution_passed'] and matrix['counts']['observed_passed_cells']==41
    ci=read('ci-code.json')
    assert len(ci)==15 and all(c['state']=='SUCCESS' for c in ci)
    assert read('pr-code-state.json')['headRefOid']==code
    assert read('pr-code-state.json')['isDraft']
    scope=read('final-scope-state.json')['data']['repository']
    assert scope['defaultBranchRef']['target']['oid']=='5d42d063a8b7076fec82dbcdd7fb3f806a0d87cd'
    assert all(scope['issue'+str(n)]['state']=='OPEN' for n in (73,90,91,92,93))
    commands=read('commands.json')
    assert len(commands)==9 and all(r['exit_code']==0 for r in commands)
    print(json.dumps(dict(verified=True,cases=13,retained_development_bases=len(retained),
                          journal_versions=versions,journal_events=events,independent_acceptance=False)))


if __name__=='__main__': main()

"""Verify the engineering PR-review record, without independent acceptance claims."""
from pathlib import Path
import gzip
import hashlib
import json
import re
import subprocess

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[2]

def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def load(name: str) -> dict:
    path=BASE/name
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)

def main() -> None:
    manifest=load('manifest.json')
    files={str(p.relative_to(BASE)) for p in BASE.rglob('*') if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts}
    assert files==set(manifest['files'])
    for name,meta in manifest['files'].items():
        path=(BASE/name).resolve()
        assert path.is_relative_to(BASE)
        raw=path.read_bytes();assert digest(raw)==meta['saved_sha256'],name
        if 'uncompressed_sha256' in meta:assert digest(gzip.decompress(raw))==meta['uncompressed_sha256'],name
    good=load('matrix/report.json.gz');bad=load('matrix-deselected/report.json.gz')
    assert good['execution_passed'] and good['counts']['observed_passed_cells']==41
    assert len(good['expected_nodes'])==len(good['phase_reports'])==55 and not good['deselected_nodes']
    assert bad['pytest_exit_code']==0 and not bad['execution_passed']
    assert bad['counts']['observed_passed_cells']==40 and bad['counts']['unverified_or_failed_cells']==1
    assert len(bad['expected_nodes'])==55 and len(bad['phase_reports'])==54 and len(bad['deselected_nodes'])==1
    assert any(bad['deselected_nodes'][0] in c['missing_nodes'] for c in bad['cells'])
    assert good['code_sha256']==bad['code_sha256']
    for helper in ('tests/test_decision_impact.py','tests/test_decision_memory.py','tests/test_decision_service.py','tools/decision_benchmark/corpus.py'):
        assert helper in good['code_manifest']
    assert re.fullmatch('[a-f0-9]{40}',good['source_commit'])
    for name,expected in good['code_manifest'].items():
        raw=subprocess.check_output(['git','show',f"{good['source_commit']}:{name}"],cwd=ROOT)
        assert digest(raw)==expected,name
    ci=load('ci/matrix-report.json.gz')
    assert ci['execution_passed'] and ci['code_sha256']==good['code_sha256']
    assert len(ci['expected_nodes'])==len(ci['phase_reports'])==55 and not ci['deselected_nodes']
    checks=load('ci/code-checks.json')
    assert checks['headRefOid']==good['source_commit']
    assert len(checks['statusCheckRollup'])==15 and all(c['conclusion']=='SUCCESS' for c in checks['statusCheckRollup'])
    solo=load('solo.json.gz')
    assert solo['status']=='complete' and solo['source_commit']==good['source_commit']
    assert solo['dirty'] is good['dirty'] is False
    assert solo['invocation_directory']==good['invocation_directory']=='/private/tmp'
    assert len(solo['results'])==8 and solo['attempted_pairs_per_profile']==27
    assert solo['semantic_quality'] is solo['human_calibration'] is solo['human_review_time'] is None
    assert not any(solo['independent_final_coverage'].values()) and not solo['release_ready']
    baseline=json.loads((ROOT/'docs/decision-evaluation-results/project-development.json').read_bytes())
    expected={r['event_id']:r['visible_inputs_sha256'] for r in baseline['results']}
    assert all(row['source_inputs_sha256']==expected[row['event_id']] for row in solo['results'])
    controls=load('production.json.gz')
    rate=controls['scores']['curated']['false_alert_rate']
    assert (rate['numerator'],rate['denominator'])==(5,95)
    assert controls['gate_assessments']['curated']['gates']['false_alerts']['status']=='fail'
    assert controls['scores']['proposed']['counts']['missed_impacts']==3
    commands=load('commands.json');assert len(commands['runs'])==7 and all(r['expectation_met'] for r in commands['runs'])
    assert good['independent_sign_off'] is good['final_candidate'] is None and not good['release_ready']
    print(json.dumps(dict(saved_files=len(files),expected_matrix_tests=55,full_matrix_cells=41,
        rejected_filtered_cells=1,ci_code_matches=True,independent_acceptance=False,release_ready=False)))

if __name__=='__main__':main()

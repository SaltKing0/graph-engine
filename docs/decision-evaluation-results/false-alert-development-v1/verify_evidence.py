"""Validate recorded development evidence; never open labels or final sources."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = '5d42d063a8b7076fec82dbcdd7fb3f806a0d87cd'
CODE = 'f506e6694bbc9a9c19390c2e7c33f60216b8cf6c'


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read(name: str) -> dict:
    path = HERE / name
    raw = gzip.decompress(path.read_bytes()) if name.endswith('.gz') else path.read_bytes()
    return json.loads(raw)


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def main() -> None:
    manifest = read('manifest.json')
    assert manifest['source_commit'] == CODE
    for name, hashes in manifest['files'].items():
        raw = (HERE / name).read_bytes()
        assert digest(raw) == hashes['sha256'], name
        if name.endswith('.gz'):
            assert digest(gzip.decompress(raw)) == hashes['uncompressed_sha256'], name
    for name, expected in manifest['measured_code'].items():
        raw = subprocess.check_output(['git', 'show', f'{CODE}:{name}'], cwd=ROOT)
        assert digest(raw) == expected, name
        assert digest((ROOT / name).read_bytes()) == expected, name
    changed = git('diff', '--name-only', BASE, 'HEAD', '--',
                  'tools/decision_benchmark/data', 'docs/decision-evaluation-results').splitlines()
    assert all(name.startswith('docs/decision-evaluation-results/false-alert-development-v1/')
               for name in changed), changed
    env = read('environment.json')
    assert env['source_commit'] == CODE and not env['dirty']
    commands = read('commands.json')
    assert len(commands) == 14
    assert {c['name']: c['exit_code'] for c in commands if c['exit_code']} == {'full': 2, 'integrity': 1}
    assert sum(c['exit_code'] == 0 for c in commands) == 12
    assert '2096 passed' in (HERE / 'full-final.log').read_text()
    assert '31 passed' in (HERE / 'focused-final.log').read_text()
    assert '6 failed' in gzip.decompress((HERE / 'before-fix.log.gz').read_bytes()).decode()
    production = read('production-controls.json.gz')
    scores = production['scores']['curated']
    assert production['status'] == 'complete' and production['smoke_passed']
    assert production['metadata']['production_mapping']['version'] == 'dm.source-change-diagnostic/2'
    assert production['baseline']['saved_reference']['matched']
    assert scores['false_alert_rate'] == dict(value=5 / 95, numerator=5, denominator=95)
    assert scores['counts']['attempted_pairs'] == 100 and scores['counts']['raw_alerts'] == 10
    assert scores['counts']['error_pairs'] == 0 and scores['miss_rate']['numerator'] == 0
    assert production['gate_assessments']['curated']['gates']['false_alerts']['status'] == 'fail'
    assert production['scores']['proposed']['miss_rate']['numerator'] == 3
    baseline = read('production-controls-baseline.json.gz')
    assert digest(gzip.decompress((HERE / 'production-controls-baseline.json.gz').read_bytes())) == production['baseline']['sha256']
    assert baseline['metadata']['kind'] == 'synthetic'
    assert all(p['source_update']['classification'] == 'changed'
               for row in production['results'] for p in row['profiles'].values())
    solo = read('solo-development.json.gz')
    previous = json.loads((ROOT / 'docs/decision-evaluation-results/project-development.json').read_bytes())
    hashes = {row['event_id']: row['visible_inputs_sha256'] for row in previous['results']}
    assert solo['status'] == 'complete' and solo['attempted_pairs_per_profile'] == 27
    assert len(solo['results']) == len(hashes) == 8
    assert solo['semantic_quality'] is solo['human_calibration'] is solo['human_review_time'] is None
    assert not solo['release_ready'] and sum(solo['independent_final_coverage'].values()) == 0
    for row in solo['results']:
        assert row['source_inputs_sha256'] == hashes[row['event_id']]
        for p in row['profiles'].values():
            assert p['error'] is None and p['complete'] and p['context_within_budget']
            assert p['source_update']['classification'] == 'changed'
    workflow = read('workflow.json.gz')
    assert len(workflow['checks']) == 7 and all(workflow['checks'].values())
    matrix = read('integrity-final/report.json')
    assert matrix['execution_passed']
    checks = read('ci-checks.json')
    assert checks['headRefOid'] == CODE and len(checks['statusCheckRollup']) == 15
    assert all(c['status'] == 'COMPLETED' and c['conclusion'] == 'SUCCESS'
               for c in checks['statusCheckRollup'])
    print(json.dumps(dict(saved_files=len(manifest['files']), development_input_hashes=8,
        historical_false_alerts='5/95: failed', independent_acceptance=False, release_ready=False)))


if __name__ == '__main__':
    main()

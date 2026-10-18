"""Verify saved engineering evidence; this never certifies independent acceptance.

Run from the repository root with its development Python environment.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
sys.path.insert(0, str(ROOT))

from tools.decision_benchmark.annotation_packets import prepare_development, validate_packet
from tools.decision_benchmark.solo import validate_notes
from tools.decision_benchmark.corpus import canonical


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load(name: str) -> dict:
    path = BASE / name
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def main() -> None:
    manifest = load('manifest.json')
    assert set(manifest['files']) == {str(path.relative_to(BASE)) for path in BASE.rglob('*')
        if path.is_file() and path.name != 'manifest.json' and '__pycache__' not in path.parts}
    for name, hashes in manifest['files'].items():
        path = (BASE / name).resolve()
        assert path.is_relative_to(BASE)
        raw = path.read_bytes()
        assert sha(raw) == hashes['saved_sha256'], name
        if 'uncompressed_sha256' in hashes:
            assert sha(gzip.decompress(raw)) == hashes['uncompressed_sha256'], name

    packet, _ = prepare_development()
    notes = load('source-notes.json')
    validate_notes(packet, notes)
    assert validate_packet(packet)['cases'] == 8 and len(notes['pairs']) == 27
    assert sum(len(row['evidence']) for row in notes['pairs']) == 54
    solo = load('solo-development.json.gz')
    assert solo['notes_sha256'] == sha((BASE / 'source-notes.json').read_bytes())
    assert solo['packet_sha256'] == sha(canonical(packet))
    assert solo['configuration']['provider_calls'] == 0
    assert solo['status'] == 'complete' and not solo['dirty']
    assert solo['semantic_quality'] is solo['human_calibration'] is solo['human_review_time'] is None
    assert not solo['release_ready'] and not any(solo['independent_final_coverage'].values())
    old = json.loads((ROOT / 'docs/decision-evaluation-results/project-development.json').read_bytes())
    old_hashes = {row['event_id']: row['visible_inputs_sha256'] for row in old['results']}
    assert len(solo['results']) == 8 and solo['attempted_pairs_per_profile'] == 27
    for row in solo['results']:
        assert row['source_inputs_sha256'] == old_hashes[row['event_id']]
        for profile in row['profiles'].values():
            assert profile['error'] is None and profile['complete'] and profile['context_within_budget']

    matrix = load('validation/integrity/report.json')
    assert matrix['counts'] == dict(defined_cells=54, applicable_cells=41,
        observed_passed_cells=41, unverified_or_failed_cells=0, declared_not_applicable_cells=13)
    assert len(matrix['phase_reports']) == 55 and matrix['execution_passed'] and not matrix['dirty']
    assert matrix['independent_sign_off'] is matrix['final_candidate'] is None
    assert matrix['final_integrity_gate']['status'] == 'unmeasured' and not matrix['release_ready']
    for phases in matrix['phase_reports'].values():
        assert set(phases) == {'setup', 'call', 'teardown'}
        assert all(phase['outcome'] == 'passed' for phase in phases.values())
    for report in (solo, matrix):
        assert report['code_sha256'] == sha(canonical(report['code_manifest']))
        for name, expected in report['code_manifest'].items():
            raw = subprocess.check_output(['git', 'show', f"{report['source_commit']}:{name}"], cwd=ROOT)
            assert sha(raw) == expected, name
    ci = load('validation/ci/integrity-report.json')
    assert ci['code_sha256'] == matrix['code_sha256'] and ci['execution_passed']
    assert ci['counts'] == matrix['counts'] and len(ci['phase_reports']) == 55
    checks = load('validation/ci/source-checks.json')
    assert checks['headRefOid'] == solo['source_commit'] == matrix['source_commit']
    assert len(checks['statusCheckRollup']) == 15
    assert all(check['conclusion'] == 'SUCCESS' for check in checks['statusCheckRollup'])
    controls = load('production-controls.json.gz')
    false = controls['scores']['curated']['false_alert_rate']
    assert (false['numerator'], false['denominator']) == (5, 95)
    assert controls['gate_assessments']['curated']['gates']['false_alerts']['status'] == 'fail'
    assert controls['scores']['proposed']['counts']['missed_impacts'] == 3
    assert controls['baseline']['saved_reference']['matched']
    commands = load('validation/commands.json')
    assert commands['source_commit'] == solo['source_commit'] and not commands['dirty']
    assert len(commands['runs']) == 11 and all(run['exit_code'] == 0 for run in commands['runs'])
    references = 0
    for path in [ROOT / 'CONTRIBUTING.md', ROOT / 'docs/decision-solo-development.md',
                 ROOT / 'docs/decision-release-readiness.md', BASE / 'README.md']:
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if re.match(r'[a-z]+://', target) or target.startswith('#'):
                continue
            assert (path.parent / target.split('#', 1)[0]).exists(), (path, target)
            references += 1
    print(json.dumps(dict(saved_files=len(manifest['files']), local_file_references=references,
        pairs=27, quotes=54, applicable_matrix_cells=41, observed_matrix_tests=55,
        independent_acceptance=False, release_ready=False)))


if __name__ == '__main__':
    main()

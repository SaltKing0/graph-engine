"""Verify saved engineering observations; never infer independent acceptance."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load(name: str) -> dict:
    path = BASE / name
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def main() -> None:
    manifest = load('manifest.json')
    actual = {str(path.relative_to(BASE)) for path in BASE.rglob('*')
              if path.is_file() and path.name != 'manifest.json' and '__pycache__' not in path.parts}
    assert actual == set(manifest['files']), 'Missing or unrecorded evidence file'
    for name, meta in manifest['files'].items():
        path = (BASE / name).resolve()
        assert path.is_relative_to(BASE)
        raw = path.read_bytes()
        assert digest(raw) == meta['sha256'], name
        if path.suffix == '.gz':
            assert digest(gzip.decompress(raw)) == meta['uncompressed_sha256'], name

    local = load('validation/matrix/report.json.gz')
    ci = load('validation/ci/report.json.gz')
    expected_counts = dict(defined_cells=54, applicable_cells=41, observed_passed_cells=41,
                           unverified_or_failed_cells=0, declared_not_applicable_cells=13)
    for report in (local, ci):
        assert report['execution_passed'] and report['pytest_exit_code'] == 0
        assert report['counts'] == expected_counts
        assert len(report['expected_nodes']) == len(report['phase_reports']) == 73
        assert not report['deselected_nodes']
        for phases in report['phase_reports'].values():
            assert set(phases) == {'setup', 'call', 'teardown'}
            assert all(value['outcome'] == 'passed' for value in phases.values())
        assert report['independent_sign_off'] is report['final_candidate'] is None
        assert report['final_integrity_gate']['status'] == 'unmeasured'
        assert report['release_ready'] is False
        # Recompute cell results from actual phase reports, including parameters.
        for cell in report['cells']:
            if not cell['applicable']:
                assert cell['result'] == 'not_applicable_declared'
                assert cell['not_applicable_reason'] and not cell['tests']
                continue
            assert cell['result'] == 'passed' and not cell['missing_nodes']
            for selector in cell['tests']:
                nodes = {node for node in report['expected_nodes']
                         if node == selector or node.startswith(selector + '[')}
                assert nodes and nodes.issubset(report['phase_reports'])
    assert local['code_sha256'] == ci['code_sha256']
    assert local['matrix_sha256'] == ci['matrix_sha256']
    canonical_manifest = json.dumps(local['code_manifest'], sort_keys=True, ensure_ascii=True,
                                    allow_nan=False, separators=(',', ':')).encode()
    assert digest(canonical_manifest) == local['code_sha256']
    assert not local['dirty']
    assert re.fullmatch('[a-f0-9]{40}', local['source_commit'])
    for name, expected in local['code_manifest'].items():
        raw = subprocess.check_output(['git', 'show', f"{local['source_commit']}:{name}"], cwd=ROOT)
        assert digest(raw) == expected, name
        assert digest((ROOT / name).read_bytes()) == expected, name

    review = load('review.json')
    assert review['engineering_candidate'] == local['source_commit']
    assert review['code_sha256'] == local['code_sha256']
    assert review['reviewer'] == dict(id='codex-implementing-agent', kind='implementing_agent',
                                     independent=False, human=False)
    assert review['final_candidate'] is review['independent_sign_off'] is None
    assert review['release_ready'] is False
    assert len(review['cells']) == 54
    assert {(c['cell']['category'], c['cell']['surface']) for c in review['cells']} == {
        (c['category'], c['surface']) for c in local['cells']}
    for recorded, cell in zip(review['cells'], local['cells']):
        assert recorded['cell'] == cell
        assert recorded['reviewer_id'] == review['reviewer']['id']
        assert recorded['engineering_candidate'] == local['source_commit']
        assert recorded['runtime_record'] == 'validation/matrix/report.json.gz'
        assert recorded['review_disposition'] == ('evidence_matches_declared_invariant'
                                                  if cell['applicable'] else 'operation_not_exposed')
        assert recorded['rationale'] and recorded['contract_reference']
        for reference in recorded['interface_references']:
            assert (ROOT / reference).is_file(), reference

    checks = load('validation/ci/checks.json')
    assert checks['headRefOid'] == local['source_commit']
    assert len(checks['statusCheckRollup']) == 15
    assert all(check['status'] == 'COMPLETED' and check['conclusion'] == 'SUCCESS'
               for check in checks['statusCheckRollup'])
    commands = load('commands.json')['runs']
    failures = [run for run in commands if run['actual_exit_code'] != run['expected_exit_code']]
    assert len(failures) == 1 and failures[0]['id'] == 'new-review-tests-initial'
    assert failures[0]['expected_exit_code'] == 0 and failures[0]['actual_exit_code'] == 1
    assert (BASE / 'validation/new-review-tests-initial.log').read_text().count('1 failed, 7 passed') == 1
    assert '8 passed' in (BASE / 'validation/new-review-tests-corrected.log').read_text()
    for name, count in [('full-suite.log', 2194), ('strict-mcp-access.log', 303),
                        ('strict-pdf.log', 48), ('strict-browser.log', 41)]:
        assert f'{count} passed' in (BASE / 'validation' / name).read_text(), name
    assert '10 skipped' in (BASE / 'validation/full-suite.log').read_text()
    print(json.dumps(dict(saved_files=len(actual), matrix_cells=54, applicable_passed=41,
                          technical_na=13, executed_tests=73, ci_code_matches=True,
                          independent_acceptance=False, release_ready=False)))


if __name__ == '__main__':
    main()

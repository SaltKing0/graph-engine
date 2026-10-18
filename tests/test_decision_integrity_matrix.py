"""Matrix completeness and honest phase accounting, not simulated acceptance."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools import decision_integrity as integrity
from tools.decision_integrity import MATRIX, validate, coverage


def matrix():
    return json.loads(MATRIX.read_bytes())


def test_inventory_has_all_declared_cells_and_resolving_evidence():
    value = matrix()
    selectors = validate(value)
    assert len(value['cells']) == 54 and len(set(selectors)) == len(selectors)
    assert sum(cell['applicable'] for cell in value['cells']) == 41
    assert value['final_sign_off'] is value['final_candidate'] is None


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'unknown-test', 'empty-na', 'invented-signoff'])
def test_malformed_inventory_cannot_hide_gaps_or_invent_sign_off(damage):
    value = matrix()
    if damage == 'missing':
        value['cells'].pop()
    elif damage == 'duplicate':
        value['cells'].append(deepcopy(value['cells'][0]))
    elif damage == 'unknown-test':
        value['cells'][0]['tests'] = ['tests/test_decision_integrity.py::test_not_present']
    elif damage == 'empty-na':
        cell = next(c for c in value['cells'] if not c['applicable'])
        cell['not_applicable_reason'] = ''
    else:
        value['final_sign_off'] = True
    with pytest.raises(ValueError):
        validate(value)


def test_missing_skipped_or_failed_teardown_never_counts_as_passed_cell():
    value = matrix()
    # These are unit-test phase fixtures for the accounting function, never
    # written as observed run data or human sign-off.
    selectors = validate(value)
    passed = {phase: dict(outcome='passed') for phase in ('setup', 'call', 'teardown')}
    reports = {selector: deepcopy(passed) for selector in selectors}
    expected = set(reports)
    result = coverage(value, reports, expected)
    assert result['software_matrix_complete'] and result['counts']['observed_passed_cells'] == 41
    assert result['independent_sign_off'] is result['final_candidate'] is None
    assert not result['release_ready'] and result['final_integrity_gate']['status'] == 'unmeasured'
    for outcome in ('failed', 'skipped'):
        damaged = deepcopy(reports)
        damaged[selectors[0]]['teardown']['outcome'] = outcome
        assert not coverage(value, damaged, expected)['software_matrix_complete']
    assert not coverage(value, {}, expected)['software_matrix_complete']
    incomplete = deepcopy(reports)
    del incomplete[selectors[0]]['call']
    assert not coverage(value, incomplete, expected)['software_matrix_complete']


def test_one_passing_parameter_cannot_hide_an_unexecuted_parameter():
    value = matrix()
    selectors = validate(value)
    passed = {phase: dict(outcome='passed') for phase in ('setup', 'call', 'teardown')}
    # Synthetic accounting fixtures; the two parameters are separate required
    # executions even though the inventory names their shared test function.
    reports = {selector: deepcopy(passed) for selector in selectors}
    selector = next(s for s in selectors if s.endswith('test_missing_and_cyclic_node_lineage_fail_closed'))
    del reports[selector]
    reports[selector + '[lineage0]'] = deepcopy(passed)
    missing = selector + '[lineage1]'
    result = coverage(value, reports, set(reports) | {missing})
    assert not result['software_matrix_complete']
    assert result['counts']['unverified_or_failed_cells'] == 1
    assert missing in next(c for c in result['cells'] if c['category'] == 'acl_revocation'
                           and c['surface'] == 'service')['missing_nodes']


def test_pytest_capture_retains_real_deselected_parameter_instances(tmp_path):
    fixture = tmp_path / 'test_parameter_fixture.py'
    fixture.write_text('import pytest\n@pytest.mark.parametrize("x", [0,1], ids=["kept","omitted"])\n'
                       'def test_fixture(x): assert x in (0,1)\n')
    code = '''import json,pytest,sys
from tools.decision_integrity import Capture
capture=Capture()
result=pytest.main([sys.argv[1], '--rootdir', sys.argv[2], '-k', 'not omitted', '-q'], plugins=[capture])
assert result == 0
print(json.dumps(dict(expected=sorted(capture.expected_nodes), observed=sorted(capture.reports),
                     deselected=sorted(capture.deselected_nodes))))
'''
    env = dict(os.environ, PYTHONPATH=str(integrity.ROOT))
    env.pop('PYTEST_ADDOPTS', None)
    child = subprocess.run([sys.executable, '-c', code, str(fixture), str(tmp_path)],
                           cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stdout + child.stderr
    result = json.loads(child.stdout.splitlines()[-1])
    assert len(result['expected']) == 2 and len(result['observed']) == 1
    assert result['deselected'] == ['test_parameter_fixture.py::test_fixture[omitted]']


def test_manifest_includes_and_detects_transitive_helper_changes(tmp_path, monkeypatch):
    manifest = integrity.code_manifest()
    for helper in ('tests/test_decision_impact.py', 'tests/test_decision_memory.py',
                   'tests/test_decision_service.py', 'tools/decision_benchmark/corpus.py'):
        assert helper in manifest
    for name in ('docs/matrix.json', '.github/workflows/ci.yml', 'docs/decision-memory-v1.md',
                 'pyproject.toml', 'tests/test_helper.py'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('original fixture')
    monkeypatch.setattr(integrity, 'ROOT', tmp_path)
    monkeypatch.setattr(integrity, 'MATRIX', tmp_path / 'docs/matrix.json')
    before = integrity.code_manifest()
    (tmp_path / 'tests/test_helper.py').write_text('changed fixture')
    after = integrity.code_manifest()
    assert before['tests/test_helper.py'] != after['tests/test_helper.py']
    assert {k: v for k, v in before.items() if k != 'tests/test_helper.py'} == {
        k: v for k, v in after.items() if k != 'tests/test_helper.py'}

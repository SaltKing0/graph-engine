"""Matrix completeness and honest phase accounting, not simulated acceptance."""
from copy import deepcopy
import json

import pytest

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
    result = coverage(value, reports)
    assert result['software_matrix_complete'] and result['counts']['observed_passed_cells'] == 41
    assert result['independent_sign_off'] is result['final_candidate'] is None
    assert not result['release_ready'] and result['final_integrity_gate']['status'] == 'unmeasured'
    for outcome in ('failed', 'skipped'):
        damaged = deepcopy(reports)
        damaged[selectors[0]]['teardown']['outcome'] = outcome
        assert not coverage(value, damaged)['software_matrix_complete']
    assert not coverage(value, {})['software_matrix_complete']
    incomplete = deepcopy(reports)
    del incomplete[selectors[0]]['call']
    assert not coverage(value, incomplete)['software_matrix_complete']

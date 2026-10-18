"""Run the declared engineering integrity matrix, without final acceptance claims."""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
import json
import importlib.metadata
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

from tools.decision_benchmark.corpus import canonical, digest

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / 'docs/decision-integrity-matrix-v1.json'
CATEGORIES = ('acl_revocation', 'tombstones', 'source_edit', 'merge', 'snapshot',
              'stale_review', 'undo', 'crash_retry', 'two_writers')
SURFACES = ('service', 'cli', 'http', 'mcp', 'browser', 'exports')


def validate(matrix: dict) -> list[str]:
    if matrix['schema'] != 'dm.integrity.matrix/1' or matrix['final_sign_off'] is not None:
        raise ValueError('Engineering inventory is not a final sign-off')
    expected = {(category, surface) for category in CATEGORIES for surface in SURFACES}
    seen = set()
    selectors = set()
    for cell in matrix['cells']:
        key = cell['category'], cell['surface']
        if key not in expected or key in seen:
            raise ValueError('Unknown or duplicate scenario/interface cell')
        seen.add(key)
        for field in ('scenario_id', 'operation', 'preconditions', 'invariant', 'scope'):
            if not isinstance(cell[field], str) or not cell[field].strip():
                raise ValueError(f'Missing concrete {field}')
        if type(cell['applicable']) is not bool:
            raise ValueError('Applicability must be explicit')
        if cell['applicable'] and (not cell['tests'] or cell.get('not_applicable_reason')):
            raise ValueError('Applicable cells require direct evidence selectors')
        if not cell['applicable'] and (cell['tests'] or not cell.get('not_applicable_reason')):
            raise ValueError('Inapplicable cells need a technical reason, not a fake pass')
        for selector in cell['tests']:
            file, function = selector.split('::')
            path = (ROOT / file).resolve()
            if not path.is_relative_to(ROOT / 'tests') or path.suffix != '.py':
                raise ValueError('Evidence must be a local test file')
            functions = {node.name for node in ast.parse(path.read_text()).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if function.split('[', 1)[0] not in functions:
                raise ValueError(f'Unknown test evidence: {selector}')
            selectors.add(selector)
    if seen != expected:
        raise ValueError('Every declared category/interface needs an explicit cell')
    return sorted(selectors)


class Capture:
    """Use actual pytest phase reports; absence, skips and teardown failures fail coverage."""
    def __init__(self) -> None:
        self.reports: dict[str, dict[str, dict]] = {}
        self.expected_nodes: set[str] = set()
        self.deselected_nodes: set[str] = set()

    def pytest_collection_finish(self, session: Any) -> None:
        self.expected_nodes.update(item.nodeid for item in session.items)

    def pytest_deselected(self, items: list[Any]) -> None:
        # -k/-m and PYTEST_ADDOPTS may remove just one parameter instance.
        # Retain that denominator even when pytest itself exits successfully.
        nodes = {item.nodeid for item in items}
        self.expected_nodes.update(nodes)
        self.deselected_nodes.update(nodes)

    def pytest_runtest_logreport(self, report: Any) -> None:
        self.reports.setdefault(report.nodeid, {})[report.when] = dict(
            outcome=report.outcome, duration_seconds=report.duration,
            detail=str(report.longrepr) if report.failed or report.skipped else None)


def coverage(matrix: dict, reports: dict, expected_nodes: set[str]) -> dict:
    validate(matrix)
    cells = []
    for cell in matrix['cells']:
        result = dict(cell, observed_nodes=[], expected_nodes=[], missing_nodes=[])
        if not cell['applicable']:
            result['result'] = 'not_applicable_declared'
        else:
            selector_results = []
            for selector in cell['tests']:
                expected = {node for node in expected_nodes
                            if node == selector or node.startswith(selector + '[')}
                matches = {node: phases for node, phases in reports.items()
                           if node == selector or node.startswith(selector + '[')}
                result['observed_nodes'].extend(sorted(matches))
                result['expected_nodes'].extend(sorted(expected))
                result['missing_nodes'].extend(sorted(expected - matches.keys()))
                passed = bool(expected) and matches.keys() == expected and all(set(phases) == {'setup', 'call', 'teardown'}
                    and all(phase['outcome'] == 'passed' for phase in phases.values())
                    for phases in matches.values())
                selector_results.append(passed)
            result['result'] = 'passed' if all(selector_results) else 'unverified_or_failed'
        cells.append(result)
    applicable = sum(c['applicable'] for c in cells)
    passed = sum(c['result'] == 'passed' for c in cells)
    return dict(cells=cells, counts=dict(defined_cells=len(cells), applicable_cells=applicable,
        observed_passed_cells=passed, unverified_or_failed_cells=applicable - passed,
        declared_not_applicable_cells=len(cells) - applicable),
        software_matrix_complete=passed == applicable,
        independent_sign_off=None, final_candidate=None, release_ready=False,
        final_integrity_gate=dict(status='unmeasured', reason=(
            'This bounded engineering inventory is not an exhaustive independent sign-off. '
            '#90/#91 final semantic evidence and the final candidate are absent; '
            'scenario sufficiency and inapplicability declarations still need review.')))


def code_manifest() -> dict[str, str]:
    """Fingerprint runtime and transitive test/tool helpers, not only test selectors."""
    code_paths = [*ROOT.glob('graph_engine/**/*.py'), *ROOT.glob('graph_engine/web/*.js'),
                  *ROOT.glob('graph_engine/web/*.html'), *ROOT.glob('graph_engine/**/*.md'),
                  *ROOT.glob('tests/**/*.py'), *ROOT.glob('tools/**/*.py'), MATRIX,
                  ROOT / '.github/workflows/ci.yml', ROOT / 'docs/decision-memory-v1.md',
                  ROOT / 'pyproject.toml']
    return {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(set(code_paths))}


def run(output: Path) -> dict:
    import pytest
    matrix = json.loads(MATRIX.read_bytes())
    selectors = validate(matrix)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    capture = Capture()
    absolute_selectors = [str(ROOT / selector.split('::', 1)[0]) + '::' + selector.split('::', 1)[1]
                          for selector in selectors]
    args = ['--rootdir', str(ROOT), *absolute_selectors, '-q', '--fail-on-skip', f'--junitxml={output / "junit.xml"}']
    manifest = code_manifest()
    report = dict(schema='dm.integrity.engineering-run/1',
        source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
        invocation_directory=str(Path.cwd()),
        python=sys.version, platform=platform.platform(),
        dependencies=dict(sorted((d.metadata['Name'], d.version) for d in importlib.metadata.distributions())),
        environment={key: os.environ.get(key) for key in ('GRAPH_ENGINE_TEST_D3', 'PLAYWRIGHT_BROWSERS_PATH')},
        matrix_sha256=digest(MATRIX.read_bytes()), code_manifest=manifest, code_sha256=digest(canonical(manifest)),
        pytest_args=args, status='running', human_reviewers=None, release_ready=False)
    with (output / 'pytest.log').open('w') as log, redirect_stdout(log), redirect_stderr(log):
        code = int(pytest.main(args, plugins=[capture]))
    report.update(coverage(matrix, capture.reports, capture.expected_nodes), pytest_exit_code=code,
        phase_reports=capture.reports, expected_nodes=sorted(capture.expected_nodes),
        deselected_nodes=sorted(capture.deselected_nodes))
    report['execution_passed'] = code == 0 and report['software_matrix_complete']
    report['status'] = 'complete' if report['execution_passed'] else 'completed_with_errors'
    (output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='NEW directory; existing paths are refused')
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps({key: report[key] for key in ('status', 'counts', 'software_matrix_complete', 'release_ready')}))
    return 0 if report['execution_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

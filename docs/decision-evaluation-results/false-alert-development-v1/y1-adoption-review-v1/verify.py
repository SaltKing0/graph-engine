"""Reproduce the preparation review without changing its historical evidence."""
import gzip
import json
from pathlib import Path
import subprocess

from review import BASE, HERE, PRIOR, ROOT, build
from tools.decision_benchmark.corpus import canonical, digest


def main() -> None:
    manifest = json.loads((HERE / 'manifest.json').read_bytes())
    files = {str(p.relative_to(HERE)) for p in HERE.rglob('*') if p.is_file()
             and p.name != 'manifest.json' and '__pycache__' not in p.parts}
    assert files == set(manifest['files'])
    for name, sha in manifest['files'].items():
        assert digest((HERE / name).read_bytes()) == sha, name
    meta = json.loads((HERE / 'metadata.json').read_bytes())
    assert meta['source_commit'] == BASE
    assert meta['review_sha256'] == digest((HERE / 'review.py').read_bytes())
    assert digest(canonical(meta['code_manifest'])) == meta['code_sha256']
    for name, sha in meta['code_manifest'].items():
        assert digest((ROOT / name).read_bytes()) == sha, name
    plan, audit = build()
    assert plan == json.loads((HERE / 'decision.json').read_bytes())
    assert audit == json.loads((HERE / 'review.json').read_bytes())
    assert plan['revises_plan_sha256'] == digest((PRIOR / 'decision.json').read_bytes())
    assert audit['domain_writes'] == 0 and audit['activation'] is audit['independent_acceptance'] is False
    assert audit['human_review'] is audit['semantic_scores'] is audit['product_benefit'] is None
    assert audit['independent_final_coverage'] == dict(positive=0, negative=0, inconclusive=0)
    assert len(audit['counterchecks']) == 11 and len(audit['original_omissions']) == 3
    assert audit['exact_state_checks']['journal_unchanged'] and audit['exact_state_checks']['preview_unchanged']
    assert plan['temporal_scope']['fictional_event_at'] == '2026-01-06T00:00:00Z'
    assert plan['temporal_scope']['present_world_availability'] is None
    assert plan['adoption_gate']['execution_permitted'] is False
    assert plan['source_mapping']['unit']['separately_repeated_in_y1'] is False
    assert all(row['assigned_owner'] is None for row in plan['finding_followup'])
    commands = json.loads((HERE / 'commands.json').read_bytes())
    assert len(commands) >= 3 and all(row['exit_code'] == 0 for row in commands)
    assert '5 passed' in (HERE / 'lifecycle-regressions.log').read_text()
    guides = {'docs/decision-source-observations.md', 'docs/decision-release-readiness.md'}
    workflow = '.github/workflows/ci.yml'
    original_workflow = subprocess.check_output(['git', 'show', BASE + ':' + workflow], cwd=ROOT, text=True)
    expected_workflow = original_workflow
    for job, name in [('test-browser', 'test (3.12, Chromium)'),
                      ('decision-integrity', 'test (3.12, Decision Memory integrity matrix)')]:
        old = f'  {job}:\n    name: {name}\n    runs-on: ubuntu-latest'
        assert expected_workflow.count(old) == 1
        expected_workflow = expected_workflow.replace(old, old.replace('ubuntu-latest', 'ubuntu-24.04'))
    assert (ROOT / workflow).read_text() == expected_workflow
    failure = json.loads((HERE / 'ci-setup/failure.json').read_bytes())
    first_run = json.loads((HERE / 'ci-setup/first-run.json').read_bytes())
    assert first_run['headSha'] == failure['failed_head'] == '0c7e0a8db5ca412f7c29c60e4db651d99b0544f6'
    assert first_run['status'] == 'completed' and first_run['conclusion'] == 'failure'
    jobs = {row['databaseId']: row for row in first_run['jobs']}
    for row, filename in zip(failure['jobs'], ('ci-chromium.log.gz', 'ci-matrix.log.gz')):
        job = jobs[row['job_id']]
        assert job['conclusion'] == 'failure'
        assert any(step['name'] == row['failed_step'] and step['conclusion'] == 'failure' for step in job['steps'])
        assert failure['error'] in gzip.decompress((HERE / 'ci-setup' / filename).read_bytes()).decode()
    allowed = guides | {workflow}
    prefix = 'docs/decision-evaluation-results/false-alert-development-v1/y1-adoption-review-v1/'
    changes = subprocess.check_output(['git', 'diff', '--name-only', BASE], cwd=ROOT, text=True).splitlines()
    assert all(name in allowed or name.startswith(prefix) for name in changes), changes
    for name in guides:
        original = subprocess.check_output(['git', 'show', BASE + ':' + name], cwd=ROOT)
        assert (ROOT / name).read_bytes().startswith(original), name
    print('Revised unsigned plan and source review reproduced: fictional-event time, exact metric/unit/condition bindings, required review outcomes.')
    print('11 invalid-plan variants rejected; no new source cases, reviewer judgments or independent scores.')
    print('Exact 18 versions / 19 events, old plan and all reviews preserved; three findings unresolved. No domain write or activation.')
    print('Future transaction execution, independent acceptance and measured benefit remain unavailable; frozen gates unchanged.')


if __name__ == '__main__':
    main()

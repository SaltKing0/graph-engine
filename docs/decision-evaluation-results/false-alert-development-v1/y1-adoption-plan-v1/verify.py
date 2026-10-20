"""Verify the unsigned plan, exact source state and absence of adoption writes."""
import json
from pathlib import Path
import subprocess

from prepare import BASE, HERE, ROOT, build
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
    assert meta['prepare_sha256'] == digest((HERE / 'prepare.py').read_bytes())
    assert digest(canonical(meta['code_manifest'])) == meta['code_sha256']
    for name, sha in meta['code_manifest'].items():
        assert digest((ROOT / name).read_bytes()) == sha, name
    plan = json.loads((HERE / 'decision.json').read_bytes())
    checks = json.loads((HERE / 'readcheck.json').read_bytes())
    actual_plan, actual_checks = build()
    assert actual_plan == plan and actual_checks == checks
    assert plan['status'] == 'unsigned_non_executable_preparation'
    assert plan['approval'] == dict(selected_option=None, authorizer=None, reviewer=None, authorized_at=None,
                                    activation_authorized=False, independent_acceptance=False)
    assert plan['activation'] is plan['resolution'] is plan['independent_acceptance'] is plan['release_ready'] is False
    assert all(plan[k] is None for k in ('human_review', 'semantic_scores', 'user_sessions', 'product_benefit'))
    assert plan['independent_final_coverage'] == dict(positive=0, negative=0, inconclusive=0)
    assert not {'idempotency_key', 'expected_heads', 'expected_generation', 'events', 'versions'} & plan.keys()
    assert len(plan['future_steps']) == 6
    assert all(step['actual_outcome'] is None for step in plan['future_steps'][1:5])
    assert all(step['future_review_event_id'] is None for step in plan['future_steps'][1:4])
    assert len(plan['future_steps'][4]['members']) == 2
    assert plan['old_history']['append_new_old_conclusion'] is plan['old_history']['undo_existing_reviews'] is False
    assert plan['findings']['disposition_changes'] == plan['findings']['workflow_changes'] == []
    assert len(plan['findings']['unresolved_references']) == 3
    memo = (HERE / 'README.md').read_text()
    for role in ('old_decision', 'decision', 'claim', 'support', 'dependency'):
        assert plan['snapshot_observation']['references'][role]['version_id'] in memo, role
    assert plan['brain_revision'] in memo and BASE in memo
    assert plan['future_steps'][4]['members'][0]['observed_previous_event_id'] in memo
    assert checks['domain_write_attempts'] == checks['reviewer_outcomes_recorded'] == 0
    assert (checks['versions'], checks['events'], checks['unresolved_findings']) == (18, 19, 3)
    assert (checks['comparison_deltas'], checks['comparison_candidates']) == (10, 3) and not checks['truncated']
    commands = json.loads((HERE / 'commands.json').read_bytes())
    assert len(commands) >= 3 and all(row['exit_code'] == 0 for row in commands)
    assert '5 passed' in (HERE / 'lifecycle-regressions.log').read_text()
    allowed = {'docs/decision-source-observations.md', 'docs/decision-release-readiness.md'}
    prefix = 'docs/decision-evaluation-results/false-alert-development-v1/y1-adoption-plan-v1/'
    changes = subprocess.check_output(['git', 'diff', '--name-only', BASE], cwd=ROOT, text=True).splitlines()
    assert all(name in allowed or name.startswith(prefix) for name in changes), changes
    for name in allowed:
        original = subprocess.check_output(['git', 'show', BASE + ':' + name], cwd=ROOT)
        assert (ROOT / name).read_bytes().startswith(original), name
    print('Unsigned Y1 adoption plan reproduced exactly from the existing bundle; actual reviewer outcomes and signers remain unfilled.')
    print('18 versions / 19 events, exact existing reviews and three unresolved findings unchanged; no domain write/dry run/activation.')
    print('Source rule, exact endpoints, event heads, atomic lifecycle constraints and non-executable plan verified.')
    print('Historical sources/results/thresholds preserved; independent acceptance, actual future transaction validation and benefit unmeasured.')


if __name__ == '__main__':
    main()

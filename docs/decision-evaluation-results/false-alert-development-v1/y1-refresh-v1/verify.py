"""Verify stored fresh comparisons and restore their exact Git state offline."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
from graph_engine import decision_schema as s
from graph_engine.brain import Brain
from graph_engine.decision_service import DecisionService
from tools.decision_benchmark.corpus import canonical, digest
from tools.decision_benchmark.reviewed_development import journal
from refresh import BASE, PRIOR, replay_mapping, roles


def validate(report: dict) -> None:
    assert report['status'] == 'complete_finding_open'
    assert report['case_id'] == 'controls-v2/event-surviving-support'
    assert report['author'] == dict(role='implementing-agent', human=False, independent=False)
    assert report['independent_acceptance'] is report['activation'] is report['resolution'] is False
    assert report['release_ready'] is False and report['provider_calls'] == 0
    assert report['human_review'] is report['semantic_scores'] is report['product_benefit'] is None
    assert report['independent_final_coverage'] == dict(positive=0, negative=0, inconclusive=0)
    assert digest(PRIOR.read_bytes()) == report['prior_archive_sha256']
    assert digest((HERE / 'refresh.py').read_bytes()) == report['runner_sha256']
    assert digest((HERE / 'brain.bundle').read_bytes()) == report['brain_bundle_sha256']
    meta = report['metadata']
    assert digest(canonical(meta['code_manifest'])) == meta['code_sha256']
    for path, sha in meta['code_manifest'].items():
        assert digest((ROOT / path).read_bytes()) == sha, path
    prior = json.loads(gzip.decompress(PRIOR.read_bytes()))['result']
    replay, final = report['replay'], report['final']
    assert replay_mapping(prior, replay) == report['mapping']
    initial = replay['final']['journal']
    assert final['journal']['versions'][:15] == initial['versions']
    assert final['journal']['events'][:16] == initial['events']
    assert len(final['journal']['versions']) == 16 and len(final['journal']['events']) == 17
    s.loads(json.dumps(dict(final['journal'], receipts=[])))
    assert report['stale_candidate_rejected']['type'] == 'RecordConflict'
    assert 'Candidate unavailable or changed' in report['stale_candidate_rejected']['message']
    refs = replay['references']
    counts = {'initial_to_y1': (10, 3), 'withdrawal_to_y1': (8, 2), 'y1_self': (0, 0)}
    for name, (deltas, candidates) in counts.items():
        comparison = report['comparisons'][name]['output']
        assert len(comparison['deltas']) == deltas and len(comparison['candidates']) == candidates
        assert not comparison['completeness']['truncated']
        assert comparison['completeness']['limits'] == dict(depth=3, objects=200, links=500, paths=20, deltas=200)
    fresh = report['fresh_candidate']
    assert fresh['target'] == refs['old_decision'] and 'support_withdrawn' in fresh['reasons']
    assert fresh['candidate_id'] != replay['comparison']['candidates'][0]['candidate_id']
    assert len(fresh['support']['remaining']) == 0 and len(fresh['support']['removed']) == 2
    assert {s.key(i['evidence']) for i in fresh['support']['removed']} == {
        s.key(refs['evidence']['X1']), s.key(refs['evidence']['Y1'])}
    new = next(c for c in report['comparisons']['initial_to_y1']['output']['candidates']
               if c['target'] == refs['decision'])
    assert 'comparability_unknown' in new['reasons']
    assert len(new['support']['remaining']) == 1
    assert new['support']['remaining'][0]['evidence'] == refs['evidence']['Y1']
    assert new['support']['remaining'][0]['relationship'] == refs['support']
    assert new['classification'] == 'proposed_preview'
    assert final['detail']['finding']['state'] == dict(finding_disposition='confirmed', finding_workflow='open')
    assert not final['detail']['finding']['basis_changed']
    assert final['detail']['finding']['record']['previous'] == refs['finding']
    assert final['old_finding']['state']['finding_workflow'] == 'acknowledged'
    assert final['old_finding']['basis_changed']
    assert final['decision']['state']['decision'] == final['dependency']['state']['workflow'] == 'proposed'
    assert final['decision']['events'] == final['dependency']['events'] == []
    assert final['old_decision']['state']['decision_conclusion'] == 'needs_investigation'
    assert final['x1']['state']['availability'] == 'withdrawn' and final['y1']['state']['availability'] == 'available'
    assert len(final['queue']['items']) == 3 and len(final['history']['items']) == 2
    assert len(final['queue_without_comparison']['items']) == 1
    assert final['queue_without_comparison']['items'][0]['reference'] == final['finding']
    current_event_ids = {e['event_id'] for e in replay['final']['journal']['events'] if e['subject'] == refs['claim']}
    assert current_event_ids <= set(fresh['basis_event_ids'])
    assert refs['support'] in fresh['basis_refs']
    assert refs['sources']['controls-v2/surviving-support-update'] in fresh['basis_refs']


def restore_check(report: dict) -> None:
    with tempfile.TemporaryDirectory(prefix='y1-refresh-restore-') as tmp:
        path = Path(tmp) / 'brain'
        subprocess.run(['git', 'clone', str(HERE / 'brain.bundle'), str(path)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(path), 'checkout', '--detach', report['final']['revision']], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(path), 'fsck', '--full'], check=True, capture_output=True)
        service = DecisionService(Brain(str(path), mode='git'))
        assert journal(path) == report['final']['journal']
        initial_preview = service.preview()
        for name, row in report['comparisons'].items():
            result = service.compare(row['input'])
            assert result['deltas'] == row['output']['deltas']
            assert result['candidates'] == row['output']['candidates']
            assert result['completeness'] == row['output']['completeness']
        refs = report['replay']['references']
        assert service.inspect(refs['finding'])['basis_changed']
        assert not service.inspect(report['final']['finding'])['basis_changed']
        assert service.inspect(refs['decision'])['state']['decision'] == 'proposed'
        request = dict(schema='dm.finding-review/1', idempotency_key=str(uuid4()),
            expected_generation=initial_preview['generation'], expected_heads=initial_preview['heads'],
            comparison=report['comparisons']['initial_to_y1']['input'],
            candidate_id=report['replay']['comparison']['candidates'][0]['candidate_id'], disposition='confirmed',
            reason='Scripted restore guard only; no independent human review or activation.')
        try:
            service.record_finding(request, dry_run=True, commit=False)
        except s.RecordConflict as exc:
            assert 'Candidate unavailable or changed' in str(exc)
        else:
            raise AssertionError('Stale candidate unexpectedly reviewable')
        assert journal(path) == report['final']['journal'] and service.preview() == initial_preview
    print('Git bundle restored: exact revisions, references, deltas and candidates reproduced; stale candidate rejected.')


def main() -> None:
    manifest = json.loads((HERE / 'manifest.json').read_bytes())
    inventory = {str(p.relative_to(HERE)) for p in HERE.rglob('*') if p.is_file()
                 and p.name != 'manifest.json' and '__pycache__' not in p.parts}
    assert set(manifest['files']) == inventory
    for name, sha in manifest['files'].items():
        assert digest((HERE / name).read_bytes()) == sha, name
    commands = json.loads((HERE / 'commands.json').read_bytes())
    assert len(commands) == 10 and all(c['exit_code'] == 0 for c in commands)
    before = json.loads((HERE / 'before-fix-snapshot-command.json').read_bytes())
    assert before['exit_code'] == 1 and before['expected_failure']
    assert '4 failed' in (HERE / 'before-fix-snapshot.log').read_text()
    history = json.loads((HERE / 'historical-commands.json').read_bytes())
    assert len(history) == 8 and all(c['exit_code'] == 0 for c in history)
    ci = json.loads((HERE / 'ci-code.json').read_bytes())
    assert len(ci) == 15 and all(c['state'] == 'SUCCESS' for c in ci)
    matrix = json.loads((HERE / 'integrity/report.json').read_bytes())
    assert matrix['execution_passed'] and matrix['software_matrix_complete']
    assert matrix['counts']['observed_passed_cells'] == matrix['counts']['applicable_cells'] == 41
    assert matrix['counts']['declared_not_applicable_cells'] == 13
    assert not matrix['release_ready'] and matrix['independent_sign_off'] is None
    comparison = json.loads((HERE / 'replay-comparison.json').read_bytes())
    assert comparison['status'] == 'pass' and comparison['original_scores_and_gates_unchanged']
    report = json.loads(gzip.decompress((HERE / 'report.json.gz').read_bytes()))
    validate(report)
    restore_check(report)
    assert not subprocess.check_output(['git', 'diff', report['metadata']['source_commit'], '--', 'graph_engine', 'tools', 'tests',
        'examples', '.github', 'pyproject.toml', 'CONTRIBUTING.md'], cwd=ROOT)
    changes = subprocess.check_output(['git', 'diff', '--name-only', BASE, '--',
        'docs/decision-evaluation-results'], cwd=ROOT, text=True).splitlines()
    assert all(p.startswith('docs/decision-evaluation-results/false-alert-development-v1/y1-refresh-v1/') for p in changes)
    print('Fresh comparison and open finding successor verified. Original archives unchanged; no activation/independent acceptance.')


if __name__ == '__main__':
    main()

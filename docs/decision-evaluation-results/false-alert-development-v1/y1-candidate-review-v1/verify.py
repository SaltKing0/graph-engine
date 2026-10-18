"""Reproduce both diagnostic reviews' source reasoning and exact saved states."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4

from review import (BASE, HERE, PRIOR, ROOT, REASONS, DISPOSITIONS, STATES, assert_preserved,
                   assert_same_comparison, compare_fields, examine, restore, source_guard)
from graph_engine import decision_schema as s
from tools.decision_benchmark.corpus import canonical, digest
from tools.decision_benchmark.reviewed_development import journal


def validate() -> None:
    inventory = json.loads((HERE / 'manifest.json').read_bytes())
    files = {str(p.relative_to(HERE)) for p in HERE.rglob('*') if p.is_file()
             and p.name != 'manifest.json' and '__pycache__' not in p.parts}
    assert files == set(inventory['files'])
    for name, sha in inventory['files'].items():
        assert digest((HERE / name).read_bytes()) == sha, name
    report = json.loads(gzip.decompress((HERE / 'report.json.gz').read_bytes()))
    prior = json.loads(gzip.decompress((PRIOR / 'report.json.gz').read_bytes()))
    assert report['schema'] == 'dm.development.y1-candidate-review/1'
    assert report['status'] == 'complete_two_diagnostics_unresolved'
    assert report['author'] == dict(role='implementing-agent', human=False, independent=False)
    assert report['source_snapshot'] == BASE and report['case_id'] == prior['case_id']
    assert report['independent_acceptance'] is report['activation'] is report['resolution'] is False
    assert report['release_ready'] is False and report['provider_calls'] == 0
    assert all(report[k] is None for k in ('human_review', 'semantic_scores', 'user_sessions', 'product_benefit'))
    assert report['independent_final_coverage'] == dict(positive=0, negative=0, inconclusive=0)
    assert digest((PRIOR / 'report.json.gz').read_bytes()) == report['prior_report_sha256']
    assert digest((PRIOR / 'brain.bundle').read_bytes()) == report['prior_bundle_sha256'] == prior['brain_bundle_sha256']
    assert digest((HERE / 'brain.bundle').read_bytes()) == report['brain_bundle_sha256']
    assert digest((HERE / 'review.py').read_bytes()) == report['runner_sha256']
    meta = report['metadata']
    assert meta['source_commit'] == BASE
    assert digest(canonical(meta['code_manifest'])) == meta['code_sha256']
    for name, sha in meta['code_manifest'].items():
        assert digest((ROOT / name).read_bytes()) == sha, name
    assert set(report['final']['finding_refs']) == set(DISPOSITIONS)
    for role, detail in report['final']['details'].items():
        assert detail['finding']['state'] == STATES[role]
        assert not detail['finding']['basis_changed'] and not detail['truncated']
        assert detail['candidate'] == report['analysis']['candidates'][role]
    assert report['analysis']['source_predicate'] == dict(value='0.8', operator='>=', threshold='0.7', unit='fraction', met=True)
    assert all(report['analysis'][k] is None for k in
               ('measurement_independence', 'statistical_sufficiency', 'general_decision_validity'))
    assert len(report['reviews']) == 2
    assert {r['request']['disposition'] for r in report['reviews']} == {'confirmed', 'inconclusive'}
    for row in report['reviews']:
        assert row['request']['reason'] == REASONS[row['role']]
    with source_guard(), tempfile.TemporaryDirectory(prefix='y1-two-candidate-check-') as tmp:
        path = Path(tmp)
        before = restore(PRIOR / 'brain.bundle', prior['final']['revision'], path / 'before')
        assert journal(path / 'before') == prior['final']['journal']
        assert examine(before, prior, report['comparison_input']) == report['analysis']
        assert compare_fields(before.compare(report['comparison_input'])) == compare_fields(report['comparison_before'])
        after = restore(HERE / 'brain.bundle', report['final']['revision'], path / 'after')
        assert journal(path / 'after') == report['final']['journal']
        assert_preserved(after, prior, prior['final']['journal'], report['final']['journal'], report['final']['finding_refs'])
        assert after.read('review-queue', {}) == report['final']['queue_without_comparison']
        assert after.read('review-queue', dict(history=True)) == report['final']['history']
        for role, ref in report['final']['finding_refs'].items():
            assert after.read('review-detail', dict(reference=ref)) == report['final']['details'][role]
        assert after.inspect(prior['final']['finding']) == report['final']['existing_withdrawal']
        for name in ('decision', 'dependency'):
            assert after.inspect(prior['replay']['references'][name]) == report['final'][name]
            assert report['final'][name]['events'] == []
        assert compare_fields(after.compare(report['comparison_input'])) == compare_fields(report['comparison_after'])
        current = report['current_comparison']
        assert compare_fields(after.compare(current['input'])) == compare_fields(current['output'])
        assert_same_comparison(report['comparison_before'], current['output'],
                               report['comparison_input']['after'], report['final']['revision'])
        # Same-key retries return their saved receipts; new-key duplicates are
        # rejected. Neither can append a third diagnostic event or erase a view.
        preview, saved = after.preview(), journal(path / 'after')
        for row in report['reviews']:
            assert after.record_finding(row['request'], commit=False) == row['result']
            duplicate = dict(row['request'], idempotency_key=str(uuid4()))
            try:
                after.record_finding(duplicate, dry_run=True, commit=False)
            except s.RecordConflict as exc:
                assert 'Candidate already reviewed' in str(exc)
            else:
                raise AssertionError('New-key duplicate finding accepted')
        assert journal(path / 'after') == saved and after.preview() == preview
    # Guard every previously committed file, including sources, freezes,
    # results, tests and review history. Only two appended guides are allowed.
    allowed = {'docs/decision-source-observations.md', 'docs/decision-release-readiness.md'}
    prefix = 'docs/decision-evaluation-results/false-alert-development-v1/y1-candidate-review-v1/'
    changes = subprocess.check_output(['git', 'diff', '--name-only', BASE], cwd=ROOT, text=True).splitlines()
    assert all(name in allowed or name.startswith(prefix) for name in changes), changes
    for name in allowed:
        original = subprocess.check_output(['git', 'show', BASE + ':' + name], cwd=ROOT)
        assert (ROOT / name).read_bytes().startswith(original), name
    commands = json.loads((HERE / 'commands.json').read_bytes())
    assert all(c['exit_code'] == 0 for c in commands)
    assert len(commands) >= 3
    assert 'passed' in (HERE / 'focused.log').read_text()
    print('Exact 16/17 prior state restored; source bindings, both candidates and raw qualifications reproduced.')
    print('18 versions / 19 events: claim confirmed/open; proposed dependency inconclusive/workflow null; withdrawal unchanged/open.')
    print('Three unresolved queue entries; exact successor bundle restored; retry/duplicate guards pass without writes.')
    print('No activation, dependency acceptance, resolution, independent evaluation or frozen-data/runtime change.')


if __name__ == '__main__':
    validate()

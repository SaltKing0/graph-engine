"""Verify the recorded development run without opening labels/reserved sources.

Re-execution uses a NEW output directory via support_paths, since Git/event IDs
and review timestamps differ. Verification checks semantic wiring and exact
stored identities, not equality of newly generated IDs or human acceptance.
"""
from __future__ import annotations

import ast

import gzip
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
from graph_engine import decision_schema as s
from tools.decision_benchmark.corpus import canonical, digest
from tools.decision_benchmark.support_paths import AUDIT, assess_source, prepare

BASE = 'ad757775ff6a03af46dcf6ac6872fc81b4f8ae08'


def validate_report(report: dict) -> None:
    assert report['schema'] == 'dm.development.support-paths/1' and report['status'] == 'complete'
    assert report['author'] == dict(role='implementing-agent', human=False, independent=False)
    assert type(report['author']['human']) is bool and type(report['author']['independent']) is bool
    assert report['independent_acceptance'] is report['release_ready'] is False
    assert report['human_review'] is report['statistical_sufficiency'] is report['semantic_scores'] is report['product_benefit'] is None
    assert report['independent_final_coverage'] == dict(positive=0, negative=0, inconclusive=0)
    assert report['provider_calls'] == 0
    old_tree = ast.parse((AUDIT.parent / 'verify.py').read_text())
    new_tree = ast.parse((ROOT / 'tools/decision_benchmark/support_paths.py').read_text())
    old = next(n for n in old_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'assessment')
    new = next(n for n in new_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'assess_source')
    old.name = new.name
    assert ast.dump(old, include_attributes=False) == ast.dump(new, include_attributes=False)
    sources, case, packet = prepare()
    assert report['case_id'] == case['id']
    assert report['source_manifest'] == packet['sources']
    assert report['source_input_sha256'] == digest(canonical(case['runtime']))
    assert report['audit_sha256'] == digest(AUDIT.read_bytes())
    r = report['result']
    assert r['assessment'] == assess_source(packet, sources, case)
    assert r['assessment']['supports_stated_rule_as_declared']
    assert r['assessment']['threshold'] == '0.7' and r['assessment']['value'] == '0.8'
    assert not r['assessment']['accepted_runtime_sufficiency']  # Source audit claim stays bounded.
    meta = report['metadata']
    assert not meta['source_dirty']
    assert meta['code_sha256'] == digest(canonical(meta['code_manifest']))
    for name, expected in meta['code_manifest'].items():
        original = subprocess.check_output(['git', 'show', meta['source_commit'] + ':' + name], cwd=ROOT)
        assert digest(original) == expected == digest((ROOT / name).read_bytes()), name
    refs, initial, proposal, final = r['references'], r['initial'], r['proposal'], r['final']
    data = final['journal']
    # Authorized exports omit retry receipts; validate every content/event chain
    # with the unchanged production schema after adding only an empty receipt list.
    s.loads(json.dumps(dict(data, receipts=[])))
    assert len(data['versions']) == 15 and len(data['events']) == 16
    records = {s.key(v): v for v in data['versions']}
    events = {e['event_id']: e for e in data['events']}
    for snapshot in (initial['journal'], r['withdrawal']['journal'], proposal['journal']):
        assert data['versions'][:len(snapshot['versions'])] == snapshot['versions']
        assert data['events'][:len(snapshot['events'])] == snapshot['events']
    for version in data['versions']:
        assert s.hash_record(version) == version['version_id']
        assert version['kind'] != 'result'  # No execution, participant or measurement invented.
        if version['previous']:
            old = records[s.key(version['previous'])]
            assert old['id'] == version['id'] and old['anchor_node_id'] == version['anchor_node_id']
        assert all(s.key(ref) in records for ref in s.content_refs(version))
        if version['kind'] == 'evidence':
            assert version['payload']['lineage_ids'] == []
            for citation in version['payload']['sources']:
                text = records[s.key(citation['ref'])]['payload']['text']
                p = citation['passage']
                assert text[p['start']:p['end']] == p['quote']
    for event in data['events']:
        assert 'Scripted synthetic developer review; no independent human validation.' in event['reason']
        assert all(b['event_id'] in events for b in event['basis'] if b['type'] == 'event_ref')
        assert s.key(event['subject']) in records
    for name, ref in refs['sources'].items():
        payload = records[s.key(ref)]['payload']
        assert payload['artifact']['sha256'] == packet['sources'][name]['text_sha256']
        assert payload['text'] == sources[name]['text'] + '\n'
        assert payload['lineage_ids'] == ['document-sha256:' + packet['sources'][name]['text_sha256']]
        assert s.key(ref) not in {s.key(v) for v in initial['journal']['versions']} or name == packet['rule']['source_id']
    assert len(r['comparison']['candidates']) == 1
    c = r['comparison']['candidates'][0]
    assert set(c['reasons']) == {'basis_changed', 'support_withdrawn'}
    assert c['target'] == refs['old_decision']
    assert [i['evidence'] for i in c['support']['removed']] == [refs['evidence']['X1']]
    assert [i['evidence'] for i in c['support']['remaining']] == [refs['evidence']['Y1']]
    removed, remaining = c['support']['removed'][0], c['support']['remaining'][0]
    assert removed['lineage_ids'] == remaining['lineage_ids']
    assert removed['sources'] == remaining['sources']
    assert removed['independence'] == remaining['independence'] == 'not inferred'
    assert events[refs['withdrawal_event']]['subject'] == refs['evidence']['X1']
    assert events[refs['withdrawal_event']]['axis'] == 'availability'
    assert events[refs['withdrawal_event']]['to'] == 'withdrawn'
    assert final['claim']['record']['previous'] == refs['old_claim']
    assert final['claim']['record']['provenance']['inputs'] == [refs['evidence']['Y1'], refs['sources'][packet['update']['source_id']]]
    assert proposal['claim']['events'] == [] and proposal['support']['events'] == []
    assert proposal['claim']['state']['epistemic'] == 'unassessed'
    assert proposal['claim']['state']['workflow'] == proposal['support']['state']['workflow'] == 'proposed'
    assert final['claim']['effective_assessment'] == 'supported' and not final['claim']['basis_changed']
    assert final['support']['record']['payload']['source'] == refs['evidence']['Y1']
    assert final['support']['record']['payload']['target'] == refs['claim']
    for subject, ev in refs['evidence'].items():
        assert records[s.key(refs['old_supports'][subject])]['payload']['source'] == ev
        assert records[s.key(refs['old_supports'][subject])]['payload']['target'] == refs['old_claim']
    for event in final['claim']['events'] + final['support']['events']:
        assert event not in initial['journal']['events']
        assert refs['evidence']['X1'] not in s.content_refs(event['basis'])
    assert final['old_claim']['record'] == initial['claim']['record'] == final['historical_claim']['record']
    assert final['old_claim']['events'] == initial['claim']['events']
    assert final['old_claim']['basis_changed'] and final['old_claim']['effective_assessment'] == 'inconclusive'
    assert final['decision']['record']['previous'] == refs['old_decision']
    assert final['decision']['events'] == [] and final['decision']['state']['decision'] == 'proposed'
    assert final['dependency']['events'] == [] and final['dependency']['state']['workflow'] == 'proposed'
    assert final['dependency']['record']['payload']['source'] == refs['decision']
    assert final['dependency']['record']['payload']['target'] == refs['claim']
    assert final['old_decision']['state']['decision'] == 'current'
    assert final['old_decision']['state']['decision_conclusion'] == 'needs_investigation'
    assert final['finding']['state']['finding_disposition'] == 'confirmed'
    assert final['finding']['state']['finding_workflow'] == 'acknowledged'
    assert final['finding']['basis_changed']


def verify() -> None:
    manifest = json.loads((HERE / 'manifest.json').read_bytes())
    files = {str(p.relative_to(HERE)) for p in HERE.rglob('*') if p.is_file()
             and p.name != 'manifest.json' and '__pycache__' not in p.parts}
    assert files == set(manifest['files'])
    for name, expected in manifest['files'].items():
        assert digest((HERE / name).read_bytes()) == expected, name
    report = json.loads(gzip.decompress((HERE / 'support-paths-report.json.gz').read_bytes()))
    validate_report(report)
    commands = json.loads((HERE / 'commands.json').read_bytes())
    assert len(commands) == 10 and all(c['exit_code'] == 0 for c in commands)
    scope = json.loads((HERE / 'scope-state.json').read_bytes())
    assert scope['documentation_edits_only'] and not scope['tracked_implementation_changes']
    matrix = json.loads((HERE / 'integrity/report.json').read_bytes())
    assert matrix['status'] == 'complete' and matrix['execution_passed'] and matrix['software_matrix_complete']
    assert matrix['counts']['observed_passed_cells'] == matrix['counts']['applicable_cells'] == 41
    assert matrix['counts']['declared_not_applicable_cells'] == 13
    assert not matrix['independent_sign_off'] and not matrix['release_ready']
    for name in ['workflow.json.gz']:
        run = json.loads(gzip.decompress((HERE / name).read_bytes()))
        assert run['status'] == 'complete'
        assert run['metadata']['source_commit'] == report['metadata']['source_commit']
        for path, expected in run['metadata']['code_manifest'].items():
            assert digest((ROOT / path).read_bytes()) == expected
    comparison = json.loads((HERE / 'replay-comparison.json').read_bytes())
    assert comparison['status'] == 'pass' and comparison['original_scores_and_gates_unchanged']
    assert len(comparison['development_cases']) == 13
    production = json.loads(gzip.decompress((HERE / 'production-controls.json.gz').read_bytes()))
    assert production['scores']['curated']['false_alert_rate']['numerator'] == 5
    assert production['scores']['curated']['false_alert_rate']['denominator'] == 95
    assert production['gate_assessments']['curated']['gates']['false_alerts']['status'] == 'fail'
    assert production['gate_assessments']['proposed']['gates']['misses']['status'] == 'fail'
    assert not production['release_readiness']['passed']
    ci = json.loads((HERE / 'ci-code.json').read_bytes())
    pr = json.loads((HERE / 'pr-code-state.json').read_bytes())
    assert len(ci) == 15 and all(c['state'] == 'SUCCESS' for c in ci)
    assert pr['headRefOid'] == report['metadata']['source_commit'] and pr['isDraft']
    historical = json.loads((HERE / 'historical-commands.json').read_bytes())
    assert len(historical) == 6 and all(c['exit_code'] == 0 for c in historical)
    assert not subprocess.check_output(['git', 'diff', BASE, '--', 'graph_engine',
        'tools/decision_benchmark/data', 'examples', '.github', 'pyproject.toml'], cwd=ROOT)
    changed = subprocess.check_output(['git', 'diff', '--name-only', BASE, '--',
        'docs/decision-evaluation-results'], cwd=ROOT, text=True).splitlines()
    assert all(name.startswith('docs/decision-evaluation-results/false-alert-development-v1/support-paths-v1/') for name in changed)
    print('Complete artifact inventory, pinned implementation, source-bound paths, fresh reviews and exact history verified.')
    print('One previously exposed synthetic case; no independent acceptance or product-benefit result.')


if __name__ == '__main__':
    verify()

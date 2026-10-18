"""Review two known development candidates in the exact restored Y1 brain.

Only diagnostic finding dispositions are written, through the public API.
No dependency acceptance, decision activation, resolution or final-data option.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
from examples.decision_memory import _commit
from graph_engine import decision_schema as s
from graph_engine.brain import Brain
from graph_engine.decision_service import DecisionService
from tools.decision_benchmark.corpus import DATA, canonical, digest
from tools.decision_benchmark.observations import value
from tools.decision_benchmark.reviewed_development import journal
from tools.decision_benchmark.support_paths import prepare
from tools.memory_benchmark.runner import source_metadata

BASE = '08f55ea4120336db83ada29ea2c305f777186fab'
PRIOR = HERE.parent / 'y1-refresh-v1'
SOURCE_REVIEW = HERE.parent / 'y1-basis-review-v1' / 'review.py'
REASONS = {
    'claim_change': 'Scripted synthetic developer diagnostic review; no human or independent acceptance. '
        'Confirmed material change of the OLD decision basis: the exact old claim/dependency remain historical; '
        'the successor claim narrows provenance from X1/Y1 to Y1 plus the withdrawal update. '
        'Y1 meets only the declared fictional recall rule under the same five conditions; '
        'its new support does not repair the old endpoint. comparability_unknown on the one-hop dependency '
        'is retained, not treated as evidence of contradictory scope. Keep investigation and finding open; '
        'do not activate, resolve, accept dependencies or infer measurement independence.',
    'proposed_dependency': 'Scripted synthetic developer diagnostic review; no human or independent acceptance. '
        'Inconclusive impact on an adopted decision: this exact new dependency and successor decision '
        'are both proposed and have no review events. Their endpoints/context are consistent with the '
        'source-qualified Y1 claim, and its explicit accepted support is available and comparable. '
        'The raw proposed_preview/comparability_unknown qualifications remain; source consistency alone '
        'does not approve the dependency or establish actual decision validity. Keep the finding open; '
        'do not activate, resolve, accept dependencies or infer measurement independence.',
}
DISPOSITIONS = {'claim_change': 'confirmed', 'proposed_dependency': 'inconclusive'}


def source_guard():
    spec = importlib.util.spec_from_file_location('known_y1_source_guard', SOURCE_REVIEW)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.development_reads()


def restore(bundle: Path, revision: str, path: Path) -> DecisionService:
    subprocess.run(['git', 'clone', str(bundle.resolve()), str(path)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(path), 'checkout', '--detach', revision], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(path), 'fsck', '--full'], check=True, capture_output=True)
    return DecisionService(Brain(str(path), mode='git'))


def compare_fields(result: dict) -> dict:
    """Exclude only clock/current-read metadata, never candidates or deltas."""
    return {k: result[k] for k in ('deltas', 'candidates', 'completeness')}


def assert_same_comparison(old: dict, new: dict, old_revision: str, new_revision: str) -> None:
    """An unchanged path is displayed at the selected revision, not its birth.

    Retain both raw outputs. Only that exact known after-revision replacement
    is permitted; IDs, endpoints, qualifications and every other field match.
    """
    expected = deepcopy(compare_fields(old))
    for candidate in expected['candidates']:
        for path in candidate['paths']:
            for step in path:
                if step['revision'] == old_revision:
                    step['revision'] = new_revision
    assert expected == compare_fields(new)


def examine(service: DecisionService, prior: dict, comparison: dict) -> dict:
    """Inspect existing engine output; audit notes are never comparison inputs."""
    sources, case, packet = prepare()
    assert case['id'] == prior['case_id'] == 'controls-v2/event-surviving-support'
    assert packet['sources'] == prior['source_manifest']
    assert digest(canonical(case['runtime'])) == prior['source_input_sha256']
    refs = prior['replay']['references']
    objects = {role: service.inspect(refs[role]) for role in
               ('old_claim', 'claim', 'old_dependency', 'dependency', 'support', 'old_decision', 'decision')}
    objects.update({name: service.inspect(refs['evidence'][name]) for name in ('X1', 'Y1')})
    rows = service.compare(comparison)
    archived = prior['comparisons']['initial_to_y1']
    assert_same_comparison(archived['output'], rows, archived['input']['after'], comparison['after'])
    candidates = {
        'claim_change': next(c for c in rows['candidates'] if c['delta']['kind'] == 'claim'),
        'proposed_dependency': next(c for c in rows['candidates']
                                   if c['delta']['new'] == refs['dependency']),
    }
    old, current = (objects[k]['record'] for k in ('old_claim', 'claim'))
    assert current['previous'] == refs['old_claim']
    assert old['provenance']['inputs'] == [refs['evidence']['X1'], refs['evidence']['Y1']]
    assert current['provenance']['inputs'] == [refs['evidence']['Y1'],
        refs['sources']['controls-v2/surviving-support-update']]
    assert refs['evidence']['X1'] not in s.content_refs(current)
    assert old['payload']['context'] == current['payload']['context']
    assert old['payload']['limitations'] == current['payload']['limitations'] == objects['Y1']['record']['payload']['limitations']
    assert objects['old_claim']['basis_changed'] and objects['old_dependency']['basis_changed']
    assert objects['old_claim']['effective_assessment'] == 'inconclusive'
    assert objects['claim']['effective_assessment'] == 'supported' and not objects['claim']['basis_changed']
    assert objects['old_decision']['state']['decision_conclusion'] == 'needs_investigation'
    assert objects['X1']['state']['availability'] == 'withdrawn'
    assert objects['Y1']['state']['availability'] == 'available'
    support = objects['support']
    assert support['state']['workflow'] == 'accepted' and not support['basis_changed']
    assert support['comparison']['status'] == 'comparable'
    assert support['record']['payload']['source'] == refs['evidence']['Y1']
    assert support['record']['payload']['target'] == refs['claim']
    for role, decision, claim in [('old_dependency', 'old_decision', 'old_claim'),
                                  ('dependency', 'decision', 'claim')]:
        relation = objects[role]['record']['payload']
        assert relation['kind'] == 'depends_on'
        assert relation['source'] == refs[decision] and relation['target'] == refs[claim]
        assert relation['context'] == objects[claim]['record']['payload']['context']
    assert objects['decision']['record']['previous'] == refs['old_decision']
    assert objects['decision']['record']['provenance']['inputs'] == [refs['claim']]
    assert objects['decision']['record']['payload']['context'] == current['payload']['context']
    assert objects['decision']['record']['payload']['action'] == objects['old_decision']['record']['payload']['action']
    assert objects['decision']['events'] == objects['dependency']['events'] == []
    assert objects['decision']['state']['decision'] == objects['dependency']['state']['workflow'] == 'proposed'
    claim, dependency = candidates['claim_change'], candidates['proposed_dependency']
    for candidate, target, link, acceptance in [(claim, 'old_decision', 'old_dependency', 'accepted'),
                                               (dependency, 'decision', 'dependency', 'proposed')]:
        assert candidate['target'] == refs[target]
        assert candidate['reasons'] == ['basis_changed', 'comparability_unknown']
        assert candidate['comparison'] == [dict(status='unknown',
            reasons=['No structured evidential scope comparison on path'], intersection={})]
        assert len(candidate['paths']) == len(candidate['paths'][0]) == 1
        step = candidate['paths'][0][0]
        assert step['relationship'] == refs[link] and step['to_ref'] == refs[target]
        assert step['from_ref'] == refs['claim' if target == 'decision' else 'old_claim']
        assert step['kind'] == 'depends_on' and step['acceptance'] == acceptance
        assert not candidate['completeness']['truncated']
    assert claim['classification'] == 'candidate_semantic_impact'
    assert claim['delta']['old'] == refs['old_claim'] and claim['delta']['new'] == refs['claim']
    assert claim['substitutions'] == [dict(old=refs['old_claim'], new=refs['claim'])]
    assert not claim['support']['remaining'] and len(claim['support']['removed']) == 2
    assert {s.key(x['relationship']) for x in claim['support']['removed']} == {
        s.key(r) for r in refs['old_supports'].values()}
    assert dependency['classification'] == 'proposed_preview'
    assert dependency['delta']['old'] is None and dependency['delta']['new'] == refs['dependency']
    assert dependency['substitutions'] == [] and not dependency['support']['removed']
    assert len(dependency['support']['remaining']) == 1
    remaining = dependency['support']['remaining'][0]
    assert remaining['evidence'] == refs['evidence']['Y1'] and remaining['relationship'] == refs['support']
    assert remaining['claim'] == refs['claim'] and remaining['status'] == 'available'
    assert remaining['independence'] == 'not inferred'
    assert remaining['sources'] == [refs['sources']['controls-v2/surviving-support-basis']]
    rule, y1 = packet['rule'], packet['remaining']
    predicate = dict(value=value(y1['value']), operator=value(rule['operator']), threshold=value(rule['threshold']),
                     unit=value(rule['unit']), met=Decimal(value(y1['value'])) >= Decimal(value(rule['threshold'])))
    assert predicate == dict(value='0.8', operator='>=', threshold='0.7', unit='fraction', met=True)
    assert y1['unit_from_rule'] and value(y1['conditions_reference']) == 'under the same conditions'
    dimensions = {k: dict(type='id', value=value(b)) for k, b in y1['conditions'].items()}
    assert dimensions == current['payload']['context']['dimensions'] == support['comparison']['intersection']
    citations = []
    for row, fields in [(rule, ['statement']), (y1, ['statement', 'conditions_reference']),
                        (packet['update'], ['withdrawal_statement', 'availability_statement', 'separate_run_statement'])]:
        for field in fields:
            binding = row[field]
            assert sources[row['source_id']]['text'][binding['start']:binding['end']] == binding['quote']
            citations.append(dict(source_id=row['source_id'], ref=refs['sources'][row['source_id']], field=field,
                                  **{k: binding[k] for k in ('start', 'end', 'quote')}))
    details = {name: service.read('review-detail', dict(comparison=comparison, candidate_id=c['candidate_id']))
               for name, c in candidates.items()}
    assert all(not d['truncated'] and d['finding'] is None for d in details.values())
    return dict(candidates=candidates, details=details, objects=objects, source_predicate=predicate,
        source_manifest=packet['sources'], source_input_sha256=digest(canonical(case['runtime'])),
        dimensions=dimensions, citations=citations, root_lineage=remaining['lineage_ids'],
        findings=dict(
            claim_change='Material source/provenance narrowing; old decision needs investigation. No old approval transfers.',
            proposed_dependency='Exact endpoints/source context consistent; impact on an adopted decision remains inconclusive.'),
        comparison_unknown='One-hop depends_on has no structured evidential scope comparison; not a proven source conflict.',
        measurement_independence=None, statistical_sufficiency=None, general_decision_validity=None)


def assert_preserved(service: DecisionService, prior: dict, before: dict, final: dict, finding_refs: dict) -> None:
    assert final['versions'][:len(before['versions'])] == before['versions']
    assert final['events'][:len(before['events'])] == before['events']
    assert len(before['versions']) == 16 and len(before['events']) == 17
    assert len(final['versions']) == 18 and len(final['events']) == 19
    assert all(v['kind'] == 'finding' and v['previous'] is None for v in final['versions'][16:])
    assert all(e['axis'] == 'finding_disposition' for e in final['events'][17:])
    for role, ref in finding_refs.items():
        item = service.inspect(ref)
        assert item['state'] == dict(finding_disposition=DISPOSITIONS[role], finding_workflow='open')
        assert not item['basis_changed'] and len(item['events']) == 1
        assert item['events'][0]['reason'] == REASONS[role]
    refs = prior['replay']['references']
    assert service.read('review-detail', dict(reference=prior['final']['finding']))['finding'] == prior['final']['detail']['finding']
    assert service.inspect(refs['finding']) == prior['final']['old_finding']
    for role in ('decision', 'dependency', 'old_decision'):
        assert service.inspect(refs[role]) == prior['final'][role]
    queue = service.read('review-queue', {})
    assert len(queue['items']) == 3 and not queue['truncated']
    assert {s.key(i['reference']) for i in queue['items']} == {
        s.key(prior['final']['finding']), *(s.key(r) for r in finding_refs.values())}
    assert all(i['item']['state']['finding_workflow'] == 'open' for i in queue['items'])
    s.loads(json.dumps(dict(final, receipts=[])))


def run(output: Path) -> dict:
    if output.resolve().is_relative_to(DATA.resolve()):
        raise ValueError('Keep output outside frozen data')
    output.mkdir(parents=True, exist_ok=False)
    report = dict(schema='dm.development.y1-candidate-review/1', status='running',
        author=dict(role='implementing-agent', human=False, independent=False), case_id='controls-v2/event-surviving-support',
        exposure='Same previously exposed development case; exact prior state restored, no new independent cases',
        source_snapshot=BASE, metadata=source_metadata(ROOT), runner_sha256=digest(Path(__file__).read_bytes()),
        prior_report_sha256=digest((PRIOR / 'report.json.gz').read_bytes()),
        prior_bundle_sha256=digest((PRIOR / 'brain.bundle').read_bytes()),
        independent_acceptance=False, activation=False, resolution=False, release_ready=False, provider_calls=0,
        human_review=None, semantic_scores=None, user_sessions=None, product_benefit=None,
        independent_final_coverage=dict(positive=0, negative=0, inconclusive=0))
    dependencies = [*ROOT.glob('tools/decision_benchmark/*.py'), ROOT / 'examples/decision_memory.py', SOURCE_REVIEW]
    report['metadata']['code_manifest'].update({str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in dependencies})
    report['metadata']['code_sha256'] = digest(canonical(report['metadata']['code_manifest']))
    try:
        with source_guard():
            prior = json.loads(gzip.decompress((PRIOR / 'report.json.gz').read_bytes()))
            assert report['prior_bundle_sha256'] == prior['brain_bundle_sha256']
            path = output / 'brain'
            service = restore(PRIOR / 'brain.bundle', prior['final']['revision'], path)
            before = journal(path)
            assert before == prior['final']['journal']
            comparison = dict(prior['comparisons']['initial_to_y1']['input'], after=prior['final']['revision'])
            report['comparison_input'] = comparison
            report['analysis'] = examine(service, prior, comparison)
            report['comparison_before'] = service.compare(comparison)
            report['queue_before'] = service.read('review-queue', dict(comparison=comparison))
            assert len(report['queue_before']['items']) == 3
            assert sum(i['kind'] == 'candidate' for i in report['queue_before']['items']) == 2
            finding_refs, reviews = {}, []
            for name in ('claim_change', 'proposed_dependency'):
                candidate = report['analysis']['candidates'][name]
                preview = service.preview()
                request = dict(schema='dm.finding-review/1', idempotency_key=str(uuid4()),
                    expected_generation=preview['generation'], expected_heads=preview['heads'],
                    comparison=comparison, candidate_id=candidate['candidate_id'],
                    disposition=DISPOSITIONS[name], reason=REASONS[name])
                result = service.record_finding(request, commit=False)
                finding_refs[name] = result['receipt']['refs'][0]
                reviews.append(dict(role=name, request=request, result=result))
                assert service.record_finding(request, commit=False) == result  # durable same-key retry
            revision = _commit(service)
            service = DecisionService(Brain(str(path), mode='git'))
            final = journal(path)
            assert_preserved(service, prior, before, final, finding_refs)
            report['reviews'] = reviews
            report['final'] = dict(revision=revision, journal=final, finding_refs=finding_refs,
                details={name: service.read('review-detail', dict(reference=ref)) for name, ref in finding_refs.items()},
                queue=service.read('review-queue', dict(comparison=comparison)),
                queue_without_comparison=service.read('review-queue', {}),
                history=service.read('review-queue', dict(history=True)),
                existing_withdrawal=service.inspect(prior['final']['finding']),
                decision=service.inspect(prior['replay']['references']['decision']),
                dependency=service.inspect(prior['replay']['references']['dependency']))
            assert all(i['kind'] == 'finding' for i in report['final']['queue']['items'])
            assert len(report['final']['queue']['items']) == 3 and len(report['final']['history']['items']) == 4
            assert all(not d['truncated'] for d in report['final']['details'].values())
            report['comparison_after'] = service.compare(comparison)
            assert compare_fields(report['comparison_after']) == compare_fields(report['comparison_before'])
            final_comparison = dict(comparison, after=revision)
            report['current_comparison'] = dict(input=final_comparison, output=service.compare(final_comparison))
            assert_same_comparison(report['comparison_before'], report['current_comparison']['output'],
                                   comparison['after'], revision)
            report['current_queue'] = service.read('review-queue', dict(comparison=final_comparison))
            assert all(i['kind'] == 'finding' for i in report['current_queue']['items'])
            subprocess.run(['git', '-C', str(path), 'bundle', 'create', str((output / 'brain.bundle').resolve()), 'HEAD'],
                           check=True, capture_output=True)
            report['brain_bundle_sha256'] = digest((output / 'brain.bundle').read_bytes())
            report['status'] = 'complete_two_diagnostics_open'
    except Exception as exc:
        report.update(status='failed', error=dict(type=type(exc).__name__, message=str(exc)))
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New development output directory')
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps(dict(status=result['status'], findings={k: v['finding']['state']
        for k, v in result['final']['details'].items()}, activation=False, independent_acceptance=False)))


if __name__ == '__main__':
    main()

"""Fresh public-API comparison of the one known synthetic Y1 development case.

Replay is explicit: the old temporary brain was deleted, not silently restored.
The prior archive/reviews stay immutable; new IDs are mapped by semantic role.
No labels, reserved cases, providers, independent acceptance or activation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
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
from graph_engine import decision_schema as s
from graph_engine.brain import Brain
from graph_engine.decision_service import DecisionService
from tools.decision_benchmark.corpus import DATA, canonical, digest
from tools.decision_benchmark.reviewed_development import journal
from tools.decision_benchmark.support_paths import REASON, capture, prepare
from tools.memory_benchmark.runner import source_metadata

BASE = '22e398a572397ca378a25ac93dc4a3b71666dd98'
PRIOR = HERE.parent / 'support-paths-v1/support-paths-report.json.gz'


def roles(result: dict) -> dict:
    refs = result['references']
    result_roles = {k: refs[k] for k in ('old_claim', 'claim', 'old_decision', 'decision',
                                       'old_dependency', 'dependency', 'support', 'finding')}
    result_roles['profile'] = result['initial']['claim']['record']['payload']['context']['profile']
    for prefix, field in [('source', 'sources'), ('evidence', 'evidence'), ('old_support', 'old_supports')]:
        result_roles.update({prefix + ':' + k: v for k, v in refs[field].items()})
    assert len(result_roles) == 15
    return result_roles


def replay_mapping(old: dict, new: dict) -> dict:
    """Compare exact payloads/provenance/bases modulo explicitly mapped refs.

    Per-run IDs, record/review timestamps and candidate derivation identities
    differ. They are never presented as the old execution's exact identities.
    """
    a, b = roles(old), roles(new)
    assert a.keys() == b.keys()
    indexes = [{s.key(ref): name for name, ref in r.items()} for r in (a, b)]
    records = [{s.key(v): v for v in r['final']['journal']['versions']} for r in (old, new)]
    event_roles = []
    for result, idx in zip((old, new), indexes):
        event_roles.append({e['event_id']: idx[s.key(e['subject'])] + ':' + e['axis']
                            for e in result['final']['journal']['events']})
    assert all(len(set(m.values())) == 16 for m in event_roles)

    def normalize(obj: object, side: int) -> object:
        if isinstance(obj, dict):
            if set(obj) == {'id', 'version_id'}:
                return dict(role=indexes[side][s.key(obj)])
            return {k: normalize(v, side) for k, v in obj.items()}
        if isinstance(obj, list):
            return [normalize(v, side) for v in obj]
        if isinstance(obj, str) and obj in event_roles[side]:
            return event_roles[side][obj]
        return obj

    rows = []
    for name in a:
        if name == 'finding':
            continue
        material = []
        for side, ref in enumerate((a[name], b[name])):
            v = records[side][s.key(ref)]
            material.append(normalize({k: v[k] for k in ('kind', 'payload', 'provenance', 'previous')}, side))
        assert material[0] == material[1], 'Replay content differs: ' + name
        rows.append(dict(role=name, previous=a[name], replay=b[name], normalized_sha256=digest(canonical(material[0]))))
    # Finding candidate IDs/revisions are per-run; compare its actual path and
    # support meanings, disposition/workflow, not invented old Git identities.
    lineage_displays = []
    for field in ('target', 'decision', 'paths', 'comparison', 'reasons', 'support', 'classification', 'judgment', 'needs_review'):
        values = []
        for side, result in enumerate((old, new)):
            val = deepcopy(result['comparison']['candidates'][0][field])
            if field == 'paths':
                for path in val:
                    for step in path:
                        step.pop('revision', None)
            if field == 'support':
                # This display tag describes iteration over available roots;
                # random per-run relationship order can change a removed item's
                # shared/distinct tag. Actual roots/status/independence remain
                # exact invariants; retain every raw tag rather than relabel it.
                for group in ('removed', 'remaining'):
                    for item in val[group]:
                        assert item['lineage'] in ('shared', 'distinct_recorded_roots')
                        assert item['independence'] == 'not inferred' and item['lineage_ids']
                        lineage_displays.append(dict(side=side, group=group,
                            evidence=normalize(item['evidence'], side), display=item.pop('lineage')))
            values.append(normalize(val, side))
        assert values[0] == values[1], 'Replay withdrawal meaning differs: ' + field
    old_events, new_events = {}, {}
    for side, result in enumerate((old, new)):
        dest = old_events if side == 0 else new_events
        for event in result['final']['journal']['events']:
            name = event_roles[side][event['event_id']]
            dest[name] = normalize({k: event[k] for k in ('subject', 'axis', 'from', 'to', 'basis',
                'reason', 'previous_event_id', 'supersedes_event_id', 'reviewer')}, side)
    assert old_events == new_events
    return dict(content_roles=rows, original_finding=a['finding'], replay_finding=b['finding'],
        equal_review_semantics=len(old_events), lineage_display_tags=lineage_displays,
        lineage_scope='Raw per-iteration shared/distinct display tags may differ. Exact root sets, source refs, availability statuses and not-inferred independence are compared, never ignored.',
        identity_policy='New per-run IDs/times and Git revisions, explicitly mapped; no claim of exact original execution identity.')


def run(output: Path) -> dict:
    if output.resolve().is_relative_to(DATA.resolve()):
        raise ValueError('Keep output outside frozen data')
    output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('known_y1_source_review', HERE.parent / 'y1-basis-review-v1/review.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    report = dict(schema='dm.development.y1-refresh/1', status='running',
        author=dict(role='implementing-agent', human=False, independent=False),
        metadata=source_metadata(ROOT), runner_sha256=digest(Path(__file__).read_bytes()),
        prior_archive_sha256=digest(PRIOR.read_bytes()), source_snapshot=BASE,
        exposure='Replay of one already exposed development case, not a new independent case',
        independent_acceptance=False, human_review=None, semantic_scores=None, product_benefit=None,
        independent_final_coverage=dict(positive=0, negative=0, inconclusive=0),
        activation=False, resolution=False, release_ready=False, provider_calls=0)
    try:
        with audit.development_reads():
            audit.examine()  # Validate the immutable prior source/basis and journal.
            sources, case, packet = prepare()
            report.update(case_id=case['id'], source_manifest=packet['sources'],
                          source_input_sha256=digest(canonical(case['runtime'])))
            prior = json.loads(gzip.decompress(PRIOR.read_bytes()))['result']
            path = output / 'brain'
            replay = capture(path, sources, case, packet)
            report['replay'] = replay
            report['mapping'] = replay_mapping(prior, replay)
            service = DecisionService(Brain(str(path), mode='git'))
            refs = replay['references']
            final_revision = replay['final']['revision']
            report['comparisons'] = {}
            for name, before in [('initial_to_y1', replay['initial']['revision']),
                                 ('withdrawal_to_y1', replay['comparison']['after']['revision']),
                                 ('y1_self', final_revision)]:
                envelope = dict(schema='dm.compare/1', before=before, after=final_revision)
                result = service.compare(envelope)
                repeat = service.compare(envelope)
                assert [c['candidate_id'] for c in repeat['candidates']] == [c['candidate_id'] for c in result['candidates']]
                assert not result['completeness']['truncated']
                report['comparisons'][name] = dict(input=envelope, output=result,
                    queue=service.read('review-queue', dict(comparison=envelope, history=True)))
            fresh = report['comparisons']['initial_to_y1']
            old_candidate = replay['comparison']['candidates'][0]
            candidate = next(c for c in fresh['output']['candidates'] if c['target'] == refs['old_decision']
                             and 'support_withdrawn' in c['reasons'])
            assert old_candidate['candidate_id'] != candidate['candidate_id']
            report['stale_detail'] = service.read('review-detail', dict(reference=refs['finding']))
            assert report['stale_detail']['finding']['basis_changed']
            before_review = journal(path)
            preview = service.preview()
            request = dict(schema='dm.finding-review/1', idempotency_key=str(uuid4()),
                expected_generation=preview['generation'], expected_heads=preview['heads'],
                comparison=fresh['input'], candidate_id=old_candidate['candidate_id'], disposition='confirmed',
                reason=REASON + 'Guard: stale candidate must not be accepted against the new comparison.')
            try:
                service.record_finding(request, dry_run=True, commit=False)
            except s.RecordConflict as exc:
                report['stale_candidate_rejected'] = dict(type=type(exc).__name__, message=str(exc))
            else:
                raise AssertionError('Stale candidate accepted')
            assert journal(path) == before_review
            request.update(idempotency_key=str(uuid4()), candidate_id=candidate['candidate_id'],
                reason=REASON + 'Fresh comparison confirms changed OLD decision basis. X1 is withdrawn; '
                'old Y1 link is stale at the previous claim endpoint, not withdrawn evidence. '
                'Available Y1 supports the new claim; its successor decision dependency is only proposed. '
                'Keep investigation, activation, resolution and independent acceptance open.')
            try:
                service.record_finding(request, commit=False)
            except s.RecordConflict as exc:
                report['fresh_review_rejected'] = dict(type=type(exc).__name__, message=str(exc),
                    gate='stale decision/basis; a fresh comparison does not authorize an old-version review')
            else:
                raise AssertionError('Unexpected acceptance of the stale target basis')
            after = journal(path)
            assert after == before_review
            assert service.preview() == preview
            assert len(after['versions']) == 15 and len(after['events']) == 16
            assert not subprocess.check_output(['git', '-C', str(path), 'status', '--porcelain'])
            report['fresh_candidate'] = candidate
            report['final'] = dict(journal=after, revision=final_revision, finding=refs['finding'],
                detail=service.read('review-detail', dict(reference=refs['finding'])),
                fresh_detail=service.read('review-detail', dict(comparison=fresh['input'],
                                                              candidate_id=candidate['candidate_id'])),
                decision=service.inspect(refs['decision']), dependency=service.inspect(refs['dependency']),
                old_decision=service.inspect(refs['old_decision']),
                x1=service.inspect(refs['evidence']['X1']), y1=service.inspect(refs['evidence']['Y1']),
                queue=service.read('review-queue', dict(comparison=fresh['input'])),
                queue_without_comparison=service.read('review-queue', {}),
                history=service.read('review-queue', dict(history=True)))
            assert report['final']['detail']['finding']['basis_changed']
            assert report['final']['detail']['finding']['state'] == dict(
                finding_disposition='confirmed', finding_workflow='acknowledged')
            assert report['final']['fresh_detail']['finding'] is None
            assert report['final']['decision']['events'] == []
            assert report['final']['decision']['state']['decision'] == 'proposed'
            assert report['final']['dependency']['state']['workflow'] == 'proposed'
            assert report['final']['old_decision']['state']['decision_conclusion'] == 'needs_investigation'
            assert report['final']['x1']['state']['availability'] == 'withdrawn'
            assert report['final']['y1']['state']['availability'] == 'available'
            s.loads(json.dumps(dict(after, receipts=[])))
            subprocess.run(['git', '-C', str(path), 'bundle', 'create', str((output / 'brain.bundle').resolve()), 'HEAD'], check=True, capture_output=True)
            report['brain_bundle_sha256'] = digest((output / 'brain.bundle').read_bytes())
            report['status'] = 'complete_with_review_blocked'
    except Exception as exc:
        report.update(status='failed', error=dict(type=type(exc).__name__, message=str(exc)))
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New dedicated output/brain directory')
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps(dict(status=result['status'], case_id=result['case_id'],
        comparisons={k: len(v['output']['candidates']) for k, v in result['comparisons'].items()},
        finding_workflow=result['final']['detail']['finding']['state']['finding_workflow'], activation=False)))


if __name__ == '__main__':
    main()

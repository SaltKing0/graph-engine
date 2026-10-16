"""Conservative production-interface diagnostic; no extraction or semantic oracle.

Only source-only inputs reach execute(). A declared basis claim is versioned to
attach the available update; accepted dependencies retain their exact old target.
This deliberately measures review alerts, not an invented interpretation of prose.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
from typing import Any, Callable

from examples.decision_memory import _basis, _commit, _draft, _review, _submit
from graph_engine.brain import Brain, Node
from graph_engine.decision_service import DecisionService
from tools.memory_benchmark.runner import checkpoint
from .corpus import DATA, canonical, digest, load_bundle, visible_inputs
from .runner import run as baseline_run, TASK
from .scoring import score
from .readiness import assess

MAPPING = {
    'version': 'dm.source-change-diagnostic/1',
    'claim': 'Declared source basis; no truth assessment or structured conditions',
    'update': 'New claim version with exact original source and current update as provenance inputs',
    'dependency': 'Curated links explicitly accepted; proposed profile uses only supplied proposed links, left proposed',
    'normalization': 'Verified old claim -> accepted depends_on -> exact decision maps to update/source/dependency/decision',
    'uncertainty': 'comparability_unknown becomes explicit uncertainty, including on known pairs',
    'interpretation': 'No prose-to-opposition/withdrawal/conditions inference; no source artifact is overwritten',
}


def execute(visible: dict, event: dict, path: Path, mode: str, *, budget: int, k: int, trace: dict | None = None) -> dict:
    """Production execution boundary. Never accepts labels, gold paths or rationales."""
    trace = trace if trace is not None else {}
    times: dict[str, list[float]] = trace.setdefault('latency_ms', {})
    outputs: list[dict] = trace.setdefault('raw_outputs', [])
    if mode not in ('curated', 'proposed'):
        raise ValueError('Unknown dependency profile')

    def timed(stage: str, operation: Callable[[], Any]) -> Any:
        start = time.perf_counter()
        try:
            value = operation()
        except Exception as exc:
            outputs.append({'stage': stage, 'error': dict(type=type(exc).__name__, message=str(exc))})
            raise
        finally:
            times.setdefault(stage, []).append((time.perf_counter() - start) * 1000)
        outputs.append({'stage': stage, 'output': value})
        return value

    brain = Brain(str(path), mode='git')
    brain.init()
    service = DecisionService(brain)
    refs, claims, decisions, links = {}, {}, {}, {}
    # Preserve the baseline's exact 800-character slices and IDs. These are
    # inert source nodes, not document-import parser output or extracted claims.
    for doc in visible['documents']:
        if doc['source_id'] == event['source_id']:
            continue
        timed('source_capture', lambda doc=doc: brain.write_node(Node(doc['text'], id=doc['id'])))
        source = _draft('source', service.source(doc['id']), anchor=doc['id'])
        ref = timed('proposal', lambda source=source: _submit(service, 'versions', [source]))['refs'][0]
        refs.setdefault(doc['source_id'], []).append(ref)
    for decision in visible['decisions']:
        draft = _draft('decision', dict(action=decision['action'], rationale='Frozen documented action; not independently adjudicated.',
            alternatives=[], context=None, revisit_checks=[]))
        decisions[decision['id']] = timed('proposal', lambda draft=draft: _submit(service, 'versions', [draft]))['refs'][0]
    for dep in visible['dependencies']:
        if dep['status'] != mode:
            continue
        draft = _draft('claim', dict(text='Declared source basis for ' + dep['decision_id'], context=None,
            limitations=['No interpreted claim, comparability or independent truth assessment.']))
        draft['provenance']['inputs'] = refs[dep['source_id']]
        claim = timed('proposal', lambda draft=draft: _submit(service, 'versions', [draft]))['refs'][0]
        claims[dep['id']] = claim
        draft = _draft('relationship', dict(kind='depends_on', source=decisions[dep['decision_id']], target=claim,
            context=None, explanation='Supplied ' + mode + ' dependency; not extracted by this diagnostic.'))
        link = timed('proposal', lambda draft=draft: _submit(service, 'versions', [draft]))['refs'][0]
        links[dep['id']] = link
        if mode == 'curated':
            timed('scripted_review', lambda link=link: _review(service, link, 'workflow', 'accepted', [],
                'Accept supplied curated dependency for wiring diagnostics only.'))
    before = _commit(service)
    update_refs = []
    for doc in visible['documents']:
        if doc['source_id'] != event['source_id']:
            continue
        timed('source_capture', lambda doc=doc: brain.write_node(Node(doc['text'], id=doc['id'])))
        draft = _draft('source', service.source(doc['id']), anchor=doc['id'])
        update_refs.extend(timed('proposal', lambda draft=draft: _submit(service, 'versions', [draft]))['refs'])
    if not update_refs:
        raise ValueError('Update has no visible source chunks')
    for dep in visible['dependencies']:
        if dep['status'] != mode or dep['source_id'] != event['changed_source_id']:
            continue
        old = service.inspect(claims[dep['id']])['record']
        draft = {key: deepcopy(old[key]) for key in ('id', 'kind', 'anchor_node_id', 'provenance', 'payload')}
        draft['previous'] = claims[dep['id']]
        draft['provenance']['inputs'].extend(update_refs)
        timed('proposal', lambda draft=draft: _submit(service, 'versions', [draft]))
    after = _commit(service)
    comp = dict(schema='dm.compare/1', before=before, after=after)
    comparison = timed('impact', lambda: service.compare(comp))
    queue = timed('review_queue', lambda: service.read('review-queue', {'comparison': comp}))
    context = timed('context', lambda: service.read('context', dict(query=TASK.format(path=event['changed_path']),
        budget=budget, k=k, revision=after)))
    alerts = []
    for candidate in comparison['candidates']:
        for dep in visible['dependencies']:
            if dep['id'] not in claims or candidate['target'] != decisions[dep['decision_id']]:
                continue
            # Normalize only a real, exact, old accepted dependency path.
            if not any(len(path) == 1 and path[0]['kind'] == 'depends_on'
                    and path[0]['from_ref'] == claims[dep['id']]
                    and path[0]['relationship'] == links[dep['id']]
                    and path[0]['to_ref'] == decisions[dep['decision_id']]
                    and path[0]['acceptance'] == 'accepted' for path in candidate['paths']):
                continue
            alerts.append(dict(decision_id=dep['decision_id'], path=[event['source_id'], event['changed_source_id'],
                dep['id'], dep['decision_id']], reason=candidate['judgment'],
                uncertainty_reason='Structured comparability is unknown' if 'comparability_unknown' in candidate['reasons'] else None,
                candidate_id=candidate['candidate_id']))
    return dict(alerts=alerts, latency_ms=times, raw_outputs=outputs, comparison=comp,
        ids=dict(decisions=decisions, claims=claims, dependencies=links),
        complete=not comparison['completeness']['truncated'] and not queue['truncated'],
        context_within_budget=context['tokens'] <= budget)



def saved_baseline_check(baseline: dict, root: Path, split: str) -> dict:
    """Compare with the preserved #75 baseline without rewriting its results."""
    repository = Path(__file__).resolve().parents[2]
    name = ('controls.json' if root.name == 'controls-v2' and split == 'all' else
            f'project-{split}.json' if root.name == 'project-v1' and split in ('development', 'evaluation') else None)
    path = repository / 'docs/decision-evaluation-results' / (name or 'unavailable')
    if not name or not path.is_file():
        return dict(available=False, matched=None, reason='No saved baseline for this corpus/split')
    saved = json.loads(path.read_bytes())
    by_id = {row['event_id']: row for row in saved['results']}
    matches = {}
    for row in baseline['results']:
        old = by_id.get(row['event_id'], {})
        matches[row['event_id']] = dict(
            source_inputs=row['visible_inputs_sha256'] == old.get('visible_inputs_sha256'),
            prepared_prompt=row.get('retrieval', {}).get('prompt_sha256') == old.get('retrieval', {}).get('prompt_sha256'),
            explicit_alerts=row['baselines'] == old.get('baselines'))
    config = baseline['metadata']['configuration'] == saved['metadata']['configuration']
    return dict(available=True, path=str(path.relative_to(repository)), sha256=digest(path.read_bytes()),
        source_commit=saved['metadata']['source_commit'], configuration_matches=config, events=matches,
        matched=config and set(by_id) == {r['event_id'] for r in baseline['results']}
            and all(all(m.values()) for m in matches.values()))


def run(root: Path, output: Path, *, split: str = 'development') -> dict:
    inputs, labels, freeze = load_bundle(root)
    baseline_path = output.with_name(output.stem + '-baseline.json')
    baseline = baseline_run(root, baseline_path, split=split)
    metadata = deepcopy(baseline['metadata'])
    repository = Path(__file__).resolve().parents[2]
    paths = [*repository.glob('examples/*.py'), *repository.glob('tools/decision_benchmark/*.py')]
    metadata['code_manifest'].update({str(p.relative_to(repository)): digest(p.read_bytes()) for p in paths})
    metadata['code_sha256'] = digest(canonical(metadata['code_manifest']))
    metadata['production_mapping'] = MAPPING
    report = dict(schema='dm.production-diagnostic/1', status='running', metadata=metadata,
        baseline=dict(path=baseline_path.name, sha256=digest(baseline_path.read_bytes()), scores=baseline['scores'],
            saved_reference=saved_baseline_check(baseline, root, split)),
        results=[], scores={}, release_readiness=baseline['release_readiness'],
        limitations=[*baseline['limitations'],
            'Source-change diagnostic only: draft corpus has no independently reviewed structured semantic inputs.',
            'Scripted acceptance is not human review or measured review time.',
            'Same availability, source slices, task, budget, k, no-model settings and pair scoring as baseline.',
            'Typed decision context is a different representation; no matched model-answer or semantic superiority claim.',
            'Production Git/UUID/time identifiers vary; compare source-input hashes and normalized paths, not raw IDs.',
            'Proposed inputs are evaluated independently; an empty profile measures no extraction ability.'])
    checkpoint(output, report)
    with tempfile.TemporaryDirectory(prefix='dm-production-') as temp:
        for event in inputs['events']:
            if split != 'all' and event['split'] != split:
                continue
            visible = visible_inputs(inputs, event, root)
            row = dict(event_id=event['id'], eligible_decisions=[d['id'] for d in visible['decisions']],
                visible_inputs_sha256=digest(canonical(visible)), profiles={})
            for mode in ('curated', 'proposed'):
                result: dict = {}
                try:
                    result = execute(visible, event, Path(temp) / event['id'] / mode, mode, budget=freeze['budget'], k=freeze['k'], trace=result)
                    result['error'] = None
                except Exception as exc:
                    result.update(alerts=[], error=dict(type=type(exc).__name__, message=str(exc)))
                row['profiles'][mode] = result
            expected = next(r for r in baseline['results'] if r['event_id'] == event['id'])
            row['baseline_input_matches'] = row['visible_inputs_sha256'] == expected['visible_inputs_sha256']
            report['results'].append(row)
            checkpoint(output, report)
    for mode in ('curated', 'proposed'):
        report['scores'][mode] = score([{**row, **row['profiles'][mode]} for row in report['results']], labels)
    report['gate_assessments'] = {mode: assess(report['scores'][mode], freeze['gates'],
        independent=inputs['kind'] == 'real' and split == 'evaluation') for mode in ('curated', 'proposed')}
    report['cost_effort'] = dict(provider_calls=0, provider_cost=0, currency=None,
        human_review_minutes=None, human_review_time_savings=None, comparability_error_rate=None,
        provenance_correctness=None, unsupported_conclusions=None,
        reason='Independent semantic/provenance/statement scoring and controlled users are absent.')
    report['status'] = 'completed_with_errors' if any(p['error'] for r in report['results'] for p in r['profiles'].values()) else 'complete'
    report['smoke_passed'] = bool(report['results']) and report['status'] == 'complete' and all(
        r['baseline_input_matches'] and p['complete'] and p['context_within_budget'] for r in report['results'] for p in r['profiles'].values())
    checkpoint(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-corpus', action='store_true', help='Opt in to the bundled project corpus; no fetching')
    parser.add_argument('--split', choices=('development', 'evaluation', 'all'), default='development')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = run(DATA / ('project-v1' if args.real_corpus else 'controls-v2'), args.output, split=args.split)
    print(json.dumps(dict(status=report['status'], smoke_passed=report['smoke_passed'], release_ready=False)))
    return 0 if report['smoke_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

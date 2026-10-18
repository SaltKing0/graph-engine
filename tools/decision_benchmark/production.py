"""Conservative production-interface diagnostic; no extraction or semantic oracle.

Only source-only inputs reach execute(). A declared basis claim is versioned to
attach a changed or unknown update; exact/CRLF-only task-text equality retains
the original basis. Accepted dependencies retain their exact old target.
This measures review alerts, not an invented interpretation of prose.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
from typing import Any, Callable

from examples.decision_memory import _commit, _draft, _submit
from graph_engine.brain import Brain, Node
from graph_engine.decision_service import DecisionService
from tools.memory_benchmark.runner import checkpoint
from .corpus import DATA, canonical, digest, load_bundle, visible_inputs
from .runner import run as baseline_run, TASK
from .scoring import score
from .readiness import assess

MAPPING = {
    'version': 'dm.source-change-diagnostic/2',
    'claim': 'Declared source basis; no truth assessment or structured conditions',
    'update': 'New claim version with exact original source and current update as provenance inputs',
    'dependency': 'Curated links explicitly accepted; proposed profile uses only supplied proposed links, left proposed',
    'normalization': 'Verified old claim -> accepted depends_on -> exact decision maps to update/source/dependency/decision',
    'uncertainty': 'comparability_unknown becomes explicit uncertainty, including on known pairs',
    'interpretation': 'No prose-to-opposition/withdrawal/conditions inference; no source artifact is overwritten',
    'no_op': 'Exact complete supplied source text or CRLF-only equality retains the original basis; update sources remain captured',
}


def source_update(documents: list[dict], event: dict) -> dict:
    """Compare complete task-input chunks, never a prose claim of equivalence.

    The chronological loader supplies the entire source, in 800-character
    slices. Refuse malformed/missing chunks rather than interpreting a prefix
    or reordered text as a no-op. This does not assess scope, truth or lineage.
    """
    def assemble(source_id: str) -> tuple[str | None, dict]:
        chunks = [d for d in documents if d['source_id'] == source_id]
        # Reconstruct numeric chunk order, including sources over 1000 chunks.
        by_id = {d['id']: d for d in chunks}
        expected = [f'{source_id}-c{i:03}' for i in range(len(chunks))]
        valid = bool(chunks) and len(by_id) == len(chunks) and set(by_id) == set(expected)
        ordered = [by_id[key] for key in expected] if valid else []
        valid = valid and all(isinstance(d['text'], str) and 0 < len(d['text']) <= 800 for d in ordered)
        valid = valid and all(len(d['text']) == 800 for d in ordered[:-1])
        text = ''.join(d['text'] for d in ordered) if valid else None
        return text, dict(source_id=source_id, chunk_ids=expected if valid else sorted(by_id),
            well_formed_task_chunks=bool(valid),
            text_sha256=digest(text.encode()) if text is not None else None,
            normalized_sha256=digest(text.replace('\r\n', '\n').encode()) if text is not None else None)

    old, old_info = assemble(event['changed_source_id'])
    new, new_info = assemble(event['source_id'])
    classification = ('unavailable' if old is None or new is None else
                      'identical' if old == new else
                      'crlf_only' if old.replace('\r\n', '\n') == new.replace('\r\n', '\n') else 'changed')
    return dict(rule='complete-task-text-exact-or-crlf/1', classification=classification,
                old=old_info, new=new_info, semantic_assessment=None)


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
    historical = [doc for doc in visible['documents'] if doc['source_id'] != event['source_id']]
    current = [doc for doc in visible['documents'] if doc['source_id'] == event['source_id']]
    selected = [dep for dep in visible['dependencies'] if dep['status'] == mode]

    def publish(drafts: list[dict]) -> list[dict]:
        # Match the public envelope's 200-item bound; each batch preserves order.
        published = []
        for start in range(0, len(drafts), 200):
            batch = drafts[start:start + 200]
            published.extend(timed('proposal', lambda: _submit(service, 'versions', batch))['refs'])
        return published

    def sources(documents: list[dict]) -> list[dict]:
        for doc in documents:
            timed('source_capture', lambda doc=doc: brain.write_node(Node(doc['text'], id=doc['id'])))
        drafts = [_draft('source', service.source(doc['id']), anchor=doc['id']) for doc in documents]
        published = publish(drafts)
        for doc, ref in zip(documents, published):
            refs.setdefault(doc['source_id'], []).append(ref)
        return published

    sources(historical)
    drafts = [_draft('decision', dict(action=decision['action'],
        rationale='Frozen documented action; not independently adjudicated.',
        alternatives=[], context=None, revisit_checks=[])) for decision in visible['decisions']]
    decisions.update(zip((d['id'] for d in visible['decisions']), publish(drafts)))
    drafts = []
    for dep in selected:
        draft = _draft('claim', dict(text='Declared source basis for ' + dep['decision_id'], context=None,
            limitations=['No interpreted claim, comparability or independent truth assessment.']))
        draft['provenance']['inputs'] = refs[dep['source_id']]
        drafts.append(draft)
    claims.update(zip((dep['id'] for dep in selected), publish(drafts)))
    drafts = [_draft('relationship', dict(kind='depends_on', source=decisions[dep['decision_id']], target=claims[dep['id']],
        context=None, explanation='Supplied ' + mode + ' dependency; not extracted by this diagnostic.')) for dep in selected]
    links.update(zip((dep['id'] for dep in selected), publish(drafts)))
    if mode == 'curated' and links:
        events = [dict(subject=link, axis='workflow', **{'from': 'proposed', 'to': 'accepted'},
            previous_event_id=None, supersedes_event_id=None, basis=[],
            reason='Accept supplied curated dependency for wiring diagnostics only.') for link in links.values()]
        timed('scripted_review', lambda: _submit(service, 'events', events))
    before = _commit(service)
    update_refs = sources(current)
    if not update_refs:
        raise ValueError('Update has no visible source chunks')
    update = source_update(visible['documents'], event)
    update['captured_update_refs'] = update_refs
    update['retained_basis_refs'] = []
    outputs.append(dict(stage='source_update', output=update))
    drafts = []
    for dep in selected:
        if dep['source_id'] != event['changed_source_id']:
            continue
        if update['classification'] in ('identical', 'crlf_only'):
            # No successor claim, inherited review or invented semantic verdict.
            # The separately captured update and exact hashes stay in the trace.
            update['retained_basis_refs'].append(claims[dep['id']])
            continue
        old = service.inspect(claims[dep['id']])['record']
        draft = {key: deepcopy(old[key]) for key in ('id', 'kind', 'anchor_node_id', 'provenance', 'payload')}
        draft['previous'] = claims[dep['id']]
        draft['provenance']['inputs'].extend(update_refs)
        drafts.append(draft)
    publish(drafts)
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
    return dict(alerts=alerts, latency_ms=times, raw_outputs=outputs, comparison=comp, source_update=update,
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
            status=baseline['status'], smoke_passed=baseline['smoke_passed'],
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
    report['status'] = 'completed_with_errors' if baseline['status'] != 'complete' or any(
        p['error'] for r in report['results'] for p in r['profiles'].values()) else 'complete'
    report['smoke_passed'] = baseline['smoke_passed'] and bool(report['results']) and report['status'] == 'complete' and all(
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

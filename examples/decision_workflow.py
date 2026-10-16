"""Complete offline workflow audit: python -m examples.decision_workflow --output report.json.

Only an empty dedicated brain is permitted. No providers, external sources,
research execution, git fetch or human-time estimates are involved.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
from typing import Any, Callable
from uuid import uuid4

from examples.decision_memory import _basis, _commit, _draft, _submit
from graph_engine.brain import Brain, Node
from graph_engine.decision_service import DecisionService
from graph_engine.document_import import import_documents
from graph_engine import decision_schema as s
from tools.memory_benchmark.runner import checkpoint, source_metadata
from tools.decision_benchmark.corpus import canonical, digest


def run(path: Path, output: Path) -> dict:
    if path.exists() and any(path.iterdir()):
        raise ValueError('Use an empty dedicated brain path')
    if output.resolve().is_relative_to(path.resolve()):
        raise ValueError('Keep the report outside the dedicated brain')
    report = dict(schema='dm.workflow-audit/1', status='running', stages=[], checks={},
        cost_effort=dict(provider_calls=0, provider_cost=0, currency=None, human_review_minutes=None),
        release_ready=False, limitations=['Scripted synthetic wiring exercise; no independent semantic or usability score.',
            'CLI/HTTP/MCP/Chromium transport and authorization coverage is recorded separately in the release report.'])
    repository = Path(__file__).resolve().parents[1]
    metadata = source_metadata(repository)
    paths = [*repository.glob('examples/*.py'), *repository.glob('tools/decision_benchmark/*.py')]
    metadata['code_manifest'].update({str(p.relative_to(repository)): digest(p.read_bytes()) for p in paths})
    metadata['code_sha256'] = digest(canonical(metadata['code_manifest']))
    report['metadata'] = metadata
    checkpoint(output, report)

    def step(name: str, call: Callable[[], Any]) -> Any:
        start = time.perf_counter()
        row = dict(name=name, error=None)
        try:
            value = call()
            row['output'] = value
        except Exception as exc:
            row['error'] = dict(type=type(exc).__name__, message=str(exc))
            raise
        finally:
            row['latency_ms'] = (time.perf_counter() - start) * 1000
            report['stages'].append(row)
            checkpoint(output, report)
        return value

    try:
        brain = Brain(str(path), mode='git')
        brain.init()
        brain.write_node(Node('Existing ordinary memory stays ordinary.', id='legacy-memory'))
        original_legacy = (path / 'nodes' / 'legacy-memory.md').read_bytes()
        service = DecisionService(brain)

        def save(kind: str, payload: dict, **kwargs) -> dict:
            return step('proposal', lambda: _submit(service, 'versions', [_draft(kind, payload, **kwargs)]))['refs'][0]

        def review(ref: dict, axis: str, after: str, basis: list[dict]) -> None:
            item = service.inspect(ref)
            previous = next((e['event_id'] for e in reversed(item['events']) if e['axis'] == axis), None)
            event = dict(subject=ref, axis=axis, **{'from': item['state'][axis], 'to': after},
                previous_event_id=previous, supersedes_event_id=None, basis=basis,
                reason='Scripted diagnostic review; no independent human validation.')
            step('scripted_review', lambda: _submit(service, 'events', [event]))

        with tempfile.TemporaryDirectory(prefix='dm-walkthrough-source-') as source_dir:
            note = Path(source_dir) / 'observation.txt'
            note.write_text('Supplied diagnostic supports keeping the feature opt-in.\n', encoding='utf-8')
            imported = step('import', lambda: import_documents(brain, [note], source_id='workflow-observation'))
        node_id = imported['files'][0]['chunks'][0]['node_id']
        profile = save('profile', dict(name='Diagnostic only', version='1', dimensions={
            'workload': dict(type='id', unit=None, required=True, compare='equal', allowed_values=None)}, interventions=[]))
        review(profile, 'workflow', 'accepted', [])
        scope = dict(schema='dm.context/1', profile=profile,
            dimensions={'workload': dict(type='id', value='offline-diagnostic')}, notes='Supplied synthetic observation')
        profile_event = dict(type='event_ref', event_id=service.inspect(profile)['events'][-1]['event_id'])
        source = save('source', service.source(node_id), anchor=node_id)
        evidence = save('evidence', dict(interpretation='Keep opt-in for the supplied diagnostic.', context=scope,
            sources=[dict(ref=source, passage=None)], lineage_ids=[], limitations=['Not an independently reproduced experiment.']))
        claim = save('claim', dict(text='Keeping opt-in is justified for this diagnostic.', context=scope, limitations=['Diagnostic only.']))
        support = save('relationship', dict(kind='supports', source=evidence, target=claim,
            context=scope, explanation='Explicitly reviewed supplied diagnostic.'))
        review(support, 'workflow', 'accepted', [_basis(evidence), _basis(claim), profile_event])
        review(claim, 'epistemic', 'supported', [_basis(evidence), _basis(support), profile_event])
        decision = save('decision', dict(action='Keep feature opt-in', rationale='One limited diagnostic.', alternatives=['Enable by default'],
            context=scope, revisit_checks=[]))
        dep = save('relationship', dict(kind='depends_on', source=decision, target=claim, context=scope,
            explanation='Recorded rationale depends on the scoped claim.'))
        review(dep, 'workflow', 'accepted', [_basis(claim)])
        review(decision, 'decision', 'current', [_basis(claim), _basis(dep),
            dict(type='event_ref', event_id=service.inspect(claim)['events'][-1]['event_id'])])
        before = _commit(service)
        # Fresh service is a separate session, using committed existing state.
        service = DecisionService(Brain(str(path), mode='git'))
        node = service.brain.read_node(node_id)
        node.text = 'Updated supplied diagnostic is inconclusive; no reversal is justified.\n'
        step('source_update', lambda: service.brain.write_node(node))
        old_source = service.inspect(source)['record']
        # The production node writer already appends the exact source successor.
        new_source = dict(id=source['id'], version_id=service.preview()['heads'][source['id']])
        step('source_successor', lambda: service.inspect(new_source))
        report['checks']['no_silent_carry_forward'] = service.inspect(claim)['effective_assessment'] == 'inconclusive'
        report['checks']['decision_not_reversed'] = service.inspect(decision)['state']['decision'] == 'current'
        after = _commit(service)
        comp = dict(schema='dm.compare/1', before=before, after=after)
        comparison = step('impact', lambda: service.compare(comp))
        candidate = next(c for c in comparison['candidates'] if c['target'] == decision)
        preview = service.preview()
        finding = step('finding_review', lambda: service.record_finding(dict(schema='dm.finding-review/1', idempotency_key=str(uuid4()),
            expected_generation=preview['generation'], expected_heads=preview['heads'], comparison=comp,
            candidate_id=candidate['candidate_id'], disposition='confirmed',
            reason='Changed exact source requires investigation; it does not refute the decision.'), commit=False))['receipt']['refs'][0]
        step('review_detail', lambda: service.read('review-detail', {'reference': finding}))
        review(finding, 'finding_workflow', 'acknowledged', [])
        review(decision, 'decision_conclusion', 'needs_investigation', [_basis(claim), _basis(new_source)])
        reviewed = _commit(service)
        step('agent_context', lambda: service.read('context', dict(query='Keep feature opt-in', budget=8000, revision=reviewed)))
        step('review_history', lambda: service.read('review-queue', {'history': True}))
        historical = step('historical_reconstruction', lambda: service.read('inspect-revision', dict(reference=source, revision=before)))
        report['checks']['history_exact'] = historical['record']['payload'] == old_source['payload']
        report['checks']['legacy_memory_unchanged'] = (path / 'nodes' / 'legacy-memory.md').read_bytes() == original_legacy
        # A new decision version receives fresh lifecycle state, never an old approval.
        old = service.inspect(decision)['record']
        successor = {key: deepcopy(old[key]) for key in ('id', 'kind', 'anchor_node_id', 'payload', 'provenance')}
        successor['previous'] = decision
        successor['payload']['rationale'] = 'Investigation remains open; activation requires another explicit review.'
        new_decision = step('proposal', lambda: _submit(service, 'versions', [successor]))['refs'][0]
        report['checks']['successor_not_activated'] = service.inspect(new_decision)['state']['decision'] == 'proposed'
        step('forget', lambda: service.brain.tombstone_node(node_id) and None)
        try:
            service.read('inspect-revision', dict(reference=source, revision=before))
        except (s.RecordError, PermissionError):
            report['checks']['forgotten_history_unavailable'] = True
        else:
            report['checks']['forgotten_history_unavailable'] = False
        report['checks']['forgotten_queue_empty'] = not service.read('review-queue', {'history': True})['items']
        report['revisions'] = dict(before=before, after=after, reviewed=reviewed)
        report['status'] = 'complete' if all(report['checks'].values()) else 'failed_checks'
    except Exception as exc:
        report['status'] = 'error'
        report['error'] = dict(type=type(exc).__name__, message=str(exc))
    checkpoint(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--brain', type=Path, help='Empty dedicated demo brain; default is temporary')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.brain:
        report = run(args.brain, args.output)
    else:
        with tempfile.TemporaryDirectory(prefix='dm-workflow-') as temp:
            report = run(Path(temp) / 'brain', args.output)
    print(json.dumps(dict(status=report['status'], checks=report['checks'], release_ready=False)))
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

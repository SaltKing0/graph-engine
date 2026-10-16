"""Two offline Decision Memory sessions: python -m examples.decision_memory.

Records supplied observations; never runs experiments, fetches sources, loads
models, or equates a deterministic wiring example with measured answer quality.
The optional memory example's --model path is separate from this demo.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4

from graph_engine.brain import Brain, Node
from graph_engine.decision_service import DecisionService, PROPOSAL, REVIEW
from graph_engine.decision_brief import render_markdown


def _draft(kind: str, payload: dict, *, anchor: str | None = None) -> dict:
    return dict(id=str(uuid4()), kind=kind, anchor_node_id=anchor or str(uuid4()),
                previous=None, provenance=dict(method='manual', inputs=[]), payload=payload)


def _submit(service: DecisionService, field: str, values: list[dict]) -> dict:
    preview = service.preview()
    return service.submit(dict(schema=PROPOSAL if field == 'versions' else REVIEW,
        idempotency_key=str(uuid4()), expected_generation=preview['generation'],
        expected_heads=preview['heads'], **{field: values}), commit=False)['receipt']


def _save(service: DecisionService, kind: str, payload: dict, *, anchor: str | None = None) -> dict:
    return _submit(service, 'versions', [_draft(kind, payload, anchor=anchor)])['refs'][0]


def _review(service: DecisionService, ref: dict, axis: str, after: str, basis: list[dict], reason: str) -> None:
    item = service.inspect(ref)
    _submit(service, 'events', [dict(subject=ref, axis=axis, **{'from': item['state'][axis], 'to': after},
        previous_event_id=None, supersedes_event_id=None, basis=basis, reason=reason)])


def _basis(ref: dict) -> dict:
    return dict(type='content_ref', ref=ref)


def _commit(service: DecisionService) -> str:
    service.brain.commit_and_push('Offline Decision Memory session', push=False)
    return subprocess.check_output(['git', '-C', str(service.brain.path), 'rev-parse', 'HEAD'], text=True).strip()


def _observation(service: DecisionService, name: str, text: str, scope: dict) -> dict:
    service.brain.write_node(Node(text, id=name))
    source = _save(service, 'source', service.source(name), anchor=name)
    _review(service, source, 'workflow', 'accepted', [], 'Accept this supplied source as a captured observation, not verified truth.')
    evidence = _save(service, 'evidence', dict(interpretation=text, context=scope,
        sources=[dict(ref=source, passage=dict(start=0, end=len(text), quote=text))],
        lineage_ids=[], limitations=['Supplied diagnostic observation, not an independently reproduced result.']))
    _review(service, evidence, 'workflow', 'accepted', [_basis(source)], 'Accept the explicit interpretation within its recorded limitations.')
    return evidence


def _link(service: DecisionService, kind: str, source: dict, target: dict, scope: dict,
          profile_event: str | None = None) -> dict:
    link = _save(service, 'relationship', dict(kind=kind, source=source, target=target,
        context=scope, explanation='Explicit scoped dependency supplied by the example author.'))
    basis = [dict(type='event_ref', event_id=profile_event)] if profile_event else []
    _review(service, link, 'workflow', 'accepted', basis, 'Reviewed the supplied structured scope and dependency.')
    return link


def first_session(path: Path) -> dict:
    """Session one: capture an explicitly justified, scoped decision."""
    brain = Brain(str(path), mode='git')
    brain.init()
    service = DecisionService(brain)
    profile = _save(service, 'profile', dict(name='Diagnostic workload', version='1', dimensions={
        'workload': dict(type='id', unit=None, required=True, compare='equal', allowed_values=None)}, interventions=[]))
    _review(service, profile, 'workflow', 'accepted', [], 'Use exact workload identity; do not generalize.')
    profile_event = service.inspect(profile)['events'][-1]['event_id']
    scope = dict(schema='dm.context/1', profile=profile,
                 dimensions=dict(workload=dict(type='id', value='offline-diagnostic')), notes='Synthetic wiring example only.')
    ev = _observation(service, 'initial-observation', 'The supplied diagnostic favors keeping expansion opt-in.', scope)
    claim = _save(service, 'claim', dict(text='Expansion should remain opt-in for this workload.',
                                        context=scope, limitations=['One supplied diagnostic only.']))
    _review(service, claim, 'workflow', 'accepted', [_basis(ev)], 'Accept the scoped claim for explicit epistemic review.')
    support = _link(service, 'supports', ev, claim, scope, profile_event)
    _review(service, claim, 'epistemic', 'supported', [_basis(ev), _basis(support),
        dict(type='event_ref', event_id=profile_event)], 'Supported within the diagnostic scope; independent validation remains open.')
    decision = _save(service, 'decision', dict(action='Keep expansion opt-in', rationale='Limited diagnostic support.',
        alternatives=['Enable by default'], context=scope, revisit_checks=[]))
    _review(service, decision, 'workflow', 'accepted', [_basis(claim)], 'Accept this proposed action for explicit lifecycle review.')
    dependency = _link(service, 'depends_on', decision, claim, scope)
    _review(service, decision, 'decision', 'current', [_basis(claim), _basis(dependency)],
            'Adopt the scoped recommendation; revisit when contrary evidence arrives.')
    return dict(revision=_commit(service), decision=decision, claim=claim,
                scope=scope, profile_event=profile_event)


def second_session(path: Path, saved: dict) -> dict:
    """Fresh service: add structured opposition, explicitly review an explained finding."""
    service = DecisionService(Brain(str(path), mode='git'))
    ev = _observation(service, 'new-observation', 'A new supplied diagnostic reports a contrary outcome.', saved['scope'])
    _link(service, 'opposes', ev, saved['claim'], saved['scope'], saved['profile_event'])
    revision = _commit(service)
    comp = dict(schema='dm.compare/1', before=saved['revision'], after=revision)
    candidates = service.compare(comp)['candidates']
    # Choose the explicit opposition change, rather than an arbitrary delta.
    candidate = next(c for c in candidates if 'comparable_opposition' in c['reasons'])
    preview = service.preview()
    service.record_finding(dict(schema='dm.finding-review/1', idempotency_key=str(uuid4()),
        expected_generation=preview['generation'], expected_heads=preview['heads'], comparison=comp,
        candidate_id=candidate['candidate_id'], disposition='confirmed',
        reason='Comparable contrary evidence requires review; it does not automatically refute the claim.'), commit=False)
    frozen = _commit(service)
    return dict(findings=service.read('findings', dict(revision=frozen, decision_id=saved['decision']['id'])),
        brief=service.read('brief', dict(reference=saved['decision'], revision=frozen)),
        context=service.read('context', dict(query='expansion opt-in', budget=8000, revision=frozen)))


def run(path: Path) -> None:
    saved = first_session(path)
    result = second_session(path, saved)
    print('Session 1: recorded a justified scoped decision at ' + saved['revision'])
    print('Session 2: added supplied structured evidence; explicitly confirmed a review finding.')
    print(json.dumps(result['findings'], ensure_ascii=False, indent=2))
    print(render_markdown(result['brief']))
    print(f"Context: {result['context']['tokens']} estimated tokens; truncated={result['context']['truncated']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--brain', type=Path, help='An empty dedicated demo path')
    args = parser.parse_args()
    if args.brain:
        if args.brain.exists() and any(args.brain.iterdir()):
            parser.error('--brain must be empty for this reproducible two-session example')
        run(args.brain)
    else:
        with tempfile.TemporaryDirectory(prefix='decision-memory-') as temp:
            run(Path(temp) / 'brain')


if __name__ == '__main__':
    main()

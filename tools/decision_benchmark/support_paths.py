"""Versioned X1/Y1 paths for one already exposed synthetic development case.

All acceptances below are scripted developer wiring, not human judgments. Run
with a NEW --output directory. No labels, reserved sources or outcome inputs.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from examples.decision_memory import _basis, _commit, _draft, _submit
from graph_engine import decision_schema as s
from graph_engine.brain import Brain, Node
from graph_engine.decision_service import DecisionService
from tools.memory_benchmark.runner import source_metadata
from .corpus import DATA, canonical, digest
from .observations import DIMENSIONS, validate_binding, value
from .reviewed_development import journal
from .solo import ROOT
from .structured_development import development_inputs

AUDIT = ROOT / 'docs/decision-evaluation-results/false-alert-development-v1/withdrawal-v1/source-audit.json'
LIMITS = ['Previously exposed fictional development case; scripted developer review only.',
          'Distinct source-declared run labels do not establish independence or statistical validity.',
          'No real execution/dataset artifacts, independent review, user session or measured benefit.']
REASON = 'Scripted synthetic developer review; no independent human validation. '


def prepare() -> tuple[dict, dict, dict]:
    sources, cases = development_inputs()
    case = next(c for c in cases if c['id'] == 'controls-v2/event-surviving-support')
    packet = json.loads(AUDIT.read_bytes())
    assess_source(packet, sources, case)
    return sources, case, packet


def assess_source(packet: dict, sources: dict, case: dict) -> dict:
    """Evaluate the declared predicate, never independent or runtime acceptance."""
    s.fields(packet, {'schema', 'author', 'exposure', 'case_id', 'sources', 'rule', 'remaining',
                      'withdrawn', 'update', 'interpretation_notes'})
    s.need(packet['schema'] == 'dm.withdrawal-source-audit/1')
    s.need(packet['author'] == dict(role='implementing-agent', human=False, independent=False))
    s.need(type(packet['author']['human']) is bool and type(packet['author']['independent']) is bool)
    s.need(packet['exposure'] == 'previously-exposed-development-only' and packet['case_id'] == case['id'])
    keys = ['controls-v2/' + case['event'][k] for k in ('changed_source_id', 'source_id')]
    s.need(set(packet['sources']) == set(keys))
    for key, entry in packet['sources'].items():
        s.fields(entry, {'text_sha256', 'available_at'})
        s.need(entry['text_sha256'] == digest(sources[key]['text'].encode()))
        s.need(entry['available_at'] == sources[key]['available_at'] <= case['event']['at'])
    r, y, x, u = (packet[k] for k in ('rule', 'remaining', 'withdrawn', 'update'))
    fields = [(r, {'source_id', 'statement', 'action', 'metric', 'operator', 'threshold', 'unit'}),
              (y, {'source_id', 'statement', 'subject', 'metric', 'value', 'unit_from_rule',
                   'conditions_reference', 'conditions_referent', 'conditions', 'measurement_root'}),
              (x, {'source_id', 'statement', 'subject', 'measurement_root'}),
              (u, {'source_id', 'statement', 'withdrawn_subject', 'withdrawal', 'remaining_subject',
                   'remaining_availability', 'separate_run_statement', 'withdrawal_statement', 'availability_statement'})]
    for row, allowed in fields:
        s.fields(row, allowed)
        s.need(row['source_id'] == (keys[1] if row is u else keys[0]))
        for name, item in row.items():
            if name not in ('source_id', 'conditions', 'unit_from_rule'):
                s.need(item is not None, 'Missing source field: ' + name)
                validate_binding(item, sources[row['source_id']]['text'])
    s.need(set(y['conditions']) == set(DIMENSIONS))
    for b in y['conditions'].values():
        validate_binding(b, sources[keys[0]]['text'])
        s.need(b is not None and b['type'] == 'id')
    def within(binding: dict, statement: dict) -> None:
        s.need(statement['start'] <= binding['start'] < binding['end'] <= statement['end'],
               'Field points outside its declared statement')

    for name in ('action', 'metric', 'operator', 'threshold', 'unit'):
        within(r[name], r['statement'])
    for name in ('subject', 'metric', 'value', 'conditions_reference', 'measurement_root'):
        within(y[name], y['statement'])
    for name in ('subject', 'measurement_root'):
        within(x[name], x['statement'])
    for binding in [y['conditions_referent'], *y['conditions'].values()]:
        within(binding, x['statement'])
    for name in ('withdrawn_subject', 'withdrawal'):
        within(u[name], u['withdrawal_statement'])
    for name in ('remaining_subject', 'remaining_availability'):
        within(u[name], u['availability_statement'])
    # Verify the complete known source clauses, not merely equal lexemes.
    rule_clause = (f"{value(r['action'])} when {value(r['metric'])} "
                   f"{value(r['operator'])}{r['threshold']['quote']} {value(r['unit'])}.")
    s.need(value(r['statement']) == rule_clause, 'Rule field roles do not match the source clause')
    support_clause = (f"Separate support {value(y['subject'])}: {value(y['metric'])}={y['value']['quote']} "
                      f"{value(y['conditions_reference'])}, independent lineage {value(y['measurement_root'])}.")
    s.need(value(y['statement']) == support_clause, 'Support field roles do not match the source clause')
    for name, binding in y['conditions'].items():
        phrase = name + ' ' + value(binding)
        at = sources[keys[0]]['text'].index(phrase, x['statement']['start']) + len(name) + 1
        s.need(binding['start'] == at, 'Condition field role changed')
    s.need(y['unit_from_rule'] is True)
    s.need(value(r['metric']) == value(y['metric']) and value(r['operator']) == '>=')
    s.need(r['threshold']['type'] == y['value']['type'] == 'decimal')
    s.need(value(y['subject']) == value(u['remaining_subject']) != value(u['withdrawn_subject']))
    s.need(value(x['subject']) == value(u['withdrawn_subject']) == value(y['conditions_referent']))
    s.need(value(u['withdrawal']) == 'withdrawn' and value(u['remaining_availability']) == 'available')
    s.need(value(y['conditions_reference']) == 'under the same conditions')
    s.need(x['subject']['start'] < y['conditions_reference']['start'])
    decision = next(d for d in case['runtime']['decisions'] if d['source_id'] == case['event']['changed_source_id'])
    s.need(decision['action'].removeprefix('SYNTHETIC: ').casefold() == value(r['action']).casefold())
    s.strings(packet['interpretation_notes'])
    # The complete known fictional source has one explicit predicate; this is
    # an implementing-agent scope interpretation, not an extracted new policy.
    meets = Decimal(value(y['value'])) >= Decimal(value(r['threshold']))
    return dict(subject=value(y['subject']), metric=value(y['metric']),
        value=value(y['value']), operator=value(r['operator']), threshold=value(r['threshold']),
        declared_unit=value(r['unit']), unit_resolution='same metric declaration; no conversion',
        conditions_as_declared={k: value(v) for k, v in y['conditions'].items()},
        condition_resolution='explicit same-conditions reference to preceding observation',
        withdrawn_subject=value(x['subject']), remaining_availability=value(u['remaining_availability']),
        recorded_roots=dict(withdrawn=value(x['measurement_root']), remaining=value(y['measurement_root'])),
        meets_stated_numeric_condition=meets, supports_stated_rule_as_declared=meets,
        independently_reviewed_measurement_independence=None, statistical_sufficiency=None,
        accepted_runtime_sufficiency=False, automatic_decision_reversal=False,
        unchanged_old_basis_safe_to_retain=False,
        runtime_action='retain withdrawal review; explain remaining source-declared support',
        limitations=['Source assertions and implementing-agent interpretation only.',
                    'No reviewed execution/dataset artifacts establish independence or statistical validity.',
                    'The old aggregate basis includes withdrawn support; do not silently preserve it as unchanged.'])


def review(service: DecisionService, ref: dict, axis: str, after: str,
           basis: list[dict], reason: str) -> str:
    """Append an explicit, fresh event; never reuse an old acceptance."""
    item = service.inspect(ref)
    previous = next((e['event_id'] for e in reversed(item['events']) if e['axis'] == axis), None)
    receipt = _submit(service, 'events', [dict(subject=ref, axis=axis,
        **{'from': item['state'][axis], 'to': after}, previous_event_id=previous,
        supersedes_event_id=None, basis=basis, reason=REASON + reason)])
    return receipt['event_ids'][0]


def successor(service: DecisionService, old: dict, payload: dict, inputs: list[dict]) -> dict:
    record = service.inspect(old)['record']
    draft = {k: deepcopy(record[k]) for k in ('id', 'kind', 'anchor_node_id')}
    draft.update(previous=old, payload=payload, provenance=dict(method='manual', inputs=inputs))
    return _submit(service, 'versions', [draft])['refs'][0]


def capture(path: Path, sources: dict, case: dict, packet: dict) -> dict:
    """Exercise the public proposal/review/compare APIs, retaining all stages."""
    assessment = assess_source(packet, sources, case)  # Validate BEFORE any writes.
    s.need(assessment['supports_stated_rule_as_declared'], 'Remaining source predicate is not met')
    if path.exists() and any(path.iterdir()):
        raise ValueError('Use an empty dedicated brain path')
    brain = Brain(str(path), mode='git')
    brain.init()
    service = DecisionService(brain)

    def save(kind: str, payload: dict, inputs: list[dict] | None = None,
             anchor: str | None = None) -> dict:
        draft = _draft(kind, payload, anchor=anchor)
        draft['provenance']['inputs'] = inputs or []
        return _submit(service, 'versions', [draft])['refs'][0]

    refs = {}

    def capture_source(key: str) -> dict:
        source = sources[key]
        node_id = source['runtime_id']
        brain.write_node(Node(source['text'], id=node_id))
        payload = service.source(node_id)
        # These are two statements in ONE document. Preserve its shared root;
        # do not manufacture separate measurement artifacts from run labels.
        payload.update(lineage_ids=['document-sha256:' + digest(source['text'].encode())],
            artifact=dict(sha256=digest(source['text'].encode()),
            locator='known-development:' + key, media_type='text/plain',
            extraction=json.dumps(source['origin'], sort_keys=True)))
        refs[key] = save('source', payload, anchor=node_id)
        return refs[key]

    old_source = capture_source(packet['rule']['source_id'])
    profile = save('profile', dict(name='Known fictional X1/Y1 scope', version='1',
        dimensions={name: dict(type='id', unit=None, required=True, compare='equal', allowed_values=None)
                    for name in DIMENSIONS}, interventions=[]))
    pe = review(service, profile, 'workflow', 'accepted', [_basis(old_source)],
                'Exact five source-declared applicability IDs only.')
    profile_basis = dict(type='event_ref', event_id=pe)
    scope = dict(schema='dm.context/1', profile=profile, dimensions={
        k: dict(type='id', value=v) for k, v in assessment['conditions_as_declared'].items()},
        notes='Unit resolved from the same recall rule; Y1 explicitly uses the preceding X1 conditions.')

    def citation(source: dict, binding: dict) -> dict:
        text = service.inspect(source)['record']['payload']['text']
        s.need(text[binding['start']:binding['end']] == binding['quote'])
        return dict(ref=source, passage={k: binding[k] for k in ('start', 'end', 'quote')})

    evidence = {}
    for subject, name in (('X1', 'withdrawn'), ('Y1', 'remaining')):
        row = packet[name]
        citations = [citation(old_source, row['statement']), citation(old_source, packet['rule']['statement'])]
        if subject == 'Y1':
            # Refer only to X1's condition fields, never import its measurement
            # into the successor basis. The reference is explicit in Y1's text.
            citations += [citation(old_source, b) for b in row['conditions'].values()]
        evidence[subject] = save('evidence', dict(interpretation=json.dumps(dict(
            subject=subject, source_statement=value(row['statement']),
            source_declared_root=value(row['measurement_root']), independence='not inferred'), sort_keys=True),
            context=scope, sources=citations, lineage_ids=[], limitations=LIMITS))
        review(service, evidence[subject], 'workflow', 'accepted', [_basis(old_source)],
               'Accept exact source interpretation for synthetic path wiring only.')

    old_claim = save('claim', dict(text='The supplied X1 and Y1 statements support mode A under the declared rule.',
        context=scope, limitations=LIMITS), list(evidence.values()))

    def link(kind: str, source: dict, target: dict, *, accepted: bool) -> dict:
        ref = save('relationship', dict(kind=kind, source=source, target=target, context=scope,
            explanation='Exact synthetic development path; no inferred measurement independence.'))
        if accepted:
            review(service, ref, 'workflow', 'accepted', [_basis(source), _basis(target), profile_basis],
                   'Check exact endpoints and comparable declared scope.')
        return ref

    old_links = {subject: link('supports', ev, old_claim, accepted=True) for subject, ev in evidence.items()}
    review(service, old_claim, 'workflow', 'accepted', [_basis(e) for e in evidence.values()],
           'Initial two-path fictional basis.')
    review(service, old_claim, 'epistemic', 'supported',
           [_basis(e) for e in [*evidence.values(), *old_links.values()]] + [profile_basis],
           'Only the source-declared synthetic predicate, not real validity.')
    decision_payload = dict(action='SYNTHETIC: choose mode A',
        rationale='Initial source-declared X1/Y1 basis; independent acceptance absent.',
        alternatives=['Reassess mode A'], context=scope, revisit_checks=[])
    decision = save('decision', decision_payload)
    old_dep = link('depends_on', decision, old_claim, accepted=True)
    review(service, decision, 'decision', 'current', [_basis(old_claim), _basis(old_dep)],
           'Initial fictional current decision, not a product acceptance.')
    before = _commit(service)
    initial = dict(journal=journal(path), claim=service.inspect(old_claim),
                   decision=service.inspect(decision), revision=before)

    service = DecisionService(Brain(str(path), mode='git'))
    update = capture_source(packet['update']['source_id'])
    withdrawal_event = review(service, evidence['X1'], 'availability', 'withdrawn', [_basis(update)],
        'Update explicitly withdraws X1; Y1 remains available. No automatic refutation.')
    withdrawn = _commit(service)
    comparison_input = dict(schema='dm.compare/1', before=before, after=withdrawn)
    comparison = service.compare(comparison_input)
    candidate = next(c for c in comparison['candidates'] if c['target'] == decision
                     and 'support_withdrawn' in c['reasons'])
    s.need([i['evidence'] for i in candidate['support']['removed']] == [evidence['X1']])
    s.need([i['evidence'] for i in candidate['support']['remaining']] == [evidence['Y1']])
    preview = service.preview()
    finding = service.record_finding(dict(schema='dm.finding-review/1', idempotency_key=str(uuid4()),
        expected_generation=preview['generation'], expected_heads=preview['heads'], comparison=comparison_input,
        candidate_id=candidate['candidate_id'], disposition='confirmed',
        reason=REASON + 'X1 withdrawal changes the basis; Y1 remains source-declared support.'), commit=False)['receipt']['refs'][0]
    review(service, finding, 'finding_workflow', 'acknowledged', [],
           'Keep the changed-basis finding visible; independent review remains open.')
    review(service, decision, 'decision_conclusion', 'needs_investigation', [_basis(update), _basis(evidence['Y1'])],
           'Review a successor basis; do not automatically reverse or preserve the old aggregate basis.')
    withdrawal_snapshot = dict(journal=journal(path), decision=service.inspect(decision),
                               claim=service.inspect(old_claim))

    new_claim = successor(service, old_claim, dict(text=
        'Y1 alone meets the source-declared recall >=0.7 fraction rule for mode A after X1 withdrawal.',
        context=scope, limitations=LIMITS), [evidence['Y1'], update])
    new_support = link('supports', evidence['Y1'], new_claim, accepted=False)
    proposal = dict(claim=service.inspect(new_claim), support=service.inspect(new_support), journal=journal(path))
    s.need(proposal['claim']['state']['epistemic'] == 'unassessed')
    s.need(proposal['support']['state']['workflow'] == 'proposed')
    review(service, new_claim, 'workflow', 'accepted', [_basis(evidence['Y1']), _basis(update)],
           'Explicit successor interpretation from only Y1 plus availability update.')
    review(service, new_support, 'workflow', 'accepted', [_basis(evidence['Y1']), _basis(new_claim), profile_basis],
           'Fresh support acceptance for the exact successor, no inherited review.')
    review(service, new_claim, 'epistemic', 'supported',
           [_basis(evidence['Y1']), _basis(new_support), _basis(update), profile_basis],
           'Source-declared 0.8 >=0.7 fraction with explicit same conditions and available Y1; '
           'no assertion of statistical sufficiency or independently reviewed validity.')
    new_decision = successor(service, decision,
        dict(decision_payload, rationale='Proposed Y1-only successor basis after X1 withdrawal; independent review pending.'),
        [new_claim])
    new_dep = link('depends_on', new_decision, new_claim, accepted=False)
    final_revision = _commit(service)
    service = DecisionService(Brain(str(path), mode='git'))
    final = dict(journal=journal(path), claim=service.inspect(new_claim), support=service.inspect(new_support),
        decision=service.inspect(new_decision), dependency=service.inspect(new_dep),
        old_claim=service.inspect(old_claim), old_decision=service.inspect(decision),
        finding=service.inspect(finding), revision=final_revision,
        brief=service.read('brief', dict(reference=new_decision, revision=final_revision)),
        historical_claim=service.read('inspect-revision', dict(reference=old_claim, revision=before)))
    return dict(assessment=assessment, initial=initial, withdrawal=withdrawal_snapshot, proposal=proposal,
        final=final, comparison=comparison, references=dict(sources=refs, evidence=evidence,
        old_claim=old_claim, old_supports=old_links, old_decision=decision, old_dependency=old_dep,
        claim=new_claim, support=new_support, decision=new_decision, dependency=new_dep,
        finding=finding, withdrawal_event=withdrawal_event))


def run(output: Path) -> dict:
    if output.resolve().is_relative_to(DATA.resolve()):
        raise ValueError('Output must be outside frozen data')
    output.mkdir(parents=True, exist_ok=False)
    sources, case, packet = prepare()
    report = dict(schema='dm.development.support-paths/1', case_id=case['id'],
        exposure='one previously exposed synthetic development case, remodeled; not a new independent case',
        author=dict(role='implementing-agent', human=False, independent=False),
        source_input_sha256=digest(canonical(case['runtime'])), audit_sha256=digest(AUDIT.read_bytes()),
        source_manifest=packet['sources'], metadata=source_metadata(ROOT),
        independent_acceptance=False, human_review=None, statistical_sufficiency=None, semantic_scores=None,
        product_benefit=None, independent_final_coverage=dict(positive=0, negative=0, inconclusive=0),
        release_ready=False, provider_calls=0, status='running', limitations=LIMITS)
    report['metadata']['code_manifest'].update({str(p.relative_to(ROOT)): digest(p.read_bytes())
        for p in ROOT.glob('tools/decision_benchmark/*.py')})
    report['metadata']['code_sha256'] = digest(canonical(report['metadata']['code_manifest']))
    try:
        with tempfile.TemporaryDirectory(prefix='dm-support-paths-') as tmp:
            report['result'] = capture(Path(tmp) / 'brain', sources, case, packet)
        report['status'] = 'complete'
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
    report = run(args.output)
    print(json.dumps(dict(status=report['status'], case_id=report['case_id'],
                          independent_acceptance=report['independent_acceptance'])))


if __name__ == '__main__':
    main()

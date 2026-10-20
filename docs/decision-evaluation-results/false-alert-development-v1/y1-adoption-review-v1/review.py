"""Source-bound review and revision of an unsigned known-development plan.

This does not submit reviews, simulate reviewer outcomes, or dry-run activation.
The original plan/results and exact 18-version/19-event brain remain unchanged.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
from tools.decision_benchmark.corpus import DATA, digest
from tools.decision_benchmark.observations import value
from tools.decision_benchmark.support_paths import prepare

BASE = 'a02f6eb9fdc8704e38d47f97c4f32b7e1dc2a7ca'
PRIOR = HERE.parent / 'y1-adoption-plan-v1'
REQUIRED_OUTCOMES = {'dependency_review': 'accepted', 'decision_review': 'accepted',
                     'successor_conclusion': 'remains_justified'}


def original_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location('preserved_y1_preparation', PRIOR / 'prepare.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def omissions(plan: dict) -> list[str]:
    missing = []
    if 'temporal_scope' not in plan:
        missing.append('No explicit fictional-event time / unknown present-world availability.')
    if 'source_mapping' not in plan:
        missing.append('Unit inheritance and exact metric/condition field roles not explicit in the JSON.')
    if 'adoption_gate' not in plan:
        missing.append('Future stage dependencies lack explicit required-outcome and unfilled-authority predicates.')
    return missing


def source_mapping(sources: dict, packet: dict, references: dict) -> dict:
    rule, remaining = packet['rule'], packet['remaining']

    def cite(source_id: str, binding: dict) -> dict:
        assert sources[source_id]['origin']['split'] == 'development'
        assert sources[source_id]['text'][binding['start']:binding['end']] == binding['quote']
        role = 'basis_source' if source_id == rule['source_id'] else 'withdrawal_update'
        return dict(source_id=source_id, ref=references[role],
                    **{key: binding[key] for key in ('start', 'end', 'quote')})

    return dict(
        metric=dict(subject=value(remaining['subject']), metric=value(remaining['metric']),
                    value=value(remaining['value']), evidence_ref=references['Y1'],
                    subject_binding=cite(remaining['source_id'], remaining['subject']),
                    metric_binding=cite(remaining['source_id'], remaining['metric']),
                    value_binding=cite(remaining['source_id'], remaining['value']),
                    statement=cite(remaining['source_id'], remaining['statement'])),
        rule=dict(operator=value(rule['operator']), threshold=value(rule['threshold']),
                  statement=cite(rule['source_id'], rule['statement']),
                  threshold_binding=cite(rule['source_id'], rule['threshold'])),
        unit=dict(value=value(rule['unit']), interpretation='inherited_from_the_same_declared_recall_rule',
                  separately_repeated_in_y1=False, binding=cite(rule['source_id'], rule['unit'])),
        conditions=dict(interpretation='explicit_same_conditions_reference_to_preceding_X1_context_fields_only',
            reference=cite(remaining['source_id'], remaining['conditions_reference']),
            referent=cite(remaining['source_id'], remaining['conditions_referent']),
            referent_statement=cite(packet['withdrawn']['source_id'], packet['withdrawn']['statement']),
            dimensions={name: dict(value=value(binding), binding=cite(remaining['source_id'], binding))
                        for name, binding in remaining['conditions'].items()},
            measurement_transferred_from_x1=False, actual_execution_artifacts_verified=None),
        availability={name: cite(packet['update']['source_id'], packet['update'][name])
                      for name in ('withdrawal_statement', 'availability_statement')},
        lineage=dict(independence_established=None,
            y1_run_binding=cite(remaining['source_id'], remaining['measurement_root']),
            shared_document_not_independent_votes=True))


def validate(plan: dict, original: dict, mapping: dict, temporal: dict) -> None:
    """Check the source roles and the declared protocol; never judge a reviewer."""
    extensions = {'temporal_scope', 'source_mapping', 'adoption_gate', 'freshness_protocol',
                  'finding_followup', 'revises_plan_sha256', 'reviewed_at_repository_snapshot'}
    assert plan['schema'] == 'dm.development.y1-adoption-plan/2'
    assert plan['revises_plan_sha256'] == digest((PRIOR / 'decision.json').read_bytes())
    assert plan['reviewed_at_repository_snapshot'] == BASE
    inherited = {k: v for k, v in plan.items() if k not in extensions and k != 'schema'}
    assert inherited == {k: v for k, v in original.items() if k != 'schema'}
    assert not omissions(plan)
    assert plan['temporal_scope'] == temporal
    assert plan['source_mapping'] == mapping
    refs = plan['snapshot_observation']['references']
    metric = mapping['metric']
    assert metric['subject'] == 'Y1' and metric['metric'] == 'recall'
    assert metric['evidence_ref'] == refs['Y1'] and metric['evidence_ref'] != refs['X1']
    for name in ('subject_binding', 'metric_binding', 'value_binding'):
        row, statement = metric[name], metric['statement']
        assert statement['start'] <= row['start'] < row['end'] <= statement['end']
    assert metric['value_binding']['quote'] == metric['value'] == '0.8'
    assert mapping['rule']['threshold_binding']['quote'] == mapping['rule']['threshold'] == '0.7'
    assert Decimal(metric['value']) >= Decimal(mapping['rule']['threshold'])
    assert mapping['rule']['operator'] == '>=' and mapping['unit']['value'] == 'fraction'
    assert mapping['unit']['separately_repeated_in_y1'] is False
    assert mapping['unit']['value'] not in metric['statement']['quote']
    rule_span = mapping['rule']['statement']
    for row in (mapping['rule']['threshold_binding'], mapping['unit']['binding']):
        assert rule_span['start'] <= row['start'] < row['end'] <= rule_span['end']
    assert mapping['conditions']['reference']['quote'] == 'under the same conditions'
    dimensions = mapping['conditions']['dimensions']
    assert {k: dict(type='id', value=v['value']) for k, v in dimensions.items()} == plan['source_facts']['dimensions']
    referent = mapping['conditions']['referent_statement']
    subject = mapping['conditions']['referent']
    assert subject['quote'] == 'X1' and referent['start'] <= subject['start'] < subject['end'] <= referent['end']
    assert len(dimensions) == 5 and mapping['conditions']['measurement_transferred_from_x1'] is False
    for row in dimensions.values():
        assert referent['start'] <= row['binding']['start'] < row['binding']['end'] <= referent['end']
    gate = plan['adoption_gate']
    assert gate['mode'] == 'declarative_unsigned_protocol_not_an_executor'
    assert gate['execution_permitted'] is gate['future_transaction_validated'] is False
    assert gate['requirements_satisfied'] is False
    assert gate['required_approval'] == dict(selected_option='bounded_development_adoption',
        activation_authorized=True, authorizer='actual_authorized_identity_required', authorized_at='actual_authorization_time_required')
    assert gate['observed_approval'] == plan['approval']
    assert gate['required_source_state'] == dict(
        exact_scope_and_source_bytes=True, y1_available=True, claim_accepted_and_supported_and_fresh=True,
        support_accepted_available_comparable_and_fresh=True, old_current_new_proposed=True,
        current_authorization_and_fresh_event_heads_required=True)
    assert gate['scope_confirmation'] is None and gate['authorization_verified_for_execution'] is None
    assert set(gate['review_requirements']) == set(REQUIRED_OUTCOMES)
    steps = {row['id']: row for row in plan['future_steps']}
    for name, required in REQUIRED_OUTCOMES.items():
        row = gate['review_requirements'][name]
        assert row == dict(required_outcome=required, nonempty_actual_returned_event_id_required=True,
                           observed_outcome=None, observed_event_id=None, satisfied=False)
        assert required in steps[name]['permitted_outcomes']
        assert steps[name]['actual_outcome'] is steps[name]['future_review_event_id'] is None
    assert gate['negative_or_unknown_or_missing_requirement'] == 'defer_execution_without_lifecycle_or_finding_write'
    assert len(steps['atomic_lifecycle_pair']['members']) == 2
    assert plan['freshness_protocol'] == dict(
        before_each_future_write='Re-read current authorization, exact heads, raw source bytes, availability and event predecessors.',
        unplanned_change='Stop and prepare a new unsigned version; do not silently replace the pinned scope or evidence.',
        planned_review_addition='Use actual returned event IDs, recompare and revalidate the next stage on current state; saved observations are not execution tokens.',
        raw_qualifications='Preserve comparability_unknown/proposed_preview and stale flags until actual comparison/review changes them.',
        future_transaction_validation='Not attempted here; actual signed transaction still requires fresh validation before any separately authorized execution.')
    assert plan['finding_followup'] == [dict(ref=row['ref'], preserved_state=row['state'], assigned_owner=None,
        required_action='Keep unresolved; after any future review recompare and inspect exact-target basis. Separate resolution authorization is required.')
        for row in refs['findings'].values()]
    assert plan['approval']['selected_option'] is plan['approval']['reviewer'] is plan['approval']['authorizer'] is None
    assert plan['activation'] is plan['resolution'] is plan['independent_acceptance'] is False


def counterchecks(plan: dict, original: dict, mapping: dict, temporal: dict, packet: dict) -> list[dict]:
    """Malformed plan variants only: no invented cases, ratings, people or events."""
    variants = []
    for key in ('temporal_scope', 'source_mapping', 'adoption_gate'):
        bad = deepcopy(plan); del bad[key]
        variants.append(('missing_' + key, bad))
    bad = deepcopy(plan); bad['temporal_scope']['present_world_availability'] = 'verified'
    variants.append(('unsupported_present_world_availability', bad))
    bad = deepcopy(plan); bad['source_mapping']['unit']['separately_repeated_in_y1'] = True
    variants.append(('unit_claimed_directly_in_y1', bad))
    bad = deepcopy(plan)
    # The known X1 measurement has the same lexical value, but is the wrong
    # subject and location. Bind it only in this invalid in-memory plan variant.
    text = packet['withdrawn']['statement']['quote']
    start = packet['withdrawn']['statement']['start'] + text.index('0.8')
    bad['source_mapping']['metric']['value_binding'].update(start=start, end=start + 3, quote='0.8')
    variants.append(('equal_number_bound_to_withdrawn_x1', bad))
    for name in REQUIRED_OUTCOMES:
        bad = deepcopy(plan); del bad['adoption_gate']['review_requirements'][name]['required_outcome']
        variants.append(('missing_required_outcome_' + name, bad))
    bad = deepcopy(plan); bad['future_steps'][4]['members'].pop(0)
    variants.append(('missing_atomic_old_terminalization', bad))
    bad = deepcopy(plan); bad['findings']['resolution_authorized'] = True
    variants.append(('implicit_finding_resolution', bad))
    result = []
    for name, bad in variants:
        try:
            validate(bad, original, mapping, temporal)
        except (AssertionError, KeyError):
            result.append(dict(check=name, result='rejected_invalid_plan_variant'))
        else:
            raise AssertionError('Invalid plan variant accepted: ' + name)
    return result


def build() -> tuple[dict, dict]:
    module = original_module()
    original = json.loads((PRIOR / 'decision.json').read_bytes())
    regenerated, checks = module.build()
    assert regenerated == original and checks == json.loads((PRIOR / 'readcheck.json').read_bytes())
    with module.guard_module().source_guard():
        sources, case, packet = prepare()
        assert case['id'] == original['case_id'] == 'controls-v2/event-surviving-support'
        assert packet['sources'] == original['snapshot_observation']['source_manifest']
        refs = original['snapshot_observation']['references']
        mapping = source_mapping(sources, packet, refs)
        temporal = dict(fictional_event_at=case['event']['at'],
            evidence_available_at={key: row['available_at'] for key, row in packet['sources'].items()},
            applicability='Only the known fictional event and declared five-condition rule; no assertion about a real present-day experiment.',
            present_world_availability=None, actual_execution_or_dataset_validity=None)
        assert all(at <= temporal['fictional_event_at'] for at in temporal['evidence_available_at'].values())
        plan = deepcopy(original)
        plan.update(schema='dm.development.y1-adoption-plan/2', temporal_scope=temporal, source_mapping=mapping,
            revises_plan_sha256=digest((PRIOR / 'decision.json').read_bytes()), reviewed_at_repository_snapshot=BASE,
            adoption_gate=dict(mode='declarative_unsigned_protocol_not_an_executor', execution_permitted=False,
                future_transaction_validated=False, requirements_satisfied=False,
                required_approval=dict(selected_option='bounded_development_adoption', activation_authorized=True,
                    authorizer='actual_authorized_identity_required', authorized_at='actual_authorization_time_required'),
                observed_approval=deepcopy(original['approval']), scope_confirmation=None, authorization_verified_for_execution=None,
                required_source_state=dict(exact_scope_and_source_bytes=True, y1_available=True,
                    claim_accepted_and_supported_and_fresh=True, support_accepted_available_comparable_and_fresh=True,
                    old_current_new_proposed=True, current_authorization_and_fresh_event_heads_required=True),
                review_requirements={name: dict(required_outcome=required, nonempty_actual_returned_event_id_required=True,
                    observed_outcome=None, observed_event_id=None, satisfied=False) for name, required in REQUIRED_OUTCOMES.items()},
                negative_or_unknown_or_missing_requirement='defer_execution_without_lifecycle_or_finding_write'),
            freshness_protocol=dict(
                before_each_future_write='Re-read current authorization, exact heads, raw source bytes, availability and event predecessors.',
                unplanned_change='Stop and prepare a new unsigned version; do not silently replace the pinned scope or evidence.',
                planned_review_addition='Use actual returned event IDs, recompare and revalidate the next stage on current state; saved observations are not execution tokens.',
                raw_qualifications='Preserve comparability_unknown/proposed_preview and stale flags until actual comparison/review changes them.',
                future_transaction_validation='Not attempted here; actual signed transaction still requires fresh validation before any separately authorized execution.'),
            finding_followup=[dict(ref=row['ref'], preserved_state=row['state'], assigned_owner=None,
                required_action='Keep unresolved; after any future review recompare and inspect exact-target basis. Separate resolution authorization is required.')
                for row in refs['findings'].values()])
        validate(plan, original, mapping, temporal)
        rejected = counterchecks(plan, original, mapping, temporal, packet)
    audit = dict(schema='dm.development.y1-adoption-review/1', author=dict(role='implementing-agent', human=False, independent=False),
        reviewed_snapshot=BASE, original_plan_sha256=plan['revises_plan_sha256'],
        original_omissions=omissions(original), original_scope_conclusion='Consistent with the sole declared fictional rule; not real-world or statistical sufficiency.',
        revision='Explicit temporal/interpretation scope, required outcome/authority predicates and unresolved finding handoff; no existing recommendation or source threshold changed.',
        exact_state_checks=checks, counterchecks=rejected,
        code_or_basis_correction=False, domain_writes=0, activation=False, independent_acceptance=False,
        human_review=None, semantic_scores=None, product_benefit=None,
        independent_final_coverage=dict(positive=0, negative=0, inconclusive=0))
    assert len(audit['original_omissions']) == 3 and len(rejected) == 11
    return plan, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New review directory outside frozen data')
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(DATA.resolve()):
        parser.error('Keep output outside frozen data')
    args.output.mkdir(parents=True, exist_ok=False)
    plan, audit = build()
    for name, data in [('decision.json', plan), ('review.json', audit)]:
        (args.output / name).write_text(json.dumps(data, indent=2) + '\n')
    print('Three preparation gaps addressed; 11 malformed-plan counterchecks rejected. Exact 18/19 brain, all reviews and three unresolved findings unchanged; no activation or independent acceptance.')


if __name__ == '__main__':
    main()

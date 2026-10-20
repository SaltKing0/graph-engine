"""Read-only preparation of an unsigned, non-executable Y1 adoption decision."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
from decimal import Decimal
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
from graph_engine import decision_schema as s
from graph_engine.brain import Brain
from graph_engine.decision_memory import DecisionMemory, body, node_text
from graph_engine.decision_service import DecisionService
from tools.decision_benchmark.corpus import DATA, canonical, digest
from tools.decision_benchmark.observations import value
from tools.decision_benchmark.reviewed_development import journal
from tools.decision_benchmark.support_paths import prepare

BASE = 'bf27c81d7c03c6483359c979603dd56c9bd2de06'
PRIOR = HERE.parent / 'y1-candidate-review-v1'


def guard_module() -> ModuleType:
    path = PRIOR / 'review.py'
    spec = importlib.util.spec_from_file_location('known_y1_read_helpers', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build() -> tuple[dict, dict]:
    """Produce observations and recommendations; never submit/dry-run a review."""
    helper = guard_module()
    raw = (PRIOR / 'report.json.gz').read_bytes()
    prior = json.loads(gzip.decompress(raw))
    assert prior['status'] == 'complete_two_diagnostics_unresolved'
    bundle = PRIOR / 'brain.bundle'
    assert digest(bundle.read_bytes()) == prior['brain_bundle_sha256']
    with helper.source_guard(), tempfile.TemporaryDirectory(prefix='y1-adoption-read-') as tmp:
        path = Path(tmp) / 'brain'
        service = helper.restore(bundle, prior['final']['revision'], path)
        before = journal(path)
        assert before == prior['final']['journal']
        preview = service.preview()
        repo_head = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
        # Fail on ANY attempted domain write, including a dry run. Git clone and
        # scratch-clone remote configuration are restore setup, not review events.
        with ExitStack() as stack:
            for cls, name in [(DecisionMemory, 'transact'), (DecisionService, 'submit'),
                              (DecisionService, 'record_finding'), (Brain, 'write_node'),
                              (Brain, 'write_edges'), (Brain, 'commit_and_push')]:
                stack.enter_context(patch.object(cls, name, side_effect=AssertionError('Adoption preparation is read-only')))
            sources, case, packet = prepare()
            assert case['id'] == prior['case_id'] == 'controls-v2/event-surviving-support'
            assert packet['sources'] == prior['analysis']['source_manifest']
            assert digest(canonical(case['runtime'])) == prior['analysis']['source_input_sha256']
            comparison = prior['current_comparison']
            assert helper.compare_fields(service.compare(comparison['input'])) == helper.compare_fields(comparison['output'])
            refs = prior['analysis']['objects']
            observed = {role: service.inspect(s.reference(item['record'])) for role, item in refs.items()}
            assert observed == refs
            queue = service.read('review-queue', {})
            assert queue == prior['final']['queue_without_comparison']
            assert len(queue['items']) == 3 and not queue['truncated']
            references = {role: s.reference(item['record']) for role, item in observed.items()}
            references['findings'] = {role: dict(ref=ref, state=service.inspect(ref)['state'])
                for role, ref in prior['final']['finding_refs'].items()}
            withdrawal = prior['final']['existing_withdrawal']
            references['findings']['withdrawal'] = dict(ref=s.reference(withdrawal['record']), state=withdrawal['state'])
            current, old = observed['decision'], observed['old_decision']
            assert current['record']['previous'] == references['old_decision']
            assert old['state']['decision'] == 'current' and old['basis_changed']
            assert old['state']['decision_conclusion'] == 'needs_investigation'
            assert current['state']['decision'] == 'proposed' and current['events'] == []
            assert observed['dependency']['state']['workflow'] == 'proposed' and observed['dependency']['events'] == []
            assert not observed['claim']['basis_changed'] and not observed['support']['basis_changed']
            assert observed['claim']['effective_assessment'] == 'supported'
            assert observed['support']['comparison']['status'] == 'comparable'
            for i in queue['items']:
                assert not i['item']['basis_changed'] and i['item']['state']['finding_workflow'] in ('open', None)
            events = {role: {event['axis']: event['event_id'] for event in item['events']}
                      for role, item in observed.items()}
            source_refs = prior['analysis']['citations']
            source_bindings = {}
            for role, source_id in [('basis_source', packet['rule']['source_id']),
                                    ('withdrawal_update', packet['update']['source_id'])]:
                references[role] = next(c['ref'] for c in source_refs if c['source_id'] == source_id)
                source = service.inspect(references[role])
                assert source['record']['kind'] == 'source' and not source['basis_changed']
                payload, original = source['record']['payload'], sources[source_id]['text']
                assert payload['artifact']['sha256'] == digest(original.encode()) == packet['sources'][source_id]['text_sha256']
                assert json.loads(payload['artifact']['extraction']) == sources[source_id]['origin']
                assert payload['source_ref']['text_sha256'] == digest(payload['text'].encode())
                node = deepcopy(service.brain.read_node(payload['source_ref']['node_id']))
                assert node_text(service.brain, payload['source_ref']['node_id']) == payload['text']
                node.text = original  # in-memory serialization check; never write
                assert body(node.to_markdown()) == payload['text'] == original + '\n'
                source_bindings[role] = dict(ref=references[role], original_artifact_sha256=payload['artifact']['sha256'],
                    captured_text_sha256=payload['source_ref']['text_sha256'],
                    original_characters=len(original), captured_characters=len(payload['text']),
                    transformation='Existing Node Markdown serialization adds exactly one final newline; raw body is verified, not the whitespace-stripping display parser. Neither representation is rewritten.')
            source_facts = dict(predicate=prior['analysis']['source_predicate'],
                dimensions=prior['analysis']['dimensions'], citations=source_refs,
                document_roots=prior['analysis']['root_lineage'], source_bindings=source_bindings, measurement_independence=None,
                statistical_sufficiency=None, real_execution_validity=None)
            assert Decimal(value(packet['remaining']['value'])) >= Decimal(value(packet['rule']['threshold']))
            assert source_facts['predicate'] == dict(value='0.8', operator='>=', threshold='0.7', unit='fraction', met=True)
            for citation in source_refs:
                assert sources[citation['source_id']]['text'][citation['start']:citation['end']] == citation['quote']
            steps = [
                dict(id='refresh', action='Re-read exact heads, sources, reviews, availability and current authorization; regenerate comparison.',
                     required_before=['dependency_review', 'decision_review', 'successor_conclusion', 'atomic_lifecycle_pair']),
                dict(id='dependency_review', subject_role='dependency', axis='workflow', observed_from='proposed',
                     conditional_recommendation='accepted', permitted_outcomes=['accepted', 'rejected'],
                     observed_previous_event_id=None,
                     basis_roles=['claim', 'support', 'Y1', 'basis_source', 'withdrawal_update'],
                     basis_event_ids=[events['claim']['epistemic'], events['support']['workflow']],
                     future_review_event_id=None, actual_outcome=None,
                     condition='Separate authorized review of this exact dependency; source consistency alone is not approval.'),
                dict(id='decision_review', subject_role='decision', axis='workflow', observed_from='proposed',
                     conditional_recommendation='accepted', permitted_outcomes=['accepted', 'rejected'],
                     observed_previous_event_id=None, basis_roles=['claim', 'support', 'dependency', 'withdrawal_update'],
                     required_future_events=['dependency_review'], future_review_event_id=None, actual_outcome=None,
                     condition='Separate authorized acceptance of the successor within the stated fictional scope.'),
                dict(id='successor_conclusion', subject_role='decision', axis='decision_conclusion', observed_from=None,
                     conditional_recommendation='remains_justified', permitted_outcomes=['remains_justified', 'needs_investigation', 'revise'],
                     observed_previous_event_id=None, basis_roles=['claim', 'support', 'Y1', 'basis_source', 'withdrawal_update'],
                     required_future_events=['dependency_review', 'decision_review'],
                     future_review_event_id=None, actual_outcome=None,
                     condition='Only if the authorized reviewer accepts source-declared fictional sufficiency; otherwise defer adoption.'),
                dict(id='atomic_lifecycle_pair', action='One public transaction, never two separate lifecycle writes.',
                     requires=['refresh', 'dependency_review', 'decision_review', 'successor_conclusion'],
                     members=[dict(subject_role='old_decision', axis='decision', observed_from='current', desired_to='superseded',
                                   observed_previous_event_id=events['old_decision']['decision'], basis_roles=['decision']),
                              dict(subject_role='decision', axis='decision', observed_from='proposed', desired_to='current',
                                   observed_previous_event_id=None, basis_roles=['claim', 'support', 'dependency', 'withdrawal_update'],
                                   required_future_events=['dependency_review', 'decision_review', 'successor_conclusion'])],
                     actual_outcome=None, condition='Later explicit lifecycle authorization, fresh preview and actual prior review IDs required.'),
                dict(id='refresh_findings', action='After any future review, regenerate comparison and inspect all three finding bases.',
                     automatic_resolution=False, preserve_dispositions=True,
                     condition='Review/basis changes can stale current finding versions. New candidate IDs require explicit review; never reuse stale IDs.'),
            ]
            for step in steps[1:4]:
                assert s.valid_transition(step['axis'], step['observed_from'], step['conditional_recommendation'], False)
            for member in steps[4]['members']:
                assert s.valid_transition(member['axis'], member['observed_from'], member['desired_to'], False)
            plan = dict(schema='dm.development.y1-adoption-plan/1', status='unsigned_non_executable_preparation',
                author=dict(role='implementing-agent', human=False, independent=False), case_id=case['id'],
                reviewed_repository_snapshot=BASE, brain_revision=repo_head,
                prior_report_sha256=digest(raw), prior_bundle_sha256=digest(bundle.read_bytes()),
                exposure='Same already exposed fictional development case; no new independent cases or scores.',
                recommendation_now='Defer execution; present conditional adoption of the exact Y1-only successor.',
                conditional_choice='Adopt this exact successor only for the source-declared fictional rule and five conditions after separate authorization and reviews.',
                alternatives=[dict(option='defer', recommended_now=True, effect='No state change; old decision current/needs_investigation, successor proposed.'),
                    dict(option='bounded_development_adoption', recommended_now=False, effect='Future authorized reviews followed by atomic old supersession/new activation; no release or independent acceptance.'),
                    dict(option='broader_or_real_world_adoption', recommended_now=False, supported_by_known_sources=False,
                         effect='Do not authorize from this evidence: real execution, dataset validity and statistical sufficiency are unavailable.')],
                approval=dict(selected_option=None, authorizer=None, reviewer=None, authorized_at=None,
                              activation_authorized=False, independent_acceptance=False),
                snapshot_observation=dict(preview=preview, not_an_execution_token=True, references=references,
                                          observed_event_heads=events, source_manifest=packet['sources']),
                source_facts=source_facts, future_steps=steps,
                old_history=dict(preserve_old_conclusion='needs_investigation',
                    append_new_old_conclusion=False, undo_existing_reviews=False,
                    explanation='The old decision is not the content head. Fresh nonterminal reviews of it are rejected; only explicit paired terminalization is exempt.'),
                findings=dict(disposition_changes=[], workflow_changes=[], resolution_authorized=False,
                    unresolved_references=[row['ref'] for row in references['findings'].values()],
                    explanation='All three remain unresolved. A successor outcome cannot resolve a finding targeting the old version; resolution must pin the exact target outcome and meet follow-up guards.'),
                independent_acceptance=False, activation=False, resolution=False, release_ready=False,
                human_review=None, semantic_scores=None, user_sessions=None, product_benefit=None,
                independent_final_coverage=dict(positive=0, negative=0, inconclusive=0),
                failed_or_unmeasured_gates=dict(historical_false_alerts=dict(numerator=5, denominator=95, threshold_percent='5', passed=False),
                    proposed_profile_missed_positives=dict(numerator=3, denominator=3),
                    independent_final_evaluation=None, matched_completed_baselines=None, final_sign_off=None, measured_benefit=None),
                independent_work=dict(actual_execution_dataset_artifacts=None, separate_reviewers=[], evaluator_custodian=None,
                    requirement='Assign qualified separate reviewers and evaluator-controlled final storage for independent acceptance; none are invented here.'))
        assert journal(path) == before and service.preview() == preview
        assert subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip() == repo_head
        assert not subprocess.check_output(['git', '-C', str(path), 'status', '--porcelain'])
        checks = dict(schema='dm.development.y1-adoption-readcheck/1', domain_write_attempts=0,
            journal_unchanged=True, preview_unchanged=True, git_head_unchanged=True, git_worktree_clean=True,
            versions=len(before['versions']), events=len(before['events']), unresolved_findings=len(queue['items']),
            comparison_deltas=len(comparison['output']['deltas']), comparison_candidates=len(comparison['output']['candidates']),
            truncated=comparison['output']['completeness']['truncated'],
            independent_acceptance=False, activation=False, reviewer_outcomes_recorded=0,
            limitation='Read-only plan and allowed-transition checks, not a full future transaction execution or approval.')
        assert (checks['versions'], checks['events'], checks['unresolved_findings']) == (18, 19, 3)
        return plan, checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory outside frozen data')
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(DATA.resolve()):
        parser.error('Keep output outside frozen data')
    args.output.mkdir(parents=True, exist_ok=False)
    plan, checks = build()
    for name, data in [('decision.json', plan), ('readcheck.json', checks)]:
        (args.output / name).write_text(json.dumps(data, indent=2) + '\n')
    print('Unsigned Y1 adoption decision prepared; exact 18/19 journal and three unresolved findings unchanged. No domain write or activation.')


if __name__ == '__main__':
    main()

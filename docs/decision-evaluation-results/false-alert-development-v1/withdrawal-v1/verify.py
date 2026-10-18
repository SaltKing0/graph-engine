"""Source-only sufficiency audit of the one already exposed withdrawal case.

This documentation tool never supplies its interpretation to the runtime,
filters alerts, accepts reviews, reads labels or opens evaluation-source files.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))

from graph_engine import decision_schema as s
from tools.decision_benchmark.corpus import DATA, canonical, digest
from tools.decision_benchmark.observations import DIMENSIONS, validate_binding, value
from tools.decision_benchmark.production import execute
from tools.decision_benchmark.reviewed_development import REVIEWS, journal, review_inputs
from tools.decision_benchmark.reviewed_observations import AUTHOR
from tools.decision_benchmark.structured_development import TRANSCRIPTIONS, development_inputs

REFERENCE = HERE.parent / 'reviewed-v1' / 'reviewed-report.json.gz'


def prepared() -> tuple[dict, dict, dict]:
    """Apply an explicit read guard before the existing development loader."""
    forbidden = set()
    for bundle in ('controls-v2', 'project-v1'):
        root = DATA / bundle
        metadata = json.loads((root / 'inputs.json').read_bytes())
        forbidden.add(root / 'labels.json')
        forbidden.update(root / source['file'] for source in metadata['sources'] if source['split'] == 'evaluation')
    read_bytes, read_text = Path.read_bytes, Path.read_text

    def guarded_bytes(path: Path) -> bytes:
        if path in forbidden:
            raise AssertionError('Forbidden evaluation/label read: ' + str(path))
        return read_bytes(path)

    def guarded_text(path: Path, *args, **kwargs) -> str:
        if path in forbidden:
            raise AssertionError('Forbidden evaluation/label read: ' + str(path))
        return read_text(path, *args, **kwargs)

    Path.read_bytes, Path.read_text = guarded_bytes, guarded_text
    try:
        sources, cases = development_inputs()
        packet = json.loads(TRANSCRIPTIONS.read_bytes())
        reviews = review_inputs(sources, packet, json.loads(REVIEWS.read_bytes()))
    finally:
        Path.read_bytes, Path.read_text = read_bytes, read_text
    case = next(c for c in cases if c['id'] == 'controls-v2/event-surviving-support')
    return sources, case, reviews


def assessment(packet: dict, sources: dict, case: dict) -> dict:
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


def replay(output: Path) -> None:
    sources, case, reviews = prepared()
    packet = json.loads((HERE / 'source-audit.json').read_bytes())
    result = assessment(packet, sources, case)
    previous = json.loads(gzip.decompress(REFERENCE.read_bytes()))
    old = next(r for r in previous['results'] if r['case_id'] == case['id'])
    for name, expected in previous['code_manifest'].items():
        s.need(digest((ROOT / name).read_bytes()) == expected, 'Runtime code changed: ' + name)
    s.need(not subprocess.check_output(['git', 'diff', '30908637cf94bacd75d69e783fef222ea38944db',
        '--', 'graph_engine', 'tools', 'tests', 'examples', '.github', 'pyproject.toml'], cwd=ROOT))
    s.need(digest(canonical(case['runtime'])) == old['source_input_sha256'])
    if output.resolve().is_relative_to(DATA.resolve()):
        raise ValueError('Output must be outside frozen data')
    output.mkdir(parents=True, exist_ok=False)
    report = dict(schema='dm.withdrawal-development-result/1', assessment=result, case_id=case['id'],
        documentation_base='30908637cf94bacd75d69e783fef222ea38944db', runtime_code_commit=previous['source_commit'],
        runtime_code_unchanged=True, original_source_input_sha256=old['source_input_sha256'],
        audit_sha256=digest((HERE / 'source-audit.json').read_bytes()), eligible_decisions=len(case['runtime']['decisions']),
        exposure='one previously exposed development case; no new independent cases', profiles={},
        independent_final_coverage=dict(positive=0, negative=0, inconclusive=0),
        independent_acceptance=False, human_review=None, semantic_scores=None, product_benefit=None,
        provider_calls=0, release_ready=False, errors=[])
    review = dict(schema='dm.development.field-review/1', author=AUTHOR,
        sources=[reviews['controls-v2/' + case['event'][key]] for key in ('changed_source_id', 'source_id')])
    with tempfile.TemporaryDirectory(prefix='dm-withdrawal-audit-') as tmp:
        for mode in ('curated', 'proposed'):
            path = Path(tmp) / mode
            trace: dict = {}
            try:
                # Deliberately original reviewed runtime input only. The new
                # source assessment never enters execute or review events.
                trace = execute(deepcopy(case['runtime']), case['event'], path, mode,
                                budget=4000, k=5, trace=trace, observation_review=review)
                trace['journal'] = journal(path)
                trace['error'] = None
                normalized = lambda p: [{k: v for k, v in a.items() if k != 'candidate_id'} for a in p['alerts']]
                s.need(normalized(trace) == normalized(old['profiles'][mode]))
            except Exception as exc:
                trace['error'] = dict(type=type(exc).__name__, message=str(exc))
                report['errors'].append(dict(profile=mode, error=trace['error']))
            report['profiles'][mode] = trace
    report['status'] = 'complete' if not report['errors'] else 'completed_with_errors'
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(status=report['status'], assessment=result)))
    s.need(report['status'] == 'complete')


def verify() -> None:
    manifest = json.loads((HERE / 'manifest.json').read_bytes())
    inventory = {str(p.relative_to(HERE)) for p in HERE.rglob('*') if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}
    s.need(set(manifest['files']) == inventory)
    for name, expected in manifest['files'].items():
        s.need(digest((HERE / name).read_bytes()) == expected, 'Artifact changed: ' + name)
    s.need(not subprocess.check_output(['git', 'diff', '30908637cf94bacd75d69e783fef222ea38944db',
        '--', 'graph_engine', 'tools', 'tests', 'examples', '.github', 'pyproject.toml'], cwd=ROOT))
    sources, case, _ = prepared()
    for name, source in json.loads((HERE / 'source-copies.json').read_bytes()).items():
        s.need(digest((HERE / name).read_bytes()) == source['text_sha256'])
        s.need((HERE / name).read_text() == sources[source['id']]['text'])
    historical = json.loads((HERE / 'historical-commands-final.json').read_bytes())
    s.need(len(historical) == 5 and all(c['exit_code'] == 0 for c in historical))
    initial = json.loads((HERE / 'historical-initial-commands.json').read_bytes())
    s.need([c['exit_code'] for c in initial] == [1, 1, 0, 0, 0])
    packet = json.loads((HERE / 'source-audit.json').read_bytes())
    report = json.loads(gzip.decompress((HERE / 'runtime-report.json.gz').read_bytes()))
    s.need(report['assessment'] == assessment(packet, sources, case))
    s.need(report['status'] == 'complete' and not report['errors'])
    s.need(report['audit_sha256'] == digest((HERE / 'source-audit.json').read_bytes()))
    s.need(report['original_source_input_sha256'] == digest(canonical(case['runtime'])))
    s.need(report['runtime_code_unchanged'])
    previous = json.loads(gzip.decompress(REFERENCE.read_bytes()))
    for name, expected in previous['code_manifest'].items():
        s.need(digest((ROOT / name).read_bytes()) == expected, 'Runtime code changed: ' + name)
    s.need(not report['independent_acceptance'] and not report['release_ready'])
    s.need(report['human_review'] is report['semantic_scores'] is report['product_benefit'] is None)
    s.need(sum(report['independent_final_coverage'].values()) == 0)
    from graph_engine.brain import Node
    from graph_engine.decision_memory import body, event_identity
    for mode, profile in report['profiles'].items():
        s.need(profile['error'] is None and profile['complete'] and profile['context_within_budget'])
        s.need(not profile['observation_assessment']['retain_basis'])
        s.need(len(profile['alerts']) == (1 if mode == 'curated' else 0))
        impact = next(o['output'] for o in profile['raw_outputs'] if o['stage'] == 'impact')
        s.need(len(impact['candidates']) == len(profile['alerts']))
        for candidate in impact['candidates']:
            s.need(candidate['reasons'] == ['basis_changed', 'comparability_unknown'])
            s.need(candidate['support']['remaining'] == candidate['support']['removed'] == [])
        context = next(o['output'] for o in profile['raw_outputs'] if o['stage'] == 'context')
        s.need(context['truncated'] and context['tokens'] <= 4000)
        records = profile['journal']['versions']
        indexed = {(v['id'], v['version_id']): v for v in records}
        for record in records:
            s.need(s.hash_record(record) == record['version_id'])
            if record['previous']:
                s.need((record['previous']['id'], record['previous']['version_id']) in indexed)
            if record['kind'] == 'source':
                doc = next(d for d in case['runtime']['documents'] if d['id'] == record['anchor_node_id'])
                s.need(record['payload']['text'] == body(Node(doc['text'], id=doc['id']).to_markdown()))
        for event in profile['journal']['events']:
            s.need(event['event_id'] == event_identity(event) and mode == 'curated')
            subject = indexed[(event['subject']['id'], event['subject']['version_id'])]
            s.need(subject['kind'] == 'relationship' and subject['payload']['kind'] == 'depends_on')
            s.need(event['axis'] == 'workflow' and event['to'] == 'accepted')
    for command in json.loads((HERE / 'commands.json').read_bytes()):
        s.need(command['exit_code'] == 0)
    print(json.dumps(dict(verified=True, case_id=case['id'], stated_condition_met=True,
                          runtime_withdrawal_review_retained=True, independent_acceptance=False)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, help='New directory for one-case/two-profile original runtime replay')
    args = parser.parse_args()
    replay(args.replay) if args.replay else verify()

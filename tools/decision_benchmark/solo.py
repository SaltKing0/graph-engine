"""Source-only engineering review of already exposed development cases.

No final-corpus switch, label loader, provider, independent scoring or human
simulation. Notes are separate from the explicitly allowlisted runtime inputs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Callable

from .annotation_packets import BUNDLE, prepare_development, validate_quote
from .corpus import canonical, digest, instant
from .production import execute

NOTES = Path(__file__).resolve().parents[2] / 'docs/decision-evaluation-results/solo-development-v1/source-notes.json'
ROOT = Path(__file__).resolve().parents[2]


def runtime_inputs(case: dict) -> tuple[dict, dict]:
    """Reconstruct only the old chronological source/task/dependency allowlist."""
    raw = (BUNDLE / 'inputs.json').read_bytes()
    freeze = json.loads((BUNDLE / 'freeze.json').read_bytes())
    if digest(raw) != freeze['files']['inputs.json']:
        raise ValueError('Original chronological metadata changed')
    metadata = json.loads(raw)
    event = next(e for e in metadata['events'] if e['id'] == case['id'])
    if event['split'] != 'development':
        raise ValueError('Only previously exposed development events are allowed')
    documents = []
    for source in case['sources']:
        for i, start in enumerate(range(0, len(source['text']), 800)):
            documents.append(dict(id=f"{source['id']}-c{i:03}", source_id=source['id'],
                                  text=source['text'][start:start + 800]))
    source_ids = {s['id'] for s in case['sources']}
    decisions = [{key: d[key] for key in ('id', 'source_id', 'action')} for d in case['decisions']]
    decision_ids = {d['id'] for d in decisions}
    dependencies = [{key: link[key] for key in ('id', 'source_id', 'decision_id', 'status')}
                    for link in metadata['dependencies'] if link['source_id'] in source_ids
                    and link['decision_id'] in decision_ids
                    and instant(link['available_at']) <= instant(case['at'])]
    return dict(documents=documents, decisions=decisions, dependencies=dependencies), {
        key: event[key] for key in ('id', 'at', 'split', 'source_id', 'changed_source_id', 'changed_path')}


def validate_notes(packet: dict, notes: dict) -> None:
    if (notes['schema'] != 'dm.solo.source-notes/1' or notes['independent'] is not False
            or notes['human_review'] is not False or notes['split'] != 'development'
            or notes['packet_sha256'] != digest(canonical(packet))):
        raise ValueError('Not disclosed development-only engineering notes')
    cases = {case['id']: case for case in packet['cases']}
    expected = {(case['id'], d['id']) for case in cases.values() for d in case['decisions']}
    if notes['pair_count'] != len(expected):
        raise ValueError('Incorrect declared pair denominator')
    seen = set()
    for row in notes['pairs']:
        key = row['case_id'], row['decision_id']
        if key in seen or key not in expected or row['working_outcome'] != 'inconclusive':
            raise ValueError('Missing/duplicate/unsupported development annotation')
        if not row['rationale'] or not row['uncertainty'] or row['accepted_historical_path'] is not None:
            raise ValueError('Do not invent reviewed paths or complete missing judgments')
        for quote in row['evidence']:
            validate_quote(cases[row['case_id']], quote)
        case = cases[row['case_id']]
        decision = next(d for d in case['decisions'] if d['id'] == row['decision_id'])
        required = {case['update_source_id'], decision['source_id']}
        if not required <= {quote['source_id'] for quote in row['evidence']}:
            raise ValueError('Both decision basis and observed update need exact references')
        update = next(source for source in case['sources'] if source['id'] == case['update_source_id'])
        if row['conditions']['code_revision'] != update['revision']:
            raise ValueError('Conditions must retain the actual update revision')
        seen.add(key)
    if seen != expected:
        raise ValueError('Every eligible development pair must be retained')


def run(output: Path, *, executor: Callable = execute) -> dict:
    packet, _ = prepare_development()
    notes = json.loads(NOTES.read_bytes())
    validate_notes(packet, notes)
    # Refuse overwriting reports or original benchmark data, including symlinks.
    if output.resolve().is_relative_to(BUNDLE.parent.resolve()):
        raise ValueError('Output must be outside preserved corpus data')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as handle:
        report = dict(schema='dm.solo.development-run/1', status='running',
            source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
            invocation_directory=str(Path.cwd()),
            packet_sha256=digest(canonical(packet)), notes_sha256=digest(NOTES.read_bytes()),
            exposure='Previously exposed project-v1 development; implementing-agent notes, not human calibration',
            release_ready=False, independent_final_coverage=dict(positive_pairs=0, negative_pairs=0, inconclusive_cases=0),
            human_calibration=None, human_review_time=None, semantic_quality=None,
            results=[], limitations=[
                'No independently reviewed structured conditions or historical accepted paths supplied.',
                'All 27 working judgments remain inconclusive; they are not scored gold or held-out coverage.',
                'Curated dependencies are old manual topic attachments, script-accepted for wiring diagnostics only.',
                'No fresh final data, providers or participant sessions; unknowns do not become negative labels.',
                'The original diagnostic false-alert gate and historical artifacts remain unchanged.'])
        repository = ROOT
        paths = [*repository.glob('graph_engine/**/*.py'), *repository.glob('graph_engine/web/*.js'),
                 *repository.glob('tools/decision_benchmark/*.py'), *repository.glob('examples/*.py')]
        report['code_manifest'] = {str(path.relative_to(repository)): digest(path.read_bytes()) for path in sorted(paths)}
        report['code_sha256'] = digest(canonical(report['code_manifest']))
        report['configuration'] = dict(budget=4000, k=5, provider_calls=0,
            curated_input='Original unadjudicated manual topic attachments; scripted acceptance only',
            proposed_input='Only separately supplied proposed links; none invented from notes')

        def checkpoint() -> None:
            handle.seek(0)
            json.dump(report, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write('\n')
            handle.truncate()
            handle.flush()

        checkpoint()
        with tempfile.TemporaryDirectory(prefix='dm-solo-development-') as temp:
            for case in packet['cases']:
                visible, event = runtime_inputs(case)
                row = dict(event_id=case['id'], eligible_pairs=len(case['decisions']),
                           source_inputs_sha256=digest(canonical(visible)), profiles={})
                for mode in ('curated', 'proposed'):
                    trace: dict = {}
                    try:
                        trace = executor(visible, event, Path(temp) / case['id'] / mode, mode,
                                         budget=4000, k=5, trace=trace)
                        trace['error'] = None
                    except Exception as exc:
                        trace.update(error=dict(type=type(exc).__name__, message=str(exc)))
                    row['profiles'][mode] = trace
                report['results'].append(row)
                checkpoint()
        report['attempted_pairs_per_profile'] = sum(row['eligible_pairs'] for row in report['results'])
        report['status'] = 'completed_with_errors' if any(
            p.get('error') or not p.get('complete') or not p.get('context_within_budget')
            for row in report['results'] for p in row['profiles'].values()) else 'complete'
        checkpoint()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='NEW report path; no overwrites')
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps(dict(status=report['status'], cases=len(report['results']),
                          pairs=report['attempted_pairs_per_profile'], release_ready=False)))
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

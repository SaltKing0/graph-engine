"""Source-bound, unreviewed observation proposals for known development only.

No label reader, arbitrary bundle/split option, independent score or warning
filter. Original production comparisons precede and survive separate capture.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile

from examples.decision_memory import _commit, _draft, _submit
from graph_engine.brain import Brain, Node
from graph_engine.decision_memory import RecordView, read_file
from graph_engine.decision_service import DecisionService, compare_context
from .annotation_packets import prepare_development
from .corpus import DATA, canonical, digest, instant, local_file, visible_inputs
from .observations import AUTHOR, DIMENSIONS, compare, validate, value
from .production import execute
from .solo import ROOT, runtime_inputs

TRANSCRIPTIONS = Path(__file__).with_name('development_observations.json')


def development_inputs() -> tuple[dict, list[dict]]:
    """Read frozen source-only development bytes, never labels/evaluation files."""
    sources, cases = {}, []
    root = DATA / 'controls-v2'
    freeze = json.loads((root / 'freeze.json').read_bytes())
    if digest(canonical(freeze['files'])) != freeze['sha256']:
        raise ValueError('Invalid control freeze')
    raw = (root / 'inputs.json').read_bytes()
    if digest(raw) != freeze['files']['inputs.json']:
        raise ValueError('Control metadata changed')
    metadata = json.loads(raw)
    for event in metadata['events']:
        if event['split'] != 'development':
            continue
        ids = []
        for source in metadata['sources']:
            if source['split'] != 'development' or instant(source['available_at']) > instant(event['at']):
                continue
            raw = local_file(root, source['file']).read_bytes()
            if digest(raw) != freeze['files'][source['file']]:
                raise ValueError('Control source changed')
            key = 'controls-v2/' + source['id']
            sources[key] = dict(id=key, runtime_id=source['id'], text=raw.decode(),
                available_at=source['available_at'], origin=dict(bundle='controls-v2', **source))
            ids.append(key)
        cases.append(dict(id='controls-v2/' + event['id'], event=event, source_ids=ids,
                          runtime=visible_inputs(metadata, event, root)))
    packet, _ = prepare_development()
    for case in packet['cases']:
        ids = []
        for source in case['sources']:
            key = 'project-v1/' + source['id']
            sources[key] = dict(id=key, runtime_id=source['id'], text=source['text'],
                available_at=source['available_at'], origin=dict(bundle='project-v1', **{
                    k: v for k, v in source.items() if k not in ('text', 'license_text')}))
            ids.append(key)
        runtime, event = runtime_inputs(case)
        cases.append(dict(id='project-v1/' + case['id'], event=event, source_ids=ids, runtime=runtime))
    return sources, cases


def _capture(path: Path, sources: list[dict], rows: dict) -> dict:
    """Use public proposals; every profile/evidence stays proposed/unassessed."""
    brain = Brain(str(path), mode='git')
    brain.init()
    service = DecisionService(brain)
    references, chunks = {}, {}

    def publish(drafts: list[dict]) -> list[dict]:
        refs = []
        for start in range(0, len(drafts), 200):
            refs.extend(_submit(service, 'versions', drafts[start:start + 200])['refs'])
        return refs

    drafts, order = [], []
    for source in sources:
        roots = sorted({value(f['measurement_lineage']) for f in rows[source['id']]['facts']
                        if f['measurement_lineage']})
        for index, start in enumerate(range(0, len(source['text']), 800)):
            text = source['text'][start:start + 800]
            node_id = f"{source['runtime_id']}-c{index:03}"
            brain.write_node(Node(text, id=node_id))
            payload = service.source(node_id)
            payload.update(lineage_ids=roots, artifact=dict(sha256=digest(source['text'].encode()),
                locator='known-development:' + source['id'], media_type='text/plain',
                extraction=json.dumps(source['origin'], sort_keys=True)))
            drafts.append(_draft('source', payload, anchor=node_id))
            order.append((source['id'], start, text, payload['text']))
    for item, ref in zip(order, publish(drafts)):
        chunks.setdefault(item[0], []).append((*item[1:], ref))
    profile = publish([_draft('profile', dict(name='Unreviewed development observation dimensions', version='1',
        dimensions={name: dict(type='id', unit=None, required=True, compare='equal', allowed_values=None)
                    for name in DIMENSIONS}, interventions=[]))])[0]
    drafts, fact_ids = [], []
    for source in sources:
        for fact in rows[source['id']]['facts']:
            # Every supplied atomic field has its own exact stored-source quote.
            bindings = [fact['subject'], fact['measurement_lineage'], fact['observed_at'], fact['availability'],
                        *fact['conditions'].values(), *(fact['metric'] or {}).values()]
            citations, seen = [], set()
            for b in bindings:
                if b is None:
                    continue
                for start, raw, stored, ref in chunks[source['id']]:
                    lo, hi = max(b['start'], start), min(b['end'], start + len(raw))
                    if lo >= hi:
                        continue
                    quote = source['text'][lo:hi]
                    # Keep exact quotes in the public stored-node coordinates.
                    # Decision Memory pins the exact node body, unlike Node's
                    # display parser. Never trim indentation or normalize CRLF.
                    at = lo - start
                    if at < 0 or stored[at:at + len(quote)] != quote:
                        raise ValueError('Quote cannot be pinned to stored source without transformation')
                    key = (ref['id'], ref['version_id'], at, quote)
                    if key not in seen:
                        citations.append(dict(ref=ref, passage=dict(start=at, end=at + len(quote), quote=quote)))
                        seen.add(key)
            if not citations:
                raise ValueError('A proposed fact requires a literal source binding')
            metric = {k: value(v) for k, v in fact['metric'].items()} if fact['metric'] else None
            interpretation = dict(kind=fact['kind'], subject=value(fact['subject']), metric=metric,
                observed_at=value(fact['observed_at']), availability=value(fact['availability']),
                source_measurement_root=value(fact['measurement_lineage']), review='pending', independence='not inferred')
            draft = _draft('evidence', dict(interpretation=json.dumps(interpretation, sort_keys=True),
                context=dict(schema='dm.context/1', profile=profile, dimensions={
                    k: dict(type='id', value=value(v)) if v else dict(type='unknown', reason='Not transcribed from source')
                    for k, v in fact['conditions'].items()}, notes='Unreviewed source transcription; no semantic acceptance.'),
                sources=citations, lineage_ids=[], limitations=[
                    'Implementing-agent transcription, not independent review or complete semantic extraction.',
                    *fact['limitations']]))
            draft['provenance']['inputs'] = list({(c['ref']['id'], c['ref']['version_id']): c['ref'] for c in citations}.values())
            drafts.append(draft)
            fact_ids.append(dict(source_id=source['id'], fact_id=fact['id']))
    evidence = publish(drafts)
    for item, ref in zip(fact_ids, evidence):
        references.setdefault(item['source_id'], []).append(dict(fact_id=item['fact_id'], ref=ref))
    revision = _commit(service)
    inspected = [service.inspect(ref) for ref in [profile, *evidence]]
    if any(item['state']['workflow'] != 'proposed' or item['events'] for item in inspected):
        raise ValueError('Observation capture must never manufacture a review')
    context = inspected[1]['record']['payload']['context'] if evidence else None
    view = RecordView(brain, read_file(brain))
    official = compare_context(context, context, view)
    # Keep the complete immutable source records as well as their references.
    # Temporary test brains disappear; the journal must still permit exact
    # source-version/hash and citation verification without trusting a rerun.
    source_records = [view.get(item[-1])['record'] for items in chunks.values() for item in items]
    return dict(revision=revision, profile=profile, evidence=references,
        proposed_profiles=1, proposed_evidence=len(evidence), review_events=0,
        official_comparability=official,
        independence='not inferred', inspected=inspected, source_records=source_records)


def run(output: Path, *, capture: bool = False) -> dict:
    sources, cases = development_inputs()
    packet = json.loads(TRANSCRIPTIONS.read_bytes())
    validate(packet, sources)
    if output.resolve().is_relative_to(DATA.resolve()):
        raise ValueError('Output must be outside preserved corpus data')
    output.mkdir(parents=True, exist_ok=False)
    rows = {row['source_id']: row for row in packet['sources']}
    report = dict(schema='dm.structured-development/1', source_commit=subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), dirty=bool(subprocess.check_output(
        ['git', 'status', '--porcelain'], cwd=ROOT)), transcriptions_sha256=digest(TRANSCRIPTIONS.read_bytes()),
        status='running', capture_requested=capture, results=[], independent_acceptance=False,
        independent_final_coverage=dict(positive=0, negative=0, inconclusive=0), release_ready=False,
        human_review=None, semantic_quality=None, provider_calls=0, limitations=[
            'Source/value binding and structural comparison do not independently validate semantic role or completeness.',
            'All transcriptions, profiles and evidence are unreviewed implementing-agent proposals.',
            'Original runtime alerts remain unchanged; no self-authored structural outcome is scored as gold.'])
    paths = [*ROOT.glob('graph_engine/**/*.py'), *ROOT.glob('graph_engine/web/*.js'),
             *ROOT.glob('tools/decision_benchmark/*.py'), *ROOT.glob('examples/*.py'), TRANSCRIPTIONS]
    report['code_manifest'] = {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(paths)}
    report['code_sha256'] = digest(canonical(report['code_manifest']))
    report['source_manifest'] = {key: dict(text_sha256=digest(source['text'].encode()),
        available_at=source['available_at'], origin=source['origin']) for key,source in sources.items()}
    report['license_notices'] = {}
    for bundle, path in (('controls-v2', ROOT / 'LICENSE'), ('project-v1', DATA / 'project-v1' / 'LICENSE')):
        raw = path.read_bytes()
        name = bundle + '-LICENSE.txt'
        (output / name).write_bytes(raw)
        report['license_notices'][bundle] = dict(path=name, sha256=digest(raw))
    (output / 'transcriptions.json').write_bytes(TRANSCRIPTIONS.read_bytes())
    with tempfile.TemporaryDirectory(prefix='dm-structured-development-') as temp:
        for case in cases:
            bundle = case['id'].split('/')[0]
            old = rows[bundle + '/' + case['event']['changed_source_id']]
            new = rows[bundle + '/' + case['event']['source_id']]
            row = dict(case_id=case['id'], source_input_sha256=digest(canonical(case['runtime'])),
                eligible_pairs=len(case['runtime']['decisions']), comparison=compare(old, new),
                untranscribed_source_ids=[key for key in case['source_ids'] if not rows[key]['facts']], profiles={})
            if capture:
                for mode in ('curated', 'proposed'):
                    trace: dict = {}
                    try:
                        trace = execute(deepcopy(case['runtime']), case['event'], Path(temp) / case['id'] / mode,
                                        mode, budget=4000, k=5, trace=trace)
                        trace['error'] = None
                    except Exception as exc:
                        trace['error'] = dict(type=type(exc).__name__, message=str(exc))
                    row['profiles'][mode] = trace
                try:
                    row['capture'] = _capture(Path(temp) / case['id'] / 'observations',
                                             [sources[key] for key in case['source_ids']], rows)
                    row['capture_error'] = None
                except Exception as exc:
                    row['capture_error'] = dict(type=type(exc).__name__, message=str(exc))
            report['results'].append(row)
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    report['status'] = 'completed_with_errors' if capture and any(
        row['capture_error'] or any(p.get('error') or not p.get('complete') or not p.get('context_within_budget')
                                   for p in row['profiles'].values()) for row in report['results']) else 'complete'
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New output directory')
    parser.add_argument('--capture', action='store_true', help='Exercise public proposals and unchanged production diagnostics')
    args = parser.parse_args()
    report = run(args.output, capture=args.capture)
    print(json.dumps(dict(status=report['status'], cases=len(report['results']), independent_acceptance=False)))
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

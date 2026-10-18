"""Replay only known development inputs with explicit developer field reviews."""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import tempfile

from graph_engine import decision_schema as s
from .corpus import DATA, canonical, digest
from .observations import validate, value
from .json_source_fields import spans
from .production import execute
from .reviewed_observations import AUTHOR
from .solo import ROOT
from .structured_development import development_inputs, TRANSCRIPTIONS

REVIEWS = Path(__file__).with_name('development_field_reviews.json')


def review_inputs(sources: dict, packet: dict, inventory: dict) -> dict:
    validate(packet, sources)
    s.fields(inventory, {'schema', 'author', 'sources'})
    s.need(inventory['schema'] == 'dm.development.field-review-inventory/1'
           and inventory['author'] == AUTHOR)
    rows = {r['source_id']: r for r in packet['sources']}
    reviews = {}
    for row in inventory['sources']:
        key = row['observations']['source_id']
        s.need(key in sources and key not in reviews)
        s.need(row['runtime_source_id'] == sources[key]['runtime_id'])
        s.need(row['observations'] == rows[key], 'Reviewed transcription differs from preserved proposal')
        s.need(row['text_sha256'] == digest(sources[key]['text'].encode()))
        s.need(row['facts_sha256'] == digest(canonical(rows[key]['facts'])))
        reviews[key] = row
    return reviews


def check_report_fields(source: dict, row: dict) -> list[dict]:
    """Check the known JSON report by paths, without supplying missing units.

    A code-manifest digest identifies code, never a measurement root. There is
    no runtime review for this incomplete report, nor for its untranscribed
    update sources. Decimal parsing preserves the stored precision exactly.
    """
    document = json.loads(source['text'], parse_float=Decimal)
    positions, keys = spans(source['text'])
    checked = []
    for fact in row['facts']:
        section, index, adapter, metric, field = fact['id'].split('/')
        s.need(section == 'measurements' and field == 'mean')
        measurement = document[section][int(index)]
        result = measurement['adapters'][adapter][metric]
        s.need(value(fact['subject']) == adapter and value(fact['metric']['name']) == metric)
        s.need(result['mean'] is not None and result['n'] > 0)
        s.need(Decimal(value(fact['metric']['value'])) == Decimal(str(result['mean'])))
        s.need(Decimal(value(fact['metric']['sample_count'])) == result['n'])
        conditions = fact['conditions']
        s.need(value(conditions['workload']) == measurement['dataset_version'])
        s.need(value(conditions['corpus']) == measurement['dataset_sha256'])
        s.need(value(conditions['code']) == document['source']['code_sha256'])
        s.need(value(conditions['protocol']) == document['method'])
        s.need(fact['metric']['unit'] is None and conditions['environment'] is None
               and fact['measurement_lineage'] is None)
        base = ('measurements', int(index))
        adapter_path = base + ('adapters', adapter)
        metric_path = adapter_path + (metric,)
        bindings = [(fact['subject'], keys[adapter_path]),
                    (fact['metric']['name'], keys[metric_path]),
                    (fact['metric']['value'], positions[metric_path + ('mean',)]),
                    (fact['metric']['sample_count'], positions[metric_path + ('n',)]),
                    (conditions['workload'], positions[base + ('dataset_version',)]),
                    (conditions['corpus'], positions[base + ('dataset_sha256',)]),
                    (conditions['code'], positions[('source', 'code_sha256')]),
                    (conditions['protocol'], positions[('method',)])]
        for binding, span in bindings:
            s.need((binding['start'], binding['end']) == span, 'Binding points to a different JSON field')
        checked.append(dict(path=f"/measurements/{index}/adapters/{adapter}/{metric}/mean",
                            value=value(fact['metric']['value']), n=result['n'],
                            unit=None, environment=None, measurement_root=None))
    return checked


def run(output: Path) -> dict:
    sources, cases = development_inputs()
    packet = json.loads(TRANSCRIPTIONS.read_bytes())
    inventory = json.loads(REVIEWS.read_bytes())
    reviews = review_inputs(sources, packet, inventory)
    rows = {r['source_id']: r for r in packet['sources']}
    checked = check_report_fields(sources['project-v1/graph-report'], rows['project-v1/graph-report'])
    if output.resolve().is_relative_to(DATA.resolve()):
        raise ValueError('Output must be outside frozen data')
    output.mkdir(parents=True, exist_ok=False)
    paths = [*ROOT.glob('graph_engine/**/*.py'), *ROOT.glob('tools/decision_benchmark/*.py'),
             *ROOT.glob('tools/decision_benchmark/*.json'), *ROOT.glob('examples/*.py')]
    report = dict(schema='dm.reviewed-development/1', source_commit=subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
        code_manifest={str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(paths)},
        author=AUTHOR, report_field_checks=checked, results=[], status='running',
        independent_acceptance=False, independent_final_coverage=dict(positive=0, negative=0, inconclusive=0),
        semantic_scores=None, human_review=None, user_sessions=None, release_ready=False,
        provider_calls=0, review_sha256=digest(REVIEWS.read_bytes()),
        transcriptions_sha256=digest(TRANSCRIPTIONS.read_bytes()),
        source_manifest={key: dict(text_sha256=digest(source['text'].encode()),
                                  available_at=source['available_at'], origin=source['origin'])
                         for key, source in sources.items()},
        limitations=['Trusted developer field/completeness review, not automatic semantic extraction.',
                     'Known development replay only; no independent scores or product-benefit measurement.',
                     'No unit conversion, inferred measurement independence or support-sufficiency judgment.'])
    report['code_sha256'] = digest(canonical(report['code_manifest']))
    (output / 'field-reviews.json').write_bytes(REVIEWS.read_bytes())
    with tempfile.TemporaryDirectory(prefix='dm-reviewed-development-') as temp:
        for case in cases:
            prefix = case['id'].split('/')[0] + '/'
            keys = [prefix + case['event'][k] for k in ('changed_source_id', 'source_id')]
            review = dict(schema='dm.development.field-review/1', author=AUTHOR,
                          sources=[reviews[k] for k in keys]) if all(k in reviews for k in keys) else None
            row = dict(case_id=case['id'], source_input_sha256=digest(canonical(case['runtime'])),
                       eligible_pairs=len(case['runtime']['decisions']), review=review, profiles={})
            for mode in ('curated', 'proposed'):
                trace: dict = {}
                try:
                    trace = execute(deepcopy(case['runtime']), case['event'], Path(temp) / case['id'] / mode,
                                    mode, budget=4000, k=5, trace=trace, observation_review=review)
                    trace['error'] = None
                except Exception as exc:
                    trace['error'] = dict(type=type(exc).__name__, message=str(exc))
                row['profiles'][mode] = trace
            report['results'].append(row)
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    report['status'] = 'complete' if all(not p.get('error') and p.get('complete') and p.get('context_within_budget')
        for row in report['results'] for p in row['profiles'].values()) else 'completed_with_errors'
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    report = run(parser.parse_args().output)
    print(json.dumps(dict(status=report['status'], cases=len(report['results']), independent_acceptance=False)))
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

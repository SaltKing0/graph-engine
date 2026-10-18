"""Read-only source review of the recorded Y1 basis, never independent gold.

Only known development sources and the existing version journal are read. No
DecisionService write/review, decision activation, comparison resolution, label
reader, arbitrary source option or provider call is supplied by this audit.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from decimal import Decimal
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Iterator
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
from graph_engine import decision_schema as s
from tools.decision_benchmark.corpus import DATA, canonical, digest
from tools.decision_benchmark.observations import value
from tools.decision_benchmark.support_paths import prepare

BASE = '75b319445d8976ce3f74c7875f686e12cb8eba85'
PRIOR = HERE.parent / 'support-paths-v1'
ARCHIVE = PRIOR / 'support-paths-report.json.gz'


@contextmanager
def development_reads() -> Iterator[None]:
    """Reject known label/evaluation-source paths during the actual review."""
    forbidden = set()
    for bundle in ('controls-v2', 'project-v1'):
        root = DATA / bundle
        metadata = json.loads((root / 'inputs.json').read_bytes())
        forbidden.add((root / 'labels.json').resolve())
        forbidden.update((root / source['file']).resolve() for source in metadata['sources']
                         if source['split'] == 'evaluation')
    raw, text = Path.read_bytes, Path.read_text

    def guarded_bytes(path: Path) -> bytes:
        assert path.resolve() not in forbidden, 'Forbidden label/evaluation read'
        return raw(path)

    def guarded_text(path: Path, *args, **kwargs) -> str:
        assert path.resolve() not in forbidden, 'Forbidden label/evaluation read'
        return text(path, *args, **kwargs)

    with patch.object(Path, 'read_bytes', guarded_bytes), patch.object(Path, 'read_text', guarded_text):
        yield


def examine() -> dict:
    """Recompute source conclusions; read the exact existing reviews unchanged."""
    with development_reads():
        sources, case, packet = prepare()
        prior_bytes = ARCHIVE.read_bytes()
        prior = json.loads(gzip.decompress(prior_bytes))
        spec = importlib.util.spec_from_file_location('recorded_support_path_checks', PRIOR / 'verify.py')
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        # Validate pinned sources/content/events, not the old verifier's original
        # Git scope assertion: this new sibling audit is deliberately additional.
        validator.validate_report(prior)
        result = prior['result']
        refs, final = result['references'], result['final']
        records = {s.key(v): v for v in final['journal']['versions']}
        rule, remaining, withdrawn, update = (packet[k] for k in ('rule', 'remaining', 'withdrawn', 'update'))
        basis_source, update_source = rule['source_id'], update['source_id']
        assert set(packet['sources']) == {basis_source, update_source}
        assert all(sources[k]['origin']['split'] == 'development' for k in packet['sources'])
        assert case['id'] == 'controls-v2/event-surviving-support'

        def cite(source_id: str, binding: dict) -> dict:
            text = sources[source_id]['text']
            assert text[binding['start']:binding['end']] == binding['quote']
            return dict(source_id=source_id, start=binding['start'], end=binding['end'], quote=binding['quote'])

        conditions = {name: value(binding) for name, binding in remaining['conditions'].items()}
        assert final['claim']['record']['payload']['context']['dimensions'] == {
            k: dict(type='id', value=v) for k, v in conditions.items()}
        assert final['decision']['record']['payload']['context'] == final['claim']['record']['payload']['context']
        y1 = records[s.key(refs['evidence']['Y1'])]
        assert json.loads(y1['payload']['interpretation'])['subject'] == value(remaining['subject']) == 'Y1'
        assert final['claim']['record']['provenance']['inputs'] == [refs['evidence']['Y1'], refs['sources'][update_source]]
        assert refs['evidence']['X1'] not in s.content_refs(final['claim']['record'])
        assert final['claim']['record']['payload']['limitations'] == y1['payload']['limitations']
        for dimension, binding in remaining['conditions'].items():
            expected = cite(basis_source, binding)
            assert dict(ref=refs['sources'][basis_source], passage={
                k: expected[k] for k in ('start', 'end', 'quote')}) in y1['payload']['sources']
        assert value(rule['metric']) == value(remaining['metric']) == 'recall'
        numeric = Decimal(value(remaining['value'])) >= Decimal(value(rule['threshold']))
        assert numeric and value(rule['operator']) == '>='
        assert value(rule['unit']) == 'fraction' and remaining['unit_from_rule'] is True
        assert value(remaining['conditions_reference']) == 'under the same conditions'
        assert value(update['withdrawn_subject']) == 'X1' and value(update['withdrawal']) == 'withdrawn'
        assert value(update['remaining_subject']) == 'Y1' and value(update['remaining_availability']) == 'available'
        assert result['initial']['claim']['record'] == final['old_claim']['record']
        assert result['initial']['claim']['events'] == final['old_claim']['events']
        assert final['decision']['state']['decision'] == 'proposed' and final['decision']['events'] == []
        assert final['dependency']['state']['workflow'] == 'proposed' and final['dependency']['events'] == []
        assert final['old_decision']['state']['decision_conclusion'] == 'needs_investigation'
        assert final['finding']['state']['finding_workflow'] == 'acknowledged' and final['finding']['basis_changed']
        assert final['claim']['effective_assessment'] == 'supported' and not final['claim']['basis_changed']
        removed, available = (result['comparison']['candidates'][0]['support'][k][0]
                              for k in ('removed', 'remaining'))
        assert removed['sources'] == available['sources'] and removed['lineage_ids'] == available['lineage_ids']
        assert y1['payload']['lineage_ids'] == []
        return dict(schema='dm.development.y1-source-review/1',
            author=dict(role='implementing-agent', human=False, independent=False),
            review_kind='source-consistency analysis; not independent annotation or acceptance',
            reviewed_snapshot_commit=BASE, case_id=case['id'],
            temporal_scope=dict(event_at=case['event']['at'],
                limitation='Availability is declared at this fictional event, not verified for real-world use today.'),
            source_manifest=packet['sources'],
            recorded_report_sha256=digest(prior_bytes),
            reviewed_references={k: refs[k] for k in ('claim', 'support', 'decision', 'dependency', 'finding')},
            preserved_journal=dict(versions=len(final['journal']['versions']), events=len(final['journal']['events']),
                versions_sha256=digest(canonical(final['journal']['versions'])),
                events_sha256=digest(canonical(final['journal']['events']))),
            findings=[
                dict(id='rule', status='direct_source_statement',
                    conclusion='The declared fictional action rule is mode A when recall >=0.7 fraction.',
                    citations=[cite(basis_source, rule['statement'])]),
                dict(id='measurement', status='direct_source_statement',
                    metric=value(remaining['metric']), value=value(remaining['value']),
                    conclusion='0.8 belongs to Y1, not the withdrawn X1 measurement.',
                    citations=[cite(basis_source, remaining[k]) for k in ('statement', 'subject', 'metric', 'value')]),
                dict(id='unit', status='explicit_interpretation', unit=value(rule['unit']),
                    conclusion='Fraction is resolved from the same declared recall rule. Y1 has no separately written unit; no conversion or outside recall convention is used.',
                    citations=[cite(basis_source, rule['unit']), cite(basis_source, rule['metric']),
                               cite(basis_source, remaining['metric'])]),
                dict(id='conditions', status='explicit_interpretation', dimensions=conditions,
                    conclusion='The explicit same-conditions reference resolves to the preceding X1 conditions. Their source fields are retained; X1 availability withdrawal is not a blanket retraction of this document or of those fields.',
                    citations=[cite(basis_source, remaining['conditions_reference']),
                               cite(basis_source, remaining['conditions_referent']),
                               *[cite(basis_source, b) for b in remaining['conditions'].values()]]),
                dict(id='availability', status='direct_source_statement',
                    conclusion='The update withdraws X1 support and separately leaves Y1 available; it does not withdraw Y1.',
                    citations=[cite(update_source, update[k]) for k in ('withdrawal_statement', 'availability_statement')]),
                dict(id='lineage', status='not_independently_established',
                    recorded_run_labels=[value(withdrawn['measurement_root']), value(remaining['measurement_root'])],
                    shared_document_roots=available['lineage_ids'],
                    conclusion='Distinct run labels and the source assertion of a separate run do not supply reviewed execution/dataset artifacts. Separate paths are not independent votes.',
                    citations=[cite(basis_source, withdrawn['measurement_root']),
                               cite(basis_source, remaining['measurement_root']),
                               cite(update_source, update['separate_run_statement'])]),
                dict(id='sufficiency', status='conditional_source_consistency',
                    numerical_predicate=dict(value=value(remaining['value']), operator=value(rule['operator']),
                        threshold=value(rule['threshold']), unit=value(rule['unit']), met=numeric),
                    conclusion='Y1 suffices for the sole rule stated in this fictional source under the documented unit/context interpretation. No run-count/statistical threshold is invented. Real measurement validity, statistical sufficiency and general decision sufficiency remain unknown.',
                    citations=[cite(basis_source, rule['statement']), cite(basis_source, remaining['statement'])]),
                dict(id='review_and_lifecycle', status='preserved_and_open',
                    conclusion='The source-qualified claim is consistent with its limitations and existing scripted reviews. No correction/new basis version is required by these sources. Existing reviews are untouched; the decision/dependency remain proposed, the old decision needs investigation, and the stale finding remains unresolved.',
                    citations=[]),
            ],
            conclusion='consistent_with_the_declared_fictional_rule_only',
            code_or_basis_correction_required=False, new_engine_events=0,
            independent_acceptance=False, independently_reviewed_measurement_independence=None,
            statistical_sufficiency=None, general_decision_sufficiency=None,
            semantic_scores=None, human_review=None, user_sessions=None, product_benefit=None,
            independent_final_coverage=dict(positive=0, negative=0, inconclusive=0),
            release_ready=False, provider_calls=0,
            open_requirements=['Actual execution/dataset artifacts and qualified separate review before independent-run credit.',
                'Independent final annotation/adjudication, protected corpus/freeze and final-candidate sign-off.',
                'Actual controlled user sessions before any benefit or review-time claim.',
                'A fresh comparison and explicit authorized review before resolving the stale finding or activating a successor.'])


def verify() -> None:
    expected = json.loads((HERE / 'review.json').read_bytes())
    assert expected == examine(), 'Source review or preserved journal changed'
    manifest = json.loads((HERE / 'manifest.json').read_bytes())
    files = {str(p.relative_to(HERE)) for p in HERE.rglob('*') if p.is_file()
             and p.name != 'manifest.json' and '__pycache__' not in p.parts}
    assert set(manifest['files']) == files
    for name, sha in manifest['files'].items():
        assert digest((HERE / name).read_bytes()) == sha, name
    assert not subprocess.check_output(['git', 'diff', BASE, '--', 'graph_engine', 'tools', 'tests',
                                        'examples', '.github', 'pyproject.toml', 'CONTRIBUTING.md'], cwd=ROOT)
    changes = subprocess.check_output(['git', 'diff', '--name-only', BASE, '--',
        'docs/decision-evaluation-results'], cwd=ROOT, text=True).splitlines()
    assert all(n.startswith('docs/decision-evaluation-results/false-alert-development-v1/y1-basis-review-v1/') for n in changes)
    print('Y1 source review consistent: 0.8 >=0.7 fraction under explicitly shared conditions; declared available.')
    print('Exact prior 15 versions / 16 events preserved. No new engine review, activation or independent acceptance.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, help='New review JSON path outside frozen data; never a runtime input')
    args = parser.parse_args()
    if args.capture:
        if args.capture.resolve().is_relative_to(DATA.resolve()):
            parser.error('Keep the review outside frozen data')
        result = examine()
        with args.capture.open('x') as stream:
            stream.write(json.dumps(result, indent=2) + '\n')
        print('Captured source-consistency review; existing journal is read-only.')
    else:
        verify()


if __name__ == '__main__':
    main()

"""Explicit developer field review for a bounded source-change diagnostic.

These are trusted, versioned interpretation inputs, not an automatic prose
extractor or independent annotations. Unknown or incomplete inputs retain the
original changed-basis path. No emitted alert is filtered after impact analysis.
"""
from __future__ import annotations

from decimal import Decimal

from graph_engine import decision_schema as s
from .corpus import canonical, digest
from .observations import compare_conditions, validate_source, value

AUTHOR = dict(role='implementing-agent', human=False, independent=False,
              review='field-mapping-checked')


def assess(review: dict | None, update: dict, *, available_at: str) -> dict:
    """Retain a basis only when every reviewed update fact is immaterial.

    The caller must supply an explicit field/completeness review. Hashes bind
    that review to both complete chronological task sources and the exact
    interpreted facts. They do not prove semantic correctness or independence.
    """
    result = dict(schema='dm.reviewed-source-assessment/1', retain_basis=False,
                  author=None, independent_acceptance=False, facts=[],
                  reason='No complete developer field review')
    if review is None:
        return result
    s.fields(review, {'schema', 'author', 'sources'})
    s.need(review['schema'] == 'dm.development.field-review/1' and review['author'] == AUTHOR)
    s.need(all(type(review['author'][k]) is bool for k in ('human', 'independent')))
    result['author'] = review['author']
    s.need(isinstance(review['sources'], list) and len(review['sources']) == 2)
    indexed = {}
    for row in review['sources']:
        s.fields(row, {'runtime_source_id', 'namespace', 'text_sha256', 'facts_sha256',
                       'complete', 'roles', 'observations'})
        s.string(row['namespace'])
        s.strings(row['roles'])
        s.need(bool(row['roles']) and type(row['complete']) is bool)
        s.need(row['runtime_source_id'] not in indexed)
        indexed[row['runtime_source_id']] = row
    s.need(set(indexed) == {update['old']['source_id'], update['new']['source_id']})
    ordered = []
    for side in ('old', 'new'):
        source = update[side]
        row = indexed[source['source_id']]
        s.need(source['well_formed_task_chunks'] and source['text_sha256'] == row['text_sha256'],
               'Review does not bind the complete task source')
        # The executor supplies complete text privately for literal validation.
        observation = row['observations']
        validate_source(observation, dict(id=observation['source_id'], text=source['text'],
                                         available_at=available_at))
        s.need(observation['text_sha256'] == row['text_sha256'])
        s.need(digest(canonical(observation['facts'])) == row['facts_sha256'], 'Reviewed facts changed')
        ordered.append(row)
    old, new = ordered
    result['review_sha256'] = digest(canonical(review))
    if not old['complete'] or not new['complete'] or old['namespace'] != new['namespace']:
        return result
    basis = old['observations']['facts']
    incoming = new['observations']['facts']
    if not basis or not incoming:
        return result
    for fact in incoming:
        status = 'unknown'
        pairs = []
        if fact['kind'] == 'measurement':
            matching = [f for f in basis if f['kind'] == 'measurement'
                        and value(f['metric']['name']) == value(fact['metric']['name'])]
            statuses = []
            for prior in matching:
                conditions = compare_conditions(prior['conditions'], fact['conditions'])
                a, b = prior['metric'], fact['metric']
                units = value(a['unit']), value(b['unit'])
                # Even a scoped negative comparison requires a reviewed metric
                # and explicit, equal units; no inferred conversions/defaults.
                pair = 'unknown'
                if None not in units and units[0] == units[1]:
                    if conditions['status'] == 'disjoint':
                        pair = 'different_conditions'
                    elif conditions['status'] == 'same_declared_conditions':
                        same = Decimal(value(a['value'])) == Decimal(value(b['value']))
                        same_n = value(a['sample_count']) == value(b['sample_count'])
                        pair = 'same_value' if same and same_n else 'changed_value_or_sample'
                statuses.append(pair)
                pairs.append(dict(old_fact=prior['id'], status=pair, conditions=conditions,
                                  old_unit=units[0], new_unit=units[1]))
            # All applicable old observations must be accounted for. Missing
            # fields on another basis cannot be hidden by one favorable match.
            if statuses and all(x in ('different_conditions', 'same_value') for x in statuses):
                status = 'same_value' if 'same_value' in statuses else 'different_conditions'
            elif 'changed_value_or_sample' in statuses:
                status = 'changed_value_or_sample'
        elif fact['kind'] == 'citation':
            root = value(fact['measurement_lineage'])
            if root and any(f['kind'] == 'measurement'
                            and value(f['measurement_lineage']) == root
                            and value(f['subject']) == value(fact['subject']) for f in basis):
                status = 'same_recorded_measurement'
        # Availability changes always retain review: surviving support is not
        # proof of sufficient support, nor proof that two runs are independent.
        result['facts'].append(dict(fact_id=fact['id'], status=status, comparisons=pairs))
    result['retain_basis'] = all(f['status'] in ('same_value', 'different_conditions',
                                              'same_recorded_measurement') for f in result['facts'])
    result['reason'] = ('Complete reviewed update adds no change to the recorded basis'
                        if result['retain_basis'] else 'Changed or insufficiently established basis')
    return result

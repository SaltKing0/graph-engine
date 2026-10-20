"""Validate source transcriptions and compare their declared fields, never gold.

Structural consistency is not independent semantic review. In particular these
helpers never accept a proposal, withdraw support or suppress a runtime alert.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re

from graph_engine import decision_schema as s
from .corpus import digest

DIMENSIONS = ('workload', 'environment', 'code', 'corpus', 'protocol')
AUTHOR = dict(role='implementing-agent', human=False, independent=False, review='pending')


def binding(text: str, raw: str, *, start: int = 0, kind: str = 'id') -> dict:
    """Authoring helper: retain the exact selected lexeme and its position."""
    offset = text.index(raw, start)
    value = raw
    if kind == 'decimal':
        value = format(Decimal(raw), 'f').rstrip('0').rstrip('.') if '.' in raw else raw
        value = '0' if Decimal(raw) == 0 else value
    return dict(type=kind, value=value, start=offset, end=offset + len(raw), quote=raw)


def validate_binding(item: dict | None, text: str) -> None:
    if item is None:
        return
    s.fields(item, {'type', 'value', 'start', 'end', 'quote'})
    s.need(type(item['start']) is int and type(item['end']) is int)
    s.need(0 <= item['start'] < item['end'] <= len(text))
    s.need(text[item['start']:item['end']] == item['quote'], 'Exact source lexeme changed')
    s.string(item['value'])
    if item['type'] == 'decimal':
        s.decimal(item['value'])
        s.need(bool(re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', item['quote'])))
        try:
            s.need(Decimal(item['value']) == Decimal(item['quote']), 'Numeric value differs from source')
        except InvalidOperation as exc:
            raise ValueError('Invalid source decimal') from exc
    else:
        s.need(item['type'] in ('id', 'date') and item['value'] == item['quote'])
        if item['type'] == 'date':
            s.need(date.fromisoformat(item['value']).isoformat() == item['value'])


def validate_source(row: dict, source: dict) -> None:
    s.fields(row, {'source_id', 'text_sha256', 'facts'})
    s.need(row['source_id'] == source['id'] and row['text_sha256'] == digest(source['text'].encode()))
    s.sequence(row['facts'])
    seen = set()
    for fact in row['facts']:
        s.fields(fact, {'id', 'kind', 'subject', 'metric', 'conditions', 'measurement_lineage',
                        'observed_at', 'availability', 'limitations'})
        s.string(fact['id'])
        s.need(fact['id'] not in seen and fact['kind'] in ('measurement', 'citation', 'availability'))
        seen.add(fact['id'])
        s.need(fact['subject'] is not None, 'Fact requires a source-bound subject')
        s.need(set(fact['conditions']) == set(DIMENSIONS))
        values = [fact['subject'], fact['measurement_lineage'], fact['observed_at'], fact['availability'],
                  *fact['conditions'].values()]
        if fact['metric'] is not None:
            s.fields(fact['metric'], {'name', 'value', 'unit', 'sample_count'})
            s.need(fact['kind'] == 'measurement')
            values.extend(fact['metric'].values())
            s.need(fact['metric']['name'] is not None and fact['metric']['value'] is not None)
            s.need(fact['metric']['value']['type'] == 'decimal')
            s.need(fact['metric']['name']['type'] == 'id')
            if fact['metric']['unit'] is not None:
                s.need(fact['metric']['unit']['type'] == 'id')
            if fact['metric']['sample_count'] is not None:
                sample = fact['metric']['sample_count']
                s.need(sample['type'] == 'decimal' and Decimal(sample['value']) >= 0
                       and Decimal(sample['value']) == Decimal(sample['value']).to_integral_value())
        else:
            s.need(fact['kind'] != 'measurement')
        for value in values:
            validate_binding(value, source['text'])
        s.need(all(v is None or v['type'] == 'id' for v in
                   [fact['subject'], fact['measurement_lineage'], fact['availability'], *fact['conditions'].values()]))
        if fact['observed_at'] is not None:
            s.need(fact['observed_at']['type'] == 'date')
            s.need(fact['observed_at']['value'] <= source['available_at'][:10], 'Future observation')
        if fact['availability'] is not None:
            s.need(fact['availability']['value'] in ('available', 'withdrawn'))
        s.need((fact['kind'] == 'availability') == (fact['availability'] is not None))
        s.strings(fact['limitations'])


def validate(packet: dict, sources: dict[str, dict]) -> None:
    s.fields(packet, {'schema', 'author', 'exposure', 'sources'})
    s.need(packet['schema'] == 'dm.development.observations/1')
    s.need(packet['author'] == AUTHOR and packet['exposure'] == 'previously-exposed-development-only')
    s.need(type(packet['author']['human']) is bool and type(packet['author']['independent']) is bool)
    rows = packet['sources']
    s.need(isinstance(rows, list) and len(rows) == len(sources))
    s.need(len({row['source_id'] for row in rows}) == len(rows))
    s.need({row['source_id'] for row in rows} == set(sources), 'Source inventory omitted or invented')
    for row in rows:
        validate_source(row, sources[row['source_id']])


def value(item: dict | None) -> str | None:
    return item['value'] if item is not None else None


def compare_conditions(a: dict, b: dict) -> dict:
    unknown, different, equal = [], [], []
    for name in DIMENSIONS:
        x, y = value(a[name]), value(b[name])
        (unknown if x is None or y is None else different if x != y else equal).append(name)
    return dict(status='disjoint' if different else 'unknown' if unknown else 'same_declared_conditions',
                different=different, unknown=unknown, equal=equal)


def compare(old: dict, new: dict) -> dict:
    """Compare selected transcribed statements, without interpreting omissions."""
    pairs, lineage, availability = [], [], []
    roots = {value(f['measurement_lineage']) for f in old['facts'] if f['measurement_lineage']}
    for fact in new['facts']:
        root = value(fact['measurement_lineage'])
        if fact['kind'] == 'citation':
            lineage.append(dict(fact_id=fact['id'], root=root,
                status='shared_recorded_root' if root in roots else 'unknown', independence='not inferred'))
        if fact['availability']:
            basis_roots = sorted({value(f['measurement_lineage']) for f in old['facts']
                if value(f['subject']) == value(fact['subject']) and f['measurement_lineage']})
            availability.append(dict(fact_id=fact['id'], subject=value(fact['subject']),
                recorded_status=value(fact['availability']), recorded_basis_roots=basis_roots,
                independence='not inferred', applied_to_runtime=False))
        if fact['metric'] is None:
            continue
        for basis in old['facts']:
            if basis['metric'] is None:
                continue
            a, b = basis['metric'], fact['metric']
            conditions = compare_conditions(basis['conditions'], fact['conditions'])
            units = value(a['unit']), value(b['unit'])
            status = 'unknown'
            if value(a['name']) == value(b['name']):
                if conditions['status'] == 'disjoint':
                    status = 'different_declared_conditions'
                elif conditions['status'] == 'same_declared_conditions' and None not in units and units[0] == units[1]:
                    status = ('same_declared_value' if Decimal(value(a['value'])) == Decimal(value(b['value']))
                              else 'changed_declared_value')
            pairs.append(dict(old_fact=basis['id'], new_fact=fact['id'], status=status, conditions=conditions,
                old_unit=units[0], new_unit=units[1], unit_conversion=False))
    return dict(schema='dm.structural-observation-comparison/1', measurements=pairs,
        citation_lineage=lineage, availability=availability, semantic_review='pending',
        independence='not inferred', warning_action='retain_original_runtime_output',
        coverage='selected transcribed statements; omissions are not proved absent')

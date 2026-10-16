"""Strict, deterministic Decision Memory v1 records (no IO or inference).

This module is the shared persistence contract. A support link or an imported
result never authors an assessment. Metrics deliberately use decimal strings.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
import json
import re
from uuid import UUID, NAMESPACE_URL, uuid5

SCHEMA = 'graph-engine.decision-memory/1'
FILENAME = 'decision-memory.v1.json'
MAX_BYTES = 64 * 1024 * 1024
MAX_ITEMS = 50_000
KINDS = {'source', 'profile', 'claim', 'evidence', 'decision', 'check', 'result', 'relationship', 'finding'}
HASH = re.compile(r'sha256:[0-9a-f]{64}\Z')
HEX = re.compile(r'[0-9a-f]{64}\Z')
DECIMAL = re.compile(r'(?:0|-?[1-9][0-9]*)(?:\.[0-9]*[1-9])?\Z|-(?:0\.[0-9]*[1-9])\Z')
TYPES = {'enum', 'id', 'integer', 'decimal', 'range', 'time_window', 'unknown'}
PAYLOADS = {
    'source': {'source_ref', 'text', 'artifact', 'locator', 'lineage_ids'},
    'profile': {'name', 'version', 'dimensions', 'interventions'},
    'claim': {'text', 'context', 'limitations'},
    'evidence': {'interpretation', 'context', 'sources', 'lineage_ids', 'limitations'},
    'decision': {'action', 'rationale', 'alternatives', 'context', 'revisit_checks'},
    'check': {'question', 'context', 'protocol', 'inputs', 'metrics', 'rule', 'limitations'},
    'result': {'check', 'outcome', 'context', 'metrics', 'metrics_reason', 'sources',
               'execution', 'limitations', 'hypothetical'},
    'relationship': {'kind', 'source', 'target', 'context', 'explanation'},
    'finding': {'candidate', 'former_candidate_id'},
}
RELATIONS = {
    'supports': ({'evidence', 'result'}, {'claim'}),
    'opposes': ({'evidence', 'result'}, {'claim'}),
    'depends_on': ({'claim', 'decision'}, {'claim'}),
    'checks': ({'check'}, {'claim', 'decision'}),
    'result_of': ({'result'}, {'check'}),
    'supersedes': ({'decision'}, {'decision'}),
    'similar_to': (KINDS, KINDS), 'analogous_to': (KINDS, KINDS),
}


class RecordError(ValueError):
    """Invalid or tampered authoritative input."""


class UnsupportedSchema(RecordError):
    """A reader must upgrade rather than silently dropping future semantics."""


class RecordConflict(RecordError):
    """Refresh the preview; the record, source or idempotency key changed."""


def need(condition: bool, message: str = 'Invalid Decision Memory record') -> None:
    if not condition:
        raise RecordError(message)


def fields(value: object, required: set[str], optional: set[str] = frozenset()) -> None:
    need(isinstance(value, dict) and required <= value.keys() and not value.keys() - required - optional,
         'Unsupported or missing record fields')


def string(value: object, *, empty: bool = False, limit: int = 4000) -> None:
    need(isinstance(value, str) and (empty or bool(value.strip())) and len(value) <= limit)


def identifier(value: object) -> None:
    string(value, limit=200)
    try:
        need(str(UUID(value)) == value, 'Logical IDs must be canonical UUIDs')
    except (ValueError, AttributeError) as exc:
        raise RecordError('Logical IDs must be canonical UUIDs') from exc


def node_id(value: object) -> None:
    string(value, limit=200)
    need(not value.startswith('.') and not any(c in value for c in '/\\\x00\r\n'), 'Invalid anchor ID')


def stamp(value: object) -> None:
    string(value, limit=40)
    need(value.endswith('Z') and 'T' in value, 'UTC instant required')
    try:
        datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError as exc:
        raise RecordError('Invalid UTC instant') from exc


def sequence(value: object) -> None:
    need(isinstance(value, list) and len(value) <= 200, 'Expected at most 200 entries')


def strings(value: object) -> None:
    sequence(value)
    for item in value:
        string(item)


def digest(value: object, *, prefix: bool = True) -> None:
    need(isinstance(value, str) and bool((HASH if prefix else HEX).fullmatch(value)), 'Invalid SHA-256')


def ref(value: object) -> None:
    fields(value, {'id', 'version_id'})
    identifier(value['id'])
    digest(value['version_id'])


def key(value: dict) -> tuple[str, str]:
    return value['id'], value['version_id']


def reference(value: dict) -> dict:
    return {k: value[k] for k in ('id', 'version_id')}


def _bounded(value: object, depth: int = 0) -> None:
    need(depth <= 32, 'Record nesting exceeds 32')
    if isinstance(value, str):
        need(len(value) <= 8_000_000 and not any(0xD800 <= ord(c) <= 0xDFFF for c in value),
             'Oversized string or invalid Unicode surrogate')
    elif isinstance(value, dict):
        need(len(value) <= MAX_ITEMS and all(isinstance(k, str) for k in value))
        for k, v in value.items():
            _bounded(k, depth + 1)
            _bounded(v, depth + 1)
    elif isinstance(value, list):
        need(len(value) <= MAX_ITEMS)
        for item in value:
            _bounded(item, depth + 1)
    else:
        need(value is None or type(value) in (bool, int), 'Floating-point JSON is unsupported')
        if type(value) is int:
            need(abs(value) < 10**100, 'Integer too large')


def canonical(value: object) -> str:
    _bounded(value)
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def hash_record(value: dict) -> str:
    return 'sha256:' + hashlib.sha256(canonical({k: v for k, v in value.items()
                                               if k != 'version_id'}).encode()).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _pairs(pairs: list[tuple]) -> dict:
    result = {}
    for k, v in pairs:
        need(k not in result, 'Duplicate JSON key')
        result[k] = v
    return result


def loads(text: str) -> dict:
    try:
        need(len(text.encode('utf-8')) <= MAX_BYTES, 'Decision Memory exceeds 64 MiB')
        result = json.loads(text, object_pairs_hook=_pairs)
        validate(result)
        return result
    except (UnicodeError, RecursionError, TypeError, KeyError, OverflowError, ValueError) as exc:
        if isinstance(exc, RecordError):
            raise
        raise RecordError('Invalid Decision Memory JSON') from exc


def empty() -> dict:
    return dict(schema=SCHEMA, generation=0, versions=[], events=[], deltas=[], candidates=[], receipts=[])


def source_ref(value: dict) -> None:
    fields(value, {'node_id', 'text_sha256', 'revision'})
    node_id(value['node_id'])
    digest(value['text_sha256'], prefix=False)
    if value['revision'] is not None:
        need(isinstance(value['revision'], str) and bool(re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value['revision'])))


def decimal(value: object) -> None:
    need(isinstance(value, str) and len(value) <= 100 and bool(DECIMAL.fullmatch(value)), 'Canonical decimal string required')


def dimension(value: dict) -> None:
    need(isinstance(value, dict) and value.get('type') in TYPES, 'Unsupported condition type')
    kind = value['type']
    if kind == 'unknown':
        fields(value, {'type', 'reason'})
        string(value['reason'])
        return
    fields(value, {'type', 'value'})
    val = value['value']
    if kind in ('enum', 'id'):
        string(val)
    elif kind == 'integer':
        need(type(val) is int)
    elif kind == 'decimal':
        decimal(val)
    elif kind == 'time_window':
        fields(val, {'from', 'to'})
        stamp(val['from'])
        stamp(val['to'])
        need(datetime.fromisoformat(val['from'].replace('Z', '+00:00')) <
             datetime.fromisoformat(val['to'].replace('Z', '+00:00')), 'Empty time window')
    elif kind == 'range':
        fields(val, {'lower', 'upper', 'lower_inclusive', 'upper_inclusive'})
        need(type(val['lower_inclusive']) is bool and type(val['upper_inclusive']) is bool)
        for bound in (val['lower'], val['upper']):
            if type(bound) is not int:
                decimal(bound)
        need(type(val['lower']) is type(val['upper']), 'Range bounds must share a type')
        lo, hi = Decimal(val['lower']), Decimal(val['upper'])
        need(lo < hi or lo == hi and val['lower_inclusive'] and val['upper_inclusive'], 'Empty range')


def context(value: dict | None) -> None:
    if value is None:
        return  # Explicitly unknown, never comparable by free text.
    fields(value, {'schema', 'profile', 'dimensions', 'notes'})
    if value['schema'] != 'dm.context/1':
        raise UnsupportedSchema('Unsupported context schema')
    if value['profile'] is not None:
        ref(value['profile'])
    need(isinstance(value['dimensions'], dict) and len(value['dimensions']) <= 200)
    for name, item in value['dimensions'].items():
        string(name, limit=200)
        dimension(item)
    string(value['notes'], empty=True)


def refs(value: list) -> None:
    sequence(value)
    for item in value:
        ref(item)


def provenance(value: dict) -> None:
    fields(value, {'method', 'inputs'}, {'locator', 'tool', 'model', 'prompt', 'confidence'})
    need(value['method'] in ('manual', 'import', 'extractor'))
    refs(value['inputs'])
    for name in value.keys() - {'method', 'inputs'}:
        if value[name] is not None:
            string(value[name], empty=True)


def content_refs(value: object) -> list[dict]:
    """All exact content inputs; references are unambiguous tagged shapes."""
    result = []
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if set(item) == {'id', 'version_id'}:
                result.append(item)
            else:
                stack.extend(v for k, v in item.items() if k not in ('previous', 'expected_heads'))
        elif isinstance(item, list):
            stack.extend(item)
    return result


def payload(kind: str, p: dict, by_ref: dict) -> None:
    fields(p, PAYLOADS[kind], {'errors'} if kind == 'result' else frozenset())
    if kind == 'finding':
        from .decision_impact import validate_candidate
        validate_candidate(p['candidate'])
        if p['former_candidate_id'] is not None:
            digest(p['former_candidate_id'])
        need(by_ref[key(p['candidate']['target'])]['kind'] == 'decision')
    if 'context' in p:
        context(p['context'])
        if p['context'] and p['context']['profile']:
            need(by_ref[key(p['context']['profile'])]['kind'] == 'profile', 'Context requires a profile')
    if 'limitations' in p:
        strings(p['limitations'])
    if 'lineage_ids' in p:
        strings(p['lineage_ids'])  # [] explicitly means unknown independence.
    if kind == 'source':
        source_ref(p['source_ref'])
        string(p['text'], empty=True, limit=8_000_000)
        need(text_hash(p['text']) == p['source_ref']['text_sha256'], 'Source text/hash mismatch')
        string(p['locator'], limit=4000)
        if p['artifact'] is not None:
            fields(p['artifact'], {'sha256', 'locator', 'media_type', 'extraction'})
            digest(p['artifact']['sha256'], prefix=False)
            string(p['artifact']['locator'])
            string(p['artifact']['media_type'])
            if p['artifact']['extraction'] is not None:
                string(p['artifact']['extraction'])
    elif kind == 'profile':
        string(p['name'])
        string(p['version'])
        need(isinstance(p['dimensions'], dict) and len(p['dimensions']) <= 200)
        for name, d in p['dimensions'].items():
            string(name, limit=200)
            fields(d, {'type', 'unit', 'required', 'compare', 'allowed_values'})
            need(d['type'] in TYPES - {'unknown'} and type(d['required']) is bool)
            need(d['compare'] in ('equal', 'overlap'))
            need(d['compare'] != 'overlap' or d['type'] in ('range', 'time_window'))
            if d['unit'] is not None:
                string(d['unit'])
            if d['allowed_values'] is not None:
                strings(d['allowed_values'])
        strings(p['interventions'])
        need(set(p['interventions']) <= p['dimensions'].keys())
    elif kind == 'claim':
        string(p['text'])
    elif kind == 'evidence':
        string(p['interpretation'])
        sequence(p['sources'])
        need(bool(p['sources']), 'Evidence requires a pinned source or result')
        for item in p['sources']:
            fields(item, {'ref', 'passage'})
            ref(item['ref'])
            src = by_ref[key(item['ref'])]
            need(src['kind'] in ('source', 'result'), 'Invalid evidence source')
            if item['passage'] is not None:
                q = item['passage']
                fields(q, {'start', 'end', 'quote'})
                need(src['kind'] == 'source' and type(q['start']) is int and type(q['end']) is int)
                need(0 <= q['start'] < q['end'] <= len(src['payload']['text']))
                string(q['quote'], limit=8_000_000)
                need(src['payload']['text'][q['start']:q['end']] == q['quote'], 'Quote/source mismatch')
            else:
                need(src['kind'] == 'result' or bool(src['payload']['locator']), 'Source location required')
    elif kind == 'decision':
        string(p['action'])
        string(p['rationale'])
        strings(p['alternatives'])
        refs(p['revisit_checks'])
        need(all(by_ref[key(r)]['kind'] == 'check' for r in p['revisit_checks']))
    elif kind == 'check':
        string(p['question'])
        fields(p['protocol'], {'id', 'version'})
        string(p['protocol']['id'])
        string(p['protocol']['version'])
        strings(p['inputs'])
        sequence(p['metrics'])
        for metric in p['metrics']:
            fields(metric, {'name', 'unit'})
            string(metric['name'])
            string(metric['unit'])
        string(p['rule'])
    elif kind == 'result':
        if 'errors' in p:
            strings(p['errors'])
            need(not p['errors'] or p['outcome'] != 'completed', 'A result with errors cannot be completed')
        ref(p['check'])
        need(by_ref[key(p['check'])]['kind'] == 'check')
        need(p['outcome'] in ('completed', 'inconclusive', 'error') and type(p['hypothetical']) is bool)
        refs(p['sources'])
        need(all(by_ref[key(r)]['kind'] == 'source' for r in p['sources']))
        sequence(p['metrics'])
        for metric in p['metrics']:
            fields(metric, {'name', 'value', 'unit', 'denominator'}, {'reason'})
            string(metric['name'])
            if metric['value'] is None:
                string(metric.get('reason'))
            else:
                decimal(metric['value'])
                need('reason' not in metric, 'Measured metric cannot have a missing-value reason')
            string(metric['unit'])
            if metric['denominator'] is not None:
                decimal(metric['denominator'])
                need(Decimal(metric['denominator']) > 0)
        if p['metrics_reason'] is not None:
            string(p['metrics_reason'])
        need(bool(p['metrics']) or bool(p['metrics_reason']), 'Missing metrics require a reason')
        fields(p['execution'], {'code', 'data', 'environment', 'configuration', 'command', 'raw_outputs', 'observed_at'})
        for name in ('code', 'data', 'environment', 'configuration', 'command'):
            if p['execution'][name] is not None:
                string(p['execution'][name])
        if p['execution']['observed_at'] is not None:
            stamp(p['execution']['observed_at'])
        refs(p['execution']['raw_outputs'])
        need(all(by_ref[key(r)]['kind'] == 'source' for r in p['execution']['raw_outputs']))
    elif kind == 'relationship':
        need(p['kind'] in RELATIONS, 'Unknown relationship kind')
        ref(p['source'])
        ref(p['target'])
        a, b = (by_ref[key(p[x])] for x in ('source', 'target'))
        need(a['kind'] in RELATIONS[p['kind']][0] and b['kind'] in RELATIONS[p['kind']][1], 'Invalid relationship direction')
        string(p['explanation'])


INITIAL = {'epistemic': 'unassessed', 'workflow': 'proposed', 'availability': 'available',
           'decision': 'proposed', 'decision_conclusion': None,
           'finding_disposition': 'unreviewed', 'finding_workflow': 'open'}
ASSESSED = {'supported', 'opposed', 'mixed', 'inconclusive'}
AXES = {'claim': {'epistemic', 'workflow'}, 'evidence': {'epistemic', 'workflow', 'availability'},
        'decision': {'decision', 'decision_conclusion', 'workflow'},
        'relationship': {'workflow', 'availability'}, 'profile': {'workflow'},
        'source': {'workflow'}, 'check': {'workflow'}, 'result': {'workflow'},
        'finding': {'finding_disposition', 'finding_workflow'}}


def valid_transition(axis: str, before: str | None, after: str, correction: bool) -> bool:
    if axis == 'finding_disposition':
        return not correction and before in ('unreviewed', 'dismissed', 'inconclusive') and after in ('confirmed', 'dismissed', 'inconclusive')
    if axis == 'finding_workflow':
        return not correction and (before, after) in {('open', 'acknowledged'), ('open', 'resolved'), ('acknowledged', 'resolved')}
    if correction:
        return after in ({'unassessed'} | ASSESSED if axis == 'epistemic' else
                         {'proposed', 'accepted', 'rejected'} if axis == 'workflow' else
                         {'available', 'withdrawn'} if axis == 'availability' else
                         {'proposed', 'current', 'superseded', 'withdrawn'} if axis == 'decision' else
                         {None, 'remains_justified', 'needs_investigation', 'revise'})
    if axis == 'epistemic':
        return before in {'unassessed'} | ASSESSED and after in ASSESSED
    if axis == 'workflow':
        return before == 'proposed' and after in ('accepted', 'rejected')
    if axis == 'availability':
        return (before, after) in {('available', 'withdrawn'), ('withdrawn', 'available')}
    if axis == 'decision':
        return (before, after) in {('proposed', 'current'), ('proposed', 'withdrawn'),
                                   ('current', 'superseded'), ('current', 'withdrawn')}
    return axis == 'decision_conclusion' and after in ('remains_justified', 'needs_investigation', 'revise')


def _validate(data: dict) -> None:
    """Validate every persisted version and event, including rejected history."""
    fields(data, {'schema', 'generation', 'versions', 'events', 'deltas', 'candidates', 'receipts'})
    if data['schema'] != SCHEMA:
        raise UnsupportedSchema('Unsupported Decision Memory schema')
    need(type(data['generation']) is int and data['generation'] >= 0)
    for name in ('versions', 'events', 'deltas', 'candidates', 'receipts'):
        need(isinstance(data[name], list))
    need(sum(len(data[n]) for n in ('versions', 'events', 'deltas', 'candidates', 'receipts')) <= MAX_ITEMS,
         'Decision Memory exceeds 50,000 items')
    # Comparisons are ephemeral; explicit reviews persist validated finding
    # content versions. Never accept a second, unvalidated persistence format.
    if data['deltas'] or data['candidates']:
        raise UnsupportedSchema('Delta/candidate persistence is not enabled by this writer')
    need(len(canonical(data).encode()) <= MAX_BYTES, 'Decision Memory exceeds 64 MiB')
    by_ref, heads, anchors = {}, {}, {}
    for v in data['versions']:
        fields(v, {'schema', 'id', 'version_id', 'kind', 'anchor_node_id', 'previous',
                   'recorded_at', 'recorded_by', 'provenance', 'payload'})
        if v['schema'] != 'dm.content/1':
            raise UnsupportedSchema('Unsupported content schema')
        identifier(v['id'])
        digest(v['version_id'])
        need(v['kind'] in KINDS)
        node_id(v['anchor_node_id'])
        stamp(v['recorded_at'])
        string(v['recorded_by'], limit=200)
        provenance(v['provenance'])
        need(v['version_id'] == hash_record(v), 'Immutable version hash mismatch')
        need(key(v) not in by_ref, 'Duplicate immutable version')
        old = heads.get(v['id'])
        need(v['previous'] == (reference(old) if old else None), 'Missing predecessor or forked version chain')
        if old:
            need((old['kind'], old['anchor_node_id']) == (v['kind'], v['anchor_node_id']), 'Logical identity changed')
        if v['kind'] == 'finding':
            from .decision_impact import series_id
            need(v['id'] == series_id(v['payload']['candidate']), 'Finding series identity mismatch')
            need(v['payload']['former_candidate_id'] == (old['payload']['candidate']['candidate_id'] if old else None),
                 'Finding must retain the former candidate identity')
            need(old is None or old['payload']['candidate']['candidate_id'] != v['payload']['candidate']['candidate_id'],
                 'Finding reconsideration requires materially new input')
        need(anchors.setdefault(v['anchor_node_id'], v['id']) == v['id'], 'Anchor reused for a different identity')
        inputs = content_refs({k: val for k, val in v.items() if k not in ('id', 'version_id')})
        need(len(inputs) <= 200, 'A content record exceeds 200 references')
        for r in inputs:
            ref(r)
            need(key(r) in by_ref, 'Missing, cyclic or forward content reference')
        payload(v['kind'], v['payload'], by_ref)
        if v['kind'] == 'source':
            need(v['anchor_node_id'] == v['payload']['source_ref']['node_id'], 'Source anchor mismatch')
        by_ref[key(v)] = v
        heads[v['id']] = v
    event_ids, event_heads = {}, {}
    for e in data['events']:
        fields(e, {'schema', 'event_id', 'subject', 'axis', 'from', 'to', 'previous_event_id',
                   'basis', 'reviewer', 'reason', 'reviewed_at', 'expected_heads', 'supersedes_event_id'})
        if e['schema'] != 'dm.event/1':
            raise UnsupportedSchema('Unsupported event schema')
        identifier(e['event_id'])
        need(e['event_id'] == str(uuid5(NAMESPACE_URL, canonical({k: v for k, v in e.items()
                                                               if k != 'event_id'}))),
             'Immutable event identity mismatch')
        need(e['event_id'] not in event_ids, 'Duplicate event ID')
        ref(e['subject'])
        subject = by_ref.get(key(e['subject']))
        need(subject is not None, 'Missing event subject')
        need(e['axis'] in AXES[subject['kind']], 'Invalid state axis for subject')
        string(e['reason'])
        string(e['reviewer'], limit=200)
        stamp(e['reviewed_at'])
        need(isinstance(e['expected_heads'], dict) and len(e['expected_heads']) <= MAX_ITEMS)
        sequence(e['basis'])
        for item in e['basis']:
            need(isinstance(item, dict) and item.get('type') in ('content_ref', 'event_ref', 'source_ref'))
            if item['type'] == 'content_ref':
                fields(item, {'type', 'ref'})
                ref(item['ref'])
                need(key(item['ref']) in by_ref, 'Missing basis version')
            elif item['type'] == 'event_ref':
                fields(item, {'type', 'event_id'})
                need(item['event_id'] in event_ids, 'Missing or forward basis event')
            else:
                fields(item, {'type', 'ref'})
                source_ref(item['ref'])
                need(any(v['kind'] == 'source' and v['payload']['source_ref'] == item['ref']
                         for v in by_ref.values()), 'Missing pinned source basis')
        chain = (*key(e['subject']), e['axis'])
        prev = event_heads.get(chain)
        need(e['previous_event_id'] == (prev['event_id'] if prev else None), 'Forked event chain')
        before = prev['to'] if prev else INITIAL[e['axis']]
        need(e['from'] == before, 'Invalid previous state')
        correction = e['supersedes_event_id'] is not None
        if correction:
            need(prev is not None and e['supersedes_event_id'] == prev['event_id'], 'Correction must target event head')
            need(e['to'] == prev['from'], 'Undo must restore exact prior state')
            need(e['basis'] == prev['basis'], 'Undo must preserve exact basis')
            need(not any(any(b.get('event_id') == prev['event_id']
                             or b['type'] == 'content_ref' and b['ref'] == prev['subject']
                             for b in x['basis'])
                         for x in list(event_ids.values())[list(event_ids).index(prev['event_id']) + 1:]),
                 'Event has dependent reviews')
        need(valid_transition(e['axis'], before, e['to'], correction), 'Invalid state transition')
        if e['axis'] == 'finding_workflow':
            disposition = event_heads.get((*key(e['subject']), 'finding_disposition'))
            need(disposition is not None and disposition['to'] == 'confirmed', 'Finding workflow requires confirmed disposition')
            if e['to'] == 'resolved':
                judgments = [event_ids[b['event_id']] for b in e['basis'] if b['type'] == 'event_ref']
                target = subject['payload']['candidate']['target']
                outcomes = [j for j in judgments if j['subject'] == target and j['axis'] == 'decision_conclusion']
                need(bool(outcomes), 'Resolution must pin an explicit decision review outcome')
                if outcomes[-1]['to'] == 'needs_investigation':
                    need(any(b['type'] == 'content_ref' and by_ref[key(b['ref'])]['kind'] == 'check' for b in e['basis']),
                         'Investigation requires a follow-up check; reviewer owns the resolution')
        if e['axis'] == 'epistemic' and e['to'] in ASSESSED or e['axis'] == 'decision_conclusion':
            need(bool(e['basis']), 'Assessment requires explicit basis')
        event_heads[chain] = e
        event_ids[e['event_id']] = e
    for v in data['versions']:
        if v['kind'] == 'finding':
            candidate = v['payload']['candidate']
            relevant = {key(r) for r in content_refs(candidate)}
            need(all(eid in event_ids and key(event_ids[eid]['subject']) in relevant
                     and by_ref[key(event_ids[eid]['subject'])]['kind'] != 'finding'
                     for eid in candidate['basis_event_ids']), 'Missing or unrelated candidate basis event')
    # Terminalizing a current choice cannot leave a missing successor.
    for e in data['events']:
        if e['axis'] == 'decision' and e['to'] == 'superseded':
            need(any(b['type'] == 'content_ref' and by_ref[key(b['ref'])]['kind'] == 'decision'
                     and by_ref[key(b['ref'])]['previous'] == e['subject']
                     and any(x['subject'] == b['ref'] and x['axis'] == 'decision' and x['to'] == 'current'
                             and x['reviewed_at'] == e['reviewed_at']
                             for x in data['events']) for b in e['basis']), 'Supersession requires activated successor')
    current_decisions = set()
    for chain, e in event_heads.items():
        if e['axis'] == 'decision' and e['to'] == 'current':
            need(e['subject']['id'] not in current_decisions, 'Multiple current versions of one decision')
            current_decisions.add(e['subject']['id'])
    keys = set()
    for receipt in data['receipts']:
        fields(receipt, {'key', 'request_hash', 'actor', 'refs', 'event_ids', 'generation'})
        string(receipt['key'], limit=200)
        need(receipt['key'] not in keys, 'Duplicate idempotency key')
        keys.add(receipt['key'])
        digest(receipt['request_hash'])
        string(receipt['actor'], limit=200)
        refs(receipt['refs'])
        need(all(key(r) in by_ref for r in receipt['refs']))
        sequence(receipt['event_ids'])
        need(all(e in event_ids for e in receipt['event_ids']))
        need(type(receipt['generation']) is int and 0 < receipt['generation'] <= data['generation'])


def validate(data: dict) -> None:
    """Normalize malformed nested shapes to the public validation error type."""
    try:
        _validate(data)
    except (KeyError, TypeError, AttributeError, RecursionError, OverflowError, UnicodeError) as exc:
        raise RecordError('Malformed Decision Memory record') from exc

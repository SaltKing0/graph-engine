"""Deterministic capture and explicit review shared by CLI and HTTP.

No extractor is configured by this surface. Sources are existing local import
nodes; locators and recorded execution commands are inert data.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from functools import wraps
import json
from typing import Callable, ParamSpec, TypeVar
from uuid import NAMESPACE_URL, uuid5

from . import decision_schema as s
from .brain import Brain
from .decision_memory import DecisionMemory, RecordView, read_file
from .write_guard import write_operation

PROPOSAL = 'dm.proposal/1'
REVIEW = 'dm.review/1'
RESULT = 'dm.result-import/1'
P = ParamSpec('P')
T = TypeVar('T')


def validated(function: Callable[P, T]) -> Callable[P, T]:
    """Keep malformed nested envelopes on the public validation error path."""
    @wraps(function)
    def checked(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return function(*args, **kwargs)
        except (KeyError, TypeError, AttributeError, RecursionError, OverflowError, UnicodeError) as exc:
            raise s.RecordError('Malformed structured envelope') from exc
    return checked


def bounded(value: dict) -> None:
    s.need(isinstance(value, dict), 'Expected a structured envelope')
    s.need(len(s.canonical(value).encode()) <= s.MAX_BYTES, 'Envelope exceeds 64 MiB')


def load_envelope(text: str) -> dict:
    """Bound input, reject duplicate keys, noncanonical numbers and bad Unicode."""
    try:
        s.need(len(text.encode('utf-8')) <= s.MAX_BYTES, 'Envelope exceeds 64 MiB')
        value = json.loads(text, object_pairs_hook=s._pairs)
        s.canonical(value)
        s.need(isinstance(value, dict), 'Expected a structured envelope')
        return value
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise s.RecordError('Invalid structured envelope') from exc


def compare_context(a: dict | None, b: dict | None, view: RecordView) -> dict:
    """Conservative contract comparison; no text similarity or unit conversion."""
    unknown, disjoint, intersection = [], [], {}
    if not a or not b or not a['profile'] or a['profile'] != b['profile']:
        return dict(status='unknown', reasons=['Missing or different profile'], intersection={})
    profile = view.get(a['profile'])
    if profile['basis_changed'] or profile['state']['workflow'] != 'accepted':
        return dict(status='unknown', reasons=['Profile requires current acceptance'], intersection={})
    rules = profile['record']['payload']['dimensions']
    unknown.extend(sorted((a['dimensions'].keys() | b['dimensions'].keys()) - rules.keys()))
    for name, rule in rules.items():
        x, y = a['dimensions'].get(name), b['dimensions'].get(name)
        if x is None and y is None and not rule['required']:
            continue
        if (not x or not y or x['type'] == 'unknown' or y['type'] == 'unknown'
                or x['type'] != rule['type'] or y['type'] != rule['type']):
            unknown.append(name)
            continue
        if rule['allowed_values'] is not None and (
                x['value'] not in rule['allowed_values'] or y['value'] not in rule['allowed_values']):
            unknown.append(name)
            continue
        if rule['compare'] == 'equal':
            if x != y:
                disjoint.append(name)
            else:
                intersection[name] = x
        elif rule['type'] == 'time_window':
            # Compare parsed UTC instants, not variable precision strings.
            lo = max((x['value']['from'], y['value']['from']), key=datetime.fromisoformat)
            hi = min((x['value']['to'], y['value']['to']), key=datetime.fromisoformat)
            if datetime.fromisoformat(lo) >= datetime.fromisoformat(hi):
                disjoint.append(name)
            else:
                intersection[name] = {'type': 'time_window', 'value': {'from': lo, 'to': hi}}
        else:
            xv, yv = x['value'], y['value']
            if type(xv['lower']) is not type(yv['lower']):
                unknown.append(name)
                continue
            lo = max((xv['lower'], yv['lower']), key=Decimal)
            hi = min((xv['upper'], yv['upper']), key=Decimal)
            li = all(v['lower_inclusive'] for v in (xv, yv) if Decimal(v['lower']) == Decimal(lo))
            ui = all(v['upper_inclusive'] for v in (xv, yv) if Decimal(v['upper']) == Decimal(hi))
            if Decimal(lo) > Decimal(hi) or Decimal(lo) == Decimal(hi) and not (li and ui):
                disjoint.append(name)
            else:
                intersection[name] = {'type': 'range', 'value': dict(lower=lo, upper=hi,
                                        lower_inclusive=li, upper_inclusive=ui)}
    # An empty profile cannot establish any comparison conditions.
    if not intersection and not disjoint:
        unknown.append('No comparable dimensions')
    return dict(status='disjoint' if disjoint else 'unknown' if unknown else 'comparable',
                reasons=disjoint or unknown, intersection=intersection)


class DecisionService:
    def __init__(self, brain: Brain) -> None:
        self.brain = brain
        self.store = DecisionMemory(brain)

    def preview(self) -> dict:
        return self.store.preview()

    @validated
    def compare(self, envelope: dict) -> dict:
        from .decision_impact import compare
        bounded(envelope)
        return compare(self.brain, envelope)

    @validated
    def read(self, operation: str, envelope: dict) -> dict:
        """Shared, no-model explanatory reads for CLI and MCP."""
        from . import decision_brief as b
        bounded(envelope)
        specs = {
            'brief': ({'reference'}, {'revision'}),
            'findings': (set(), {'revision', 'decision_id', 'unresolved_only'}),
            'context': ({'query'}, {'revision', 'budget', 'k'}),
            'inspect-revision': ({'reference', 'revision'}, set()),
        }
        s.need(operation in specs, 'Unsupported decision read')
        s.fields(envelope, *specs[operation])
        options = dict(envelope)
        if 'revision' in options:
            options['revision_name'] = options.pop('revision')
        function = {'brief': b.brief, 'findings': b.findings,
                    'context': b.build_context, 'inspect-revision': b.inspect}[operation]
        return function(self.brain, **options)

    @write_operation
    @validated
    def record_finding(self, envelope: dict, *, dry_run: bool = False, commit: bool = True) -> dict:
        """Explicitly review one regenerated candidate; no caller-authored paths.

        Workflow acknowledgement/resolution then uses the ordinary review API.
        The reviewer is the authenticated actor, also the resolution owner.
        """
        from .decision_impact import series_id
        bounded(envelope)
        s.fields(envelope, {'schema', 'idempotency_key', 'expected_generation', 'expected_heads',
                            'comparison', 'candidate_id', 'disposition', 'reason'})
        s.need(envelope['schema'] == 'dm.finding-review/1', 'Unsupported finding review schema')
        s.need(envelope['disposition'] in ('confirmed', 'dismissed', 'inconclusive'))
        s.string(envelope['reason'])
        s.digest(envelope['candidate_id'])
        result = self.compare(envelope['comparison'])
        candidate = next((c for c in result['candidates'] if c['candidate_id'] == envelope['candidate_id']), None)
        if candidate is None:
            raise s.RecordConflict('Candidate unavailable or changed; compare again')
        fid = series_id(candidate)
        data = read_file(self.brain)
        view = RecordView(self.brain, data)
        versions = [v for v in data['versions'] if v['id'] == fid]
        existing = next((v for v in versions if v['payload']['candidate']['candidate_id'] == candidate['candidate_id']), None)
        if existing is not None:
            view.get(s.reference(existing))
            previous = view.versions[s.key(existing['previous'])] if existing['previous'] else None
            # Reconstruct the exact request for a durable same-key retry. A new
            # key cannot duplicate a finding or erase its former disposition.
            if not any(r['key'] == envelope['idempotency_key'] for r in data['receipts']):
                raise s.RecordConflict('Candidate already reviewed; use its explicit review workflow')
        else:
            previous = versions[-1] if versions else None
        if previous is not None:
            view.get(s.reference(previous))
        anchor = previous['anchor_node_id'] if previous else str(uuid5(NAMESPACE_URL, 'finding-anchor:' + fid))
        draft = dict(id=fid, kind='finding', anchor_node_id=anchor,
            previous=s.reference(previous) if previous else None,
            provenance={'method': 'manual', 'inputs': []}, payload=dict(candidate=candidate,
                former_candidate_id=previous['payload']['candidate']['candidate_id'] if previous else None))
        judgment = dict(subject={'local': fid}, axis='finding_disposition', **{'from': 'unreviewed', 'to': envelope['disposition']},
            previous_event_id=None, basis=[{'type': 'content_ref', 'ref': candidate['target']}],
            reason=envelope['reason'], supersedes_event_id=None)
        request = {k: envelope[k] for k in ('idempotency_key', 'expected_generation', 'expected_heads')}
        request.update(schema=s.SCHEMA, versions=[draft], events=[judgment])
        result = self.store.transact(request, dry_run=dry_run, commit=commit)
        return result if result.get('dry_run') else dict(dry_run=dry_run, receipt=result)

    def source(self, node_id: str) -> dict:
        """Pin exact stored bytes and inherited document-import identity."""
        s.node_id(node_id)
        payload = self.store.source_payload(node_id, locator='nodes/' + node_id + '.md')
        node = self.brain.read_node(node_id)
        if node.document:
            d = node.document
            payload.update(artifact=dict(sha256=d['content_sha256'], locator=d['source_id'],
                media_type='application/octet-stream', extraction=s.canonical(d)),
                lineage_ids=['document-sha256:' + d['content_sha256']])
        return payload

    def inspect(self, reference: dict) -> dict:
        self.brain.authorize('read')
        # One snapshot for authorization, judgments and lineage. A second raw
        # sidecar read could introduce newly private basis into an older view.
        view = RecordView(self.brain, read_file(self.brain))
        result = view.get(reference)
        result['comparison'] = None
        p = result['record']['payload']
        if result['record']['kind'] == 'relationship' and p['kind'] in ('supports', 'opposes'):
            a, b = (view.get(p[k])['record']['payload'] for k in ('source', 'target'))
            result['comparison'] = compare_context(a['context'], b['context'], view)
        # Lineage groups are descriptive; citation counts never become confidence.
        deps, _ = view.dependencies(result['record'], reviews=True)
        sources = [view.versions[k] for k in sorted(deps) if view.versions[k]['kind'] == 'source']
        result['source_lineage'] = [dict(ref=s.reference(v), lineage_ids=v['payload']['lineage_ids']) for v in sources]
        result['independence'] = 'not inferred'
        return result

    def pending(self) -> dict:
        self.brain.authorize('read')
        view = RecordView(self.brain, read_file(self.brain))
        pending = []
        for v in view.heads.values():
            if not view.allowed(v):
                continue
            item = self.inspect(s.reference(v))
            state = item['state']
            if state.get('workflow') == 'rejected' or state.get('availability') == 'withdrawn':
                continue
            if state.get('workflow') == 'proposed' or (
                    v['kind'] in ('claim', 'evidence') and state['epistemic'] == 'unassessed'):
                pending.append(item)
        return dict(items=pending, preview=self.preview())

    @write_operation
    @validated
    def submit(self, envelope: dict, *, dry_run: bool = False, commit: bool = True) -> dict:
        """Capture or review, with the same strict preconditions on both surfaces."""
        bounded(envelope)
        schema = envelope.get('schema')
        if schema not in (PROPOSAL, REVIEW):
            raise s.UnsupportedSchema('Unsupported proposal/review schema')
        field = 'versions' if schema == PROPOSAL else 'events'
        s.fields(envelope, {'schema', 'idempotency_key', 'expected_generation', 'expected_heads', field})
        if schema == PROPOSAL:
            s.need(not any(v.get('kind') == 'finding' for v in envelope['versions']),
                   'Use explicit finding review to regenerate and persist candidates')
        request = dict(deepcopy(envelope), schema=s.SCHEMA)
        request['events' if field == 'versions' else 'versions'] = []
        # Validation has no pull, directory creation, anchors, index, lock file,
        # model initialization or sync. A successful retry remains a receipt.
        plan = self.store.transact(request, dry_run=True, commit=False)
        if not plan.get('dry_run'):
            return dict(dry_run=dry_run, replay=True, receipt=plan)
        data = read_file(self.brain)
        data['versions'].extend(plan['versions'])
        data['events'].extend(plan['events'])
        view = RecordView(self.brain, data)
        # Use validated planned provenance for semantic review checks too. A
        # batch may accept a profile with newly introduced source restrictions.
        for nid, sources in plan['anchor_sources'].items():
            if nid in view.current:
                view.current[nid].derived_from = sources
        from .access import derivation_parents
        view.current_parents = derivation_parents(view.current, Brain.read_edges(self.brain, include_rejected=True))
        view.parents = view.current_parents
        for v in plan['versions']:
            if view.changed(v):
                raise s.RecordConflict('Proposal references stale content or source bytes')
        for e in plan['events']:
            self._review_rules(e, view)
        if dry_run:
            return plan
        return dict(dry_run=False, receipt=self.store.transact(request, commit=commit))

    def _review_rules(self, e: dict, view: RecordView) -> None:
        if e['supersedes_event_id']:
            return  # The store checks exact undo, dependent reviews and freshness.
        subject = view.versions[s.key(e['subject'])]
        p = subject['payload']
        if subject['kind'] == 'relationship' and e['axis'] == 'workflow' and e['to'] == 'accepted' and p['kind'] in ('supports', 'opposes'):
            a, b = (view.versions[s.key(p[k])] for k in ('source', 'target'))
            comparison = compare_context(a['payload']['context'], b['payload']['context'], view)
            s.need(comparison['status'] == 'comparable', 'Support/opposition requires comparable reviewed scope')
            s.need(p['context'] is not None and p['context']['profile'] == b['payload']['context']['profile']
                   and p['context']['dimensions'] == comparison['intersection'],
                   'Relationship must pin the exact comparable intersection')
            self._profile_basis(e, p['context']['profile'], view)
            deps, _ = view.dependencies(a)
            results = [view.versions[k] for k in deps if view.versions[k]['kind'] == 'result']
            s.need(all(v['payload']['outcome'] == 'completed' for v in results),
                   'Failed/inconclusive runs cannot establish support or opposition')
            # An interpretation cannot broaden the scope of its recorded runs.
            comparisons = [compare_context(v['payload']['context'], p['context'], view) for v in results]
            s.need(all(c['status'] == 'comparable' and c['intersection'] == p['context']['dimensions']
                       for c in comparisons), 'Support/opposition requires results covering its reviewed scope')
        if e['axis'] == 'epistemic' and e['to'] in ('supported', 'opposed', 'mixed'):
            deps, _ = view.dependencies(e)
            s.need(not any(view.versions[k]['kind'] == 'result' and view.versions[k]['payload']['outcome'] != 'completed'
                           for k in deps), 'Failed/inconclusive runs cannot establish an assessment')
            candidates = [view.versions[k] for k in deps if view.versions[k]['kind'] in ('evidence', 'result')]
            s.need(bool(candidates), 'Assessment requires evidence or a result')
            comparisons = [compare_context(v['payload']['context'], p['context'], view) for v in candidates]
            s.need(all(c['status'] == 'comparable' and c['intersection'] == p['context']['dimensions']
                       for c in comparisons), 'Assessment requires comparable evidence covering its reviewed scope')
            self._profile_basis(e, p['context']['profile'], view)

    def _profile_basis(self, e: dict, profile: dict, view: RecordView) -> None:
        judgment = next(x for x in reversed(view.data['events'])
                        if x['subject'] == profile and x['axis'] == 'workflow')
        s.need({'type': 'event_ref', 'event_id': judgment['event_id']} in e['basis'],
               'Review basis must pin the current profile acceptance event')

    @validated
    def result_draft(self, envelope: dict) -> dict:
        """Validate a strict, manually mapped result; raw artifact refs stay pinned."""
        bounded(envelope)
        s.fields(envelope, {'schema', 'id', 'anchor_node_id', 'previous', 'payload'})
        if envelope['schema'] != RESULT:
            raise s.UnsupportedSchema('Unsupported result import schema')
        p = envelope['payload']
        s.fields(p, s.PAYLOADS['result'], {'errors'})
        s.need(bool(p['sources']) and bool(p['execution']['raw_outputs']), 'Result import requires raw artifact sources')
        # Import only references existing records. It never reads paths or URLs.
        self.brain.authorize('read')
        data = read_file(self.brain)
        view = RecordView(self.brain, data)
        for r in s.content_refs(p):
            view.get(r)
        s.payload('result', p, view.versions)
        s.identifier(envelope['id'])
        s.node_id(envelope['anchor_node_id'])
        head = view.heads.get(envelope['id'])
        if head is not None:
            view.get(s.reference(head))
            if (envelope['previous'] != s.reference(head) or head['kind'] != 'result'
                    or head['anchor_node_id'] != envelope['anchor_node_id']):
                raise s.RecordConflict('Result predecessor or logical identity changed')
        else:
            s.need(envelope['previous'] is None, 'New result cannot have a predecessor')
        return dict(id=envelope['id'], anchor_node_id=envelope['anchor_node_id'], previous=envelope['previous'],
                    kind='result', payload=deepcopy(p), provenance={'method': 'import', 'inputs': p['sources']})

"""Read-only, bounded Decision Memory revision comparisons (#78).

Git selects content AND review state. Current authorization is applied before
classification, paths, support summaries or counts. No model or vector access.
"""
from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass
import json
import re
from uuid import NAMESPACE_URL, uuid5

from . import decision_schema as s
from .brain import Brain
from .decision_memory import RecordView, body, now
from .decision_service import compare_context
from .snapshots import _records, _parse_records

RULE = 'dm.impact-rules/1'
COMPARE = 'dm.compare/1'
LIMITS = dict(depth=3, objects=200, links=500, paths=20, deltas=200)


def identity(value: dict) -> str:
    return s.hash_record(value)


def candidate_identity(candidate: dict) -> str:
    material = deepcopy(candidate)
    material.pop('candidate_id', None)
    material.pop('completeness', None)
    for path in material['paths']:
        for step in path:
            step.pop('revision', None)
    return identity(material)


def series_id(candidate: dict) -> str:
    """New material input succeeds a finding; its former disposition survives."""
    return str(uuid5(NAMESPACE_URL, s.canonical(dict(rule=RULE,
        seed=candidate['delta']['subject_id'], target=candidate['target']['id']))))


def authorization(brain: Brain) -> dict | None:
    if hasattr(brain, 'identity'):
        from .access import load_policy
        return load_policy()
    return None


def current_fingerprint(current: tuple) -> str:
    """Hash graph storage, whose edge confidences may be finite floats.

    Decision records retain their stricter, decimal-string JSON contract.
    """
    value = dict(nodes={nid: n.to_markdown() for nid, n in current[0].items()},
                 edges=[e.to_dict() for e in current[1]])
    return s.text_hash(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False))


@dataclass
class Revision:
    revision: str
    commit_time: str
    view: RecordView
    records: dict
    events: dict
    states: dict
    supports: dict


def revision(brain: Brain, name: str, current: tuple, policy: dict | None) -> Revision:
    sha, stamp, raw = _records(brain, name)
    nodes, edges = _parse_records(raw)
    data = s.loads(raw[s.FILENAME]) if s.FILENAME in raw else s.empty()
    view = RecordView(brain, data, nodes=nodes, edges=edges,
        texts={nid: body(raw[f'nodes/{nid}.md']) for nid in nodes}, current=current, policy=policy,
        allow_tombstones=False)
    # Historical inspection may display tombstones; impact never reuses forgotten
    # evidence. Omit its entire dependent record, without hidden counts or IDs.
    visible = {}
    for k, v in view.versions.items():
        if view.allowed(v):
            visible[k] = v
    events = {eid: e for eid, e in view.events.items()
              if s.key(e['subject']) in visible and view.allowed(e)}
    states = {k: {axis: s.INITIAL[axis] for axis in s.AXES[v['kind']]} for k, v in visible.items()}
    for e in events.values():
        states[s.key(e['subject'])][e['axis']] = e['to']
    supports = defaultdict(list)
    for k, v in sorted(visible.items()):
        if (v['kind'] == 'relationship' and v['payload']['kind'] == 'supports'
                and states[k]['workflow'] == 'accepted' and view.heads[v['id']] == v):
            supports[s.key(v['payload']['target'])].append(v)
    return Revision(sha, stamp, view, visible, events, states, supports)


def state(rev: Revision, reference: dict) -> dict:
    return rev.states[s.key(reference)]


def heads(rev: Revision) -> dict:
    # Do not substitute an older accessible version for an inaccessible head.
    return {vid: v for vid, v in rev.view.heads.items() if s.key(v) in rev.records}


def excerpt(value: object) -> dict:
    encoded = s.canonical(value)
    return dict(text=encoded[:400], sha256=s.text_hash(encoded), truncated=len(encoded) > 400)


def delta(old: dict | None, new: dict | None, *, event: dict | None = None) -> dict:
    v = new or old
    fields, classes = [], []
    if event:
        fields = [event['axis']]
        classes = ['availability' if event['axis'] == 'availability' else 'review']
    elif old is None or new is None:
        fields = ['payload', 'provenance']
        classes = ['relationship' if v['kind'] == 'relationship' else 'content']
    else:
        fields = ['payload.' + k for k in sorted(old['payload'].keys() | new['payload'].keys())
                  if old['payload'].get(k) != new['payload'].get(k)]
        if old['provenance'] != new['provenance']:
            fields.append('provenance')
        if 'payload.context' in fields:
            classes.append('context')
        if 'provenance' in fields or any(f in fields for f in ('payload.lineage_ids', 'payload.sources', 'payload.artifact')):
            classes.append('provenance')
        if v['kind'] == 'relationship':
            classes.append('relationship')
        if fields:
            classes.append('content')
        # Only an exact, named deterministic formatting rule can suppress impact.
        a, b = deepcopy(old['payload']), deepcopy(new['payload'])
        if v['kind'] == 'source':
            for p in (a, b):
                p['text'] = p['text'].replace('\r\n', '\n')
                p['source_ref'] = {'node_id': p['source_ref']['node_id']}
        if a == b and old['provenance'] == new['provenance']:
            classes = ['cosmetic']
    result = dict(schema='dm.delta/1', rule=RULE, subject_id=v['id'], kind=v['kind'],
        old=s.reference(old) if old else None, new=s.reference(new) if new else None,
        event_id=event['event_id'] if event else None, fields=fields, classes=sorted(set(classes)),
        actor=event['reviewer'] if event else v['recorded_by'],
        recorded_at=event['reviewed_at'] if event else v['recorded_at'],
        certainty='verified_record_delta', cosmetic_rule='exact-payload-or-crlf/1' if classes == ['cosmetic'] else None)
    details = []
    for field in fields:
        if event:
            a, b = event['from'], event['to']
        elif field.startswith('payload.'):
            name = field.split('.', 1)[1]
            a, b = old['payload'].get(name) if old else None, new['payload'].get(name) if new else None
        else:
            a, b = old.get(field) if old else None, new.get(field) if new else None
        details.append(dict(field=field, before=excerpt(a), after=excerpt(b)))
    result['changes'] = details
    result['delta_id'] = identity(result)
    return result


class Budget:
    def __init__(self, limits: dict) -> None:
        self.limits = limits
        self.hit: set[str] = set()
        self.objects: set[tuple] = set()
        self.links = 0
        self.paths = 0

    def object(self, k: tuple) -> bool:
        if k not in self.objects and len(self.objects) >= self.limits['objects']:
            self.hit.add('objects')
            return False
        self.objects.add(k)
        return True

    def link(self) -> bool:
        if self.links >= self.limits['links']:
            self.hit.add('links')
            return False
        self.links += 1
        return True


def _accepted(rev: Revision, v: dict) -> bool:
    st = state(rev, s.reference(v))
    return (rev.view.heads[v['id']] == v and st.get('workflow') == 'accepted'
            and st.get('availability') != 'withdrawn')


def _graph(before: Revision, after: Revision, budget: Budget) -> dict:
    """Only typed accepted links and explicit input steps; deterministic union.

    Retain baseline accepted links to explain an old endpoint's replacement or
    retraction. Their revision label prevents implying acceptance of a successor.
    """
    adjacency = defaultdict(list)
    seen = set()
    for label, rev in (('after', after), ('before', before)):
        for k, v in sorted(rev.records.items()):
            if v['kind'] == 'finding':
                continue
            if v['kind'] == 'relationship':
                p = v['payload']
                if k in seen or not _accepted(rev, v) or p['kind'] not in ('supports', 'opposes', 'depends_on', 'checks', 'result_of'):
                    continue
                if not budget.link():
                    break
                seen.add(k)
                a, b = (p['target'], p['source']) if p['kind'] == 'depends_on' else (p['source'], p['target'])
                adjacency[s.key(a)].append(dict(from_ref=a, to_ref=b, relationship=s.reference(v),
                    kind=p['kind'], direction='reverse' if p['kind'] == 'depends_on' else 'forward',
                    revision=rev.revision, acceptance='accepted', view=label))
            else:
                for r in sorted(rev.view.inputs(v), key=s.key):
                    src = rev.records.get(s.key(r))
                    # A source/profile update may seed its recorded consumers;
                    # evidence may consume exact results. Never infer result_of
                    # or decision dependencies from a generic content reference.
                    if not src or not (src['kind'] in ('source', 'profile') or
                                       src['kind'] == 'result' and v['kind'] == 'evidence'):
                        continue
                    stepkey = (s.key(r), k)
                    if stepkey in seen:
                        continue
                    if not budget.link():
                        break
                    seen.add(stepkey)
                    adjacency[s.key(r)].append(dict(from_ref=r, to_ref=s.reference(v), relationship=None,
                        kind='explicit_input', direction='consumer', revision=rev.revision,
                        acceptance='recorded_input', view=label))
    for steps in adjacency.values():
        steps.sort(key=lambda step: (s.key(step['relationship']) if step['relationship'] else ('', ''),
                                    s.key(step['to_ref']), step['revision']))
    return adjacency


def _comparison(step: dict, before: Revision, after: Revision, substitutions: dict) -> dict | None:
    if step['kind'] not in ('supports', 'opposes'):
        return None
    rev = after if step['view'] == 'after' else before
    r = rev.records[s.key(step['relationship'])]['payload']
    # Compare successor scope without transferring acceptance to that version.
    a, b = [substitutions.get(s.key(r[key]), rev.records[s.key(r[key])]) for key in ('source', 'target')]
    from .decision_memory import BasisUnavailable
    try:
        return compare_context(a['payload']['context'], b['payload']['context'], after.view)
    except BasisUnavailable:
        return dict(status='unknown', reasons=['Profile unavailable in selected revision'], intersection={})


def _supports(claims: list[dict], before: Revision, after: Revision, budget: Budget) -> dict:
    remaining, removed = [], []
    known_lineage: set[str] = set()
    links = {s.key(v): v for rev in (before, after) for c in claims for v in rev.supports.get(s.key(c), [])
             if s.key(v) in after.records}
    for v in sorted(links.values(), key=s.key):
        p = v['payload']
        src = after.records[s.key(p['source'])]
        deps, _ = after.view.dependencies(src)
        sources = [after.records[k] for k in sorted(deps) if k in after.records and after.records[k]['kind'] == 'source']
        if len(sources) > 20:
            sources = sources[:20]
            budget.hit.add('support_sources')
        # Root lineage comes from sources, never a new interpretation's label.
        groups = sorted({lineage for source in sources for lineage in source['payload']['lineage_ids']})
        if len(groups) > 200:
            groups = groups[:200]
            budget.hit.add('support_lineage')
        unknown = not sources or any(not source['payload']['lineage_ids'] for source in sources)
        st = state(after, p['source'])
        unavailable = (st.get('availability') == 'withdrawn' or after.view.changed(v) or not _accepted(after, v))
        item = dict(relationship=s.reference(v), evidence=p['source'], claim=p['target'],
                    sources=[s.reference(source) for source in sources], lineage_ids=groups,
                    lineage='unknown' if unknown else 'shared' if known_lineage.intersection(groups) else 'distinct_recorded_roots',
                    status='withdrawn_or_stale' if unavailable else 'available', independence='not inferred')
        if not unavailable:
            known_lineage.update(groups)
        target = removed if unavailable else remaining
        if len(remaining) + len(removed) >= 20:
            budget.hit.add('support_output')
            break
        target.append(item)
    return dict(remaining=remaining, removed=removed, independence='not inferred; shared roots are not independent votes')


def compare(brain: Brain, envelope: dict) -> dict:
    """Compare two explicit Git revisions; output is ephemeral until reviewed."""
    s.fields(envelope, {'schema', 'before', 'after'}, {'limits'})
    if envelope['schema'] != COMPARE:
        raise s.UnsupportedSchema('Unsupported comparison schema')
    limits = dict(LIMITS)
    requested = envelope.get('limits', {})
    s.need(isinstance(requested, dict) and not requested.keys() - LIMITS.keys(), 'Unsupported comparison limit')
    for name, value in requested.items():
        s.need(type(value) is int and 1 <= value <= LIMITS[name], 'Limits may only lower v1 hard bounds')
        limits[name] = value
    brain.authorize('read')
    policy = authorization(brain)
    if policy is not None:
        from .access import permitted
        if not permitted(brain.graph_name, brain.identity, 'read', _policy=policy):
            raise PermissionError('Access denied')
    current = ({n.id: n for n in Brain.read_nodes(brain)}, Brain.read_edges(brain, include_rejected=True))
    fingerprint = current_fingerprint(current)
    before, after = (revision(brain, envelope[k], current, policy) for k in ('before', 'after'))
    budget = Budget(limits)
    old, new = heads(before), heads(after)
    changes = []
    for vid in sorted(old.keys() | new.keys()):
        a, b = old.get(vid), new.get(vid)
        # Missing/inaccessible records are not evidence of withdrawal. The
        # append-only store expresses withdrawal through explicit review events.
        if b is None or a is None and vid in before.view.heads:
            continue
        if a != b and b['kind'] != 'finding':
            changes.append(delta(a, b))
    for eid, e in sorted(after.events.items()):
        if eid not in before.view.events and after.records[s.key(e['subject'])]['kind'] != 'finding':
            v = after.records[s.key(e['subject'])]
            changes.append(delta(before.records.get(s.key(v)), v, event=e))
    changes.sort(key=lambda d: (d['subject_id'], d['event_id'] or '', d['delta_id']))
    if len(changes) > limits['deltas']:
        changes = changes[:limits['deltas']]
        budget.hit.add('deltas')
    graph = _graph(before, after, budget)
    all_records = {**before.records, **after.records}
    candidates = []
    warnings = set()
    for change in changes:
        if change['classes'] == ['cosmetic']:
            continue
        v = all_records[s.key(change['new'] or change['old'])]
        starts = []
        if v['kind'] == 'relationship':
            seeded = set()
            for reference in (change['old'], change['new']):
                if reference is None or s.key(reference) in seeded:
                    continue
                seeded.add(s.key(reference))
                rel = all_records[s.key(reference)]
                p = rel['payload']
                if p['kind'] not in ('supports', 'opposes', 'depends_on', 'checks', 'result_of'):
                    continue
                st = state(after, reference)
                was_accepted = s.key(reference) in before.records and _accepted(before, rel)
                if st.get('workflow') == 'rejected' and not was_accepted:
                    continue
                start, target = (p['target'], p['source']) if p['kind'] == 'depends_on' else (p['source'], p['target'])
                step = dict(from_ref=start, to_ref=target, relationship=reference, kind=p['kind'],
                    direction='reverse' if p['kind'] == 'depends_on' else 'forward', revision=after.revision,
                    acceptance=st.get('workflow'), view='after')
                if was_accepted and not _accepted(after, rel):
                    step.update(revision=before.revision, acceptance='accepted', view='before')
                starts.append((target, [step], {s.key(start), s.key(target)}))
        else:
            for reference in (change['old'], change['new']):
                if reference and reference not in [x[0] for x in starts]:
                    starts.append((reference, [], {s.key(reference)}))
        substitutions = {}
        if change['old'] and change['new'] and change['old'] != change['new']:
            substitutions[s.key(change['old'])] = v
        queue = deque(starts)
        visited = set()
        found = {}
        while queue:
            reference, path, seen = queue.popleft()
            k = s.key(reference)
            if k in visited or not budget.object(k):
                continue
            visited.add(k)
            obj = all_records.get(k)
            if obj is None:
                continue
            if obj['kind'] == 'decision' and path:
                if all(step['kind'] == 'explicit_input' for step in path):
                    continue
                if k not in after.records or state(after, reference).get('decision') in ('superseded', 'withdrawn'):
                    continue
                if budget.paths >= limits['paths']:
                    budget.hit.add('paths')
                    break
                comparisons = [c for step in path if (c := _comparison(step, before, after, substitutions))]
                if not comparisons:
                    comparisons = [dict(status='unknown', reasons=['No structured evidential scope comparison on path'], intersection={})]
                if any(c['status'] == 'disjoint' for c in comparisons) and any(step['acceptance'] == 'proposed' for step in path):
                    continue
                claims = sorted({s.key(step[key]) for step in path for key in ('from_ref', 'to_ref')
                                 if all_records[s.key(step[key])]['kind'] == 'claim'})
                claim_refs = [dict(id=i, version_id=h) for i, h in claims]
                support = _supports(claim_refs, before, after, budget)
                reasons = ['basis_changed']
                if any(c['status'] == 'disjoint' for c in comparisons):
                    reasons.append('scope_changed')
                if any(c['status'] == 'unknown' for c in comparisons):
                    reasons.append('comparability_unknown')
                if any(step['kind'] == 'opposes' for step in path) and comparisons and all(c['status'] == 'comparable' for c in comparisons):
                    reasons.append('comparable_opposition')
                event = after.events.get(change['event_id'])
                if event and event['axis'] == 'availability' and event['to'] == 'withdrawn':
                    reasons.append('support_withdrawn')
                if any(step['kind'] in ('result_of', 'checks') for step in path):
                    reasons.append('revisit_check_result')
                preview = any(step['acceptance'] == 'proposed' for step in path)
                clean_path = [{key: val for key, val in step.items() if key != 'view'} for step in path]
                # Basis heads include relevant judgments only; unrelated commits
                # and evaluation clocks cannot generate a new candidate identity.
                refs = {s.key(r) for r in s.content_refs(dict(path=clean_path, support=support))}
                # Preserve membership beyond the bounded support summary so a
                # finding can detect later accepted attachments without treating
                # already selected, clipped supports as newly introduced ones.
                refs.update(s.key(v) for claim in claim_refs for v in after.supports.get(s.key(claim), []))
                refs.add(k)
                refs.update(s.key(r) for r in (change['old'], change['new']) if r)
                closure = set(refs)
                for ref_key in sorted(refs):
                    if ref_key in after.records:
                        dependencies, _ = after.view.dependencies(after.records[ref_key])
                        closure.update(dependencies)
                if len(closure) > 200:
                    budget.hit.add('basis_refs')
                refs = set(sorted(closure)[:200])
                # Pin the selected revision's heads for freshness while retaining
                # old path versions as historical explanations, not current basis.
                basis_heads = [s.reference(after.view.heads[vid]) for vid in sorted({i for i, _ in refs})
                               if vid in after.view.heads and s.key(after.view.heads[vid]) in after.records]
                basis_events = sorted(eid for eid, e in after.events.items() if s.key(e['subject']) in refs)
                if len(basis_events) > 200:
                    budget.hit.add('basis_events')
                    basis_events = sorted(sorted(basis_events, key=after.view.event_positions.get)[-200:])
                candidate = dict(schema='dm.candidate/1', rule=RULE, delta=change, target=reference,
                    decision=dict(action=obj['payload']['action'], rationale=obj['payload']['rationale']),
                    paths=[clean_path], substitutions=[dict(old=dict(id=i, version_id=h), new=s.reference(n))
                                                      for (i, h), n in sorted(substitutions.items())],
                    comparison=comparisons, reasons=sorted(reasons), support=support,
                    basis_event_ids=basis_events, basis_heads=basis_heads,
                    basis_refs=[dict(id=i, version_id=h) for i, h in sorted(refs)],
                    classification='proposed_preview' if preview else 'candidate_semantic_impact',
                    judgment='unreviewed; no established refutation or automatic decision change',
                    needs_review='Review changed basis, scope and surviving support; retain or revise explicitly')
                candidate['candidate_id'] = candidate_identity(candidate)
                found[candidate['candidate_id']] = candidate
                budget.paths += 1
                continue
            outgoing = graph.get(k, [])
            if len(path) >= limits['depth']:
                if outgoing:
                    budget.hit.add('depth')
                continue
            for step in outgoing:
                if not budget.link():
                    break
                dest = s.key(step['to_ref'])
                if dest in seen:
                    warnings.add('dependency_cycle')
                    continue
                queue.append((step['to_ref'], path + [step], seen | {dest}))
        candidates.extend(found.values())
    # Reject a concurrent ACL or current-lineage change instead of publishing a
    # mixture. Historical text/reviews always came from their selected commits.
    current_after = ({n.id: n for n in Brain.read_nodes(brain)}, Brain.read_edges(brain, include_rejected=True))
    if (policy != authorization(brain) or fingerprint != current_fingerprint(current_after)):
        raise s.RecordConflict('Authorization or current lineage changed during comparison; retry')
    completeness = dict(truncated=bool(budget.hit), hit_limits=sorted(budget.hit), limits=limits,
                        visited_objects=len(budget.objects), examined_links=budget.links, retained_paths=budget.paths)
    for candidate in candidates:
        candidate['completeness'] = completeness
    judgments = [e for _, e in sorted(after.events.items()) if e['event_id'] not in before.view.events]
    if len(judgments) > limits['deltas']:
        budget.hit.add('judgments')
        completeness.update(truncated=True, hit_limits=sorted(budget.hit))
        judgments = judgments[:limits['deltas']]
    return dict(schema='dm.comparison/1', rule=RULE, evaluated_at=now(),
        before=dict(revision=before.revision, commit_time=before.commit_time, generation=before.view.data['generation']),
        after=dict(revision=after.revision, commit_time=after.commit_time, generation=after.view.data['generation']),
        deltas=changes, candidates=sorted(candidates, key=lambda c: c['candidate_id']),
        reviewed_judgments=judgments,
        completeness=completeness, warnings=sorted(warnings),
        uncertainty=['Ambiguous free text is unresolved; only explicit structured conditions are compared.',
                     'Missing, forgotten or unauthorized basis is omitted before analysis.',
                     'Incomplete traversal cannot establish absence of impact.'] if budget.hit else
                    ['Ambiguous free text is unresolved; only explicit structured conditions are compared.',
                     'Missing, forgotten or unauthorized basis is omitted before analysis.'])


def validate_candidate(c: dict) -> None:
    """Strict persisted candidate schema; derived IDs detect accidental tampering."""
    s.fields(c, {'schema', 'rule', 'delta', 'target', 'decision', 'paths', 'substitutions', 'comparison',
        'reasons', 'support', 'basis_event_ids', 'basis_heads', 'basis_refs', 'classification', 'judgment',
        'needs_review', 'candidate_id', 'completeness'})
    s.need(c['schema'] == 'dm.candidate/1' and c['rule'] == RULE)
    s.digest(c['candidate_id'])
    s.need(c['candidate_id'] == candidate_identity(c), 'Immutable candidate identity mismatch')
    s.ref(c['target'])
    s.fields(c['decision'], {'action', 'rationale'})
    s.string(c['decision']['action'])
    s.string(c['decision']['rationale'])
    s.refs(c['basis_heads'])
    s.refs(c['basis_refs'])
    s.sequence(c['basis_event_ids'])
    for eid in c['basis_event_ids']:
        s.identifier(eid)
    s.strings(c['reasons'])
    s.string(c['judgment'])
    s.string(c['needs_review'])
    s.need(c['classification'] in ('proposed_preview', 'candidate_semantic_impact'))
    d = c['delta']
    s.fields(d, {'schema', 'rule', 'subject_id', 'kind', 'old', 'new', 'event_id', 'fields',
                 'classes', 'actor', 'recorded_at', 'certainty', 'cosmetic_rule', 'delta_id', 'changes'})
    s.need(d['schema'] == 'dm.delta/1' and d['rule'] == RULE and d['certainty'] == 'verified_record_delta')
    s.need(d['delta_id'] == identity({k: v for k, v in d.items() if k != 'delta_id'}))
    s.identifier(d['subject_id'])
    s.need(d['kind'] in s.KINDS - {'finding'})
    for r in (d['old'], d['new']):
        if r is not None:
            s.ref(r)
            s.need(r['id'] == d['subject_id'])
    s.need(d['old'] is not None or d['new'] is not None)
    if d['event_id'] is not None:
        s.identifier(d['event_id'])
    s.strings(d['fields'])
    s.sequence(d['changes'])
    s.need([item['field'] for item in d['changes']] == d['fields'])
    for item in d['changes']:
        s.fields(item, {'field', 'before', 'after'})
        for name in ('before', 'after'):
            s.fields(item[name], {'text', 'sha256', 'truncated'})
            s.string(item[name]['text'], limit=400)
            s.digest(item[name]['sha256'], prefix=False)
            s.need(type(item[name]['truncated']) is bool)
    s.strings(d['classes'])
    s.need(set(d['classes']) <= {'content', 'context', 'provenance', 'availability', 'relationship', 'review', 'cosmetic'})
    s.string(d['actor'])
    s.stamp(d['recorded_at'])
    s.need(d['cosmetic_rule'] in (None, 'exact-payload-or-crlf/1'))
    s.sequence(c['paths'])
    s.need(1 <= len(c['paths']) <= LIMITS['paths'])
    for path in c['paths']:
        s.need(isinstance(path, list) and 1 <= len(path) <= LIMITS['depth'])
        for step in path:
            s.fields(step, {'from_ref', 'to_ref', 'relationship', 'kind', 'direction', 'revision', 'acceptance'})
            s.ref(step['from_ref'])
            s.ref(step['to_ref'])
            if step['relationship'] is not None:
                s.ref(step['relationship'])
            s.need(step['kind'] in ('explicit_input', 'supports', 'opposes', 'depends_on', 'checks', 'result_of'))
            s.need(step['direction'] in ('consumer', 'forward', 'reverse'))
            s.need(step['acceptance'] in ('accepted', 'proposed', 'rejected', 'recorded_input'))
            s.need(isinstance(step['revision'], str) and bool(re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', step['revision'])))
        s.need(path[-1]['to_ref'] == c['target'])
        s.need(all(a['to_ref'] == b['from_ref'] for a, b in zip(path, path[1:])))
    s.sequence(c['substitutions'])
    for substitution in c['substitutions']:
        s.fields(substitution, {'old', 'new'})
        s.ref(substitution['old'])
        s.ref(substitution['new'])
    s.sequence(c['comparison'])
    for comparison in c['comparison']:
        s.fields(comparison, {'status', 'reasons', 'intersection'})
        s.need(comparison['status'] in ('comparable', 'disjoint', 'unknown'))
        s.strings(comparison['reasons'])
        s.need(isinstance(comparison['intersection'], dict))
        for value in comparison['intersection'].values():
            s.dimension(value)
    s.fields(c['support'], {'remaining', 'removed', 'independence'})
    s.string(c['support']['independence'])
    for name in ('remaining', 'removed'):
        s.need(isinstance(c['support'][name], list) and len(c['support'][name]) <= 20)
        for item in c['support'][name]:
            s.fields(item, {'relationship', 'evidence', 'claim', 'sources', 'lineage_ids', 'lineage', 'status', 'independence'})
            for r in ('relationship', 'evidence', 'claim'):
                s.ref(item[r])
            s.refs(item['sources'])
            s.strings(item['lineage_ids'])
            s.need(item['lineage'] in ('unknown', 'shared', 'distinct_recorded_roots'))
            s.need(item['status'] in ('available', 'withdrawn_or_stale'))
            s.string(item['independence'])
    b = c['completeness']
    s.fields(b, {'truncated', 'hit_limits', 'limits', 'visited_objects', 'examined_links', 'retained_paths'})
    s.need(type(b['truncated']) is bool)
    s.strings(b['hit_limits'])
    s.fields(b['limits'], set(LIMITS))
    for name, limit in b['limits'].items():
        s.need(type(limit) is int and 1 <= limit <= LIMITS[name])
    for count, name in (('visited_objects', 'objects'), ('examined_links', 'links'), ('retained_paths', 'paths')):
        s.need(type(b[count]) is int and 0 <= b[count] <= b['limits'][name])

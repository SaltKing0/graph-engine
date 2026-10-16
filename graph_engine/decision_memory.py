"""Opt-in versioned Decision Memory storage, shared by capture/review adapters.

No model calls, source fetching or command execution. Reads never repair files.
Publication is one atomic sidecar replacement, after conservative ACL anchors.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat
from uuid import NAMESPACE_URL, uuid4, uuid5

from . import decision_schema as s
from .brain import Brain, Edge, Node, _atomic_write
from .write_guard import write_operation

TAG = 'decision-memory-v1'
SOURCE_TAG = 'decision-memory-source-v1'


class BasisUnavailable(PermissionError):
    """No existence, ID or payload details are exposed for inaccessible basis."""


class RecordPublished(RuntimeError):
    """Publication succeeded; commit/index/sync may need an explicit retry."""

    def __init__(self, receipt: dict) -> None:
        super().__init__('Decision Memory published locally; commit/index/sync incomplete. '
                         'Retry the identical request to obtain its receipt, then sync explicitly.')
        self.receipt = receipt


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def actor(brain: Brain) -> str:
    return getattr(brain, 'identity', 'local')


def anchor_text(record: dict) -> str:
    return f'Decision Memory v1 record: {record["kind"]} {record["id"]}. Read versioned content and assessment from the sidecar.'


def body(markdown: str) -> str:
    """Exact UTF-8 node body, including whitespace; Node's display parser strips."""
    match = re.match(r'^---\n.*?\n---\n\n?', markdown, re.DOTALL)
    s.need(match is not None, 'Invalid source Markdown')
    return markdown[match.end():]


def node_text(brain: Brain, nid: str) -> str:
    path = brain.node_path(nid)
    if not path.is_file() or path.is_symlink():
        raise BasisUnavailable('Record or basis unavailable')
    with path.open('r', encoding='utf-8', newline='') as stream:
        return body(stream.read())


def read_file(brain: Brain) -> dict:
    path = brain.path / s.FILENAME
    if not path.exists():
        if path.is_symlink():
            raise s.RecordError('Decision Memory must be a regular file')
        return s.empty()
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, 'rb') as stream:
            s.need(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'Decision Memory must be a regular file')
            raw = stream.read(s.MAX_BYTES + 1)
        s.need(len(raw) <= s.MAX_BYTES, 'Decision Memory exceeds 64 MiB')
        return s.loads(raw.decode('utf-8'))
    except OSError as exc:
        raise s.RecordError('Decision Memory file unavailable') from exc


def _heads(data: dict) -> dict:
    return {v['id']: v for v in data['versions']}


def _event_key(e: dict) -> str:
    return 'event:' + e['subject']['id'] + ':' + e['subject']['version_id'] + ':' + e['axis']


def event_identity(e: dict) -> str:
    return str(uuid5(NAMESPACE_URL, s.canonical({k: v for k, v in e.items() if k != 'event_id'})))


def resolve_local(value: object, created: dict[str, dict]) -> object:
    """Resolve only explicit, backward references within a bounded proposal."""
    if isinstance(value, dict):
        if set(value) == {'local'}:
            s.identifier(value['local'])
            s.need(value['local'] in created, 'Missing or forward local reference')
            return deepcopy(created[value['local']])
        return {k: resolve_local(v, created) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_local(v, created) for v in value]
    return value


class RecordView:
    """Validate sidecar lineage itself, in addition to persisted anchor ACLs.

    Historical views check both sets of node lineage under current policy.
    Logical dependency cycles never become cycles in source ACL provenance.
    """

    def __init__(self, brain: Brain, data: dict, *, nodes: dict[str, Node] | None = None,
                 texts: dict[str, str] | None = None, edges: list[Edge] | None = None,
                 current: tuple[dict[str, Node], list[Edge]] | None = None,
                 policy: dict | None = None, allow_tombstones: bool | None = None) -> None:
        from .access import derivation_parents
        self.brain, self.data = brain, data
        self.policy = policy
        self.current = current[0] if current else {n.id: n for n in Brain.read_nodes(brain)}
        self.current_parents = derivation_parents(self.current, current[1] if current else Brain.read_edges(brain, include_rejected=True))
        self.nodes = self.current if nodes is None else nodes
        self.historical = nodes is not None
        self.allow_tombstones = self.historical if allow_tombstones is None else allow_tombstones
        self.texts = texts
        self.parents = (self.current_parents if nodes is None else derivation_parents(self.nodes, edges or []))
        self.versions = {s.key(v): v for v in data['versions']}
        self.events = {e['event_id']: e for e in data['events']}
        self.event_heads = {_event_key(e): e['event_id'] for e in data['events']}
        self.event_positions = {e['event_id']: i for i, e in enumerate(data['events'])}
        self.reviews_by_id: dict[str, list[dict]] = {}
        for e in data['events']:
            self.reviews_by_id.setdefault(e['subject']['id'], []).append(e)
        self.heads = _heads(data)

    def node_allowed(self, nid: str, action: str = 'read') -> bool:
        from .access import provenance_allowed
        # Current missing lineage is never treated as a new writable root.
        def check(source: str) -> bool:
            n = self.current.get(source)
            from .access import SecuredBrain, permitted
            access = (permitted(self.brain.graph_name, self.brain.identity, action, source, _policy=self.policy)
                      if isinstance(self.brain, SecuredBrain) and self.policy is not None else
                      self.brain.can_access(action, source, _view=(self.current, self.current_parents))
                      if isinstance(self.brain, SecuredBrain) else self.brain.can_access(action, source))
            return (n is not None and (self.allow_tombstones or n.status != 'tombstone')
                    and access)
        def historical_check(source: str) -> bool:
            n = self.nodes.get(source)
            return (n is not None and (self.allow_tombstones or n.status != 'tombstone')
                    and check(source))
        return (provenance_allowed(nid, self.current, self.current_parents, check)
                and provenance_allowed(nid, self.nodes, self.parents, historical_check))

    def inputs(self, v: dict) -> list[dict]:
        return s.content_refs({'payload': v['payload'], 'provenance': v['provenance']})

    def dependencies(self, item: dict, *, reviews: bool = False) -> tuple[set[tuple], set[str]]:
        versions, nodes, seen_events = set(), set(), set()
        pending = [item]
        while pending:
            value = pending.pop()
            if 'event_id' in value:
                if value['event_id'] in seen_events:
                    continue
                seen_events.add(value['event_id'])
                pending.append(self.versions[s.key(value['subject'])])
                for b in value['basis']:
                    if b['type'] == 'content_ref':
                        pending.append(self.versions[s.key(b['ref'])])
                    elif b['type'] == 'event_ref':
                        pending.append(self.events[b['event_id']])
                    else:
                        # Include the source's complete recorded lineage, not
                        # just the node named in the direct source basis.
                        pending.extend(v for v in self.versions.values() if v['kind'] == 'source'
                                       and v['payload']['source_ref'] == b['ref'])
                # Authorization retains the entire history; a fresh review
                # does not inherit the basis of the judgment it replaces.
                if reviews and value['previous_event_id']:
                    pending.append(self.events[value['previous_event_id']])
            else:
                k = s.key(value)
                if k in versions:
                    continue
                versions.add(k)
                nodes.add(value['anchor_node_id'])
                pending.extend(self.versions[s.key(r)] for r in self.inputs(value))
                if value['kind'] == 'finding':
                    pending.extend(self.events[eid] for eid in value['payload']['candidate']['basis_event_ids'])
                if reviews:
                    pending.extend(self.reviews_by_id.get(value['id'], []))
        return versions, nodes

    def allowed(self, item: dict, action: str = 'read') -> bool:
        versions, nodes = self.dependencies(item, reviews=True)
        if not all(self.node_allowed(nid, action) for nid in nodes):
            return False
        for k in versions:
            v = self.versions[k]
            anchor = self.nodes.get(v['anchor_node_id'])
            if anchor is None:
                return False
            if v['kind'] != 'source' and (TAG not in anchor.tags or anchor.text != anchor_text(v)):
                return False
            # Manual ACL edits cannot launder copied text out of an anchor.
            required = self.source_nodes(v) - {v['anchor_node_id']}
            if not required <= set(anchor.derived_from):
                return False
        return True

    def source_nodes(self, item: dict) -> set[str]:
        versions, _ = self.dependencies(item, reviews=True)
        return {self.versions[k]['anchor_node_id'] for k in versions if self.versions[k]['kind'] == 'source'}

    def changed(self, item: dict, *, terminal_decision: bool = False) -> bool:
        subject = self.versions[s.key(item['subject'])] if 'event_id' in item else item
        if subject['kind'] == 'finding':
            # Old versions in an impact path explain a change. Freshness is
            # pinned separately to the selected after revision's relevant heads.
            candidate = subject['payload']['candidate']
            if self.heads[subject['id']] != subject:
                return True
            if 'event_id' in item and item['axis'] == 'finding_workflow':
                # Acknowledge/resolve the recorded candidate even when newer
                # evidence exists. This does not reopen it or replace its basis.
                return any(self.changed(self.events[b['event_id']]) for b in item['basis']
                           if b['type'] == 'event_ref')
            for r in candidate['basis_heads']:
                v = self.versions[s.key(r)]
                if self.heads[v['id']] != v:
                    return True
                if v['kind'] == 'source':
                    try:
                        text = self.texts[v['anchor_node_id']] if self.texts is not None else node_text(self.brain, v['anchor_node_id'])
                    except (KeyError, BasisUnavailable):
                        return True
                    if s.text_hash(text) != v['payload']['source_ref']['text_sha256']:
                        return True
            # Historical basis events remain cited; a newer event on the same
            # chain makes this candidate stale until explicitly regenerated.
            latest = {}
            for eid in sorted(candidate['basis_event_ids'], key=self.event_positions.get):
                e = self.events[eid]
                latest[_event_key(e)] = eid
            relevant = {s.key(r) for r in s.content_refs(candidate)}
            # New accepted support is an incoming dependency: it cannot be
            # found by checking only versions/events already in this candidate.
            # Comparisons pin all selected support heads, even when the readable
            # support summary is clipped. Check membership before publication.
            claims = {s.key(r) for path in candidate['paths'] for step in path
                      for r in (step['from_ref'], step['to_ref'])
                      if self.versions[s.key(r)]['kind'] == 'claim'}
            workflows = {s.key(e['subject']): e['to'] for e in self.data['events'] if e['axis'] == 'workflow'}
            for v in self.heads.values():
                if (v['kind'] == 'relationship' and v['payload']['kind'] == 'supports'
                        and s.key(v['payload']['target']) in claims and s.key(v) not in relevant
                        and workflows.get(s.key(v)) == 'accepted' and self.allowed(v)):
                    return True
            current = {_event_key(e): e['event_id'] for e in self.data['events'] if s.key(e['subject']) in relevant}
            return current != latest
        versions, _ = self.dependencies(item)
        for k in versions:
            v = self.versions[k]
            is_subject = 'event_id' in item and k == s.key(item['subject'])
            if s.key(self.heads[v['id']]) != k and not (terminal_decision and is_subject):
                return True
            if v['kind'] == 'source':
                try:
                    text = self.texts[v['anchor_node_id']] if self.texts is not None else node_text(self.brain, v['anchor_node_id'])
                except (KeyError, BasisUnavailable, s.RecordError):
                    return True
                if s.text_hash(text) != v['payload']['source_ref']['text_sha256']:
                    return True
        # Check every referenced judgment's own basis, including withdrawals
        # since that judgment. Restoring an input cannot refresh its reviews.
        pending = [item] if 'event_id' in item else []
        seen = set()
        while pending:
            judgment = pending.pop()
            if judgment['event_id'] in seen:
                continue
            seen.add(judgment['event_id'])
            for b in judgment['basis']:
                if b['type'] != 'event_ref':
                    continue
                before = self.events[b['event_id']]
                if self.event_heads[_event_key(before)] != before['event_id']:
                    return True
                pending.append(before)
            basis_versions, _ = self.dependencies(judgment)
            basis_keys = basis_versions - {s.key(judgment['subject'])}
            availability = {}
            for e in self.data['events']:
                if s.key(e['subject']) in basis_keys and e['axis'] == 'availability':
                    availability[s.key(e['subject'])] = e['to']
                    # A restored basis still requires a fresh review.
                    if (e['to'] == 'withdrawn' and self.event_positions[e['event_id']] >
                            self.event_positions[judgment['event_id']]):
                        return True
            if 'withdrawn' in availability.values():
                return True
        return False

    def export(self) -> dict:
        visible = [v for v in self.data['versions'] if self.allowed(v)]
        visible_keys = {s.key(v) for v in visible}
        events = [e for e in self.data['events'] if s.key(e['subject']) in visible_keys and self.allowed(e)]
        # Receipts contain request identities and potentially hidden refs. They
        # are only returned for an authorized matching retry, never an export.
        return deepcopy(dict(schema=s.SCHEMA, generation=self.data['generation'], versions=visible,
                             events=events, deltas=[], candidates=[]))

    def get(self, reference: dict) -> dict:
        s.ref(reference)
        v = self.versions.get(s.key(reference))
        if v is None or not self.allowed(v):
            raise BasisUnavailable('Record or basis unavailable')
        events = [e for e in self.data['events'] if e['subject'] == reference]
        visible = [e for e in events if self.allowed(e)]
        state = {axis: s.INITIAL[axis] for axis in s.AXES[v['kind']]}
        changed, hidden = self.changed(v), len(visible) != len(events)
        judgments = {}
        for e in visible:
            state[e['axis']] = e['to']
            if e['axis'] == 'epistemic':
                judgments['epistemic'] = e
            elif e['axis'] in ('decision', 'decision_conclusion'):
                # Activation supplies the initial justification; a subsequent
                # decision review can replace it without changing lifecycle.
                judgments['decision'] = e
        if v['kind'] == 'finding' and state['finding_disposition'] != 'confirmed':
            state['finding_workflow'] = None
        changed = changed or any(self.changed(e) for e in judgments.values())
        # Hidden reviews cannot confer their recorded assessment.
        effective = ('inconclusive' if changed or hidden else state.get('epistemic', 'unassessed'))
        dependencies, _ = self.dependencies(v, reviews=True)
        hypothetical = any(self.versions[k]['kind'] == 'result' and self.versions[k]['payload']['hypothetical']
                           for k in dependencies)
        return deepcopy(dict(record=v, events=visible, state=state, basis_changed=changed or hidden,
                             effective_assessment=effective, hypothetical=hypothetical))


class DecisionMemory:
    """Low-level typed persistence API used by the shared capture/review service."""

    def __init__(self, brain: Brain) -> None:
        self.brain = brain

    def get(self, reference: dict) -> dict:
        self.brain.authorize('read')
        return RecordView(self.brain, read_file(self.brain)).get(reference)

    def export(self) -> dict:
        self.brain.authorize('read')
        return RecordView(self.brain, read_file(self.brain)).export()

    def preview(self) -> dict:
        self.brain.authorize('read')
        data = read_file(self.brain)
        view = RecordView(self.brain, data)
        heads = {vid: v['version_id'] for vid, v in view.heads.items() if view.allowed(v)}
        if hasattr(self.brain, 'identity'):
            from .access import load_policy
            # Opaque policy fingerprint protects a review preview across ACL
            # edits without persisting or exposing policy contents.
            heads['authorization'] = s.hash_record(load_policy())
        for e in data['events']:
            if view.allowed(e):
                heads[_event_key(e)] = e['event_id']
        for v in data['versions']:
            if v['kind'] == 'source' and view.allowed(v):
                heads['source:' + v['anchor_node_id']] = s.text_hash(node_text(self.brain, v['anchor_node_id']))
        return dict(schema=s.SCHEMA, generation=data['generation'], heads=heads)

    def source_payload(self, node_id: str, *, locator: str, lineage_ids: list[str] | None = None,
                       artifact: dict | None = None, revision: str | None = None) -> dict:
        self.brain.authorize('read', node_id)
        view = RecordView(self.brain, read_file(self.brain))
        if not view.node_allowed(node_id):
            raise BasisUnavailable('Record or basis unavailable')
        text = node_text(self.brain, node_id)
        if revision is not None:
            _check_revision(self.brain, node_id, text, revision)
        return dict(source_ref=dict(node_id=node_id, text_sha256=s.text_hash(text), revision=revision),
                    text=text, artifact=artifact, locator=locator, lineage_ids=lineage_ids or [])

    @write_operation
    def transact(self, request: dict, *, commit: bool = True, dry_run: bool = False) -> dict:
        """Append drafts/events and a durable receipt in one guarded publication.

        Callers supply UUIDs and exact predecessor refs; server supplies actor,
        clock, hashes and event IDs. A request's previews are part of its retry
        identity. Never retry a changed request under the same key.
        """
        b = self.brain
        b.authorize('write')
        s.fields(request, {'schema', 'idempotency_key', 'expected_generation', 'expected_heads', 'versions', 'events'})
        if request['schema'] != s.SCHEMA:
            raise s.UnsupportedSchema('Unsupported write schema')
        s.string(request['idempotency_key'], limit=200)
        s.need(type(request['expected_generation']) is int and isinstance(request['expected_heads'], dict))
        s.sequence(request['versions'])
        s.sequence(request['events'])
        s.need(bool(request['versions'] or request['events']), 'Empty transaction')
        request_hash = s.hash_record(request)
        # An already published local receipt takes precedence over pull/sync.
        # Even a failed commit must not duplicate accepted records on retry.
        data = read_file(b)
        replay = self._replay(data, request, request_hash)
        if replay is not None:
            return replay
        if not dry_run:
            b.ensure_ready()
            b.pull()
        data = read_file(b)
        replay = self._replay(data, request, request_hash)
        if replay is not None:
            return replay
        preview = self.preview()
        if (preview['generation'] != request['expected_generation']
                or preview['heads'] != request['expected_heads']):
            raise s.RecordConflict('Decision Memory preview changed; refresh before writing')
        new = deepcopy(data)
        timestamp, identity = now(), actor(b)
        created = []
        local = {}
        for draft in request['versions']:
            s.fields(draft, {'id', 'kind', 'anchor_node_id', 'previous', 'provenance', 'payload'})
            draft = resolve_local(draft, local)
            version = dict(schema='dm.content/1', recorded_at=timestamp, recorded_by=identity, **deepcopy(draft))
            version['version_id'] = s.hash_record(version)
            new['versions'].append(version)
            created.append(s.reference(version))
            local[version['id']] = s.reference(version)
        event_ids = []
        by_ref = {s.key(v): v for v in new['versions']}
        heads = _heads(new)
        for draft in request['events']:
            s.fields(draft, {'subject', 'axis', 'from', 'to', 'previous_event_id', 'basis', 'reason', 'supersedes_event_id'})
            draft = resolve_local(draft, local)
            e = dict(schema='dm.event/1', reviewer=identity, reviewed_at=timestamp,
                     expected_heads={}, **deepcopy(draft))
            s.ref(e['subject'])
            # Never embed the full preview: unrelated records may later be
            # revoked while this event remains readable.
            e['event_id'] = 'pending'
            try:
                dependencies, source_nodes = RecordView(b, new).dependencies(e)
            except (KeyError, TypeError, AttributeError) as exc:
                raise s.RecordError('Malformed or unavailable event basis') from exc
            ids = {vid for vid, _ in dependencies}
            e['expected_heads'] = {k: val for k, val in preview['heads'].items()
                                   if k in ids or k == 'authorization'
                                   or k.startswith('source:') and k[7:] in source_nodes
                                   or k.startswith('event:') and any(k.startswith('event:' + vid + ':') for vid in ids)}
            e['event_id'] = event_identity(e)
            new['events'].append(e)
            event_ids.append(e['event_id'])
            # New review of an old head is stale even when it was just explicitly
            # requested. History is immutable; users must review the successor.
            subject = by_ref.get(s.key(e['subject']))
            terminal = e['axis'] == 'decision' and e['from'] == 'current' and e['to'] in ('superseded', 'withdrawn')
            if subject is not None and heads[subject['id']] != subject and not terminal:
                raise s.RecordConflict('Review target is no longer the content head')
        new['generation'] += 1
        receipt = dict(key=request['idempotency_key'], request_hash=request_hash, actor=identity,
                       refs=created, event_ids=event_ids, generation=new['generation'])
        new['receipts'].append(receipt)
        s.validate(new)  # Validate before changing ANY anchor or file.
        view = RecordView(b, new)
        changed = [by_ref[s.key(r)] for r in created] + [view.events[eid] for eid in event_ids]
        # A review may introduce source restrictions to an already-referenced
        # claim. Propagate that new union to existing dependent anchors in this
        # same publication; otherwise even authorized readers could no longer
        # inspect/review those dependents. Never repair pre-existing tampering.
        before_view = RecordView(b, data)
        for old in data['versions']:
            added = view.source_nodes(old) - before_view.source_nodes(old)
            if added and old not in changed:
                if not before_view.allowed(old, 'write'):
                    raise BasisUnavailable('Record or basis unavailable')
                changed.append(old)
        planned = {}
        # Construct all anchors before testing provenance, so no half-published
        # review can reference an absent input. Nothing is written yet.
        for v in (by_ref[s.key(r)] for r in created):
            nid = v['anchor_node_id']
            old = view.current.get(nid)
            if v['kind'] == 'source':
                if old is None or not view.node_allowed(nid, 'write'):
                    raise BasisUnavailable('Record or basis unavailable')
                if node_text(b, nid) != v['payload']['text']:
                    raise s.RecordConflict('Source bytes changed')
                if v['payload']['source_ref']['revision'] is not None:
                    _check_revision(b, nid, v['payload']['text'], v['payload']['source_ref']['revision'])
                n = deepcopy(old)
                n.tags = sorted(set(n.tags) | {SOURCE_TAG})
            else:
                if old is not None and (TAG not in old.tags or old.text != anchor_text(v)):
                    raise s.RecordConflict('Record anchor identity changed')
                n = deepcopy(old) if old else Node(anchor_text(v), id=nid, tags=[TAG])
            planned[nid] = n
        # Reviews may introduce additional source restrictions; rejected or
        # corrected events never remove dependencies already persisted.
        for item in changed:
            v = view.versions[s.key(item['subject'])] if 'event_id' in item else item
            nid = v['anchor_node_id']
            if nid not in planned:
                old = view.current.get(nid)
                if old is None:
                    raise BasisUnavailable('Record or basis unavailable')
                planned[nid] = deepcopy(old)
            n = planned[nid]
            sources = view.source_nodes(item) - {nid}
            n.derived_from = sorted(set(n.derived_from) | sources)
        view.current.update(planned)
        view.nodes = view.current
        from .access import derivation_parents
        view.current_parents = derivation_parents(view.current, Brain.read_edges(b, include_rejected=True))
        view.parents = view.current_parents
        for item in changed:
            if not view.allowed(item, 'write'):
                raise BasisUnavailable('Record or basis unavailable')
            if 'event_id' in item:
                terminal = item['axis'] == 'decision' and item['from'] == 'current' and item['to'] in ('superseded', 'withdrawn')
                if view.changed(item, terminal_decision=terminal):
                    raise s.RecordConflict('Review basis is stale; refresh the content and basis')
                # A hypothetical result may be kept as a labelled example but
                # cannot establish support or justify a real decision.
                deps, _ = view.dependencies(item)
                if item['to'] in ('supported', 'current', 'remains_justified') and any(
                        view.versions[k]['kind'] == 'result' and view.versions[k]['payload']['hypothetical'] for k in deps):
                    raise s.RecordError('Hypothetical results cannot justify a real decision')
        if dry_run:
            return deepcopy(dict(dry_run=True, receipt=receipt,
                                 versions=[by_ref[s.key(r)] for r in created],
                                 events=[view.events[eid] for eid in event_ids],
                                 anchor_sources={nid: n.derived_from for nid, n in planned.items()}))
        # The source union of a review must also persist on the subject anchor.
        # All writes below reuse the same brain guard. Orphan labelled anchors
        # after interruption are safe and may be reused by the identical retry.
        for n in planned.values():
            b.write_node(n)
        # Anchor preparation may be interrupted or race a trusted manual file
        # edit. Check the actual files/policy once more before publication.
        final = RecordView(b, new)
        for item in changed:
            if not final.allowed(item, 'write'):
                raise BasisUnavailable('Record or basis unavailable')
            if 'event_id' in item:
                terminal = item['axis'] == 'decision' and item['from'] == 'current' and item['to'] in ('superseded', 'withdrawn')
                if final.changed(item, terminal_decision=terminal):
                    raise s.RecordConflict('Review basis changed before publication')
        if hasattr(b, 'identity'):
            from .access import load_policy
            if s.hash_record(load_policy()) != preview['heads']['authorization']:
                raise s.RecordConflict('Access policy changed before publication')
        if read_file(b) != data:
            raise s.RecordConflict('Sidecar changed before publication')
        _atomic_write(b.path / s.FILENAME, s.canonical(new) + '\n')
        try:
            b.rebuild_index()
            if commit:
                b.commit_and_push('decision-memory: publish versioned records')
        except Exception as exc:
            raise RecordPublished(deepcopy(receipt)) from exc
        return deepcopy(receipt)

    def _replay(self, data: dict, request: dict, request_hash: str) -> dict | None:
        for receipt in data['receipts']:
            if receipt['key'] != request['idempotency_key']:
                continue
            if receipt['actor'] != actor(self.brain):
                raise BasisUnavailable('Record or basis unavailable')
            view = RecordView(self.brain, data)
            items = [view.versions[s.key(r)] for r in receipt['refs']] + [view.events[eid] for eid in receipt['event_ids']]
            if not all(view.allowed(item, 'write') for item in items):
                raise BasisUnavailable('Record or basis unavailable')
            if receipt['request_hash'] != request_hash:
                raise s.RecordConflict('Idempotency key reused with a different request')
            return deepcopy(receipt)
        return None


def _check_revision(brain: Brain, node: str, text: str, revision: str) -> None:
    from .snapshots import _records, SnapshotError
    try:
        sha, _, records = _records(brain, revision)
        s.need(sha == revision and body(records[f'nodes/{node}.md']) == text,
               'Pinned Git source content/version mismatch')
    except (SnapshotError, KeyError) as exc:
        raise s.RecordError('Pinned Git source revision unavailable') from exc


def check_merge(brain: Brain, node_ids: set[str]) -> None:
    """No version-unaware reassignment of pinned sources or anchor identities."""
    data = read_file(brain)
    pinned = {v['anchor_node_id'] for v in data['versions']}
    if node_ids & pinned:
        raise s.RecordConflict('Pinned Decision Memory nodes require a version-aware merge')


def prepare_node_write(brain: Brain, node: Node, markdown: str) -> dict | None:
    """Prepare a source successor before a normal node edit; publish after it.

    An interrupted node/sidecar pair fails freshness checks. A subsequent write
    reconciles that exact current text as a successor; reads never repair it.
    """
    path = brain.path / s.FILENAME
    if not path.exists():
        if TAG in node.tags or SOURCE_TAG in node.tags:
            # Initial anchor publication is performed before the sidecar exists.
            return None
        return None
    data = read_file(brain)
    versions = [v for v in data['versions'] if v['anchor_node_id'] == node.id]
    if not versions:
        return None
    head = versions[-1]
    existing = Brain.read_node(brain, node.id)
    if existing is None or existing.status == 'tombstone' and node.status != 'tombstone':
        raise s.RecordConflict('Missing or forgotten pinned content cannot be recreated')
    if not set(existing.derived_from) <= set(node.derived_from):
        raise s.RecordConflict('Pinned source lineage cannot be removed')
    if head['kind'] != 'source':
        if node.text != anchor_text(head) or TAG not in node.tags:
            raise s.RecordConflict('Decision Memory anchors cannot be text-edited')
        return None
    if SOURCE_TAG not in node.tags:
        raise s.RecordConflict('Pinned source marker cannot be removed')
    text = body(markdown)
    if text == head['payload']['text']:
        return None
    successor = deepcopy(head)
    successor.update(previous=s.reference(head), recorded_at=now(), recorded_by=actor(brain))
    successor['payload']['text'] = text
    successor['payload']['source_ref']['text_sha256'] = s.text_hash(text)
    successor['payload']['source_ref']['revision'] = None
    # Artifact bytes no longer describe the edited node's text extraction.
    successor['payload']['artifact'] = None
    successor['provenance'] = {'method': 'manual', 'inputs': head['provenance']['inputs']}
    successor['version_id'] = s.hash_record(successor)
    data['versions'].append(successor)
    data['generation'] += 1
    s.validate(data)
    return data

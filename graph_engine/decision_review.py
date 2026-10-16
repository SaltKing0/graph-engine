"""Bounded review projections over the existing Decision Memory contracts."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .decision_service import DecisionService

from . import decision_schema as s
from .brain import Brain
from .decision_impact import authorization, current_fingerprint
from .decision_memory import RecordView, read_file

QUEUE_LIMIT = 50
DETAIL_LIMIT = 200
DETAIL_DEPTH = 3


class ReviewReader:
    def __init__(self, service: DecisionService) -> None:
        self.service = service
        self.brain = service.brain
        self.preview = service.preview()
        self.policy = authorization(self.brain)
        self.fingerprint = self.current()
        self.view = RecordView(self.brain, read_file(self.brain))

    def current(self) -> str:
        return current_fingerprint(({n.id: n for n in Brain.read_nodes(self.brain)},
                                    Brain.read_edges(self.brain, include_rejected=True)))

    def finish(self, result: dict) -> dict:
        if (self.preview != self.service.preview() or self.policy != authorization(self.brain)
                or self.fingerprint != self.current()):
            raise s.RecordConflict('Evidence or permissions changed during review; refresh')
        return dict(result, preview=self.preview)

    def queue(self, envelope: dict) -> dict:
        s.fields(envelope, set(), {'comparison', 'history'})
        history = envelope.get('history', False)
        s.need(type(history) is bool, 'history must be a boolean')
        entries, recorded = [], set()
        versions = self.view.data['versions'] if history else self.view.heads.values()
        for v in self.view.data['versions']:
            if v['kind'] == 'finding' and self.view.allowed(v):
                recorded.add(v['payload']['candidate']['candidate_id'])
        for v in versions:
            if v['kind'] != 'finding' or not self.view.allowed(v):
                continue
            item = self.view.get(s.reference(v))
            state = item['state']
            if not history and (state['finding_disposition'] == 'dismissed'
                                or state['finding_workflow'] in ('acknowledged', 'resolved')):
                continue
            entries.append(dict(kind='finding', reference=s.reference(v), item=item,
                                candidate=v['payload']['candidate']))
        comparison = None
        if 'comparison' in envelope:
            comparison = self.service.compare(envelope['comparison'])
            pinned = dict(schema='dm.compare/1', before=comparison['before']['revision'],
                          after=comparison['after']['revision'])
            # Keep lower caller bounds when regenerating a candidate for review.
            if 'limits' in envelope['comparison']:
                pinned['limits'] = envelope['comparison']['limits']
            entries.extend(dict(kind='candidate', candidate=c, comparison=pinned)
                           for c in comparison['candidates'] if c['candidate_id'] not in recorded)
        entries.sort(key=lambda e: (e['candidate']['delta']['recorded_at'], e['candidate']['candidate_id']), reverse=True)
        return self.finish(dict(schema='dm.review-queue/1', items=entries[:QUEUE_LIMIT],
            truncated=len(entries) > QUEUE_LIMIT or bool(comparison and comparison['completeness']['truncated']),
            limit=QUEUE_LIMIT, comparison=comparison and dict(before=comparison['before'], after=comparison['after'],
                completeness=comparison['completeness'], warnings=comparison['warnings'])))

    def detail(self, envelope: dict) -> dict:
        if 'reference' in envelope:
            s.fields(envelope, {'reference'})
            item = self.view.get(envelope['reference'])
            s.need(item['record']['kind'] == 'finding', 'Review detail requires a finding')
            candidate = item['record']['payload']['candidate']
        else:
            s.fields(envelope, {'comparison', 'candidate_id'})
            s.digest(envelope['candidate_id'])
            result = self.service.compare(envelope['comparison'])
            candidate = next((c for c in result['candidates'] if c['candidate_id'] == envelope['candidate_id']), None)
            if candidate is None:
                raise s.RecordConflict('Candidate changed or unavailable; refresh')
            item = None
        # Exact pinned objects plus their current successors and review basis.
        # Never fall back to an older accessible version of a hidden head.
        selected = set()
        refs = list(s.content_refs(candidate))
        refs.append(candidate['target'])
        for ref in refs:
            self.view.get(ref)
            selected.add(s.key(ref))
            head = self.view.heads[ref['id']]
            if self.view.allowed(head):
                selected.add(s.key(head))
        truncated = len(selected) > DETAIL_LIMIT
        selected = set(sorted(selected)[:DETAIL_LIMIT])
        # Add support, opposition, checks and explicit dependencies symmetrically.
        for depth in range(DETAIL_DEPTH + 1):
            extra = set()
            for key in selected:
                deps, _ = self.view.dependencies(self.view.versions[key], reviews=True)
                extra.update(deps)
            for v in self.view.heads.values():
                if v['kind'] != 'relationship' or not self.view.allowed(v):
                    continue
                p = v['payload']
                if p['kind'] not in ('supports', 'opposes', 'depends_on', 'checks', 'result_of'):
                    continue
                if s.key(p['target']) in selected or s.key(p['source']) in selected:
                    extra.update((s.key(v), s.key(p['source']), s.key(p['target'])))
            for key in sorted(extra - selected):
                if self.view.allowed(self.view.versions[key]):
                    if len(selected) == DETAIL_LIMIT or depth == DETAIL_DEPTH:
                        truncated = True
                        break
                    selected.add(key)
        records = [self.view.get(dict(id=i, version_id=h)) for i, h in sorted(selected)]
        return self.finish(dict(schema='dm.review-detail/1', candidate=candidate, finding=item,
            records=records, truncated=truncated or candidate['completeness']['truncated'],
            limit=DETAIL_LIMIT))

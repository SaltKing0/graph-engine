"""Storage, provenance, historical access and interruption regressions for #76."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from graph_engine.brain import Brain, Node
from graph_engine.decision_memory import (DecisionMemory, RecordView, BasisUnavailable,
                                          RecordPublished, body, read_file)
from graph_engine import decision_schema as s
from graph_engine.merge import merge_nodes
from graph_engine.snapshots import snapshot, SnapshotError


def uid():
    return str(uuid4())


def draft(kind, payload, *, previous=None, identity=None, anchor=None, inputs=None):
    return dict(id=identity or uid(), kind=kind, anchor_node_id=anchor or uid(),
                previous=previous, provenance={'method': 'manual', 'inputs': inputs or []}, payload=payload)


def request(store, versions=(), events=(), *, retry_key=None):
    preview = store.preview()
    return dict(schema=s.SCHEMA, idempotency_key=retry_key or uid(), expected_generation=preview['generation'],
                expected_heads=preview['heads'], versions=list(versions), events=list(events))


def save(store, *versions):
    return store.transact(request(store, versions), commit=False)['refs']


def claim(text='Graph expansion stays opt-in', context=None, **kwargs):
    return draft('claim', dict(text=text, context=context, limitations=[]), **kwargs)


def source(store, node='source', text='Measured recall is 0.8', *, inputs=None):
    if store.brain.read_node(node) is None:
        store.brain.write_node(Node(text, id=node))
    return draft('source', store.source_payload(node, locator=f'nodes/{node}.md', lineage_ids=['experiment-1']),
                 anchor=node, inputs=inputs)


def evidence(src, quote='Measured recall', **kwargs):
    return draft('evidence', dict(interpretation='Limited synthetic observation', context=None,
                                 sources=[{'ref': src, 'passage': {'start': 0, 'end': len(quote), 'quote': quote}}],
                                 lineage_ids=['experiment-1'], limitations=['Synthetic only']), **kwargs)


def event(subject, *, axis='epistemic', before='unassessed', after='supported', basis=(), previous=None, correct=None):
    return dict(subject=subject, axis=axis, **{'from': before, 'to': after}, basis=list(basis),
                previous_event_id=previous, supersedes_event_id=correct, reason='Explicit review of the supplied basis')


def content_basis(r):
    return {'type': 'content_ref', 'ref': r}


def review(store, target, basis, **kwargs):
    return store.transact(request(store, events=[event(target, basis=[content_basis(basis)], **kwargs)]), commit=False)


@pytest.fixture
def store(tmp_path):
    b = Brain(str(tmp_path / 'brain'))
    b.init()
    return DecisionMemory(b)


def files(brain):
    return {str(p.relative_to(brain.path)): p.read_bytes() for p in brain.path.rglob('*')
            if p.is_file() and '.git' not in p.relative_to(brain.path).parts}


def assessed(store):
    src, = save(store, source(store))
    ev, = save(store, evidence(src))
    c, = save(store, claim())
    r = review(store, c, ev)
    return src, ev, c, r


def test_legacy_reads_and_construction_do_not_migrate(store):
    before = files(store.brain)
    assert store.export()['versions'] == []
    assert store.preview()['generation'] == 0
    assert not (store.brain.path / s.FILENAME).exists()
    assert files(store.brain) == before


def test_round_trip_canonical_and_exact_quotes(store):
    src, ev, c, receipt = assessed(store)
    data = read_file(store.brain)
    assert s.loads(s.canonical(data)) == data
    assert (store.brain.path / s.FILENAME).read_text() == s.canonical(data) + '\n'
    view = DecisionMemory(Brain(str(store.brain.path))).get(c)
    assert view['state']['epistemic'] == view['effective_assessment'] == 'supported'
    assert not view['basis_changed']
    assert view['events'][0]['reviewer'] == 'local'
    assert view['events'][0]['subject'] == c
    assert store.get(ev)['state']['epistemic'] == 'unassessed'
    assert store.get(src)['record']['payload']['text'].endswith('\n')
    assert 'receipts' not in store.export()


def test_claim_wording_and_context_edit_never_transfer_review(store):
    src, ev, c, _ = assessed(store)
    old = store.get(c)['record']
    next_draft = claim('Expansion is suitable only for diagnostics', previous=c, identity=c['id'], anchor=old['anchor_node_id'])
    new, = save(store, next_draft)
    assert new['id'] == c['id'] and new != c
    assert store.get(new)['effective_assessment'] == 'unassessed'
    assert store.get(new)['events'] == []
    assert store.get(c)['events'][0]['subject'] == c
    with pytest.raises(s.RecordConflict, match='head'):
        review(store, c, ev)
    assert store.get(ev)['record']['payload']['sources'][0]['ref'] == src


def test_source_edit_versions_exact_bytes_and_marks_basis_changed(store):
    src, ev, c, _ = assessed(store)
    n = store.brain.read_node('source')
    n.text = 'A different measured observation  '
    store.brain.write_node(n)
    sources = [v for v in store.export()['versions'] if v['kind'] == 'source']
    assert len(sources) == 2
    assert sources[-1]['previous'] == src
    assert sources[-1]['payload']['text'] == 'A different measured observation  \n'
    assert sources[0]['payload']['text'] == 'Measured recall is 0.8\n'
    assert store.get(c)['state']['epistemic'] == 'supported'
    assert store.get(c)['effective_assessment'] == 'inconclusive'
    assert store.get(c)['basis_changed']
    assert store.get(ev)['record']['payload']['sources'][0]['ref'] == src


def test_source_capture_preserves_leading_trailing_and_crlf_bytes(store):
    n = Node('  exact\r\ntext  \n', id='whitespace')
    store.brain.write_node(n)
    original = body(store.brain.node_path(n.id).read_bytes().decode())
    src, = save(store, source(store, node=n.id))
    assert store.get(src)['record']['payload']['text'] == original
    assert body(store.brain.node_path(n.id).read_bytes().decode()) == original
    store.brain.promote_node(n.id)
    assert body(store.brain.node_path(n.id).read_bytes().decode()) == original
    assert len(store.export()['versions']) == 1


def test_manual_source_edit_is_detected_without_read_repair(store):
    _, _, c, _ = assessed(store)
    path = store.brain.node_path('source')
    path.write_text(path.read_text().replace('Measured', 'Unmeasured'))
    before = files(store.brain)
    assert store.get(c)['basis_changed']
    assert store.get(c)['effective_assessment'] == 'inconclusive'
    assert files(store.brain) == before


def test_tombstone_and_deletion_hide_all_dependent_bodies(store):
    src, ev, c, _ = assessed(store)
    store.brain.tombstone_node('source')
    assert store.export()['versions'] == []
    for r in (src, ev, c):
        with pytest.raises(BasisUnavailable):
            store.get(r)
    with pytest.raises(s.RecordConflict, match='forgotten'):
        store.brain.promote_node('source')
    store.brain.node_path('source').unlink()
    with pytest.raises(BasisUnavailable):
        store.get(c)
    with pytest.raises(s.RecordConflict, match='Missing'):
        store.brain.write_node(Node('recreated', id='source'))


def test_pinned_merge_refuses_before_any_changes(store):
    save(store, source(store))
    store.brain.write_node(Node('ordinary', id='other'))
    before = files(store.brain)
    with pytest.raises(s.RecordConflict, match='version-aware'):
        merge_nodes(store.brain, 'source', 'other', commit=False)
    assert files(store.brain) == before
    store.brain.write_node(Node('another', id='third'))
    merge_nodes(store.brain, 'other', 'third', commit=False)
    assert store.brain.read_node('third').status == 'tombstone'


def test_retry_is_durable_read_only_and_payload_mismatch_conflicts(store, monkeypatch):
    req = request(store, [claim()])
    receipt = store.transact(req, commit=False)
    before = files(store.brain)
    monkeypatch.setattr(store.brain, 'pull', lambda: pytest.fail('Retry pulled'))
    assert DecisionMemory(store.brain).transact(req) == receipt
    assert files(store.brain) == before
    req['versions'][0]['payload']['text'] = 'different'
    with pytest.raises(s.RecordConflict, match='Idempotency'):
        store.transact(req)
    assert files(store.brain) == before


def test_stale_generation_and_source_hash_previews_conflict(store):
    src, ev, c, _ = assessed(store)
    req = request(store, events=[event(c, before='supported', after='mixed', basis=[content_basis(ev)],
                                       previous=store.get(c)['events'][-1]['event_id'])])
    path = store.brain.node_path('source')
    path.write_text(path.read_text().replace('Measured', 'Unmeasured'))
    with pytest.raises(s.RecordConflict, match='preview'):
        store.transact(req, commit=False)
    assert len(read_file(store.brain)['events']) == 1


def test_two_store_instances_do_not_fork(store):
    another = DecisionMemory(Brain(str(store.brain.path)))
    first = request(store, [claim('First')])
    second = request(another, [claim('Second')])
    store.transact(first, commit=False)
    with pytest.raises(s.RecordConflict):
        another.transact(second, commit=False)
    assert len(store.export()['versions']) == 1


def test_interrupted_sidecar_publication_leaves_only_reusable_anchors(store, monkeypatch):
    import graph_engine.decision_memory as dm
    req = request(store, [claim()])
    atomic = dm._atomic_write
    monkeypatch.setattr(dm, '_atomic_write', lambda *a: (_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError):
        store.transact(req, commit=False)
    assert store.export()['versions'] == []
    assert len(store.brain.read_nodes()) == 1
    monkeypatch.setattr(dm, '_atomic_write', atomic)
    receipt = store.transact(req, commit=False)
    assert len(store.export()['versions']) == len(store.brain.read_nodes()) == 1
    assert store.transact(req, commit=False) == receipt


def test_commit_failure_preserves_authoritative_receipt(store, monkeypatch):
    req = request(store, [claim()])
    monkeypatch.setattr(store.brain, 'commit_and_push', lambda *a: (_ for _ in ()).throw(OSError('commit failed')))
    with pytest.raises(RecordPublished) as exc:
        store.transact(req)
    assert store.transact(req) == exc.value.receipt
    assert len(store.export()['versions']) == 1


def test_source_write_interruption_is_stale_then_reconciled(store, monkeypatch):
    import graph_engine.brain as module
    _, _, c, _ = assessed(store)
    original = module._atomic_write
    def fail_sidecar(path, content):
        if path.name == s.FILENAME:
            raise OSError('interrupted')
        return original(path, content)
    monkeypatch.setattr(module, '_atomic_write', fail_sidecar)
    node = store.brain.read_node('source')
    node.text = 'New source body'
    with pytest.raises(OSError):
        store.brain.write_node(node)
    assert store.get(c)['basis_changed']
    monkeypatch.setattr(module, '_atomic_write', original)
    store.brain.write_node(node)
    assert len([v for v in store.export()['versions'] if v['kind'] == 'source']) == 2
    assert store.get(c)['basis_changed']


@pytest.mark.parametrize('axis,before,after', [('epistemic', 'unassessed', 'current'),
                                             ('decision', 'proposed', 'superseded'),
                                             ('workflow', 'proposed', 'supported'),
                                             ('epistemic', 'unassessed', 'unassessed')])
def test_invalid_transitions_rejected_without_mutation(store, axis, before, after):
    c, = save(store, claim())
    before_files = files(store.brain)
    with pytest.raises(s.RecordError):
        store.transact(request(store, events=[event(c, axis=axis, before=before, after=after)]), commit=False)
    assert files(store.brain) == before_files


def test_correction_history_and_dependent_undo_guard(store):
    _, ev, c, receipt = assessed(store)
    first = receipt['event_ids'][0]
    correction = event(c, before='supported', after='unassessed', basis=[content_basis(ev)], previous=first, correct=first)
    store.transact(request(store, events=[correction]), commit=False)
    view = store.get(c)
    assert view['state']['epistemic'] == 'unassessed'
    assert len(view['events']) == 2
    assert view['events'][1]['supersedes_event_id'] == first
    c2, = save(store, claim('Other'))
    current = view['events'][-1]['event_id']
    dependent = event(c2, basis=[{'type': 'event_ref', 'event_id': current}])
    store.transact(request(store, events=[dependent]), commit=False)
    undo = event(c, before='unassessed', after='supported', basis=[content_basis(ev)], previous=current, correct=current)
    with pytest.raises(s.RecordError, match='dependent'):
        store.transact(request(store, events=[undo]), commit=False)


def test_withdrawal_changes_freshness_without_authored_opposition(store):
    _, ev, c, _ = assessed(store)
    store.transact(request(store, events=[event(ev, axis='availability', before='available', after='withdrawn')]), commit=False)
    assert store.get(c)['state']['epistemic'] == 'supported'
    assert store.get(c)['effective_assessment'] == 'inconclusive'
    prev = store.get(c)['events'][-1]['event_id']
    with pytest.raises(s.RecordConflict, match='stale'):
        review(store, c, ev, before='supported', after='mixed', previous=prev)


@pytest.mark.parametrize('damage', ['quote', 'hash', 'fork', 'missing', 'cycle', 'unknown_field', 'actor', 'float'])
def test_malformed_content_is_rejected_before_anchors(store, damage):
    src, = save(store, source(store))
    d = evidence(src)
    if damage == 'quote':
        d['payload']['sources'][0]['passage']['quote'] = 'Fabricated quote'
    elif damage == 'hash':
        d['payload']['sources'][0]['ref']['version_id'] = 'sha256:' + '0' * 64
    elif damage == 'fork':
        d['previous'] = src
    elif damage == 'missing':
        d['provenance']['inputs'] = [{'id': uid(), 'version_id': 'sha256:' + '1' * 64}]
    elif damage == 'cycle':
        d['provenance']['inputs'] = [{'id': d['id'], 'version_id': 'sha256:' + '2' * 64}]
    elif damage == 'unknown_field':
        d['payload']['confidence'] = 'supported'
    elif damage == 'actor':
        d['recorded_by'] = 'admin'
    else:
        d['provenance']['confidence'] = 0.99
    before = files(store.brain)
    with pytest.raises(s.RecordError):
        save(store, d)
    assert files(store.brain) == before


@pytest.mark.parametrize('damage', ['text', 'event', 'schema', 'duplicate', 'unicode'])
def test_manual_sidecar_identity_edits_fail_clearly(store, damage):
    assessed(store)
    data = read_file(store.brain)
    if damage == 'text':
        data['versions'][-1]['payload']['text'] = 'rewritten'
    elif damage == 'event':
        data['events'][0]['reason'] = 'rewritten review'
    elif damage == 'schema':
        data['schema'] = 'graph-engine.decision-memory/2'
    elif damage == 'duplicate':
        data['versions'].append(data['versions'][0])
    else:
        data['versions'][0]['payload']['text'] = '\ud800'
    (store.brain.path / s.FILENAME).write_text(json.dumps(data))
    with pytest.raises(s.RecordError):
        store.export()


def secure(store, tmp_path, monkeypatch):
    from graph_engine.access import SecuredBrain
    path = tmp_path / 'policy.json'
    policy = {'graphs': {'default': {'roles': {'alice': 'editor', 'viewer': 'viewer'}, 'nodes': {}}}}
    path.write_text(json.dumps(policy))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    b = SecuredBrain(str(store.brain.path), mode=store.brain.mode, graph_name='default', identity='alice')
    return DecisionMemory(b), path, policy


def test_revocation_filters_exports_reviews_and_retries(store, tmp_path, monkeypatch):
    protected, path, policy = secure(store, tmp_path, monkeypatch)
    src, ev, c, _ = assessed(protected)
    req = request(protected, [claim('Private derivative', inputs=[ev])])
    protected.transact(req, commit=False)
    policy['graphs']['default']['nodes']['source'] = {'read': ['owner']}
    path.write_text(json.dumps(policy))
    before = files(store.brain)
    assert protected.export()['versions'] == []
    assert protected.export()['events'] == []
    assert set(protected.preview()['heads']) == {'authorization'}
    with pytest.raises(BasisUnavailable):
        protected.get(c)
    with pytest.raises(BasisUnavailable):
        protected.transact(req, commit=False)
    assert files(store.brain) == before


def test_sidecar_checks_lineage_after_manual_anchor_acl_removal(store, tmp_path, monkeypatch):
    src, ev, c, _ = assessed(store)
    protected, path, policy = secure(store, tmp_path, monkeypatch)
    for node in store.brain.read_nodes():
        if node.id != 'source':
            p = store.brain.node_path(node.id)
            p.write_text(p.read_text().replace('derived_from: ["source"]\n', ''))
    assert ev['id'] not in {v['id'] for v in protected.export()['versions']}
    policy['graphs']['default']['nodes']['source'] = {'read': []}
    path.write_text(json.dumps(policy))
    assert protected.export()['versions'] == []


@pytest.mark.parametrize('lineage', [['absent'], ['source']])
def test_missing_and_cyclic_node_lineage_fail_closed(store, lineage):
    src, = save(store, source(store))
    p = store.brain.node_path('source')
    p.write_text(p.read_text().replace('tags:', 'derived_from: ' + json.dumps(lineage) + '\ntags:'))
    assert store.export()['versions'] == []
    with pytest.raises(BasisUnavailable):
        store.get(src)


def test_viewer_cannot_write(store, tmp_path, monkeypatch):
    from graph_engine.access import SecuredBrain
    _, _, _ = secure(store, tmp_path, monkeypatch)
    viewer = DecisionMemory(SecuredBrain(str(store.brain.path), mode='local', graph_name='default', identity='viewer'))
    with pytest.raises(PermissionError):
        viewer.transact(request(viewer, [claim()]), commit=False)


def test_historical_versions_reviews_and_old_absent_schema_are_read_only(tmp_path):
    b = Brain(str(tmp_path / 'history'), mode='git')
    b.init()
    store = DecisionMemory(b)
    old = snapshot(b, 'HEAD')
    assert old['decision_memory']['versions'] == []
    src, ev, c, _ = assessed(store)
    b.commit_and_push('reviewed', push=False)
    first = snapshot(b, 'HEAD')['revision']
    n = b.read_node('source')
    n.text = 'New measurement'
    b.write_node(n)
    b.commit_and_push('changed', push=False)
    before = files(b)
    historical = snapshot(b, first)['decision_memory']
    assert historical['events'][0]['subject'] == c
    assert len(historical['versions']) == 3
    assert historical['versions'][0]['payload']['text'] == 'Measured recall is 0.8\n'
    assert len(snapshot(b, 'HEAD')['decision_memory']['versions']) == 4
    assert files(b) == before


def test_historical_revocation_and_authorized_tombstone_history(tmp_path, monkeypatch):
    b = Brain(str(tmp_path / 'history'), mode='git')
    b.init()
    store = DecisionMemory(b)
    _, _, c, _ = assessed(store)
    b.commit_and_push('reviewed', push=False)
    first = snapshot(b, 'HEAD')['revision']
    b.tombstone_node('source')
    b.commit_and_push('forgotten', push=False)
    assert store.export()['versions'] == []
    assert snapshot(b, first)['decision_memory']['events'][0]['subject'] == c
    protected, path, policy = secure(store, tmp_path, monkeypatch)
    policy['graphs']['default']['nodes']['source'] = {'read': []}
    path.write_text(json.dumps(policy))
    historical = snapshot(protected.brain, first)['decision_memory']
    assert historical['versions'] == historical['events'] == []


def test_future_historical_sidecar_schema_fails(tmp_path):
    b = Brain(str(tmp_path / 'history'), mode='git')
    b.init()
    (b.path / s.FILENAME).write_text('{"schema":"graph-engine.decision-memory/2"}')
    b.commit_and_push('future', push=False)
    with pytest.raises(SnapshotError, match='Decision Memory schema'):
        snapshot(b, 'HEAD')


def test_reads_never_touch_brain_or_vectors(store, monkeypatch):
    _, _, c, _ = assessed(store)
    before = files(store.brain)
    for name in ('write_node', 'rebuild_index', 'commit_and_push', 'pull', 'ensure_ready', 'write_vectors'):
        monkeypatch.setattr(store.brain, name, lambda *a: pytest.fail('read mutation'))
    store.get(c)
    store.export()
    store.preview()
    assert files(store.brain) == before


def check_record():
    return draft('check', dict(question='Does the local diagnostic improve recall?', context=None,
                               protocol={'id': 'paired-local', 'version': '1'}, inputs=['code', 'data'],
                               metrics=[{'name': 'recall', 'unit': 'fraction'}], rule='Compare paired observations',
                               limitations=['No production generalization']))


def result_record(check, sources=(), *, hypothetical=False):
    return draft('result', dict(check=check, outcome='completed', context=None,
                                metrics=[{'name': 'recall', 'unit': 'fraction', 'value': '0.8', 'denominator': None}],
                                metrics_reason=None, sources=list(sources),
                                execution=dict(code=None, data=None, environment=None, configuration=None,
                                               command='raise RuntimeError("must never execute")',
                                               raw_outputs=list(sources), observed_at=None),
                                limitations=['Imported observation'], hypothetical=hypothetical))


def decision_record(**kwargs):
    return draft('decision', dict(action='Keep expansion opt-in', rationale='Diagnostic evidence is limited',
                                  alternatives=['Enable by default'], context=None, revisit_checks=[]), **kwargs)


def test_checks_results_unknowns_and_decisions_round_trip_without_execution(store):
    check, = save(store, check_record())
    src, = save(store, source(store))
    result, = save(store, result_record(check, [src]))
    c, = save(store, claim())
    relationship, = save(store, draft('relationship', dict(kind='supports', source=result, target=c,
                                                           context=None, explanation='Local synthetic diagnostic')))
    decision, = save(store, decision_record())
    review(store, relationship, result, axis='workflow', before='proposed', after='accepted')
    review(store, decision, c, axis='decision', before='proposed', after='current')
    payload = store.get(result)['record']['payload']
    assert payload['execution']['code'] is payload['execution']['environment'] is None
    assert payload['execution']['raw_outputs'] == [src]
    assert payload['metrics'][0]['value'] == '0.8'
    assert store.get(c)['effective_assessment'] == 'unassessed'
    assert store.get(decision)['state']['decision'] == 'current'
    assert store.get(decision)['state']['workflow'] == 'proposed'
    old = store.get(decision)['record']
    new, = save(store, decision_record(previous=decision, identity=decision['id'], anchor=old['anchor_node_id']))
    with pytest.raises(s.RecordError, match='Invalid state transition'):
        store.transact(request(store, events=[event(new, axis='decision', before='proposed', after='superseded')]), commit=False)


def test_successor_decision_activation_is_atomic(store):
    c, = save(store, claim())
    old, = save(store, decision_record())
    first = review(store, old, c, axis='decision', before='proposed', after='current')['event_ids'][0]
    old_record = store.get(old)['record']
    successor, = save(store, decision_record(previous=old, identity=old['id'], anchor=old_record['anchor_node_id']))
    # Supersession is the one lifecycle action that deliberately targets an
    # older content version, paired with explicit successor activation.
    req = request(store, events=[event(old, axis='decision', before='current', after='superseded',
                                       previous=first, basis=[content_basis(successor)]),
                                 event(successor, axis='decision', before='proposed', after='current', basis=[content_basis(c)])])
    store.transact(req, commit=False)
    assert store.get(old)['state']['decision'] == 'superseded'
    assert store.get(successor)['state']['decision'] == 'current'


def test_hypothetical_result_retains_label_and_cannot_supply_real_support(store):
    check, = save(store, check_record())
    result, = save(store, result_record(check, hypothetical=True))
    ev = draft('evidence', dict(interpretation='Example only', context=None, sources=[{'ref': result, 'passage': None}],
                               lineage_ids=[], limitations=['Hypothetical']))
    evidence_ref, = save(store, ev)
    assert store.get(evidence_ref)['hypothetical']
    c, = save(store, claim())
    with pytest.raises(s.RecordError, match='Hypothetical'):
        review(store, c, evidence_ref)
    assert store.get(c)['effective_assessment'] == 'unassessed'
    review(store, c, evidence_ref, after='inconclusive')
    assert store.get(c)['hypothetical']
    assert store.get(c)['effective_assessment'] == 'inconclusive'


@pytest.mark.parametrize('metric', [0.8, '0.80', 'NaN', '1e-3', '-0', '01'])
def test_metric_values_require_canonical_decimal_strings(store, metric):
    check, = save(store, check_record())
    result = result_record(check)
    result['payload']['metrics'][0]['value'] = metric
    with pytest.raises(s.RecordError):
        save(store, result)


def test_profile_and_typed_conditions_remain_versions(store):
    p = draft('profile', dict(name='Synthetic diagnostic', version='1', interventions=[], dimensions={
        'metric': {'type': 'enum', 'unit': None, 'required': True, 'compare': 'equal', 'allowed_values': ['recall']},
        'budget': {'type': 'range', 'unit': 'tokens', 'required': True, 'compare': 'overlap', 'allowed_values': None}}))
    profile, = save(store, p)
    context = {'schema': 'dm.context/1', 'profile': profile, 'dimensions': {
        'metric': {'type': 'enum', 'value': 'recall'},
        'budget': {'type': 'range', 'value': {'lower': 64, 'upper': 256, 'lower_inclusive': True, 'upper_inclusive': True}},
        'host': {'type': 'unknown', 'reason': 'not supplied'}}, 'notes': ''}
    c, = save(store, claim(context=context))
    assert store.get(c)['record']['payload']['context'] == context
    assert store.get(profile)['state']['workflow'] == 'proposed'
    changed = deepcopy(context)
    changed['dimensions']['host'] = {'type': 'id', 'value': 'test-host'}
    old = store.get(c)['record']
    new, = save(store, claim(context=changed, previous=c, identity=c['id'], anchor=old['anchor_node_id']))
    assert new != c
    assert store.get(c)['record']['payload']['context']['dimensions']['host']['type'] == 'unknown'


def test_event_does_not_export_unrelated_preview_ids_after_revocation(store, tmp_path, monkeypatch):
    private, = save(store, source(store, node='private-input', text='Unrelated private observation'))
    _, _, c, _ = assessed(store)
    protected, path, policy = secure(store, tmp_path, monkeypatch)
    policy['graphs']['default']['nodes']['private-input'] = {'read': []}
    path.write_text(json.dumps(policy))
    exported = json.dumps(protected.get(c))
    assert private['id'] not in exported
    assert 'private-input' not in exported


def test_acl_change_invalidates_authorized_review_preview(store, tmp_path, monkeypatch):
    protected, path, policy = secure(store, tmp_path, monkeypatch)
    c, = save(protected, claim())
    req = request(protected, events=[event(c, axis='workflow', before='proposed', after='accepted')])
    policy['graphs']['default']['nodes']['unrelated'] = {'read': ['alice']}
    path.write_text(json.dumps(policy))
    with pytest.raises(s.RecordConflict, match='preview'):
        protected.transact(req, commit=False)


@pytest.mark.parametrize('damage', ['subject', 'basis', 'event_ref', 'source_ref'])
def test_malformed_event_refs_are_validation_errors(store, damage):
    c, = save(store, claim())
    e = event(c)
    if damage == 'subject':
        e['subject'] = {'id': uid(), 'version_id': 'sha256:' + '0' * 64}
    elif damage == 'basis':
        e['basis'] = [{'type': 'content_ref', 'ref': {'id': uid(), 'version_id': 'sha256:' + '0' * 64}}]
    elif damage == 'event_ref':
        e['basis'] = [{'type': 'event_ref', 'event_id': uid()}]
    else:
        e['basis'] = [{'type': 'source_ref', 'ref': {'node_id': 'missing', 'text_sha256': '0' * 64, 'revision': None}}]
    with pytest.raises(s.RecordError):
        store.transact(request(store, events=[e]), commit=False)


def test_git_source_revision_must_match_exact_committed_body(tmp_path):
    b = Brain(str(tmp_path / 'history'), mode='git')
    b.init()
    b.write_node(Node('Committed input', id='input'))
    b.commit_and_push('input', push=False)
    sha = snapshot(b, 'HEAD')['revision']
    store = b.decision_memory()
    payload = store.source_payload('input', locator='nodes/input.md', revision=sha)
    save(store, draft('source', payload, anchor='input'))
    n = b.read_node('input')
    n.text = 'Changed input'
    b.write_node(n)
    with pytest.raises(s.RecordError, match='mismatch'):
        store.source_payload('input', locator='nodes/input.md', revision=sha)
    with pytest.raises(s.RecordError, match='unavailable'):
        store.source_payload('input', locator='nodes/input.md', revision='0' * 40)


def test_snapshot_sidecar_checks_legacy_historical_capture_lineage(tmp_path, monkeypatch):
    b = Brain(str(tmp_path / 'history'), mode='git')
    b.init()
    b.write_node(Node('Original private source', id='original'))
    b.write_node(Node('Copied source', id='copy', capture={
        'input': 'Copied source', 'node_id': 'original', 'duplicate': True, 'source': 'human'}))
    store = b.decision_memory()
    copied, = save(store, source(store, node='copy'))
    c, = save(store, claim('Derived copy', inputs=[copied]))
    b.commit_and_push('captured history', push=False)
    sha = snapshot(b, 'HEAD')['revision']
    n = b.read_node('copy')
    n.capture = None
    b.write_node(n)
    protected, path, policy = secure(store, tmp_path, monkeypatch)
    policy['graphs']['default']['nodes']['original'] = {'read': []}
    path.write_text(json.dumps(policy))
    result = snapshot(protected.brain, sha)['decision_memory']
    assert result['versions'] == []


def test_maintenance_tiers_and_usage_do_not_assess_or_version_content(store):
    src, ev, c, _ = assessed(store)
    before = (store.brain.path / s.FILENAME).read_bytes()
    for n in store.brain.read_nodes():
        n.storage_tier = 'main'
        n.recall_count = 50
        n.status = 'active'
        store.brain.write_node(n)
    assert (store.brain.path / s.FILENAME).read_bytes() == before
    assert store.get(c)['effective_assessment'] == 'supported'
    assert store.get(ev)['effective_assessment'] == 'unassessed'


def test_transaction_is_guarded_through_pull_publication_and_commit(store, monkeypatch):
    from graph_engine.write_guard import _HELD
    def checked(*args, **kwargs):
        assert _HELD
    monkeypatch.setattr(store.brain, 'ensure_ready', checked)
    monkeypatch.setattr(store.brain, 'pull', checked)
    monkeypatch.setattr(store.brain, 'commit_and_push', checked)
    monkeypatch.setattr(store.brain, 'rebuild_index', checked)
    store.transact(request(store, [claim()]))


def test_no_multiple_current_versions_and_no_implicit_undo(store):
    c, = save(store, claim())
    old, = save(store, decision_record())
    review(store, old, c, axis='decision', before='proposed', after='current')
    record = store.get(old)['record']
    new, = save(store, decision_record(previous=old, identity=old['id'], anchor=record['anchor_node_id']))
    with pytest.raises(s.RecordError, match='Multiple current'):
        review(store, new, c, axis='decision', before='proposed', after='current')


def test_oversized_reason_and_unknown_json_fields_fail_before_mutation(store):
    c, = save(store, claim())
    e = event(c, axis='workflow', before='proposed', after='accepted')
    e['reason'] = 'x' * 4001
    before = files(store.brain)
    with pytest.raises(s.RecordError):
        store.transact(request(store, events=[e]), commit=False)
    assert files(store.brain) == before
    with pytest.raises(s.RecordError, match='Duplicate JSON'):
        s.loads('{"schema": "a", "schema": "b"}')


def test_sidecar_reference_acl_checks_basis_anchor_as_well_as_source(store, tmp_path, monkeypatch):
    _, ev, c, _ = assessed(store)
    protected, path, policy = secure(store, tmp_path, monkeypatch)
    evidence_anchor = store.get(ev)['record']['anchor_node_id']
    policy['graphs']['default']['nodes'][evidence_anchor] = {'read': []}
    path.write_text(json.dumps(policy))
    assert c['id'] not in {v['id'] for v in protected.export()['versions']}
    with pytest.raises(BasisUnavailable):
        protected.get(c)


def test_cannot_undo_assessment_used_by_later_decision_content_basis(store):
    _, ev, c, receipt = assessed(store)
    decision, = save(store, decision_record())
    review(store, decision, c, axis='decision', before='proposed', after='current')
    eid = receipt['event_ids'][0]
    undo = event(c, before='supported', after='unassessed', previous=eid, correct=eid, basis=[content_basis(ev)])
    with pytest.raises(s.RecordError, match='dependent'):
        store.transact(request(store, events=[undo]), commit=False)


def test_fresh_review_replaces_obsolete_basis_without_erasing_history(store):
    _, _, c, receipt = assessed(store)
    original = deepcopy(store.get(c)['events'][0])
    node = store.brain.read_node('source')
    node.text = 'New measurement'
    store.brain.write_node(node)
    src = next(s.reference(v) for v in reversed(store.export()['versions']) if v['kind'] == 'source')
    ev, = save(store, evidence(src, quote='New measurement'))
    req = request(store, events=[event(c, before='supported', after='supported',
                                       previous=receipt['event_ids'][0], basis=[content_basis(ev)])])
    fresh = store.transact(req, commit=False)
    view = store.get(c)
    assert view['effective_assessment'] == 'supported'
    assert not view['basis_changed']
    assert view['events'][0] == original
    assert view['events'][-1]['basis'] == [content_basis(ev)]
    before = files(store.brain)
    assert store.transact(req, commit=False) == fresh
    assert files(store.brain) == before


def test_restored_evidence_requires_fresh_review_but_does_not_poison_it(store):
    _, ev, c, receipt = assessed(store)
    withdrawn = store.transact(request(store, events=[event(
        ev, axis='availability', before='available', after='withdrawn')]), commit=False)
    store.transact(request(store, events=[event(
        ev, axis='availability', before='withdrawn', after='available',
        previous=withdrawn['event_ids'][0])]), commit=False)
    assert store.get(c)['basis_changed']
    review(store, c, ev, before='supported', after='supported', previous=receipt['event_ids'][0])
    assert not store.get(c)['basis_changed']
    assert store.get(c)['effective_assessment'] == 'supported'


def test_replaced_review_basis_still_restricts_access_and_retries(store, tmp_path, monkeypatch):
    protected, path, policy = secure(store, tmp_path, monkeypatch)
    _, _, c, receipt = assessed(protected)
    src, = save(protected, source(protected, node='replacement'))
    ev, = save(protected, evidence(src))
    req = request(protected, events=[event(c, before='supported', after='supported',
                                           previous=receipt['event_ids'][0], basis=[content_basis(ev)])])
    protected.transact(req, commit=False)
    assert not protected.get(c)['basis_changed']
    policy['graphs']['default']['nodes']['source'] = {'read': []}
    path.write_text(json.dumps(policy))
    with pytest.raises(BasisUnavailable):
        protected.get(c)
    with pytest.raises(BasisUnavailable):
        protected.transact(req, commit=False)
    assert c['id'] not in {v['id'] for v in protected.export()['versions']}


@pytest.mark.parametrize('change', ['review', 'source', 'withdraw_restore'])
def test_review_basis_freshness_is_transitive_for_reads_and_writes(store, change):
    _, ev, first, receipt = assessed(store)
    middle, top, other = save(store, claim('Middle'), claim('Top'), claim('Other'))
    def assess_event(target, eid):
        return store.transact(request(store, events=[event(
            target, basis=[{'type': 'event_ref', 'event_id': eid}])]), commit=False)
    second = assess_event(middle, receipt['event_ids'][0])
    third = assess_event(top, second['event_ids'][0])
    if change == 'review':
        review(store, first, ev, before='supported', after='opposed', previous=receipt['event_ids'][0])
    elif change == 'source':
        node = store.brain.read_node('source')
        node.text = 'Changed measurement'
        store.brain.write_node(node)
    else:
        withdrawn = store.transact(request(store, events=[event(
            ev, axis='availability', before='available', after='withdrawn')]), commit=False)
        store.transact(request(store, events=[event(
            ev, axis='availability', before='withdrawn', after='available',
            previous=withdrawn['event_ids'][0])]), commit=False)
    for ref in (middle, top):
        view = store.get(ref)
        assert view['state']['epistemic'] == 'supported'
        assert view['basis_changed']
        assert view['effective_assessment'] == 'inconclusive'
    before = files(store.brain)
    with pytest.raises(s.RecordConflict, match='stale'):
        assess_event(other, third['event_ids'][0])
    assert files(store.brain) == before


def test_new_review_can_replace_a_stale_referenced_review(store):
    _, ev, first, receipt = assessed(store)
    target, = save(store, claim('Dependent'))
    dependent = store.transact(request(store, events=[event(target, basis=[
        {'type': 'event_ref', 'event_id': receipt['event_ids'][0]}])]), commit=False)
    latest = review(store, first, ev, before='supported', after='mixed', previous=receipt['event_ids'][0])
    assert store.get(target)['basis_changed']
    store.transact(request(store, events=[event(
        target, before='supported', after='mixed', previous=dependent['event_ids'][0],
        basis=[{'type': 'event_ref', 'event_id': latest['event_ids'][0]}])]), commit=False)
    assert not store.get(target)['basis_changed']
    assert store.get(target)['effective_assessment'] == 'mixed'


@pytest.mark.parametrize('change', ['source', 'withdrawal'])
def test_current_decision_reports_changed_activation_basis(store, change):
    _, ev, _, _ = assessed(store)
    decision, = save(store, decision_record())
    review(store, decision, ev, axis='decision', before='proposed', after='current')
    assert not store.get(decision)['basis_changed']
    if change == 'source':
        node = store.brain.read_node('source')
        node.text = 'Changed result'
        store.brain.write_node(node)
    else:
        store.transact(request(store, events=[event(
            ev, axis='availability', before='available', after='withdrawn')]), commit=False)
    view = store.get(decision)
    assert view['state']['decision'] == 'current'
    assert view['basis_changed']
    assert view['effective_assessment'] == 'inconclusive'


def test_fresh_decision_conclusion_replaces_obsolete_justification(store):
    _, ev, _, _ = assessed(store)
    decision, = save(store, decision_record())
    review(store, decision, ev, axis='decision', before='proposed', after='current')
    first = review(store, decision, ev, axis='decision_conclusion', before=None, after='remains_justified')
    node = store.brain.read_node('source')
    node.text = 'Changed result'
    store.brain.write_node(node)
    assert store.get(decision)['basis_changed']
    src = next(s.reference(v) for v in reversed(store.export()['versions']) if v['kind'] == 'source')
    fresh_ev, = save(store, evidence(src, quote='Changed result'))
    review(store, decision, fresh_ev, axis='decision_conclusion', before='remains_justified',
           after='remains_justified', previous=first['event_ids'][0])
    view = store.get(decision)
    assert view['state']['decision'] == 'current'
    assert view['state']['decision_conclusion'] == 'remains_justified'
    assert not view['basis_changed']
    assert len(view['events']) == 3

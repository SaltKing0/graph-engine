"""No-provider capture/review workflow and adapter security regressions (#77)."""
from copy import deepcopy
import hashlib
import json
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from graph_engine import decision_schema as s, runtime
from graph_engine.brain import Brain, Node
from graph_engine.decision_memory import RecordPublished, read_file
from graph_engine.decision_service import DecisionService, PROPOSAL, REVIEW, RESULT, load_envelope, compare_context
from graph_engine.document_import import import_documents
from test_decision_memory import draft, claim, event, content_basis, check_record, result_record, files


def uid():
    return str(uuid4())


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.delenv('IG_ACCESS_POLICY', raising=False)
    monkeypatch.delenv('IG_GRAPH_HOME', raising=False)
    monkeypatch.delenv('IG_GRAPH', raising=False)
    b = Brain(str(tmp_path / 'brain'), mode='local')
    b.init()
    monkeypatch.setenv('IG_BRAIN_PATH', str(b.path))
    monkeypatch.setenv('IG_BRAIN_MODE', 'local')
    monkeypatch.setattr(runtime, 'make_engine', lambda: pytest.fail('Model engine constructed'))
    return DecisionService(b)


def envelope(service, *, versions=None, events=None):
    p = service.preview()
    return dict(schema=PROPOSAL if events is None else REVIEW, idempotency_key=uid(),
                expected_generation=p['generation'], expected_heads=p['heads'],
                **({'versions': versions} if events is None else {'events': events}))


def save(service, *versions):
    return service.submit(envelope(service, versions=list(versions)), commit=False)['receipt']['refs']


def review(service, subject, *, axis='workflow', after='accepted', basis=()):
    item = service.inspect(subject)
    previous = next((e['event_id'] for e in reversed(item['events']) if e['axis'] == axis), None)
    basis = list(basis)
    p = item['record']['payload']
    if ((item['record']['kind'] == 'relationship' and p['kind'] in ('supports', 'opposes')
            and axis == 'workflow' and after == 'accepted')
            or axis == 'epistemic' and after in ('supported', 'opposed', 'mixed')) and p.get('context'):
        profile = service.inspect(p['context']['profile'])
        enabling = [e for e in profile['events'] if e['axis'] == 'workflow']
        if enabling:
            basis.append({'type': 'event_ref', 'event_id': enabling[-1]['event_id']})
    e = event(subject, axis=axis, before=item['state'][axis], after=after, basis=basis, previous=previous)
    return service.submit(envelope(service, events=[e]), commit=False)


def context(profile, workload='diagnostic'):
    return dict(schema='dm.context/1', profile=profile, dimensions={'workload': {'type': 'id', 'value': workload}}, notes='')


def profile(service):
    p, = save(service, draft('profile', dict(name='diagnostic scope', version='1', dimensions={
        'workload': dict(type='id', unit=None, required=True, compare='equal', allowed_values=None)}, interventions=[])))
    review(service, p)
    return p


def captured(service, tmp_path):
    p = profile(service)
    note = tmp_path / 'negative.md'
    note.write_text('Der Ansatz ist nicht korrekt; die Annahme ist falsch.\n')
    imported = import_documents(service.brain, [note], source_id='experiment-notes')
    nid = imported['files'][0]['chunks'][0]['node_id']
    src = draft('source', service.source(nid), anchor=nid)
    c = claim('The approach fails in this diagnostic.', context(p))
    ev = draft('evidence', dict(interpretation='nicht korrekt; falsch', context=context(p),
        sources=[dict(ref={'local': src['id']}, passage={'start': 0, 'end': 10, 'quote': 'Der Ansatz'})],
        lineage_ids=['same-experiment'], limitations=['Diagnostic only']))
    dep = draft('relationship', dict(kind='supports', source={'local': ev['id']}, target={'local': c['id']},
                                    context=context(p), explanation='Same diagnostic and exact negative observation'))
    d = draft('decision', dict(action='Keep the feature opt-in', rationale='Diagnostic limitation',
                              alternatives=['Enable by default'], context=context(p), revisit_checks=[]))
    link = draft('relationship', dict(kind='depends_on', source={'local': d['id']}, target={'local': c['id']},
                                    context=context(p), explanation='The limited diagnostic motivates retaining the default'))
    req = envelope(service, versions=[src, c, ev, dep, d, link])
    return req, nid


def test_import_propose_review_changed_source_and_stale_review(service, tmp_path):
    req, nid = captured(service, tmp_path)
    before = files(service.brain)
    plan = service.submit(req, dry_run=True)
    assert files(service.brain) == before and len(plan['versions']) == 6
    refs = service.submit(req, commit=False)['receipt']['refs']
    src, c, ev, dep, d, link = refs
    assert service.inspect(c)['effective_assessment'] == 'unassessed'
    assert service.inspect(dep)['state']['workflow'] == 'proposed'
    assert 'document-sha256:' in service.inspect(src)['record']['payload']['lineage_ids'][0]
    review(service, dep, basis=[content_basis(ev), content_basis(c)])
    review(service, c, axis='epistemic', after='supported', basis=[content_basis(ev), content_basis(dep)])
    review(service, link, basis=[content_basis(c)])
    review(service, d, axis='decision', after='current', basis=[content_basis(c), content_basis(link),
        {'type': 'event_ref', 'event_id': service.inspect(c)['events'][-1]['event_id']}])
    stale = envelope(service, events=[event(d, axis='decision_conclusion', before=None, after='remains_justified', basis=[content_basis(c)])])
    assert service.inspect(d)['state']['decision'] == 'current'
    n = service.brain.read_node(nid)
    n.text = 'The diagnostic has changed.'
    service.brain.write_node(n)
    assert service.inspect(c)['effective_assessment'] == 'inconclusive'
    assert service.inspect(c)['state']['epistemic'] == 'supported'  # loss of support, not counterevidence
    assert service.inspect(d)['basis_changed']
    with pytest.raises(s.RecordConflict):
        service.submit(stale, commit=False)
    # Replaying the capture cannot restore old support or reopen proposals.
    generation = read_file(service.brain)['generation']
    assert service.submit(req, commit=False)['replay']
    assert read_file(service.brain)['generation'] == generation


def test_dry_run_never_initializes_or_writes_brain(service, monkeypatch, tmp_path):
    fresh = DecisionService(Brain(str(tmp_path / 'absent'), mode='local'))
    req = envelope(fresh, versions=[claim()])
    for name in ('ensure_ready', 'pull', 'write_node', 'rebuild_index', 'commit_and_push', 'write_guard'):
        monkeypatch.setattr(fresh.brain, name, lambda *a: pytest.fail('Dry-run side effect'))
    assert fresh.submit(req, dry_run=True)['versions'][0]['kind'] == 'claim'
    assert not fresh.brain.path.exists()


@pytest.mark.parametrize('damage', ['quote', 'offset', 'forward', 'missing', 'stale'])
def test_invalid_or_stale_evidence_fails_before_any_write(service, tmp_path, damage):
    req, nid = captured(service, tmp_path)
    ev = req['versions'][2]
    if damage == 'quote':
        ev['payload']['sources'][0]['passage']['quote'] = 'fabricated'
    elif damage == 'offset':
        ev['payload']['sources'][0]['passage']['end'] = 9999
    elif damage == 'forward':
        req['versions'][0], req['versions'][2] = req['versions'][2], req['versions'][0]
    elif damage == 'missing':
        ev['payload']['sources'][0]['ref'] = {'local': uid()}
    else:
        n = service.brain.read_node(nid)
        n.text = 'changed'
        service.brain.write_node(n)
    before = files(service.brain)
    with pytest.raises(s.RecordError):
        service.submit(req, commit=False)
    assert files(service.brain) == before


def test_dismiss_retry_and_key_conflict_do_not_duplicate_or_reopen(service):
    req = envelope(service, versions=[claim()])
    ref, = service.submit(req, commit=False)['receipt']['refs']
    review(service, ref, after='rejected')
    before = files(service.brain)
    assert service.submit(req, commit=False)['replay']
    assert service.pending()['items'] == []
    assert files(service.brain) == before
    req['versions'][0]['payload']['text'] = 'changed'
    with pytest.raises(s.RecordConflict):
        service.submit(req, commit=False)


def test_explicit_revise_and_guarded_undo(service):
    c, = save(service, claim())
    r = review(service, c, after='accepted')
    e = service.inspect(c)['events'][-1]
    undo = event(c, axis='workflow', before='accepted', after='proposed', basis=e['basis'],
                 previous=e['event_id'], correct=e['event_id'])
    req = envelope(service, events=[undo])
    service.submit(req, commit=False)
    assert service.inspect(c)['state']['workflow'] == 'proposed'
    with pytest.raises(s.RecordError):
        service.submit(envelope(service, events=[undo]), commit=False)
    d, = save(service, draft('decision', dict(action='Retain default', rationale='Limited evidence',
        alternatives=['change'], context=None, revisit_checks=[])))
    review(service, d, axis='decision_conclusion', after='revise', basis=[content_basis(c)])
    assert service.inspect(d)['state']['decision'] == 'proposed'
    assert service.inspect(d)['state']['decision_conclusion'] == 'revise'


@pytest.mark.parametrize('workload', ['other-workload', None])
def test_incomparable_contradiction_remains_proposed(service, tmp_path, workload):
    req, _ = captured(service, tmp_path)
    req['versions'][3]['payload']['kind'] = 'opposes'
    req['versions'][2]['payload']['context'] = (None if workload is None else context(
        req['versions'][1]['payload']['context']['profile'], workload))
    src, c, ev, rel, *_ = service.submit(req, commit=False)['receipt']['refs']
    assert service.inspect(rel)['comparison']['status'] == ('unknown' if workload is None else 'disjoint')
    with pytest.raises(s.RecordError, match='comparable'):
        review(service, rel)
    assert service.inspect(rel)['state']['workflow'] == 'proposed'
    assert service.inspect(c)['effective_assessment'] == 'unassessed'
    review(service, rel, after='rejected')


def result_import(service, outcome='error'):
    check, = save(service, check_record())
    service.brain.write_node(Node('{"error":"run failed", "recall":null}', id='raw'))
    src, = save(service, draft('source', service.source('raw'), anchor='raw'))
    d = result_record(check, [src])
    p = d['payload']
    p.update(outcome=outcome, errors=['run failed'] if outcome == 'error' else [], metrics_reason='No answer model was run')
    p['metrics'][0].update(value=None, reason='Not measured after run failure')
    p['execution'].update(code='sha256:' + '1' * 64, data='sha256:' + '2' * 64,
                          configuration='sha256:' + '3' * 64, command='do not execute this')
    envelope = {k: d[k] for k in ('id', 'anchor_node_id', 'previous', 'payload')}
    return dict(schema=RESULT, **envelope), src


def test_failed_run_null_metrics_hashes_errors_and_artifact_preserved(service):
    env, src = result_import(service)
    d = service.result_draft(env)
    result, = save(service, d)
    assert service.inspect(result)['record']['payload'] == env['payload']
    assert service.inspect(result)['state']['workflow'] == 'proposed'
    c, = save(service, claim())
    with pytest.raises(s.RecordError, match='Failed'):
        review(service, c, axis='epistemic', after='opposed', basis=[content_basis(result)])
    review(service, c, axis='epistemic', after='inconclusive', basis=[content_basis(result)])
    assert service.inspect(c)['effective_assessment'] == 'inconclusive'


@pytest.mark.parametrize('damage', ['null-without-reason', 'measured-with-reason', 'no-raw', 'float', 'unknown', 'missing-check'])
def test_strict_result_mapping(service, damage):
    env, _ = result_import(service)
    if damage == 'null-without-reason':
        env['payload']['metrics'][0].pop('reason')
    elif damage == 'measured-with-reason':
        env['payload']['metrics'][0]['value'] = '0.8'
    elif damage == 'no-raw':
        env['payload']['execution']['raw_outputs'] = []
    elif damage == 'float':
        env['payload']['metrics'][0]['value'] = 0.5
    elif damage == 'unknown':
        env['extra'] = 'unknown'
    else:
        env['payload']['check']['id'] = uid()
    with pytest.raises((s.RecordError, PermissionError)):
        service.result_draft(env)


def test_multiple_sources_duplicate_lineage_never_confers_assessment(service, tmp_path):
    req, _ = captured(service, tmp_path)
    other = deepcopy(req['versions'][0])
    other['id'], other['anchor_node_id'] = uid(), 'copy'
    service.brain.write_node(Node(other['payload']['text'], id='copy'))
    other['payload']['source_ref']['node_id'] = 'copy'
    # Node serialization may append a newline, obtain exact bytes.
    other['payload']['text'] = service.source('copy')['text']
    other['payload']['source_ref']['text_sha256'] = s.text_hash(other['payload']['text'])
    req['versions'].insert(1, other)
    req['versions'][3]['payload']['sources'].append(dict(ref={'local': other['id']}, passage=None))
    refs = service.submit(req, commit=False)['receipt']['refs']
    item = service.inspect(refs[3])
    assert len(item['source_lineage']) == 2
    assert item['source_lineage'][0]['lineage_ids'] == item['source_lineage'][1]['lineage_ids']
    assert item['independence'] == 'not inferred'
    assert item['effective_assessment'] == 'unassessed'


def test_post_publication_failure_returns_durable_retry(service, monkeypatch):
    req = envelope(service, versions=[claim()])
    monkeypatch.setattr(service.brain, 'rebuild_index', lambda: (_ for _ in ()).throw(OSError('index failure')))
    with pytest.raises(RecordPublished) as exc:
        service.submit(req)
    assert service.submit(req)['receipt'] == exc.value.receipt


def test_cli_and_http_share_service_and_do_not_load_models(service, monkeypatch, capsys, tmp_path):
    from graph_engine.__main__ import main
    from graph_engine.server import app
    req = envelope(service, versions=[claim('nicht falsch')])
    f = tmp_path / 'proposal.json'
    f.write_text(json.dumps(req))
    monkeypatch.setattr(sys, 'argv', ['ig', 'decision', 'propose', str(f), '--dry-run'])
    main()
    assert json.loads(capsys.readouterr().out)['dry_run']
    with TestClient(app) as client:
        assert client.get('/api/decision-memory/preview').json() == service.preview()
        result = client.post('/api/decision-memory/proposals', json=req)
        assert result.status_code == 200
        ref = result.json()['receipt']['refs'][0]
        assert client.post('/api/decision-memory/inspect', json=ref).json()['record']['payload']['text'] == 'nicht falsch'
        assert len(client.get('/api/decision-memory/pending').json()['items']) == 1
        e = envelope(service, events=[event(ref, axis='workflow', before='proposed', after='accepted')])
        assert client.post('/api/decision-memory/reviews?dry_run=true', json=e).json()['dry_run']
        assert client.post('/api/decision-memory/reviews', json=e).status_code == 200
        stale = deepcopy(e)
        stale['idempotency_key'] = uid()
        assert client.post('/api/decision-memory/reviews', json=stale).status_code == 409
        for raw in ('{"schema":1,"schema":2}', '[]', '{"x":NaN}', '{"x":1.2}', '{"x":"\\ud800"}'):
            assert client.post('/api/decision-memory/proposals', content=raw).status_code == 400


def test_http_auth_inheritance_revocation_and_retry(service, tmp_path, monkeypatch):
    from graph_engine.access import SecuredBrain
    from graph_engine.server import app
    policy = {'graphs': {'default': {'roles': {'alice': 'editor', 'bob': 'viewer'}, 'nodes': {}}},
              'tokens': {hashlib.sha256(b'edit').hexdigest(): 'alice', hashlib.sha256(b'view').hexdigest(): 'bob'}}
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    secured = DecisionService(SecuredBrain(str(service.brain.path), mode='local', graph_name='default', identity='alice'))
    service.brain.write_node(Node('Private source', id='private'))
    src = draft('source', secured.source('private'), anchor='private')
    c = claim(inputs=[{'local': src['id']}])
    req = envelope(secured, versions=[src, c])
    editor = {'Authorization': 'Bearer edit'}
    viewer = {'Authorization': 'Bearer view'}
    with TestClient(app) as client:
        assert client.get('/api/decision-memory/pending').status_code == 401
        assert client.post('/api/decision-memory/proposals?dry_run=true', json=req, headers=viewer).status_code == 403
        response = client.post('/api/decision-memory/proposals', json=req, headers=editor)
        assert response.status_code == 200, response.text
        ref = response.json()['receipt']['refs'][1]
        assert read_file(service.brain)['versions'][-1]['recorded_by'] == 'alice'
        policy['graphs']['default']['nodes']['private'] = {'read': [], 'write': []}
        path.write_text(json.dumps(policy))
        assert client.get('/api/decision-memory/pending', headers=editor).json()['items'] == []
        assert client.post('/api/decision-memory/inspect', json=ref, headers=editor).status_code == 403
        assert client.post('/api/decision-memory/proposals', json=req, headers=editor).status_code == 403
        assert client.get('/api/decision-memory/sources/private', headers=editor).status_code == 403


@pytest.mark.parametrize('value', [[], {'schema': 'future'}, {'schema': PROPOSAL, 'versions': [1]}])
def test_malformed_envelopes_are_validation_errors(service, value):
    with pytest.raises(s.RecordError):
        service.submit(value, dry_run=True)


def test_json_benchmark_artifact_import_retains_exact_provenance(service, tmp_path):
    raw = '{"status":"completed_with_errors","metadata":{"code_sha256":"' + 'a' * 64 + '"},"results":[{"error":"failed","recall":null,"latency":1.25}]}\n'
    path = tmp_path / 'benchmark.json'
    path.write_text(raw)
    imported = import_documents(service.brain, [path], extensions=['.json'])
    assert imported['failed_files'] == 0
    nid = imported['files'][0]['chunks'][0]['node_id']
    payload = service.source(nid)
    assert payload['text'] == raw
    assert payload['artifact']['sha256'] == hashlib.sha256(raw.encode()).hexdigest()
    provenance = json.loads(payload['artifact']['extraction'])
    assert provenance['char_start'] == 0 and provenance['char_end'] == len(raw.rstrip())
    assert provenance['source_id'] == path.as_uri()
    assert import_documents(service.brain, [path], extensions=['.json'])['reused_chunks'] == 1


def test_content_update_resets_review_and_rejects_old_claim_proposals(service):
    c, = save(service, claim())
    review(service, c)
    old = service.inspect(c)['record']
    c2, = save(service, claim('Changed scope', identity=c['id'], anchor=old['anchor_node_id'], previous=c))
    assert service.inspect(c2)['state']['workflow'] == 'proposed'
    assert service.inspect(c2)['effective_assessment'] == 'unassessed'
    rel = draft('relationship', dict(kind='depends_on', source=c2, target=c, context=None,
                                    explanation='Attempt to use obsolete wording'))
    with pytest.raises(s.RecordConflict, match='stale'):
        save(service, rel)


def test_atomic_decision_successor_review(service):
    d, = save(service, draft('decision', dict(action='Retain default', rationale='Existing rule',
        alternatives=['change'], context=None, revisit_checks=[])))
    review(service, d, axis='decision', after='current')
    old = service.inspect(d)['record']
    successor, = save(service, draft('decision', dict(old['payload'], action='Use the revised rule'),
        identity=d['id'], anchor=old['anchor_node_id'], previous=d))
    last = service.inspect(d)['events'][-1]
    events = [event(d, axis='decision', before='current', after='superseded',
                    basis=[content_basis(successor)], previous=last['event_id']),
              event(successor, axis='decision', before='proposed', after='current')]
    service.submit(envelope(service, events=events), commit=False)
    assert service.inspect(d)['state']['decision'] == 'superseded'
    assert service.inspect(successor)['state']['decision'] == 'current'


def test_comparable_opposition_is_reviewable_without_assessing_target(service, tmp_path):
    req, _ = captured(service, tmp_path)
    req['versions'][3]['payload']['kind'] = 'opposes'
    _, c, ev, rel, *_ = service.submit(req, commit=False)['receipt']['refs']
    assert service.inspect(rel)['comparison']['status'] == 'comparable'
    review(service, rel, basis=[content_basis(ev), content_basis(c)])
    assert service.inspect(rel)['state']['workflow'] == 'accepted'
    assert service.inspect(c)['effective_assessment'] == 'unassessed'
    review(service, c, axis='epistemic', after='opposed', basis=[content_basis(ev), content_basis(rel)])
    assert service.inspect(c)['effective_assessment'] == 'opposed'


def test_undo_fails_after_dependent_review(service):
    c, = save(service, claim())
    review(service, c)
    e = service.inspect(c)['events'][-1]
    d, = save(service, draft('decision', dict(action='Retain', rationale='Review basis',
        alternatives=[], context=None, revisit_checks=[])))
    review(service, d, axis='decision', after='current', basis=[{'type': 'event_ref', 'event_id': e['event_id']}])
    undo = event(c, axis='workflow', before='accepted', after='proposed', basis=e['basis'],
                 previous=e['event_id'], correct=e['event_id'])
    with pytest.raises(s.RecordError, match='dependent'):
        service.submit(envelope(service, events=[undo]), commit=False)


@pytest.mark.parametrize('damage', [None, [], {'payload': []}, {'payload': {'execution': []}}])
def test_result_nested_malformed_input(service, damage):
    env, _ = result_import(service)
    if isinstance(damage, dict):
        env.update(damage)
    else:
        env = damage
    with pytest.raises(s.RecordError):
        service.result_draft(env)


def test_relationship_review_requires_pinned_profile_acceptance(service, tmp_path):
    req, _ = captured(service, tmp_path)
    _, _, _, rel, *_ = service.submit(req, commit=False)['receipt']['refs']
    e = event(rel, axis='workflow', before='proposed', after='accepted')
    with pytest.raises(s.RecordError, match='profile acceptance'):
        service.submit(envelope(service, events=[e]), commit=False)


@pytest.mark.parametrize('kind,x,y,status', [
    ('range', dict(lower=1, upper=5, lower_inclusive=True, upper_inclusive=False),
              dict(lower=3, upper=7, lower_inclusive=True, upper_inclusive=True), 'comparable'),
    ('range', dict(lower=1, upper=3, lower_inclusive=True, upper_inclusive=False),
              dict(lower=3, upper=7, lower_inclusive=True, upper_inclusive=True), 'disjoint'),
    ('range', dict(lower='0.1', upper='0.5', lower_inclusive=True, upper_inclusive=True),
              dict(lower='0.5', upper='0.7', lower_inclusive=True, upper_inclusive=True), 'comparable'),
    ('time_window', {'from': '2026-01-01T00:00:00Z', 'to': '2026-01-02T00:00:00.1Z'},
                    {'from': '2026-01-02T00:00:00Z', 'to': '2026-01-03T00:00:00Z'}, 'comparable'),
    ('time_window', {'from': '2026-01-01T00:00:00Z', 'to': '2026-01-02T00:00:00Z'},
                    {'from': '2026-01-02T00:00:00Z', 'to': '2026-01-03T00:00:00Z'}, 'disjoint'),
])
def test_typed_scope_overlap(service, kind, x, y, status):
    from graph_engine.decision_memory import RecordView
    p, = save(service, draft('profile', dict(name='overlap', version='1', dimensions={
        'window': dict(type=kind, unit=None, required=True, compare='overlap', allowed_values=None)}, interventions=[])))
    review(service, p)
    a = dict(schema='dm.context/1', profile=p, dimensions={'window': dict(type=kind, value=x)}, notes='')
    b = dict(a, dimensions={'window': dict(type=kind, value=y)})
    result = compare_context(a, b, RecordView(service.brain, read_file(service.brain)))
    assert result['status'] == status
    if status == 'comparable':
        assert result['intersection']['window']['type'] == kind


def test_known_disjoint_dimension_wins_over_unknown(service):
    from graph_engine.decision_memory import RecordView
    p = profile(service)
    a = context(p, 'one')
    b = context(p, 'two')
    a['dimensions']['host'] = {'type': 'unknown', 'reason': 'missing'}
    assert compare_context(a, b, RecordView(service.brain, read_file(service.brain)))['status'] == 'disjoint'


def test_result_draft_rejects_mismatched_predecessor(service):
    env, _ = result_import(service)
    result, = save(service, service.result_draft(env))
    with pytest.raises(s.RecordConflict):
        service.result_draft(env)
    env['previous'] = result
    assert service.result_draft(env)['previous'] == result
    env['anchor_node_id'] = 'other-anchor'
    with pytest.raises(s.RecordConflict):
        service.result_draft(env)


def test_new_review_provenance_requires_writable_existing_dependents(service, tmp_path, monkeypatch):
    from graph_engine.access import SecuredBrain
    req, _ = captured(service, tmp_path)
    _, c, ev, _, _, link = service.submit(req, commit=False)['receipt']['refs']
    anchor = service.inspect(link)['record']['anchor_node_id']
    policy = {'graphs': {'default': {'roles': {'alice': 'editor'}, 'nodes': {anchor: {'write': ['owner']}}}}}
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    secured = DecisionService(SecuredBrain(str(service.brain.path), mode='local', graph_name='default', identity='alice'))
    before = files(service.brain)
    with pytest.raises(PermissionError):
        review(secured, c, axis='epistemic', after='supported', basis=[content_basis(ev)])
    assert files(service.brain) == before
    assert service.inspect(c)['effective_assessment'] == 'unassessed'


def test_new_review_does_not_repair_preexisting_lineage_tampering(service):
    service.brain.write_node(Node('first source', id='a'))
    service.brain.write_node(Node('second source', id='b'))
    a, b = save(service, draft('source', service.source('a'), anchor='a'), draft('source', service.source('b'), anchor='b'))
    c, = save(service, claim(inputs=[a]))
    link, = save(service, draft('relationship', dict(kind='depends_on', source=c, target=c,
        context=None, explanation='Dependency with inherited source'), inputs=[a]))
    ev, = save(service, draft('evidence', dict(interpretation='second source', context=None,
        sources=[{'ref': b, 'passage': None}], lineage_ids=[], limitations=[])))
    anchor = service.inspect(link)['record']['anchor_node_id']
    n = service.brain.read_node(anchor)
    n.derived_from = []
    service.brain.node_path(anchor).write_text(n.to_markdown())
    before = files(service.brain)
    with pytest.raises(PermissionError):
        review(service, c, axis='epistemic', after='inconclusive', basis=[content_basis(ev)])
    assert files(service.brain) == before


def test_failed_result_cannot_be_laundered_through_evidence_into_opposition(service):
    env, _ = result_import(service)
    p = profile(service)
    env['payload']['context'] = context(p)
    result, = save(service, service.result_draft(env))
    ev, = save(service, draft('evidence', dict(interpretation='The run failed', context=context(p),
        sources=[{'ref': result, 'passage': None}], lineage_ids=[], limitations=[])))
    c, = save(service, claim(context=context(p)))
    rel, = save(service, draft('relationship', dict(kind='opposes', source=ev, target=c,
        context=context(p), explanation='Proposed interpretation of the failed run')))
    with pytest.raises(s.RecordError, match='Failed'):
        review(service, rel)
    assert service.inspect(rel)['state']['workflow'] == 'proposed'

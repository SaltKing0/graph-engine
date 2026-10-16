"""Pinned semantic comparisons, bounded paths and explicit finding review (#78)."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from graph_engine import decision_schema as s, runtime
from graph_engine.brain import Brain, Node
from graph_engine.decision_memory import read_file
from graph_engine.decision_service import DecisionService
from graph_engine.decision_impact import COMPARE, LIMITS, candidate_identity, validate_candidate
from test_decision_memory import draft, claim, event, content_basis, files, check_record, result_record
from test_decision_service import save, review, profile, context, envelope


def commit(service, message='frozen knowledge revision'):
    service.brain.commit_and_push(message, push=False)
    return subprocess.check_output(['git', '-C', str(service.brain.path), 'rev-parse', 'HEAD'], text=True).strip()


def comparison(before, after, **limits):
    return dict(schema=COMPARE, before=before, after=after, **({'limits': limits} if limits else {}))


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.delenv('IG_ACCESS_POLICY', raising=False)
    monkeypatch.delenv('IG_GRAPH_HOME', raising=False)
    monkeypatch.delenv('IG_GRAPH', raising=False)
    b = Brain(str(tmp_path / 'brain'), mode='git')
    b.init()
    monkeypatch.setenv('IG_BRAIN_PATH', str(b.path))
    monkeypatch.setenv('IG_BRAIN_MODE', 'git')
    monkeypatch.setattr(runtime, 'make_engine', lambda: pytest.fail('Model engine constructed'))
    return DecisionService(b)


def link(service, kind, a, b, ctx, *, accepted=True):
    r, = save(service, draft('relationship', dict(kind=kind, source=a, target=b, context=ctx, explanation='Explicit reviewed relationship')))
    if accepted:
        review(service, r)
    return r


def evidence(service, p, *, node='source', text='Local observation', lineage='experiment-1', ctx=None):
    ctx = ctx or context(p)
    service.brain.write_node(Node(text, id=node))
    source, = save(service, draft('source', dict(service.source(node), lineage_ids=[lineage] if lineage else []), anchor=node))
    ev, = save(service, draft('evidence', dict(interpretation=text, context=ctx,
        sources=[dict(ref=source, passage=None)], lineage_ids=['interpretation-is-not-an-independent-run'], limitations=[])))
    return source, ev


def scenario(service):
    p = profile(service)
    src, ev = evidence(service, p)
    c, = save(service, claim(context=context(p)))
    rel = link(service, 'supports', ev, c, context(p))
    d, = save(service, draft('decision', dict(action='Keep opt-in', rationale='Limited diagnostic',
        alternatives=['Enable'], context=context(p), revisit_checks=[])))
    dep = link(service, 'depends_on', d, c, context(p))
    return dict(profile=p, source=src, evidence=ev, claim=c, support=rel, decision=d, dependency=dep)


def change_source(service, text='Changed local result'):
    n = service.brain.read_node('source')
    n.text = text
    service.brain.write_node(n)


def test_pinned_source_update_has_exact_accepted_path_and_no_mutations(service, monkeypatch):
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    state = files(service.brain)
    head = subprocess.check_output(['git', '-C', str(service.brain.path), 'rev-parse', 'HEAD'])
    for name in ('ensure_ready', 'pull', 'write_node', 'write_vectors', 'rebuild_index', 'commit_and_push', 'write_guard'):
        monkeypatch.setattr(service.brain, name, lambda *a, **kw: pytest.fail('Read mutation'))
    result = service.compare(comparison(before, after))
    assert result['before']['revision'] == before and result['after']['revision'] == after
    assert result['evaluated_at'].endswith('Z')
    assert len(result['deltas']) == len(result['candidates']) == 1
    c = result['candidates'][0]
    assert c['target'] == refs['decision']
    assert c['decision']['action'] == 'Keep opt-in'
    text_change = next(item for item in c['delta']['changes'] if item['field'] == 'payload.text')
    assert 'Local observation' in text_change['before']['text']
    assert 'Changed local result' in text_change['after']['text']
    assert [step['kind'] for step in c['paths'][0]] == ['explicit_input', 'supports', 'depends_on']
    assert c['paths'][0][-1]['direction'] == 'reverse'
    assert c['paths'][0][0]['from_ref'] == refs['source']
    assert c['substitutions'][0]['old'] == refs['source']
    assert c['support']['remaining'] == [] and len(c['support']['removed']) == 1
    assert not c['completeness']['truncated']
    validate_candidate(c)
    assert files(service.brain) == state
    assert subprocess.check_output(['git', '-C', str(service.brain.path), 'rev-parse', 'HEAD']) == head
    assert service.compare(comparison(before, after))['candidates'] == result['candidates']


def test_irrelevant_serialization_usage_tier_and_repeated_capture_have_no_deltas(service):
    scenario(service)
    before = commit(service)
    data = read_file(service.brain)
    (service.brain.path / s.FILENAME).write_text(json.dumps(data, indent=4))
    node = service.brain.read_node('source')
    node.recall_count += 1
    node.storage_tier = 'archival'
    service.brain.write_node(node)
    after = commit(service)
    result = service.compare(comparison(before, after))
    assert result['deltas'] == result['candidates'] == []
    save(service, claim('Unrelated free text; no explicit dependency'))
    other = commit(service)
    result = service.compare(comparison(after, other))
    assert len(result['deltas']) == 1 and result['candidates'] == []


@pytest.mark.parametrize('accepted', [False, True])
def test_new_comparable_opposition_is_candidate_not_refutation(service, accepted):
    refs = scenario(service)
    before = commit(service)
    _, ev = evidence(service, refs['profile'], node='counter', text='Counter observation', lineage='experiment-2')
    rel = link(service, 'opposes', ev, refs['claim'], context(refs['profile']), accepted=accepted)
    after = commit(service)
    result = service.compare(comparison(before, after))
    assert result['candidates']
    for c in result['candidates']:
        assert 'comparable_opposition' in c['reasons']
        assert c['classification'] == ('candidate_semantic_impact' if accepted else 'proposed_preview')
        assert 'unreviewed' in c['judgment']
        assert c['target'] == refs['decision']
    assert service.inspect(refs['claim'])['effective_assessment'] == 'unassessed'


@pytest.mark.parametrize('workload,expected', [('other', 'disjoint'), (None, 'unknown')])
def test_incomparable_or_unknown_opposition_never_becomes_contradiction(service, workload, expected):
    refs = scenario(service)
    before = commit(service)
    ctx = context(refs['profile'], workload) if workload else None
    _, ev = evidence(service, refs['profile'], node='counter')
    original = service.inspect(ev)['record']
    updated = draft('evidence', dict(original['payload'], context=ctx), identity=ev['id'],
                    anchor=original['anchor_node_id'], previous=ev)
    ev2, = save(service, updated)
    rel = link(service, 'opposes', ev2, refs['claim'], context(refs['profile']), accepted=False)
    after = commit(service)
    result = service.compare(comparison(before, after))
    if expected == 'disjoint':
        assert result['candidates'] == []
    else:
        assert result['candidates']
        assert all('comparability_unknown' in c['reasons'] and 'comparable_opposition' not in c['reasons'] for c in result['candidates'])


def test_withdrawal_retains_independent_support_and_shared_lineage_is_not_vote(service):
    refs = scenario(service)
    _, ev2 = evidence(service, refs['profile'], node='second', lineage='experiment-2')
    _, duplicate = evidence(service, refs['profile'], node='copy', lineage='experiment-2')
    link(service, 'supports', ev2, refs['claim'], context(refs['profile']))
    link(service, 'supports', duplicate, refs['claim'], context(refs['profile']))
    before = commit(service)
    review(service, refs['evidence'], axis='availability', after='withdrawn')
    after = commit(service)
    result = service.compare(comparison(before, after))
    assert len(result['candidates']) == 1
    c = result['candidates'][0]
    assert 'support_withdrawn' in c['reasons'] and 'comparable_opposition' not in c['reasons']
    assert len(c['support']['removed']) == 1
    assert len(c['support']['remaining']) == 2
    assert {x['lineage'] for x in c['support']['remaining']} == {'shared', 'distinct_recorded_roots'}
    assert service.inspect(refs['claim'])['state']['epistemic'] == 'unassessed'


def test_retracted_attachment_reports_removed_support(service):
    refs = scenario(service)
    before = commit(service)
    review(service, refs['support'], axis='availability', after='withdrawn')
    after = commit(service)
    c, = service.compare(comparison(before, after))['candidates']
    assert len(c['support']['removed']) == 1 and c['support']['remaining'] == []
    assert 'support_withdrawn' in c['reasons']


def test_bounds_cycles_deterministic_paths_and_similar_edges_do_not_prove_dependencies(service):
    refs = scenario(service)
    c2, = save(service, claim('A second premise', context(refs['profile'])))
    link(service, 'depends_on', c2, refs['claim'], context(refs['profile']))
    link(service, 'depends_on', refs['claim'], c2, context(refs['profile']))
    d2, = save(service, draft('decision', dict(action='Other choice', rationale='Unrelated', alternatives=[], context=None, revisit_checks=[])))
    link(service, 'similar_to', d2, refs['claim'], None)
    before = commit(service)
    change_source(service)
    after = commit(service)
    result = service.compare(comparison(before, after))
    assert all(c['target'] != d2 for c in result['candidates'])
    assert 'dependency_cycle' in result['warnings'] or 'depth' in result['completeness']['hit_limits']
    bounded = service.compare(comparison(before, after, depth=1))
    assert bounded['candidates'] == []
    assert bounded['completeness']['truncated'] and 'depth' in bounded['completeness']['hit_limits']
    for name in LIMITS:
        with pytest.raises(s.RecordError):
            service.compare(comparison(before, after, **{name: LIMITS[name] + 1}))
        tiny = service.compare(comparison(before, after, **{name: 1}))
        assert tiny['completeness']['examined_links'] <= tiny['completeness']['limits']['links']


def test_current_revocation_and_tombstones_filter_historical_paths_before_analysis(service, tmp_path, monkeypatch):
    from graph_engine.access import SecuredBrain
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    assert service.compare(comparison(before, after))['candidates']
    policy = {'graphs': {'default': {'roles': {'reader': 'viewer'}, 'nodes': {'source': {'read': []}}}}, 'tokens': {}}
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    secured = DecisionService(SecuredBrain(str(service.brain.path), mode='git', graph_name='default', identity='reader'))
    result = secured.compare(comparison(before, after))
    raw = json.dumps(result)
    for r in refs.values():
        assert r['id'] not in raw
    assert 'Local observation' not in raw and result['deltas'] == result['candidates'] == []
    monkeypatch.delenv('IG_ACCESS_POLICY')
    service.brain.tombstone_node('source')
    forgotten = service.compare(comparison(before, after))
    assert forgotten['deltas'] == forgotten['candidates'] == []


def finding_envelope(service, comp, candidate, disposition='confirmed'):
    p = service.preview()
    return dict(schema='dm.finding-review/1', idempotency_key=str(uuid4()),
        expected_generation=p['generation'], expected_heads=p['heads'], comparison=comp,
        candidate_id=candidate['candidate_id'], disposition=disposition, reason='Explicit triage review')


@pytest.mark.parametrize('secured', [False, True])
@pytest.mark.parametrize('forgotten_at', ['current', 'historical'])
def test_forgotten_ancestor_filters_comparisons_but_not_explicit_snapshots(
        service, tmp_path, monkeypatch, secured, forgotten_at):
    from graph_engine.access import SecuredBrain
    from graph_engine.snapshots import snapshot
    refs = scenario(service)
    service.brain.write_node(Node('Original observation', id='root'))
    service.brain.write_node(Node('Copied observation', id='copy', derived_from=['root']))
    source = service.brain.read_node('source')
    source.derived_from = ['copy']
    service.brain.write_node(source)
    before = commit(service)
    change_source(service)
    if forgotten_at == 'historical':
        service.brain.tombstone_node('root')
    after = commit(service)
    if forgotten_at == 'current':
        assert service.compare(comparison(before, after))['candidates']
        service.brain.tombstone_node('root')
    else:
        root = service.brain.read_node('root')
        root.status = 'active'
        service.brain.write_node(root)
    if secured:
        path = tmp_path / 'policy.json'
        path.write_text(json.dumps({'graphs': {'default': {'roles': {'reader': 'viewer'}, 'nodes': {}}}, 'tokens': {}}))
        monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
        service = DecisionService(SecuredBrain(str(service.brain.path), mode='git', graph_name='default', identity='reader'))
    saved = files(service.brain)
    result = service.compare(comparison(before, after))
    assert result['deltas'] == result['candidates'] == result['reviewed_judgments'] == []
    assert refs['source']['id'] not in json.dumps(result)
    assert refs['evidence']['id'] not in json.dumps(result)
    assert not result['completeness']['truncated']
    historical = snapshot(service.brain, after)['decision_memory']
    assert any(v['id'] == refs['source']['id'] for v in historical['versions'])
    assert files(service.brain) == saved


@pytest.mark.parametrize('already_proposed', [False, True])
def test_newly_accepted_support_prevents_stale_finding_publication(service, already_proposed):
    refs = scenario(service)
    _, ev = evidence(service, refs['profile'], node='second', lineage='experiment-2')
    proposed = link(service, 'supports', ev, refs['claim'], context(refs['profile']), accepted=False) if already_proposed else None
    before = commit(service)
    change_source(service)
    after = commit(service)
    comp = comparison(before, after)
    candidate, = service.compare(comp)['candidates']
    if proposed:
        review(service, proposed)
    else:
        link(service, 'supports', ev, refs['claim'], context(refs['profile']))
    latest = commit(service)
    updated = next(c for c in service.compare(comparison(before, latest))['candidates']
                   if c['delta']['delta_id'] == candidate['delta']['delta_id'])
    assert updated['support']['remaining'] and updated['candidate_id'] != candidate['candidate_id']
    saved = files(service.brain)
    request = finding_envelope(service, comp, candidate)
    for dry_run in (True, False):
        with pytest.raises(s.RecordConflict, match='stale'):
            service.record_finding(request, dry_run=dry_run, commit=False)
        assert files(service.brain) == saved
    finding, = service.record_finding(finding_envelope(service, comparison(before, latest), updated), commit=False)['receipt']['refs']
    assert not service.inspect(finding)['basis_changed']


def test_added_support_marks_recorded_finding_stale_without_blocking_retry_or_acknowledgment(service):
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    comp = comparison(before, after)
    candidate, = service.compare(comp)['candidates']
    request = finding_envelope(service, comp, candidate)
    result = service.record_finding(request, commit=False)
    finding, = result['receipt']['refs']
    _, ev = evidence(service, refs['profile'], node='second', lineage='experiment-2')
    link(service, 'supports', ev, refs['claim'], context(refs['profile']))
    assert service.inspect(finding)['basis_changed']
    assert service.record_finding(request, commit=False) == result
    review(service, finding, axis='finding_workflow', after='acknowledged')
    assert service.inspect(finding)['state']['finding_workflow'] == 'acknowledged'


def test_unrelated_or_proposed_support_does_not_stale_finding(service):
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    comp = comparison(before, after)
    candidate, = service.compare(comp)['candidates']
    _, ev = evidence(service, refs['profile'], node='second', lineage='experiment-2')
    link(service, 'supports', ev, refs['claim'], context(refs['profile']), accepted=False)
    other, = save(service, claim('An unrelated premise', context(refs['profile'])))
    link(service, 'supports', ev, other, context(refs['profile']))
    finding, = service.record_finding(finding_envelope(service, comp, candidate), commit=False)['receipt']['refs']
    assert not service.inspect(finding)['basis_changed']


def test_clipped_support_summary_keeps_complete_membership_for_finding_freshness(service):
    refs = scenario(service)
    extra = save(service, *(draft('relationship', dict(kind='supports', source=refs['evidence'],
        target=refs['claim'], context=context(refs['profile']), explanation='Another recorded attachment'))
        for _ in range(20)))
    profile_review = service.inspect(refs['profile'])['events'][-1]
    service.submit(envelope(service, events=[event(r, axis='workflow', before='proposed', after='accepted',
        basis=[{'type': 'event_ref', 'event_id': profile_review['event_id']}]) for r in extra]), commit=False)
    before = commit(service)
    change_source(service)
    after = commit(service)
    comp = comparison(before, after)
    candidate, = service.compare(comp)['candidates']
    assert 'support_output' in candidate['completeness']['hit_limits']
    assert len(candidate['support']['removed']) == 20
    assert all(r in candidate['basis_refs'] for r in [refs['support'], *extra])
    request = finding_envelope(service, comp, candidate)
    result = service.record_finding(request, commit=False)
    finding, = result['receipt']['refs']
    assert not service.inspect(finding)['basis_changed']
    assert service.record_finding(request, commit=False) == result


def test_findings_explicit_idempotent_resolved_and_material_successor_preserves_disposition(service):
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    comp = comparison(before, after)
    candidate, = service.compare(comp)['candidates']
    req = finding_envelope(service, comp, candidate)
    state_before = files(service.brain)
    service.record_finding(req, dry_run=True, commit=False)
    assert files(service.brain) == state_before
    result = service.record_finding(req, commit=False)
    finding, = result['receipt']['refs']
    assert service.inspect(finding)['state']['finding_workflow'] == 'open'
    review(service, finding, axis='finding_workflow', after='acknowledged')
    review(service, refs['decision'], axis='decision_conclusion', after='needs_investigation', basis=[content_basis(refs['claim'])])
    decision_review = service.inspect(refs['decision'])['events'][-1]
    followup, = save(service, check_record())
    review(service, finding, axis='finding_workflow', after='resolved', basis=[
        {'type': 'event_ref', 'event_id': decision_review['event_id']}, content_basis(followup)])
    state_before = files(service.brain)
    assert service.record_finding(req, commit=False)['receipt'] == result['receipt']
    assert service.compare(comp)['candidates'][0]['candidate_id'] == candidate['candidate_id']
    assert files(service.brain) == state_before
    with pytest.raises(s.RecordConflict, match='already reviewed'):
        service.record_finding(finding_envelope(service, comp, candidate), commit=False)
    change_source(service, 'Materially newer observation')
    newer = commit(service)
    successor = service.compare(comparison(before, newer))['candidates'][0]
    assert successor['candidate_id'] != candidate['candidate_id']
    req2 = finding_envelope(service, comparison(before, newer), successor, 'inconclusive')
    stored = service.record_finding(req2, commit=False)['receipt']['refs'][0]
    assert stored['id'] == finding['id'] and stored != finding
    assert service.inspect(finding)['state']['finding_workflow'] == 'resolved'
    assert service.inspect(stored)['record']['previous'] == finding
    assert service.inspect(stored)['state']['finding_disposition'] == 'inconclusive'


def test_unrelated_commit_does_not_change_candidate_identity(service):
    scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    c, = service.compare(comparison(before, after))['candidates']
    save(service, claim('Unrelated new record'))
    unrelated = commit(service)
    same, = service.compare(comparison(before, unrelated))['candidates']
    assert same['candidate_id'] == c['candidate_id']


def test_cli_http_share_no_model_comparison_and_validation(service, monkeypatch, capsys, tmp_path):
    from graph_engine.__main__ import cmd_decision
    from graph_engine.server import app
    scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    env = comparison(before, after)
    path = tmp_path / 'compare.json'
    path.write_text(json.dumps(env))
    cmd_decision(['compare', str(path)])
    result = json.loads(capsys.readouterr().out)
    assert result['candidates']
    with TestClient(app) as client:
        response = client.post('/api/decision-memory/compare', json=env)
        assert response.status_code == 200, response.text
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['candidates'] == result['candidates']
        assert client.post('/api/decision-memory/compare', json=dict(env, limits={'depth': 4})).status_code == 400
        req = finding_envelope(service, env, result['candidates'][0])
        response = client.post('/api/decision-memory/findings?dry_run=true', json=req)
        assert response.status_code == 200, response.text


def test_local_or_malformed_revisions_fail_without_writes(service):
    before = files(service.brain)
    for bad in ('../secret', '-x', '', None, 'no-such-ref'):
        with pytest.raises(ValueError):
            service.compare(comparison(bad, 'HEAD'))
    local = DecisionService(Brain(str(service.brain.path), mode='local'))
    with pytest.raises(ValueError, match='Git'):
        local.compare(comparison('HEAD', 'HEAD'))
    assert files(service.brain) == before


@pytest.mark.parametrize('dimension,a,b,mode', [
    ('unit', {'type': 'enum', 'value': 'ms'}, {'type': 'enum', 'value': 's'}, 'equal'),
    ('code_revision', {'type': 'id', 'value': 'v1'}, {'type': 'id', 'value': 'v2'}, 'equal'),
    ('environment', {'type': 'id', 'value': 'cpu'}, {'type': 'id', 'value': 'gpu'}, 'equal'),
    ('window', {'type': 'time_window', 'value': {'from': '2026-01-01T00:00:00Z', 'to': '2026-02-01T00:00:00Z'}},
               {'type': 'time_window', 'value': {'from': '2026-02-01T00:00:00Z', 'to': '2026-03-01T00:00:00Z'}}, 'overlap'),
])
def test_different_structured_units_versions_environments_and_windows_do_not_conflict(service, dimension, a, b, mode):
    p, = save(service, draft('profile', dict(name='Exact comparison scope', version='1', dimensions={
        dimension: dict(type=a['type'], unit=None, required=True, compare=mode, allowed_values=None)}, interventions=[])))
    review(service, p)
    ctx = dict(schema='dm.context/1', profile=p, dimensions={dimension: a}, notes='')
    c, = save(service, claim(context=ctx))
    d, = save(service, draft('decision', dict(action='Retain', rationale='Pinned scope', alternatives=[], context=ctx, revisit_checks=[])))
    link(service, 'depends_on', d, c, ctx)
    before = commit(service)
    ctx2 = dict(ctx, dimensions={dimension: b})
    _, ev = evidence(service, p, ctx=ctx2)
    link(service, 'opposes', ev, c, ctx, accepted=False)
    after = commit(service)
    assert service.compare(comparison(before, after))['candidates'] == []


def test_changed_scope_of_old_support_requests_review_without_claiming_opposition(service):
    refs = scenario(service)
    before = commit(service)
    original = service.inspect(refs['evidence'])['record']
    ev2, = save(service, draft('evidence', dict(original['payload'], context=context(refs['profile'], 'different-workload')),
        identity=original['id'], anchor=original['anchor_node_id'], previous=refs['evidence']))
    after = commit(service)
    c, = service.compare(comparison(before, after))['candidates']
    assert 'scope_changed' in c['reasons'] and 'comparable_opposition' not in c['reasons']
    assert c['support']['remaining'] == []
    assert c['substitutions'] == [{'old': refs['evidence'], 'new': ev2}]


def test_check_result_explicit_direction_is_required(service):
    refs = scenario(service)
    check, = save(service, check_record())
    link(service, 'checks', check, refs['decision'], None)
    before = commit(service)
    res, = save(service, result_record(check, [refs['source']]))
    no_attachment = commit(service)
    assert service.compare(comparison(before, no_attachment))['candidates'] == []
    rel = link(service, 'result_of', res, check, None)
    after = commit(service)
    candidates = service.compare(comparison(no_attachment, after))['candidates']
    assert candidates and all('revisit_check_result' in c['reasons'] for c in candidates)
    assert [x['kind'] for x in candidates[0]['paths'][0]] == ['result_of', 'checks']


def test_new_review_events_have_distinct_stable_identities(service):
    refs = scenario(service)
    before = commit(service)
    review(service, refs['claim'], after='accepted')
    after = commit(service)
    result = service.compare(comparison(before, after))
    c, = result['candidates']
    assert result['deltas'][0]['classes'] == ['review']
    assert result['reviewed_judgments'][0]['subject'] == refs['claim']
    assert c['delta']['event_id'] in c['basis_event_ids']


def test_no_hidden_intermediate_explanation_and_concurrent_acl_change_fails_closed(service, tmp_path, monkeypatch):
    from graph_engine.access import SecuredBrain
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    middle = service.inspect(refs['claim'])['record']['anchor_node_id']
    policy = {'graphs': {'default': {'roles': {'reader': 'viewer'}, 'nodes': {middle: {'read': []}}}}, 'tokens': {}}
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    secured = DecisionService(SecuredBrain(str(service.brain.path), mode='git', graph_name='default', identity='reader'))
    result = secured.compare(comparison(before, after))
    raw = json.dumps(result)
    assert result['candidates'] == [] and refs['claim']['id'] not in raw and middle not in raw
    import graph_engine.decision_impact as impact
    real = impact.authorization
    calls = []
    def race(brain):
        calls.append(1)
        return real(brain) if len(calls) == 1 else 'changed-policy'
    monkeypatch.setattr(impact, 'authorization', race)
    with pytest.raises(s.RecordConflict, match='Authorization'):
        secured.compare(comparison(before, after))


def test_missing_evidence_does_not_resurrect_historical_source(service):
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    service.brain.node_path('source').unlink()
    result = service.compare(comparison(before, after))
    assert refs['source']['id'] not in json.dumps(result)
    assert result['deltas'] == result['candidates'] == []


@pytest.mark.parametrize('family', ['graph', 'context', 'documents', 'cache'])
def test_frozen_development_sources_are_unresolved_without_invented_dependencies(service, family):
    # Source-only development split. No held-out labels or rationales are read.
    root = Path(__file__).resolve().parents[1] / 'tools/decision_benchmark/data/project-v1'
    inputs = json.loads((root / 'inputs.json').read_text())
    freeze = json.loads((root / 'freeze.json').read_text())
    sources = {v['id']: v for v in inputs['sources'] if v['split'] == 'development'}
    basis, update = (sources[family + suffix] for suffix in ('-basis', '-update-1'))
    def read_source(metadata):
        raw = (root / metadata['file']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == freeze['files'][metadata['file']]
        return raw.decode()
    text, updated = read_source(basis), read_source(update)
    service.brain.write_node(Node(text, id='frozen-development'))
    src, = save(service, draft('source', service.source('frozen-development'), anchor='frozen-development'))
    c, = save(service, claim('A manually captured development-only proposition', inputs=[src]))
    d, = save(service, draft('decision', dict(action='Retain documented choice', rationale='Development fixture; unknown scope', alternatives=[], context=None, revisit_checks=[])))
    unrelated, = save(service, draft('decision', dict(action='Another choice', rationale='No dependency', alternatives=[], context=None, revisit_checks=[])))
    link(service, 'depends_on', d, c, None)
    before = commit(service)
    n = service.brain.read_node('frozen-development')
    n.text = updated
    service.brain.write_node(n)
    after = commit(service)
    result = service.compare(comparison(before, after))
    assert result['deltas'] and len(result['candidates']) == 1
    candidate = result['candidates'][0]
    assert candidate['target'] == d and candidate['target'] != unrelated
    assert [x['kind'] for x in candidate['paths'][0]] == ['explicit_input', 'depends_on']
    assert 'comparable_opposition' not in candidate['reasons']
    assert candidate['comparison'][0]['status'] == 'unknown'  # No scoped contradiction from free text.
    assert service.inspect(c)['effective_assessment'] == 'inconclusive'
    assert service.inspect(d)['state']['decision'] == 'proposed'


def test_resolution_requires_decision_review_and_followup_and_same_input_cannot_reopen(service):
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    comp = comparison(before, after)
    c, = service.compare(comp)['candidates']
    finding, = service.record_finding(finding_envelope(service, comp, c), commit=False)['receipt']['refs']
    before_state = files(service.brain)
    with pytest.raises(s.RecordError, match='decision review'):
        review(service, finding, axis='finding_workflow', after='resolved')
    assert files(service.brain) == before_state
    # Dismissed and unconfirmed findings never acquire an open workflow.
    req = finding_envelope(service, comp, c)
    with pytest.raises(s.RecordConflict):
        service.record_finding(req, commit=False)
    bad = deepcopy(c)
    bad['paths'][0][-1]['direction'] = 'forward'
    assert candidate_identity(bad) != c['candidate_id']
    with pytest.raises(s.RecordError, match='identity'):
        validate_candidate(bad)


def test_profile_successor_prevents_stale_finding_publication(service):
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    comp = comparison(before, after)
    c, = service.compare(comp)['candidates']
    old = service.inspect(refs['profile'])['record']
    save(service, draft('profile', dict(old['payload'], version='2'), identity=old['id'],
                        anchor=old['anchor_node_id'], previous=refs['profile']))
    state_before = files(service.brain)
    with pytest.raises(s.RecordConflict, match='stale'):
        service.record_finding(finding_envelope(service, comp, c), commit=False)
    assert files(service.brain) == state_before


def test_relationship_review_correction_retains_lost_support_explanation(service):
    refs = scenario(service)
    before = commit(service)
    accepted = service.inspect(refs['support'])['events'][-1]
    correction = event(refs['support'], axis='workflow', before='accepted', after='proposed',
                       basis=accepted['basis'], previous=accepted['event_id'], correct=accepted['event_id'])
    service.submit(envelope(service, events=[correction]), commit=False)
    after = commit(service)
    c, = service.compare(comparison(before, after))['candidates']
    assert c['support']['remaining'] == [] and len(c['support']['removed']) == 1
    assert c['paths'][0][0]['revision'] == before
    assert c['classification'] == 'candidate_semantic_impact'


def test_dismissed_candidate_has_no_workflow_and_cannot_be_acknowledged(service):
    scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    comp = comparison(before, after)
    candidate, = service.compare(comp)['candidates']
    finding, = service.record_finding(finding_envelope(service, comp, candidate, 'dismissed'), commit=False)['receipt']['refs']
    assert service.inspect(finding)['state']['finding_workflow'] is None
    with pytest.raises(s.RecordError):
        review(service, finding, axis='finding_workflow', after='acknowledged')


def test_moving_support_to_another_claim_preserves_original_loss_path(service):
    refs = scenario(service)
    other, = save(service, claim('Another scope-compatible proposition', context(refs['profile'])))
    before = commit(service)
    old = service.inspect(refs['support'])['record']
    save(service, draft('relationship', dict(old['payload'], target=other), identity=old['id'],
                        anchor=old['anchor_node_id'], previous=refs['support']))
    after = commit(service)
    c, = service.compare(comparison(before, after))['candidates']
    assert c['target'] == refs['decision']
    assert c['paths'][0][0]['relationship'] == refs['support']
    assert c['paths'][0][0]['revision'] == before
    assert c['support']['remaining'] == [] and len(c['support']['removed']) == 1


def test_source_provenance_alone_is_not_an_accepted_decision_dependency(service):
    service.brain.write_node(Node('Unreviewed input', id='source'))
    src, = save(service, draft('source', service.source('source'), anchor='source'))
    save(service, draft('decision', dict(action='Retain', rationale='A source is provenance', alternatives=[], context=None, revisit_checks=[]), inputs=[src]))
    before = commit(service)
    change_source(service)
    after = commit(service)
    result = service.compare(comparison(before, after))
    assert result['deltas'] and result['candidates'] == []


def test_http_compare_current_auth_and_finding_write_permissions(service, tmp_path, monkeypatch):
    from graph_engine.server import app
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    comp = comparison(before, after)
    candidate, = service.compare(comp)['candidates']
    req = finding_envelope(service, comp, candidate)
    policy = {'graphs': {'default': {'roles': {'editor': 'editor', 'reader': 'viewer'}, 'nodes': {}}},
              'tokens': {hashlib.sha256(b'edit').hexdigest(): 'editor', hashlib.sha256(b'read').hexdigest(): 'reader'}}
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    with TestClient(app) as client:
        assert client.post('/api/decision-memory/compare', json=comp).status_code == 401
        viewer = {'Authorization': 'Bearer read'}
        assert client.post('/api/decision-memory/compare', json=comp, headers=viewer).json()['candidates']
        assert client.post('/api/decision-memory/findings', json=req, headers=viewer).status_code == 403
        policy['graphs']['default']['nodes']['source'] = {'read': []}
        path.write_text(json.dumps(policy))
        result = client.post('/api/decision-memory/compare', json=comp, headers=viewer)
        assert result.status_code == 200
        assert refs['source']['id'] not in result.text and result.json()['candidates'] == []


def test_mixed_integer_decimal_ranges_remain_unknown(service):
    from graph_engine.decision_service import compare_context
    from graph_engine.decision_memory import RecordView
    p, = save(service, draft('profile', dict(name='Typed range', version='1', dimensions={
        'range': dict(type='range', unit=None, required=True, compare='overlap', allowed_values=None)}, interventions=[])))
    review(service, p)
    def ctx(lower, upper):
        return dict(schema='dm.context/1', profile=p, notes='', dimensions={'range': {'type': 'range', 'value': dict(
            lower=lower, upper=upper, lower_inclusive=True, upper_inclusive=True)}})
    view = RecordView(service.brain, read_file(service.brain))
    result = compare_context(ctx(1, 2), ctx('1', '2'), view)
    assert result['status'] == 'unknown'


def test_policy_is_frozen_even_if_changed_then_restored_during_comparison(service, tmp_path, monkeypatch):
    from graph_engine.access import SecuredBrain
    import graph_engine.decision_impact as impact
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    policy = {'graphs': {'default': {'roles': {'reader': 'viewer'}, 'nodes': {'source': {'read': []}}}}, 'tokens': {}}
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    secured = DecisionService(SecuredBrain(str(service.brain.path), mode='git', graph_name='default', identity='reader'))
    real = impact.revision
    calls = []
    def race(brain, name, current, frozen_policy):
        calls.append(name)
        relaxed = deepcopy(policy)
        relaxed['graphs']['default']['nodes'] = {}
        path.write_text(json.dumps(relaxed))
        result = real(brain, name, current, frozen_policy)
        if len(calls) == 2:
            path.write_text(json.dumps(policy))
        return result
    monkeypatch.setattr(impact, 'revision', race)
    result = secured.compare(comparison(before, after))
    assert result['deltas'] == result['candidates'] == []
    assert refs['source']['id'] not in json.dumps(result)

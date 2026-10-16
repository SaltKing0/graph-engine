"""Atomic qualified context, pinned briefs, and shared read surfaces (#79)."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from graph_engine import decision_schema as s, runtime
from graph_engine.brain import Edge, Node
from graph_engine.context import estimate_tokens
from graph_engine.decision_brief import render_markdown, DecisionReader
from graph_engine.decision_memory import BasisUnavailable
from graph_engine.decision_service import DecisionService
from test_decision_memory import draft, claim, content_basis, files, check_record, result_record
from test_decision_service import save, review, context, profile
from test_decision_impact import (service, scenario, commit, evidence, link, comparison,
                                  change_source, finding_envelope)


def read(service, operation, **kwargs):
    return service.read(operation, kwargs)


def conflict(service):
    refs = scenario(service)
    # A review judgment stays visible as a judgment, never as connectivity-derived truth.
    review(service, refs['claim'], axis='epistemic', after='supported', basis=[content_basis(refs['evidence'])])
    review(service, refs['decision'], axis='decision', after='current', basis=[content_basis(refs['claim'])])
    _, ev = evidence(service, refs['profile'], node='counter', text='Counter observation', lineage='experiment-2')
    opposition = link(service, 'opposes', ev, refs['claim'], context(refs['profile']), accepted=False)
    refs.update(counter=ev, opposition=opposition)
    return refs


def scored_edge(service):
    service.brain.write_node(Node('Unrelated memory', id='ordinary'))
    service.brain.add_edge(Edge('source', 'ordinary', 'similar', confidence=0.8, origin='suggester'))


def reviewed_basis(service):
    p = profile(service)
    src, ev = evidence(service, p)
    c, = save(service, claim(context=context(p)))
    support = link(service, 'supports', ev, c, context(p))
    review(service, c, axis='epistemic', after='supported', basis=[content_basis(ev), content_basis(support)])
    d, = save(service, draft('decision', dict(action='Keep opt-in', rationale='Limited diagnostic',
        alternatives=[], context=context(p), revisit_checks=[])))
    review(service, d, axis='decision', after='current', basis=[content_basis(c)])
    return dict(profile=p, source=src, evidence=ev, claim=c, support=support, decision=d)


def test_scored_graph_edges_allow_all_reads_and_still_detect_concurrent_changes(service):
    refs = scenario(service)
    scored_edge(service)
    sha = commit(service)
    before = files(service.brain)
    assert refs['source']['id'] in read(service, 'brief', reference=refs['decision'])['included_ids']
    assert read(service, 'context', query='Keep opt-in', budget=8000)['context']
    assert read(service, 'findings')['items'] == []
    assert read(service, 'inspect-revision', reference=refs['decision'], revision=sha)['record']['id'] == refs['decision']['id']
    assert service.compare(comparison(sha, sha))['deltas'] == []
    assert files(service.brain) == before
    reader = DecisionReader(service.brain, sha)
    result = reader.brief(refs['decision'])
    edges = service.brain.read_edges(include_rejected=True)
    edges[-1].confidence = 0.9
    service.brain.write_edges(edges)
    with pytest.raises(s.RecordConflict):
        reader.finish(result)


def test_review_basis_claim_keeps_new_opposition_in_brief_and_context(service):
    refs = reviewed_basis(service)
    before = commit(service)
    source, ev = evidence(service, refs['profile'], node='counter', text='Contrary observation')
    opposition = link(service, 'opposes', ev, refs['claim'], context(refs['profile']))
    sha = commit(service)
    brief = read(service, 'brief', reference=refs['decision'], revision=sha)
    assert {source['id'], ev['id'], opposition['id']} <= set(brief['included_ids'])
    assert not brief['completeness']['truncated']
    assert any(path['relationship'] == opposition for path in brief['paths'])
    assert 'Unresolved opposition' in render_markdown(brief)
    packed = read(service, 'context', query='Keep opt-in', budget=8000)
    assert packed['context'] and opposition['id'] in packed['included_ids']
    assert 'Contrary observation' in packed['context'] and 'Unresolved opposition' in packed['context']
    assert opposition['id'] not in read(service, 'brief', reference=refs['decision'], revision=before)['included_ids']


def test_payload_revisit_check_keeps_linked_result_in_brief_and_context(service):
    check, = save(service, check_record())
    decision, = save(service, draft('decision', dict(action='Keep opt-in', rationale='Revisit the diagnostic',
        alternatives=[], context=None, revisit_checks=[check])))
    result, = save(service, result_record(check, hypothetical=True))
    relationship = link(service, 'result_of', result, check, None)
    commit(service)
    brief = read(service, 'brief', reference=decision)
    assert {check['id'], result['id'], relationship['id']} <= set(brief['included_ids'])
    assert not brief['completeness']['truncated']
    assert any(path['relationship'] == relationship for path in brief['paths'])
    packed = read(service, 'context', query='Keep opt-in', budget=8000)
    assert packed['context'] and result['id'] in packed['included_ids']
    assert '"hypothetical":true' in packed['context']


@pytest.mark.parametrize('limit,value,hit', [('MAX_DEPTH', 0, 'depth'), ('MAX_LINKS', 1, 'links'),
                                           ('MAX_RECORDS', 3, 'records')])
def test_review_dependency_expansion_retains_hard_bounds(service, monkeypatch, limit, value, hit):
    import graph_engine.decision_brief as module
    refs = reviewed_basis(service)
    _, ev = evidence(service, refs['profile'], node='counter', text='Contrary observation')
    link(service, 'opposes', ev, refs['claim'], context(refs['profile']))
    commit(service)
    monkeypatch.setattr(module, limit, value)
    brief = read(service, 'brief', reference=refs['decision'])
    assert brief['completeness']['truncated'] and hit in brief['completeness']['hit_limits']
    assert len(brief['records']) <= module.MAX_RECORDS
    packed = read(service, 'context', query='Keep opt-in', budget=8000)
    assert packed['context'] == '' and packed['omitted'][0]['reason'] == 'incomplete'


def test_conflicting_evidence_conditions_reviews_and_exact_citations(service, monkeypatch):
    refs = conflict(service)
    sha = commit(service)
    before = files(service.brain)
    for name in ('ensure_ready', 'pull', 'write_node', 'write_vectors', 'rebuild_index', 'commit_and_push', 'write_guard'):
        monkeypatch.setattr(service.brain, name, lambda *a, **kw: pytest.fail('Read mutated brain'))
    result = read(service, 'brief', reference=refs['decision'], revision=sha)
    ids = result['included_ids']
    assert {r['id'] for r in refs.values()} <= set(ids)
    assert {s.key(r) for r in result['included_refs']} == {s.key(i['record']) for i in result['records']}
    assert result['included_event_ids'] == sorted({e['event_id'] for item in result['records'] for e in item['events']})
    text = render_markdown(result)
    for value in ('Counter observation', 'Limited diagnostic', 'diagnostic', 'proposed',
                  'supported', 'Explicit review', 'not truth confidence', 'opposes'):
        assert value in text
    assert refs['source']['version_id'] in text
    assert not result['completeness']['truncated']
    assert result == read(service, 'brief', reference=refs['decision'], revision=sha)
    assert text == render_markdown(read(service, 'brief', reference=refs['decision'], revision='HEAD'))
    assert files(service.brain) == before


def test_budget_atomicity_and_exact_included_id_accounting(service):
    refs = conflict(service)
    sha = commit(service)
    full = render_markdown(read(service, 'brief', reference=refs['decision'], revision=sha), compact=True)
    required = estimate_tokens(full)
    assert required < 8000
    for budget in (0, 1, 20, required - 1, required, 8000):
        result = read(service, 'context', query='Keep opt-in', budget=budget)
        assert result['tokens'] == estimate_tokens(result['context']) <= budget
        if budget < required:
            assert result['context'] == ''
            assert result['included_refs'] == result['included_ids'] == result['included_event_ids'] == []
            assert result['truncated'] and result['omitted'][0]['reason'] == 'budget'
        else:
            assert result['context'] == full
            assert refs['opposition']['id'] in result['included_ids']
            assert 'Counter observation' in result['context']
            assert result['decisions'] == [refs['decision']]
            assert not result['truncated']


def test_long_scope_is_omitted_with_conclusion(service):
    refs = scenario(service)
    original = service.inspect(refs['decision'])['record']
    scope = dict(context(refs['profile']), notes='Very long necessary scope condition ' * 90)
    successor, = save(service, draft('decision', dict(original['payload'], context=scope),
        identity=original['id'], anchor=original['anchor_node_id'], previous=refs['decision']))
    commit(service)
    result = read(service, 'context', query='Keep opt-in', budget=1000)
    assert result['context'] == '' and result['truncated']
    brief = read(service, 'brief', reference=successor)
    assert scope['notes'] in render_markdown(brief)


def test_unresolved_findings_include_exact_paths_review_reason_and_history(service):
    refs = scenario(service)
    before = commit(service)
    change_source(service)
    after = commit(service)
    comp = comparison(before, after)
    candidate, = service.compare(comp)['candidates']
    request = finding_envelope(service, comp, candidate)
    finding, = service.record_finding(request, commit=False)['receipt']['refs']
    reviewed = commit(service)
    result = read(service, 'findings', revision=reviewed, decision_id=refs['decision']['id'])
    item, = result['items']
    assert item['record']['payload']['candidate']['paths'] == candidate['paths']
    assert item['events'][0]['reason'] == request['reason']
    assert item['state']['finding_workflow'] == 'open'
    brief = read(service, 'brief', reference=refs['decision'], revision=reviewed)
    assert finding['id'] in brief['included_ids']
    assert request['reason'] in render_markdown(brief)
    review(service, finding, axis='finding_workflow', after='acknowledged')
    review(service, refs['decision'], axis='decision_conclusion', after='needs_investigation', basis=[content_basis(refs['claim'])])
    outcome = service.inspect(refs['decision'])['events'][-1]['event_id']
    followup, = save(service, check_record())
    review(service, finding, axis='finding_workflow', after='resolved', basis=[dict(type='event_ref', event_id=outcome), content_basis(followup)])
    commit(service)
    assert read(service, 'findings')['items'] == []
    assert read(service, 'findings', unresolved_only=False)['items'][0]['state']['finding_workflow'] == 'resolved'
    assert read(service, 'findings', revision=reviewed, decision_id=refs['decision']['id']) == result


def test_revoked_evidence_and_tombstones_cannot_reappear_in_historical_context(service, tmp_path, monkeypatch):
    from graph_engine.access import SecuredBrain
    refs = scenario(service)
    sha = commit(service)
    policy = {'graphs': {'default': {'roles': {'reader': 'viewer'}, 'nodes': {}}}, 'tokens': {}}
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    secured = DecisionService(SecuredBrain(str(service.brain.path), mode='git', identity='reader', graph_name='default'))
    assert refs['source']['id'] in read(secured, 'brief', reference=refs['decision'], revision=sha)['included_ids']
    policy['graphs']['default']['nodes']['source'] = {'read': []}
    path.write_text(json.dumps(policy))
    text = json.dumps(read(secured, 'brief', reference=refs['decision'], revision=sha))
    assert refs['source']['id'] not in text and 'Local observation' not in text
    assert 'Missing evidence' in text
    with pytest.raises(BasisUnavailable):
        read(secured, 'inspect-revision', reference=refs['evidence'], revision=sha)
    monkeypatch.delenv('IG_ACCESS_POLICY')
    from graph_engine.agent_memory import forget
    forget(service.brain, 'source', reason='forget source', commit=False)
    result = read(service, 'brief', reference=refs['decision'], revision=sha)
    assert refs['source']['id'] not in json.dumps(result)


def test_acl_or_current_lineage_changes_during_read_fail_closed(service, monkeypatch):
    refs = scenario(service)
    commit(service)
    reader = DecisionReader(service.brain, 'HEAD')
    value = reader.brief(refs['decision'])
    node = service.brain.read_node('source')
    node.text = 'Concurrent edit'
    service.brain.write_node(node)
    with pytest.raises(s.RecordConflict):
        reader.finish(value)


def test_brief_is_pinned_after_successor_and_unrelated_commits(service):
    refs = scenario(service)
    sha = commit(service)
    original = read(service, 'brief', reference=refs['decision'], revision=sha)
    change_source(service)
    commit(service)
    assert read(service, 'brief', reference=refs['decision'], revision=sha) == original
    assert read(service, 'inspect-revision', reference=refs['claim'], revision=sha)['effective_assessment'] == 'unassessed'
    assert read(service, 'brief', reference=refs['decision'])['records'] != original['records']


def test_limits_warn_and_context_omits_incomplete_units(service, monkeypatch):
    import graph_engine.decision_brief as module
    refs = scenario(service)
    commit(service)
    monkeypatch.setattr(module, 'MAX_RECORDS', 3)
    brief = read(service, 'brief', reference=refs['decision'])
    assert brief['completeness']['truncated']
    assert 'do not treat this decision' in render_markdown(brief)
    result = read(service, 'context', query='Keep opt-in', budget=8000)
    assert result['context'] == '' and result['omitted'][0]['reason'] == 'incomplete'


@pytest.mark.parametrize('operation,envelope', [('brief', {}), ('context', {'query': '', 'budget': 1}),
    ('context', {'query': 'x', 'budget': True}), ('findings', {'unresolved_only': 'yes'}),
    ('findings', {'unexpected': 1}), ('brief', {'reference': {}})])
def test_invalid_reads_fail_explicitly(service, operation, envelope):
    commit(service)
    with pytest.raises(s.RecordError):
        service.read(operation, envelope)


def test_cli_json_markdown_and_context(service):
    refs = scenario(service)
    sha = commit(service)
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent))
    for operation, envelope in [('brief', {'reference': refs['decision'], 'revision': sha}),
                                ('findings', {}), ('context', {'query': 'Keep opt-in', 'budget': 0})]:
        args = [sys.executable, '-m', 'graph_engine', 'decision', operation, '-']
        result = subprocess.run(args, env=env, input=json.dumps(envelope), text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == service.read(operation, envelope)
        if operation == 'brief':
            md = subprocess.run(args + ['--format', 'markdown'], env=env, input=json.dumps(envelope), text=True, capture_output=True)
            assert md.stdout == render_markdown(json.loads(result.stdout))


def test_offline_two_sessions_keep_qualifications_and_resolvable_references(tmp_path, monkeypatch):
    from examples import decision_memory as example
    import httpx
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: pytest.fail('Provider called'))
    path = tmp_path / 'demo'
    saved = example.first_session(path)
    result = example.second_session(path, saved)
    assert result['findings']['items']
    text = render_markdown(result['brief'])
    assert 'contrary outcome' in text and 'requires review' in text
    assert 'Unresolved opposition' in text
    packed = result['context']
    assert packed['context'] and packed['tokens'] <= 8000
    assert 'Unresolved opposition' in packed['context'] and 'path_reference' in packed['context']
    service = DecisionService(example.Brain(str(path), mode='git'))
    for ref in packed['included_refs']:
        assert read(service, 'inspect-revision', reference=ref, revision=packed['revision'])['record']['id'] == ref['id']


@pytest.mark.skipif(__import__('importlib.util').util.find_spec('mcp') is None, reason='mcp extra not installed')
@pytest.mark.parametrize('write', [False, True])
def test_new_reads_through_stdio_are_readonly_in_both_modes(service, write):
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    refs = conflict(service)
    scored_edge(service)
    sha = commit(service)
    before = files(service.brain)
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent), IG_MCP_CACHE_VECTORS='1')
    env.pop('IG_MCP_WRITE', None)
    arguments = ['-m', 'graph_engine', 'mcp'] + (['--write'] if write else [])
    calls = [('decision_inspect', dict(reference=refs['claim'], revision=sha)),
             ('decision_compare', dict(envelope=comparison(sha, sha))),
             ('decision_findings', dict(revision=sha)),
             ('decision_brief', dict(reference=refs['decision'], revision=sha)),
             ('decision_brief', dict(reference=refs['decision'], revision=sha, format='markdown')),
             ('build_decision_context', dict(query='Keep opt-in', budget=8000, revision=sha))]

    async def run():
        with anyio.fail_after(30):
            async with stdio_client(StdioServerParameters(command=sys.executable, args=arguments, env=env)) as (r, w):
                async with ClientSession(r, w) as client:
                    await client.initialize()
                    tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                    for name, args in calls:
                        assert tools[name].annotations.readOnlyHint is True
                        response = await client.call_tool(name, args)
                        assert not response.isError
                        value = json.loads(response.content[0].text)
                        assert value['ok'], value
                        if name == 'build_decision_context':
                            assert 'Unresolved opposition' in value['context']
                            assert refs['opposition']['id'] in value['included_ids']
    anyio.run(run)
    assert files(service.brain) == before


@pytest.mark.skipif(__import__('importlib.util').util.find_spec('mcp') is None, reason='mcp extra not installed')
def test_mcp_current_acl_revocation_and_validation(service, tmp_path, monkeypatch):
    from test_mcp import _call
    refs = scenario(service)
    commit(service)
    policy = {'graphs': {'default': {'roles': {'reader': 'viewer'}, 'nodes': {}}}, 'tokens': {}}
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    monkeypatch.setenv('IG_PRINCIPAL', 'reader')
    value, err = _call('decision_inspect', dict(reference=refs['evidence'], revision='HEAD'))
    assert not err and value['ok']
    policy['graphs']['default']['nodes']['source'] = {'read': []}
    path.write_text(json.dumps(policy))
    value, err = _call('decision_inspect', dict(reference=refs['evidence'], revision='HEAD'))
    assert not err and value['error']['code'] == 'record_unavailable'
    value, _ = _call('build_decision_context', dict(query='Keep opt-in', budget=-1))
    assert value['error']['code'] == 'invalid_params'
    policy['graphs']['default']['roles'] = {}
    path.write_text(json.dumps(policy))
    for name, args in [('decision_findings', {}), ('decision_brief', dict(reference=refs['decision'])),
                       ('decision_inspect', dict(reference=refs['claim'])),
                       ('decision_compare', dict(envelope=comparison('HEAD', 'HEAD'))),
                       ('build_decision_context', dict(query='Keep opt-in'))]:
        value, _ = _call(name, args)
        assert value['error']['code'] == 'forbidden'


def test_long_sources_are_explicit_excerpts_with_exact_pinned_resolver(service):
    refs = scenario(service)
    # This unassessed extra evidence does not rewrite the conclusion.
    _, ev = evidence(service, refs['profile'], node='long', text='Bounded local observation. ' * 60)
    link(service, 'opposes', ev, refs['claim'], context(refs['profile']), accepted=False)
    commit(service)
    result = read(service, 'context', query='Keep opt-in', budget=8000)
    assert result['context'] and 'source excerpt truncated' in result['context']
    assert result['truncated'] and result['abbreviated']
    assert result['tokens'] == estimate_tokens(result['context'])
    for item in result['abbreviated']:
        exact = read(service, 'inspect-revision', reference=item['reference'], revision=result['revision'])
        assert exact['record']['payload']['text'].strip() == ('Bounded local observation. ' * 60).strip()


def test_multiple_units_include_separators_and_no_ghost_ids(service):
    refs = scenario(service)
    extra, = save(service, draft('decision', dict(action='Keep opt-in also for an empty workload',
        rationale='Pending review', alternatives=[], context=None, revisit_checks=[])))
    commit(service)
    result = read(service, 'context', query='Keep opt-in', budget=8000)
    assert len(result['decisions']) == 2
    assert '\n\n---\n\n' in result['context']
    assert result['tokens'] == estimate_tokens(result['context']) <= 8000
    assert {d['id'] for d in result['decisions']} == {extra['id'], refs['decision']['id']}
    assert set(result['included_ids']) == {r['id'] for r in result['included_refs']}
    for ref in result['included_refs']:
        assert f"[decision:{ref['id']}@{ref['version_id']}]" in result['context']
    limited = read(service, 'context', query='Keep opt-in', budget=8000, k=1)
    assert limited['truncated'] and len(limited['decisions']) == 1

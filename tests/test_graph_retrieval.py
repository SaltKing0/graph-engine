"""Graph ranking is opt-in, bounded, explainable, and access-filtered."""
from __future__ import annotations

import json
import math

import pytest
from fastapi.testclient import TestClient

from graph_engine.access import SecuredBrain
from graph_engine.brain import Brain, Edge, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.graph_retrieval import GraphOptions, graph_options
from graph_engine.retrieval import explain, retrieve, retrieve_with_evidence
from graph_engine.reranker import ReverseReranker


class OrthogonalEmbedder:
    """Only the seed has query overlap; no accidental hash collisions."""
    def embed(self, text: str) -> list[float]:
        return [1., 0.] if 'launch' in text else [0., 1.]


@pytest.fixture
def engine(tmp_path):
    brain = Brain(tmp_path / 'brain', mode='local')
    for nid, text in [('a', 'launch'), ('b', 'Project Cedar'), ('c', 'Oslo office'),
                      ('e', 'Evidence: Cedar is based in Oslo'), ('x', 'Unrelated')]:
        brain.write_node(Node(text, id=nid, status='active'))
    brain.write_edges([
        Edge('a', 'b', 'mentions', pending=False, id='ab'),
        Edge('c', 'b', 'fact', pending=False, id='cb', predicate='based_in',
             evidence=[{'node_id': 'e', 'text': 'Cedar is based in Oslo'}]),
    ])
    result = BrainEngine(brain, embedder=OrthogonalEmbedder(), reranker=False)
    result.reranker = None
    return result


def snapshot(brain):
    return {str(p.relative_to(brain.path)): p.read_bytes() for p in brain.path.rglob('*') if p.is_file()}


def test_multihop_miss_becomes_candidate_with_reconstructible_score(engine):
    assert retrieve(engine, 'launch', persist=False) == retrieve(engine, 'launch', persist=False, graph=None)
    assert [nid for nid, _ in retrieve(engine, 'launch', persist=False)] == ['a']
    before = snapshot(engine.brain)
    options = GraphOptions(seed_limit=1)
    result = retrieve_with_evidence(engine, 'launch', graph=options)
    assert [nid for nid, _ in result['hits']] == ['a', 'b', 'c']
    traced = explain(engine, 'c', 'launch', graph=options)
    assert traced['matched_terms'] == []
    assert traced['graph_used_for_ranking'] is True
    path = traced['graph']['paths'][0]
    assert path['seed_id'] == 'a' and path['hops'] == 2
    assert [s['edge_id'] for s in path['steps']] == ['ab', 'cb']
    assert [s['direction'] for s in path['steps']] == ['out', 'in']
    expected = path['seed_score'] * options.weight * math.prod(step['factor'] for step in path['steps'])
    assert path['raw_contribution'] == pytest.approx(expected)
    assert traced['rrf']['score'] == pytest.approx(traced['dense']['rrf_contribution'] +
        traced['bm25']['rrf_contribution'] + traced['graph']['contribution'] +
        traced['learning']['feedback_adjustment'])
    assert dict(result['hits'])['c'] == traced['rrf']['score']
    assert result['evidence']['c'] == traced['graph']['paths']
    assert path['steps'][1]['edge']['evidence'][0]['node_id'] == 'e'
    assert traced['rank'] == 3
    assert snapshot(engine.brain) == before


@pytest.mark.parametrize('changes', [
    {'pending': True}, {'pending': None}, {'rejected': True}, {'valid_from': '2999-01-01T00:00:00Z'},
    {'valid_from': 'not-a-date'}, {'valid_to': '2001-01-01T00:00:00Z'},
    {'valid_to': '2999-01-01T00:00:00Z'},  # legacy invalidation
    {'valid_to': '2001-01-01T00:00:00Z', 'extracted_validity': {}},
    {'invalidated_at': '2001-01-01T00:00:00Z'}, {'invalidated_by': 'decision'},
    {'kind': 'contradicts'}, {'kind': 'supersedes'}, {'kind': 'similar'},
    {'source': 'missing'}, {'evidence': [{'node_id': 'missing', 'text': 'orphan'}]},
])
def test_ineligible_assertions_cannot_expand(engine, changes):
    attrs = dict(source='a', target='b', kind='fact', id='bad', pending=False)
    attrs.update(changes)
    engine.brain.write_edges([Edge(**attrs)])
    result = retrieve_with_evidence(engine, 'launch', graph=GraphOptions())
    assert [nid for nid, _ in result['hits']] == ['a']
    assert result['graph']['graph_used_for_ranking'] is False


def test_bounded_current_fact_is_allowed(engine):
    engine.brain.write_edges([Edge('a', 'b', 'fact', pending=False,
        valid_from='2000-01-01T00:00:00Z', valid_to='2999-01-01T00:00:00Z', extracted_validity={})])
    assert 'b' in dict(retrieve(engine, 'launch', persist=False, graph=GraphOptions()))


@pytest.mark.parametrize('dead', ['a', 'b', 'c', 'e'])
def test_tombstones_never_supply_paths_or_embedded_evidence(engine, dead):
    node = engine.brain.read_node(dead)
    node.status = 'tombstone'
    engine.brain.write_node(node)
    result = retrieve_with_evidence(engine, 'launch', graph=GraphOptions())
    assert dead not in dict(result['hits'])
    assert 'c' not in dict(result['hits'])
    assert 'Cedar is based in Oslo' not in json.dumps(result)


@pytest.mark.parametrize('hidden', ['b', 'e'])
def test_hidden_intermediates_and_evidence_do_not_affect_visible_ranking(engine, tmp_path, monkeypatch, hidden):
    policy = {'graphs': {'default': {'roles': {'viewer': 'viewer'},
              'nodes': {hidden: {'read': ['owner']}}}}}
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    secured = SecuredBrain(engine.brain.path, mode='local', graph_name='default', identity='viewer')
    engine = BrainEngine(secured, embedder=OrthogonalEmbedder(), reranker=False)
    engine.reranker = None
    before = snapshot(secured)
    result = retrieve_with_evidence(engine, 'launch', graph=GraphOptions())
    assert 'c' not in dict(result['hits'])
    assert 'Cedar is based in Oslo' not in json.dumps(result)
    assert f'"{hidden}"' not in json.dumps(result)
    with pytest.raises(PermissionError):
        retrieve(engine, 'launch', persist=False, graph=GraphOptions(focal_id=hidden))
    assert snapshot(secured) == before


def test_revoked_edge_and_focal_access_observed_by_existing_engine(engine, tmp_path, monkeypatch):
    path = tmp_path / 'policy.json'
    policy = {'graphs': {'g': {'roles': {'v': 'viewer'}, 'nodes': {}}}}
    path.write_text(json.dumps(policy)); monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    secured = BrainEngine(SecuredBrain(engine.brain.path, mode='local', graph_name='g', identity='v'), OrthogonalEmbedder(), reranker=False)
    secured.reranker = None
    options = GraphOptions(focal_id='b')
    assert 'c' in dict(retrieve(secured, 'launch', persist=False, graph=options))
    policy['graphs']['g']['nodes']['b'] = {'read': ['owner']}
    path.write_text(json.dumps(policy))
    assert 'c' not in dict(retrieve(secured, 'launch', persist=False, graph=GraphOptions()))
    with pytest.raises(PermissionError):
        retrieve(secured, 'launch', persist=False, graph=options)


def test_hubs_do_not_expand_or_accumulate_boosts(engine):
    edges = [Edge('a', 'b', 'linked', id='ab', pending=False)]
    for i in range(25):
        nid = f'hub-{i}'
        engine.brain.write_node(Node('disconnected topic', id=nid))
        edges.append(Edge('b', nid, 'linked', pending=False))
    engine.brain.write_edges(edges)
    result = retrieve_with_evidence(engine, 'launch', graph=GraphOptions())
    assert [nid for nid, _ in result['hits']] == ['a']
    assert result['graph']['truncation_reasons'] == ['degree_limit']


@pytest.mark.parametrize('options,reason', [
    (GraphOptions(hops=1), 'hop_limit'), (GraphOptions(candidate_limit=1), 'candidate_limit'),
    (GraphOptions(visit_limit=1), 'visit_limit')])
def test_limits_are_visible_in_explanation(engine, options, reason):
    result = explain(engine, 'c', 'launch', graph=options)
    assert result['graph']['truncated']
    assert reason in result['graph']['truncation_reasons']
    assert not result['retrieved']


def test_duplicate_edges_cycles_and_file_order_do_not_amplify(engine):
    options = GraphOptions(seed_limit=1)
    original = retrieve_with_evidence(engine, 'launch', graph=options)
    edges = engine.brain.read_edges()
    engine.brain.write_edges([*reversed(edges), Edge('a', 'b', 'mentions', id='zz', pending=False)])
    repeated = retrieve_with_evidence(engine, 'launch', graph=options)
    assert repeated['hits'] == original['hits']
    assert repeated['evidence'] == original['evidence']
    assert len(repeated['evidence']['c']) == 1


def test_focal_id_is_explicit_and_works_without_query_overlap(engine):
    result = retrieve_with_evidence(engine, 'unmatched', graph=GraphOptions(focal_id='b'))
    assert {'a', 'c'} <= set(dict(result['hits']))
    assert result['graph']['seeds'][0]['id'] == 'b'
    for nid in ('Project Cedar', 'missing'):
        with pytest.raises(ValueError, match='accessible live node'):
            retrieve_with_evidence(engine, 'launch', graph=GraphOptions(focal_id=nid))


def test_connectivity_is_not_transitive_fact_entailment(engine):
    engine.brain.write_edges([
        Edge('a', 'b', 'fact', pending=False, id='ab', predicate='likes'),
        Edge('b', 'c', 'fact', pending=False, id='bc', predicate='based_in')])
    before = snapshot(engine.brain)
    result = explain(engine, 'c', 'launch', graph=GraphOptions())
    assert result['retrieved']
    assert 'not logical entailment' in result['graph']['semantics']
    assert [s['edge']['predicate'] for s in result['graph']['paths'][0]['steps']] == ['likes', 'based_in']
    assert snapshot(engine.brain) == before
    assert not any(e.source == 'a' and e.target == 'c' for e in engine.brain.read_edges())


def test_tier_priority_and_reranker_still_apply(engine):
    node = engine.brain.read_node('c'); node.storage_tier = 'main'; engine.brain.write_node(node)
    engine.reranker = ReverseReranker()
    hits = retrieve(engine, 'launch', persist=False, graph=GraphOptions())
    assert [nid for nid, _ in hits] == ['c', 'b', 'a']
    assert explain(engine, 'c', 'launch', graph=GraphOptions())['rank'] == 1
    assert explain(engine, 'c', 'launch', rerank_k=1, graph=GraphOptions())['rank'] == 1


def test_feedback_applies_once_to_expanded_candidate(engine, monkeypatch):
    from graph_engine.feedback import LearningProfile
    monkeypatch.setattr('graph_engine.retrieval.learning_profile',
        lambda *a: LearningProfile('launch', adjustments={'c': -.001}))
    result = explain(engine, 'c', 'launch', graph=GraphOptions())
    assert result['learning']['feedback_adjustment'] == -.001
    assert result['rrf']['score'] == pytest.approx(result['graph']['contribution'] - .001)


@pytest.mark.parametrize('kwargs', [
    {'hops': 4}, {'hops': True}, {'candidate_limit': 0}, {'visit_limit': 5001},
    {'weight': float('nan')}, {'weight': 2}, {'decay': 0}, {'kinds': ('contradicts',)},
    {'focal_id': ''}, {'kinds': ('fact', 'fact')}, {'kinds': ['fact']}, {'seed_limit': 11}, {'max_degree': 51}])
def test_option_validation(kwargs):
    with pytest.raises(ValueError):
        GraphOptions(**kwargs)


def test_surface_options_cannot_silently_ignore_focal():
    assert graph_options() is None
    with pytest.raises(ValueError):
        graph_options(0, 'a')


def test_http_graph_search_and_explanation_are_read_only(engine, monkeypatch):
    from graph_engine.server import app
    monkeypatch.delenv('IG_ACCESS_POLICY', raising=False)
    monkeypatch.setattr('graph_engine.runtime.make_engine', lambda: engine)
    client = TestClient(app)
    before = snapshot(engine.brain)
    params = {'query': 'launch', 'graph_hops': 2}
    result = client.get('/api/search', params=params)
    assert result.status_code == 200
    assert [r['id'] for r in result.json()['results']] == ['a', 'b', 'c']
    assert result.json()['results'][2]['graph_evidence'][0]['seed_id'] == 'a'
    explained = client.get('/api/search/c/explain', params=params)
    assert explained.status_code == 200 and explained.json()['graph_used_for_ranking']
    assert snapshot(engine.brain) == before
    assert client.get('/api/search', params={**params, 'graph_hops': 4}).status_code == 422
    assert client.get('/api/search', params={**params, 'focal_id': 'missing'}).status_code == 400
    assert client.get('/api/search', params={'query': 'launch', 'focal_id': 'a'}).status_code == 400


def test_cli_graph_flags_roundtrip(engine, capsys):
    from graph_engine.__main__ import cmd_search, cmd_explain
    before = snapshot(engine.brain)
    cmd_search(engine, ['launch', '--graph-hops', '2', '--json'])
    search = json.loads(capsys.readouterr().out)
    cmd_explain(engine, ['c', '--query', 'launch', '--graph-hops', '2', '--json'])
    explanation = json.loads(capsys.readouterr().out)
    assert search['results'][2]['graph_evidence'] == explanation['graph']['paths']
    assert snapshot(engine.brain) == before


def test_mcp_graph_search_explain_readonly_even_with_cache_optin(engine, monkeypatch):
    pytest.importorskip('mcp')
    from graph_engine.mcp import server
    monkeypatch.delenv('IG_ACCESS_POLICY', raising=False)
    monkeypatch.setenv('IG_BRAIN_PATH', str(engine.brain.path))
    monkeypatch.setenv('IG_MCP_CACHE_VECTORS', '1')
    monkeypatch.setattr(server, 'make_engine', lambda: engine)
    before = snapshot(engine.brain)
    result = server.search_brain('launch', graph_hops=2)
    explanation = server.explain_search('c', 'launch', graph_hops=2)
    assert result['ok'] and explanation['ok']
    assert result['results'][2]['graph_evidence'] == explanation['graph']['paths']
    assert server.search_brain('launch', graph_hops=4)['error']['code'] == 'invalid_params'
    assert server.explain_search('c', 'launch', focal_id='a')['error']['code'] == 'invalid_params'
    assert snapshot(engine.brain) == before


def test_seed_feedback_can_prevent_unwanted_expansion(engine, monkeypatch):
    from graph_engine.feedback import LearningProfile
    monkeypatch.setattr('graph_engine.retrieval.learning_profile',
        lambda *a: LearningProfile('launch', adjustments={'a': -1.}))
    result = retrieve_with_evidence(engine, 'launch', graph=GraphOptions())
    assert result['graph']['seeds'] == []
    assert 'c' not in dict(result['hits'])


def test_multiple_seeds_have_a_shared_contribution_cap(engine):
    engine.brain.write_node(Node('launch launch', id='d'))
    engine.brain.add_edge(Edge('d', 'b', 'mentions', id='db', pending=False))
    result = explain(engine, 'b', 'launch', graph=GraphOptions())
    assert len(result['graph']['paths']) == 2
    assert result['graph']['contribution'] <= result['graph']['contribution_cap']
    assert result['graph']['contribution'] == pytest.approx(sum(p['contribution'] for p in result['graph']['paths']))


def test_http_and_mcp_graph_access_fail_closed(engine, tmp_path, monkeypatch):
    import hashlib
    from graph_engine.server import app
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps({'graphs': {'default': {'roles': {'v': 'viewer'},
        'nodes': {'b': {'read': ['owner']}}}},
        'tokens': {hashlib.sha256(b'token').hexdigest(): 'v'}}))
    monkeypatch.setenv('IG_ACCESS_POLICY', str(path))
    monkeypatch.setenv('IG_PRINCIPAL', 'v')
    monkeypatch.setenv('IG_BRAIN_PATH', str(engine.brain.path))
    monkeypatch.setenv('IG_BRAIN_MODE', 'local')
    secured = BrainEngine(SecuredBrain(engine.brain.path, mode='local', graph_name='default', identity='v'), OrthogonalEmbedder(), reranker=False)
    secured.reranker = None
    monkeypatch.setattr('graph_engine.runtime.make_engine', lambda: secured)
    client = TestClient(app)
    headers = {'Authorization': 'Bearer token'}
    params = {'query': 'launch', 'graph_hops': 2}
    before = snapshot(engine.brain)
    assert client.get('/api/search', params=params).status_code == 401
    result = client.get('/api/search', params=params, headers=headers)
    assert result.status_code == 200 and [r['id'] for r in result.json()['results']] == ['a']
    assert client.get('/api/search', params={**params, 'focal_id': 'b'}, headers=headers).status_code == 403
    assert client.get('/api/search/b/explain', params=params, headers=headers).status_code == 403
    assert snapshot(engine.brain) == before
    pytest.importorskip('mcp')
    from graph_engine.mcp import server
    monkeypatch.setattr(server, 'make_engine', lambda: secured)
    assert server.search_brain('launch', graph_hops=2, focal_id='b')['error']['code'] == 'forbidden'
    assert server.explain_search('b', 'launch', graph_hops=2)['error']['code'] == 'forbidden'

"""Issue #56: rejected ingest inputs must never leave durable records."""
from __future__ import annotations

import json
import subprocess
import sys
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from graph_engine import runtime
from graph_engine.brain import Brain, Edge, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.embedder import HashEmbedder
from graph_engine.server import app


def snapshot(brain):
    return {str(p.relative_to(brain.path)): p.read_bytes()
            for p in brain.path.rglob('*') if p.is_file() and '.git' not in p.parts}


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv('IG_BRAIN_PATH', str(tmp_path / 'brain'))
    monkeypatch.setenv('IG_BRAIN_MODE', 'local')
    monkeypatch.setenv('IDEAGRAPH_EMBEDDER', 'hash')
    monkeypatch.delenv('IG_EDGE_CONF_FLOOR', raising=False)
    monkeypatch.delenv('IG_INTENT_AUTO_ACCEPT_MAX', raising=False)
    runtime.reset_engine_cache()
    eng = runtime.make_engine()
    eng.brain.write_node(Node('Existing alpha note', id='alpha'))
    eng.brain.write_node(Node('Existing beta note', id='beta'))
    eng.brain.add_edge(Edge('alpha', 'beta', 'similar'))
    eng.brain.rebuild_index()
    # Deliberately leave vectors absent: duplicate detection must not fill them.
    (eng.brain.path / 'recalls.jsonl').write_text('{"sentinel": true}\n')
    yield eng
    runtime.reset_engine_cache()


@pytest.mark.parametrize('raw', ['invalid', '', 'nan', 'NaN', 'inf', '-inf', '-0.01', '1.01'])
@pytest.mark.parametrize('override', [False, True])
@pytest.mark.parametrize('text', ['New submitted note', 'Existing alpha note'])
def test_invalid_floor_leaves_every_record_unchanged(engine, monkeypatch, raw, override, text):
    before = snapshot(engine.brain)
    engine.embedder = Mock(wraps=engine.embedder)
    kwargs = {'env': {'IG_EDGE_CONF_FLOOR': raw}} if override else {}
    if not override:
        monkeypatch.setenv('IG_EDGE_CONF_FLOOR', raw)
    with pytest.raises(ValueError, match='IG_EDGE_CONF_FLOOR'):
        engine.ingest(text, source='new-source', **kwargs)
    assert snapshot(engine.brain) == before
    engine.embedder.embed.assert_not_called()
    engine.embedder.embed_batch.assert_not_called()


@pytest.mark.parametrize('kwargs', [
    {'text': None}, {'source': 'bad\nsource'}, {'tags': [42]}, {'tags': 'bad'},
    {'ntype': 'unknown'}, {'relations': [('alpha',)]}, {'relations': [(42, 'similar')]},
    {'relations': [('alpha', None)]}, {'edge_origin': object()},
    {'_document': {}}, {'_node_id': '../escape'}, {'_capture_input': 42},
    {'auto_accept': 'yes'}, {'allow_duplicates': 'no'}, {'env': []},
    {'text': 'bad \ud800'}, {'env': {'IG_INTENT_AUTO_ACCEPT_MAX': float('inf')}},
])
def test_operation_inputs_fail_before_any_storage_or_embedding(engine, kwargs):
    before = snapshot(engine.brain)
    with pytest.raises(ValueError):
        engine.ingest(**({'text': 'New note'} | kwargs))
    assert snapshot(engine.brain) == before


@pytest.mark.parametrize('extraction', [None, 'rules'])
def test_invalid_config_does_not_initialize_a_missing_brain(tmp_path, monkeypatch, extraction):
    brain = Brain(tmp_path / 'missing')
    eng = BrainEngine(brain, HashEmbedder())
    monkeypatch.setenv('IG_EDGE_CONF_FLOOR', 'invalid')
    with pytest.raises(ValueError, match='IG_EDGE_CONF_FLOOR'):
        eng.capture('Alice works at Acme.', extraction=extraction)
    assert not brain.path.exists()


def test_capture_retry_also_validates_before_extraction(engine, monkeypatch):
    engine.capture('Alice works at Acme.', extraction='rules')
    before = snapshot(engine.brain)
    monkeypatch.setenv('IG_EDGE_CONF_FLOOR', 'nan')
    with pytest.raises(ValueError, match='IG_EDGE_CONF_FLOOR'):
        engine.capture('Alice works at Acme.', extraction='rules')
    assert snapshot(engine.brain) == before


@pytest.mark.parametrize('extraction', [None, 'rules'])
def test_http_rejected_config_leaves_no_note(engine, monkeypatch, extraction):
    before = snapshot(engine.brain)
    monkeypatch.setenv('IG_EDGE_CONF_FLOOR', 'invalid')
    with TestClient(app) as client:
        response = client.post('/api/ingest', json={'text': 'Alice works at Acme.', 'extraction': extraction})
    assert response.status_code == 400
    assert 'IG_EDGE_CONF_FLOOR' in response.json()['error']
    assert snapshot(engine.brain) == before


@pytest.mark.parametrize('extract', [[], ['--extract-entities']])
def test_cli_rejected_config_leaves_no_note(engine, monkeypatch, extract):
    monkeypatch.setenv('IG_EDGE_CONF_FLOOR', 'invalid')
    before = snapshot(engine.brain)
    result = subprocess.run([sys.executable, '-m', 'graph_engine', 'ingest',
                             'Alice works at Acme.', '--json', *extract], capture_output=True, text=True)
    assert result.returncode == 1
    assert 'IG_EDGE_CONF_FLOOR' in result.stderr
    assert 'Traceback' not in result.stderr
    assert snapshot(engine.brain) == before


@pytest.mark.parametrize('extraction', [None, 'rules'])
def test_http_post_capture_failure_has_explicit_receipt(engine, monkeypatch, extraction):
    def fail(*args, **kwargs):
        raise ValueError('private backend diagnostic')
    monkeypatch.setattr(engine.brain, 'commit_and_push', fail)
    with TestClient(app) as client:
        response = client.post('/api/ingest', json={'text': 'Alice works at Acme.', 'extraction': extraction})
    assert response.status_code == 502
    result = response.json()
    assert result['captured'] and result['error'] == 'ingest_incomplete'
    assert engine.brain.read_node(result['node_id']).text == 'Alice works at Acme.'
    assert result['retryable'] is (extraction is not None)
    if extraction:
        assert engine.brain.read_node(result['source_node_id']).capture['input'] == 'Alice works at Acme.'
    assert 'private backend' not in response.text


def test_cli_post_capture_failure_reports_receipt(engine, monkeypatch, capsys):
    from graph_engine.__main__ import cmd_ingest
    def fail(*args, **kwargs):
        raise ValueError('private backend diagnostic')
    monkeypatch.setattr(engine.brain, 'commit_and_push', fail)
    with pytest.raises(SystemExit) as exc:
        cmd_ingest(engine, ['Alice works at Acme.', '--extract-entities', '--json'])
    assert exc.value.code == 1
    result = json.loads(capsys.readouterr().out)
    assert result['captured'] and result['source_node_id']
    assert engine.brain.read_node(result['node_id']) is not None


@pytest.mark.parametrize('raw', ['0', '1', '0.45'])
def test_valid_floor_and_per_call_precedence(engine, monkeypatch, raw):
    monkeypatch.setenv('IG_EDGE_CONF_FLOOR', 'invalid')
    node, _, _ = engine.ingest('A distinct new note', env={'IG_EDGE_CONF_FLOOR': raw})
    assert engine.brain.read_node(node.id) is not None


@pytest.mark.parametrize('extraction', [None, 'rules'])
@pytest.mark.parametrize('config', [{'IG_INTENT_AUTO_ACCEPT_MAX': '-1'},
                                    {'IG_INTENT_AUTO_ACCEPT_MAX': 'invalid'},
                                    {'IG_WRITE_LOCK_TIMEOUT': 'nan'}])
def test_other_invalid_ingest_configuration_is_side_effect_free(engine, monkeypatch, config, extraction):
    before = snapshot(engine.brain)
    for key, value in config.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        engine.capture('Alice works at Acme.', extraction=extraction)
    assert snapshot(engine.brain) == before


@pytest.mark.parametrize('threshold', [float('nan'), float('inf'), 'invalid'])
def test_invalid_dedupe_threshold_is_side_effect_free(engine, threshold):
    before = snapshot(engine.brain)
    engine.dedupe_threshold = threshold
    with pytest.raises(ValueError, match='dedupe_threshold'):
        engine.ingest('A rejected note')
    assert snapshot(engine.brain) == before


@pytest.mark.parametrize('duplicate', [False, True])
def test_capture_commit_failure_receipt_supports_retry(engine, monkeypatch, duplicate):
    from graph_engine.brain_engine import IngestPartialError
    text = 'Alice works at Acme.'
    if duplicate:
        engine.ingest(text)
    commit = engine.brain.commit_and_push
    def fail(*args, **kwargs):
        raise RuntimeError('sync unavailable')
    monkeypatch.setattr(engine.brain, 'commit_and_push', fail)
    with pytest.raises(IngestPartialError) as exc:
        engine.capture(text, extraction='rules')
    receipt = exc.value.to_dict()
    assert receipt['captured'] and receipt['retryable'] and receipt['duplicate'] is duplicate
    count = len(engine.brain.read_nodes())
    monkeypatch.setattr(engine.brain, 'commit_and_push', commit)
    node, _, _, extraction = engine.capture(text, extraction='rules')
    assert extraction['retried'] and extraction['status'] == 'complete'
    assert extraction['source_node_id'] == receipt['source_node_id'] and node.id == receipt['node_id']
    assert len(engine.brain.read_nodes()) == count + 2  # only the two extracted entities


def test_late_backend_value_error_is_partial_success(engine, monkeypatch):
    from graph_engine.brain_engine import IngestPartialError
    def fail(*args, **kwargs):
        raise ValueError('embedding backend unavailable')
    monkeypatch.setattr(engine.brain, 'vectors_for', fail)
    with pytest.raises(IngestPartialError) as exc:
        engine.ingest('A saved note', allow_duplicates=True)
    assert engine.brain.read_node(exc.value.node_id).text == 'A saved note'


def test_mcp_validation_and_post_capture_receipt(engine, monkeypatch):
    pytest.importorskip('mcp')
    from graph_engine.mcp import server
    monkeypatch.setenv('IG_MCP_WRITE', '1')
    before = snapshot(engine.brain)
    monkeypatch.setenv('IG_EDGE_CONF_FLOOR', 'nan')
    rejected = server.remember('Alice works at Acme.', extraction='rules')
    assert not rejected['ok'] and rejected['error']['code'] == 'invalid_params'
    assert snapshot(engine.brain) == before
    monkeypatch.delenv('IG_EDGE_CONF_FLOOR')
    def fail(*args, **kwargs):
        raise ValueError('private backend diagnostic')
    monkeypatch.setattr(engine.brain, 'commit_and_push', fail)
    result = server.remember('Alice works at Acme.', extraction='rules')
    assert not result['ok'] and result['error']['code'] == 'ingest_incomplete'
    assert result['captured'] and result['retryable']
    assert engine.brain.read_node(result['source_node_id']).capture['input'] == 'Alice works at Acme.'
    assert 'private backend' not in json.dumps(result)

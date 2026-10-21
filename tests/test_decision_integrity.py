"""Concrete public-interface integrity cases; scripted tests, not human sign-off."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier
import time

import pytest
from fastapi.testclient import TestClient

from graph_engine import decision_schema as s, runtime
from graph_engine.access import SecuredBrain
from graph_engine.brain import Node
from graph_engine.decision_brief import render_markdown
from graph_engine.decision_memory import read_file
from graph_engine.decision_service import DecisionService
from graph_engine.server import app
from test_decision_impact import service, scenario, commit, comparison, change_source
from test_decision_memory import claim, draft, event, files
from test_decision_service import envelope, save, review

ROOT = Path(__file__).resolve().parent.parent
SURFACES = ('service', 'cli', 'http', 'mcp', 'exports')
READ_CASES = [(case, surface) for case in ('acl', 'multisource-acl', 'tombstone', 'source-edit') for surface in SURFACES]


def child_env() -> dict:
    return dict(os.environ, PYTHONPATH=str(ROOT), IDEAGRAPH_EMBEDDER='hash',
                IG_MCP_CACHE_VECTORS='0')


def mcp_reads(calls: list[tuple[str, dict]]) -> list[dict]:
    """Real CLI stdio JSON-RPC, not a direct service-function substitution."""
    pytest.importorskip('mcp', reason='requires optional [mcp] extra')
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def invoke() -> list[dict]:
        with anyio.fail_after(30):
            params = StdioServerParameters(command=sys.executable,
                args=['-m', 'graph_engine', 'mcp'], env=child_env())
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    await client.initialize()
                    result = []
                    for name, body in calls:
                        value = await client.call_tool(name, body)
                        assert not value.isError, value.content
                        result.append(dict(is_error=value.isError, value=json.loads(value.content[0].text)))
                    return result
    return anyio.run(invoke)


def public_reads(service: DecisionService, surface: str, refs: dict, before: str, after: str,
                 monkeypatch) -> list[dict]:
    operations = [
        ('inspect-revision', dict(reference=refs['source'], revision=before)),
        ('brief', dict(reference=refs['decision'], revision=before)),
        ('review-queue', dict(comparison=comparison(before, after), history=True)),
        ('context', dict(query='Keep opt-in', budget=8000, revision=before)),
    ]
    if surface == 'mcp':
        return mcp_reads([
            ('decision_inspect', operations[0][1]), ('decision_brief', operations[1][1]),
            ('decision_review_queue', dict(envelope=operations[2][1])), ('build_decision_context', operations[3][1]),
        ])
    result = []
    for operation, body in operations:
        if surface == 'exports' and operation not in ('brief', 'context'):
            continue
        if surface in ('service', 'exports'):
            try:
                value = service.read(operation, body)
                if surface == 'exports' and operation == 'brief':
                    value = dict(value, markdown=render_markdown(value))
                result.append(dict(value=value))
            except PermissionError as exc:
                result.append(dict(error=str(exc)))
        elif surface == 'cli':
            args = ['-m', 'graph_engine', 'decision', operation, '-']
            request = body
            if operation == 'inspect-revision':
                args = ['-m', 'graph_engine', 'decision', 'inspect', '-', '--revision', before]
                request = body['reference']
            proc = subprocess.run([sys.executable, *args], input=json.dumps(request),
                text=True, capture_output=True, env=child_env(), cwd=ROOT, timeout=30)
            result.append(dict(code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                               value=json.loads(proc.stdout) if proc.stdout.strip() else None))
        else:
            monkeypatch.setattr(runtime, 'make_brain', lambda: service.brain)
            with TestClient(app) as client:
                response = client.post('/api/decision-memory/read/' + operation, json=body,
                                       headers={'Authorization': 'Bearer integrity-reader'})
            result.append(dict(code=response.status_code, value=response.json()))
    return result


@pytest.mark.parametrize('case_name,surface', READ_CASES, ids=[f'{c}-{a}' for c, a in READ_CASES])
def test_historical_privacy_and_read_only_adapters(service, tmp_path, monkeypatch, case_name, surface):
    if case_name == 'multisource-acl':
        service.brain.write_node(Node('Public local observation', id='source'))
        service.brain.write_node(Node('MULTI_SOURCE_SECRET private qualifying source', id='private-aux'))
        public, = save(service, draft('source', service.source('source'), anchor='source'))
        private, = save(service, draft('source', service.source('private-aux'), anchor='private-aux'))
        c, = save(service, claim('MULTI_SOURCE_SECRET derived claim', inputs=[public, private]))
        d, = save(service, draft('decision', dict(action='Keep opt-in', rationale='MULTI_SOURCE_SECRET rationale',
            alternatives=[], context=None, revisit_checks=[]), inputs=[c]))
        relation, = save(service, draft('relationship', dict(kind='depends_on', source=d, target=c,
            context=None, explanation='Explicit two-source derived dependency')))
        review(service, relation)
        refs = dict(source=private, evidence=c, decision=d)
    else:
        refs = scenario(service)
    before = commit(service)
    change_source(service, 'Changed exact source after the frozen historical revision')
    after = commit(service)
    if case_name == 'tombstone':
        service.brain.tombstone_node('source')
    elif case_name in ('acl', 'multisource-acl'):
        policy = tmp_path / 'policy.json'
        policy.write_text(json.dumps(dict(graphs={'default': dict(roles={'reader': 'viewer'},
            nodes={('private-aux' if case_name == 'multisource-acl' else 'source'): {'read': []}})},
            tokens={hashlib.sha256(b'integrity-reader').hexdigest(): 'reader'})))
        monkeypatch.setenv('IG_ACCESS_POLICY', str(policy))
        monkeypatch.setenv('IG_PRINCIPAL', 'reader')
        service = DecisionService(SecuredBrain(str(service.brain.path), mode='git',
                                              graph_name='default', identity='reader'))
    original = files(service.brain)
    head = subprocess.check_output(['git', '-C', str(service.brain.path), 'rev-parse', 'HEAD'])
    values = public_reads(service, surface, refs, before, after, monkeypatch)
    encoded = json.dumps(values)
    if case_name in ('acl', 'multisource-acl', 'tombstone'):
        # A broken adapter returning only errors is not successful privacy/read
        # evidence. Authorized queue/context projections must still work.
        projections = [('dm.context-result/1', values[-1])]
        if surface != 'exports':
            projections.append(('dm.review-queue/1', values[-2]))
        for schema, value in projections:
            assert not value.get('error') and value.get('code', 0) in (0, 200)
            assert value['value']['schema'] == schema
        assert 'MULTI_SOURCE_SECRET' not in encoded
        assert 'Local observation' not in encoded
        assert 'Changed exact source' not in encoded
        assert refs['source']['id'] not in encoded and refs['evidence']['id'] not in encoded
    else:
        # A successful historical read must return old bytes, not silently fall
        # back to the successor or treat a missing response as a pass.
        assert 'Local observation' in encoded
        assert refs['source']['version_id'] in encoded
        first = values[0].get('value')
        if surface != 'exports':
            assert first['record']['payload']['text'].strip() == 'Local observation'
        for value in values:
            assert not value.get('error') and value.get('code', 0) in (0, 200)
    assert files(service.brain) == original
    assert subprocess.check_output(['git', '-C', str(service.brain.path), 'rev-parse', 'HEAD']) == head


@pytest.mark.parametrize('case_name,surface', [(c, a) for c in ('stale', 'dependent-undo', 'fresh-undo') for a in ('cli', 'http')],
                         ids=[f'{c}-{a}' for c in ('stale', 'dependent-undo', 'fresh-undo') for a in ('cli', 'http')])
def test_review_preconditions_through_write_adapters(service, tmp_path, monkeypatch, case_name, surface):
    c, = save(service, claim())
    review(service, c)
    accepted = service.inspect(c)['events'][-1]
    undo = event(c, axis='workflow', before='accepted', after='proposed', basis=accepted['basis'],
                 previous=accepted['event_id'], correct=accepted['event_id'])
    request = envelope(service, events=[undo])
    if case_name == 'stale':
        save(service, claim('An intervening proposal makes the captured generation stale'))
    elif case_name == 'dependent-undo':
        d, = save(service, draft('decision', dict(action='Retain', rationale='Reviewed basis',
            alternatives=[], context=None, revisit_checks=[])))
        review(service, d, axis='decision', after='current',
               basis=[dict(type='event_ref', event_id=accepted['event_id'])])
        request = envelope(service, events=[undo])
    commit(service)
    original = files(service.brain)
    if surface == 'cli':
        result = subprocess.run([sys.executable, '-m', 'graph_engine', 'decision', 'review', '-'],
            input=json.dumps(request), text=True, capture_output=True, cwd=ROOT, env=child_env(), timeout=30)
        assert (result.returncode == 0) == (case_name == 'fresh-undo')
        if case_name != 'fresh-undo':
            assert ('refresh' if case_name == 'stale' else 'dependent') in (result.stdout + result.stderr).lower()
    else:
        monkeypatch.setattr(runtime, 'make_brain', lambda: service.brain)
        with TestClient(app) as client:
            result = client.post('/api/decision-memory/reviews', json=request)
        assert result.status_code == {'stale': 409, 'dependent-undo': 400, 'fresh-undo': 200}[case_name], result.text
    inspected = service.inspect(c)
    assert inspected['state']['workflow'] == ('proposed' if case_name == 'fresh-undo' else 'accepted')
    assert inspected['events'][0] == accepted
    if case_name != 'fresh-undo':
        assert files(service.brain) == original


@pytest.mark.parametrize('surface', ['cli', 'http'])
@pytest.mark.parametrize('failure_point', ['index', 'commit'])
def test_post_publication_retry_through_adapters(service, tmp_path, monkeypatch, capsys, surface, failure_point):
    request = envelope(service, versions=[claim('Durable proposal despite interrupted index rebuild')])
    monkeypatch.setattr(runtime, 'make_brain', lambda: service.brain)
    method = 'rebuild_index' if failure_point == 'index' else 'commit_and_push'
    monkeypatch.setattr(service.brain, method, lambda *a, **kw: (_ for _ in ()).throw(OSError('scripted publication failure')))
    if surface == 'cli':
        from graph_engine.__main__ import cmd_decision
        path = tmp_path / 'request.json'
        path.write_text(json.dumps(request))
        with pytest.raises(SystemExit) as exc:
            cmd_decision(['propose', str(path)])
        assert exc.value.code == 1
        first = json.loads(capsys.readouterr().err)
        assert first['published_locally']
        cmd_decision(['propose', str(path)])
        retry = json.loads(capsys.readouterr().out)
    else:
        with TestClient(app) as client:
            response = client.post('/api/decision-memory/proposals', json=request)
            assert response.status_code == 502
            first = response.json()
            assert first['published_locally']
            response = client.post('/api/decision-memory/proposals', json=request)
            assert response.status_code == 200
            retry = response.json()
    assert retry['receipt'] == first['receipt']
    data = read_file(service.brain)
    assert data['generation'] == 1 and len(data['versions']) == len(data['receipts']) == 1


def test_simultaneous_cli_proposals_have_one_winner_and_lossless_retry(service, tmp_path):
    requests = [envelope(service, versions=[claim(f'Concurrent structured proposal {i}')]) for i in range(2)]
    gate = tmp_path / 'go'
    code = ('import os,sys,time; from pathlib import Path; '
            'Path(sys.argv[1]).write_text("ready"); '
            'gate=Path(sys.argv[2]);\n'
            'while not gate.exists(): time.sleep(0.01)\n'
            'os.execv(sys.executable,[sys.executable,"-m","graph_engine","decision","propose",sys.argv[3]])')
    children = []
    try:
        for i, request in enumerate(requests):
            path = tmp_path / f'request-{i}.json'
            path.write_text(json.dumps(request))
            children.append(subprocess.Popen([sys.executable, '-c', code, str(tmp_path / f'ready-{i}'), str(gate), str(path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT, env=child_env()))
        deadline = time.monotonic() + 15
        while not all((tmp_path / f'ready-{i}').exists() for i in range(2)):
            assert time.monotonic() < deadline, 'CLI workers did not reach the common start barrier'
            time.sleep(0.01)
        gate.touch()
        outputs = [child.communicate(timeout=30) for child in children]
        assert sorted(child.returncode for child in children) == [0, 1], outputs
        data = read_file(service.brain)
        assert data['generation'] == len(data['versions']) == len(data['receipts']) == 1
        loser = next(i for i, child in enumerate(children) if child.returncode)
        assert 'refresh' in outputs[loser][1].lower()
        request = requests[loser]
        preview = service.preview()
        request.update(expected_generation=preview['generation'], expected_heads=preview['heads'])
        service.submit(request)
        data = read_file(service.brain)
        assert data['generation'] == len(data['versions']) == len(data['receipts']) == 2
        assert {v['payload']['text'] for v in data['versions']} == {f'Concurrent structured proposal {i}' for i in range(2)}
        assert not subprocess.check_output(['git', '-C', str(service.brain.path), 'status', '--porcelain'])
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


def test_simultaneous_http_proposals_share_generation_and_preserve_both_on_retry(service, monkeypatch):
    requests = [envelope(service, versions=[claim(f'HTTP proposal {i}')]) for i in range(2)]
    monkeypatch.setattr(runtime, 'make_brain', lambda: service.brain)
    barrier = Barrier(2)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        def post(request):
            barrier.wait(timeout=10)
            return client.post('/api/decision-memory/proposals', json=request)
        responses = list(pool.map(post, requests))
        assert sorted(r.status_code for r in responses) == [200, 409]
        loser = next(i for i, r in enumerate(responses) if r.status_code == 409)
        preview = service.preview()
        requests[loser].update(expected_generation=preview['generation'], expected_heads=preview['heads'])
        assert client.post('/api/decision-memory/proposals', json=requests[loser]).status_code == 200
    data = read_file(service.brain)
    assert data['generation'] == len(data['versions']) == len(data['receipts']) == 2
    assert {v['payload']['text'] for v in data['versions']} == {'HTTP proposal 0', 'HTTP proposal 1'}


def test_cli_cannot_merge_version_pinned_source_or_reassign_reviews(service):
    refs = scenario(service)
    service.brain.write_node(Node('Other unrelated node', id='other'))
    commit(service)
    original = files(service.brain)
    proc = subprocess.run([sys.executable, '-m', 'graph_engine', 'merge', 'source', 'other'],
        text=True, capture_output=True, cwd=ROOT, env=child_env(), timeout=30)
    assert proc.returncode == 1
    assert 'decision' in (proc.stdout + proc.stderr).lower()
    assert service.inspect(refs['support'])['record']['payload']['source'] == refs['evidence']
    assert files(service.brain) == original


@pytest.mark.parametrize('surface', ['cli', 'http'])
@pytest.mark.parametrize('failure_point', ['sidecar', 'index', 'commit'])
def test_review_batch_recovery_keeps_exact_targets_and_one_receipt(service, tmp_path, monkeypatch,
                                                                  capsys, surface, failure_point):
    """Inject at publication boundaries; a review batch is never half accepted."""
    import graph_engine.decision_memory as dm
    from graph_engine.__main__ import cmd_decision

    refs = [save(service, claim(f'Review target {i}'))[0] for i in range(2)]
    request = envelope(service, events=[event(ref, axis='workflow', before='proposed', after='accepted')
                                        for ref in refs])
    commit(service)
    original = read_file(service.brain)
    original_files = files(service.brain)
    monkeypatch.setattr(runtime, 'make_brain', lambda: service.brain)
    path = tmp_path / 'review.json'
    path.write_text(json.dumps(request))

    def submit():
        if surface == 'http':
            with TestClient(app) as client:
                response = client.post('/api/decision-memory/reviews', json=request)
            return response.status_code, response.json()
        code = 0
        try:
            cmd_decision(['review', str(path)])
        except SystemExit as exc:
            code = exc.code
        output = capsys.readouterr()
        if code and failure_point == 'sidecar':
            return code, {'error': output.err}
        return code, json.loads(output.err if code else output.out)

    def fail(*args, **kwargs):
        raise OSError('Scripted review publication interruption')

    with monkeypatch.context() as fault:
        if failure_point == 'sidecar':
            fault.setattr(dm, '_atomic_write', fail)
            if surface == 'http':
                with pytest.raises(OSError, match='Scripted review'):
                    submit()
            else:
                code, error = submit()
                assert code == 1 and 'Scripted review publication interruption' in error['error']
            assert read_file(service.brain) == original
            assert files(service.brain) == original_files
        else:
            method = 'rebuild_index' if failure_point == 'index' else 'commit_and_push'
            fault.setattr(service.brain, method, fail)
            code, interrupted = submit()
            assert code == (502 if surface == 'http' else 1)
            assert interrupted['published_locally']
            published = read_file(service.brain)
            assert published['generation'] == original['generation'] + 1
            assert len(published['events']) == len(original['events']) + 2
            assert len(published['receipts']) == len(original['receipts']) + 1
            code, replay = submit()
            assert code == (200 if surface == 'http' else 0)
            assert replay['replay'] and replay['receipt'] == interrupted['receipt']
            assert read_file(service.brain) == published

    code, result = submit()
    assert code == (200 if surface == 'http' else 0)
    settled = read_file(service.brain)
    assert settled['versions'] == original['versions']
    assert settled['generation'] == original['generation'] + 1
    assert len(settled['events']) == len(original['events']) + 2
    assert len(settled['receipts']) == len(original['receipts']) + 1
    assert [e['subject'] for e in settled['events']] == refs
    assert all(service.inspect(ref)['state']['workflow'] == 'accepted' for ref in refs)
    # Retry via a newly constructed service/CLI, not only an in-memory instance.
    if surface == 'cli':
        child = subprocess.run([sys.executable, '-m', 'graph_engine', 'decision', 'review', str(path)],
                               text=True, capture_output=True, cwd=ROOT, env=child_env(), timeout=30)
        assert child.returncode == 0, child.stderr
        replay = json.loads(child.stdout)
    else:
        _, replay = submit()
    assert replay['replay'] and replay['receipt'] == result['receipt']
    assert read_file(service.brain) == settled


@pytest.mark.parametrize('surface', ['cli', 'http'])
def test_concurrent_reviews_keep_exact_targets_and_lossless_retry(service, tmp_path, monkeypatch, surface):
    refs = [save(service, claim(f'Concurrent review target {i}'))[0] for i in range(2)]
    requests = [envelope(service, events=[event(ref, axis='workflow', before='proposed', after='accepted')])
                for ref in refs]
    commit(service)
    original = read_file(service.brain)
    monkeypatch.setattr(runtime, 'make_brain', lambda: service.brain)
    if surface == 'cli':
        paths = [tmp_path / f'review-{i}.json' for i in range(2)]
        for path, request in zip(paths, requests):
            path.write_text(json.dumps(request))
        gate = tmp_path / 'start-reviews'
        code = ('import os,sys,time; from pathlib import Path; '
                'Path(sys.argv[1]).write_text("ready"); gate=Path(sys.argv[2]);\n'
                'while not gate.exists(): time.sleep(0.01)\n'
                'os.execv(sys.executable,[sys.executable,"-m","graph_engine","decision","review",sys.argv[3]])')
        children = []
        try:
            for i, path in enumerate(paths):
                children.append(subprocess.Popen([sys.executable, '-c', code,
                    str(tmp_path / f'review-ready-{i}'), str(gate), str(path)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT, env=child_env()))
            deadline = time.monotonic() + 15
            while not all((tmp_path / f'review-ready-{i}').exists() for i in range(2)):
                assert time.monotonic() < deadline, 'Review writers did not reach the start barrier'
                time.sleep(0.01)
            gate.touch()
            outputs = [child.communicate(timeout=30) for child in children]
            assert sorted(child.returncode for child in children) == [0, 1], outputs
            loser = next(i for i, child in enumerate(children) if child.returncode)
            assert 'refresh' in outputs[loser][1].lower()
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=5)
    else:
        barrier = Barrier(2)
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
            def post(request):
                barrier.wait(timeout=10)
                return client.post('/api/decision-memory/reviews', json=request)
            responses = list(pool.map(post, requests))
        assert sorted(response.status_code for response in responses) == [200, 409]
        loser = next(i for i, response in enumerate(responses) if response.status_code == 409)
    won = read_file(service.brain)
    assert won['versions'] == original['versions']
    assert won['generation'] == original['generation'] + 1
    assert len(won['events']) == len(original['events']) + 1
    assert len(won['receipts']) == len(original['receipts']) + 1
    assert won['events'][-1]['subject'] == refs[1 - loser]
    preview = service.preview()
    requests[loser].update(expected_generation=preview['generation'], expected_heads=preview['heads'])
    if surface == 'cli':
        paths[loser].write_text(json.dumps(requests[loser]))
        response = subprocess.run([sys.executable, '-m', 'graph_engine', 'decision', 'review', str(paths[loser])],
            text=True, capture_output=True, cwd=ROOT, env=child_env(), timeout=30)
        assert response.returncode == 0, response.stderr
    else:
        with TestClient(app) as client:
            assert client.post('/api/decision-memory/reviews', json=requests[loser]).status_code == 200
    settled = read_file(service.brain)
    assert settled['versions'] == original['versions']
    assert settled['generation'] == original['generation'] + 2
    assert len(settled['events']) == len(original['events']) + 2
    assert len(settled['receipts']) == len(original['receipts']) + 2
    assert [e['subject'] for e in settled['events']] == [refs[1 - loser], refs[loser]]
    assert all(service.inspect(ref)['state']['workflow'] == 'accepted' for ref in refs)

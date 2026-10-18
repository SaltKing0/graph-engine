"""Real Chromium workflows and hostile-content regressions for the shipped UI."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

import pytest

PW = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect
from graph_engine.brain import Brain, Edge, Node

REPO = Path(__file__).resolve().parent.parent
HOSTILE = '<img src=x onerror=window.__pwned=1><script>window.__pwned=1</script>'
NODE_TEXT = f"Benign note {HOSTILE}"
D3_URL = "https://d3js.org/d3.v7.min.js"


@pytest.fixture(scope="session")
def d3_script():
    path = os.environ.get("GRAPH_ENGINE_TEST_D3")
    if not path:
        return None  # Local runs may load the production CDN directly.
    data = Path(path).read_bytes()
    digest = base64.b64encode(hashlib.sha384(data).digest()).decode()
    assert f'integrity="sha384-{digest}"' in (REPO / "graph_engine/web/index.html").read_text(), (
        "Test D3 must match the production script's integrity attribute")
    return data


@pytest.fixture
def server(tmp_path, request):
    """Each workflow gets a fresh brain and a real HTTP/WebSocket server."""
    options = getattr(request, 'param', {})
    brain = Brain(str(tmp_path / "brain"), mode=options.get('mode', 'local'))
    if options.get('mode') == 'git':
        brain.init()
    else:
        brain.ensure_ready()
    brain.write_node(Node(id="hostile", text=NODE_TEXT))
    brain.write_node(Node(id="safe", text="A second idea about memory"))
    brain.write_edges([Edge(id="suggestion", source="hostile", target="safe",
                           kind="fact", predicate=HOSTILE, pending=True,
                           evidence=[{"node_id": "hostile", "text": HOSTILE}])])
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("IG_", "IDEAGRAPH_"))}
    env.update(IG_BRAIN_MODE=brain.mode, IG_BRAIN_PATH=str(brain.path),
               IDEAGRAPH_EMBEDDER="hash", PYTHONPATH=str(REPO))
    headers = {}
    if options.get('secure'):
        policy = tmp_path / 'browser-policy.json'
        policy.write_text(json.dumps({'graphs': {'default': {
            'roles': {'reviewer': 'editor', 'reader': 'viewer'},
            'nodes': {'source': {'read': ['reviewer'], 'write': ['reviewer']}}}},
            'tokens': {hashlib.sha256(token.encode()).hexdigest(): identity for token, identity in
                       [('reviewer-token', 'reviewer'), ('reader-token', 'reader')]}}))
        env['IG_ACCESS_POLICY'] = str(policy)
        headers['Authorization'] = 'Bearer reviewer-token'
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (tmp_path / "server.log").open("w+") as log:
        command = [sys.executable, "-m", "uvicorn", "graph_engine.server:app",
                   "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"]
        if options.get('fail_finding_index_once'):
            # Fault injection is confined to this test server process. No
            # production environment switch or changed recovery policy.
            code = '''import json,sys
from graph_engine.brain import Brain
from graph_engine.decision_schema import FILENAME
original = Brain.rebuild_index
failed = False
def injected(self, *args, **kwargs):
    global failed
    path = self.path / FILENAME
    if path.exists() and not failed:
        data = json.loads(path.read_text())
        if any(v['kind'] == 'finding' for v in data['versions']):
            failed = True
            raise OSError('Scripted finding index failure after publication')
    return original(self, *args, **kwargs)
Brain.rebuild_index = injected
import uvicorn
uvicorn.run('graph_engine.server:app',host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
'''
            command = [sys.executable, '-c', code, str(port)]
        proc = subprocess.Popen(
            command,
            env=env, cwd=REPO, stdout=log, stderr=log)
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    with urlopen(Request(f"{base}/api/graph", headers=headers), timeout=1):
                        break
                except OSError:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
            else:
                pytest.fail("server did not become ready")
            if proc.poll() is not None:
                log.seek(0)
                pytest.fail(f"server exited: {log.read()}")
            yield base
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)


@pytest.fixture
def page(d3_script):
    with PW.sync_playwright() as pw:
        # Use Playwright's downloaded Chromium by default. Missing browsers
        # fail instead of silently skipping an installed browser test suite.
        options = {}
        if os.environ.get("PLAYWRIGHT_CHROMIUM"):
            options["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM"]
        browser = pw.chromium.launch(**options)
        context = browser.new_context()
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        if d3_script is not None:
            page.route(D3_URL, lambda route: route.fulfill(
                body=d3_script, content_type="application/javascript",
                headers={"Access-Control-Allow-Origin": "*"}))
        # These workflows exercise 2D; optional 3D libraries add no network
        # dependency to the test.
        page.route("https://unpkg.com/**", lambda route: route.abort())
        try:
            yield page
            assert not errors, f"Browser JavaScript errors: {errors}"
        finally:
            browser.close()


def open_graph(page, server):
    page.goto(server)
    expect(page.locator("#graph .node")).to_have_count(2)
    expect(page.locator("#cards .card")).to_have_count(1)


@pytest.mark.parametrize("close_detail", [False, True])
def test_forgetting_removes_text_from_graph_details_and_review(server, page, tmp_path, close_detail):
    from graph_engine.agent_memory import forget
    brain = Brain(str(tmp_path / "brain"), mode="local")
    secret = "Synthetic forgotten browser memory"
    brain.write_node(Node(secret, id="forgotten", status="active"))
    brain.add_edge(Edge("hostile", "safe", "fact", id="secret-fact", predicate="uses",
                        evidence=[{"node_id": "forgotten", "text": secret}]))
    page.goto(server)
    expect(page.locator("#graph .node")).to_have_count(3)
    expect(page.locator("#cards .card")).to_have_count(2)
    page.locator('#graph .node').filter(has_text=secret).click()
    expect(page.locator("#detail-text")).to_have_text(secret)
    if close_detail:
        page.locator("#close-detail").click()
        expect(page.locator("#detail")).not_to_be_visible()
    forget(brain, "forgotten", reason="synthetic browser regression", commit=False)
    # Refresh with either an open detail pane or a previously closed one.
    assert page.request.post(f"{server}/api/edge", data={
        "source": "hostile", "target": "safe", "kind": "same_as"}).status == 200
    expect(page.locator("#graph .node")).to_have_count(2)
    expect(page.locator("#cards .card")).to_have_count(1)
    assert secret not in page.locator("body").inner_text()
    assert secret not in page.locator("body").inner_html()
    assert secret not in page.request.get(f"{server}/api/graph").text()
    page.goto(f"{server}/review")
    expect(page.locator("#count")).to_have_text("1 pending")
    assert secret not in page.locator("body").inner_text()
    assert brain.read_node("forgotten").text == secret


def test_refresh_removes_forgotten_focused_search_result(server, page, tmp_path):
    from graph_engine.agent_memory import forget
    brain = Brain(tmp_path / "brain", mode="local")
    secret = "Synthetic forgotten search memory"
    brain.write_node(Node(secret, id="forgotten", status="active"))
    page.goto(server)
    expect(page.locator("#graph .node")).to_have_count(3)
    page.locator("#search").fill("Synthetic forgotten")
    hit = page.locator('#search-results button[data-node="forgotten"]')
    expect(hit).to_contain_text(secret)
    hit.focus()
    forget(brain, "forgotten", reason="search refresh regression", commit=False)
    assert page.request.post(f"{server}/api/edge", data={
        "source": "hostile", "target": "safe", "kind": "same_as"}).status == 200
    expect(page.locator("#graph .node")).to_have_count(2)
    expect(page.locator("#search-results")).to_contain_text("No matching idea")
    expect(page.locator("#search")).to_be_focused()
    assert secret not in page.locator("body").inner_html()
    assert secret not in page.request.get(f"{server}/api/graph").text()


def test_review_refresh_clears_forgotten_picker_and_search_hits(server, page, tmp_path):
    from graph_engine.agent_memory import forget
    brain = Brain(tmp_path / "brain", mode="local")
    secret = "Synthetic forgotten picker memory"
    brain.write_node(Node(secret, id="forgotten", status="active"))
    brain.add_edge(Edge("forgotten", "safe", "similar", id="secret-edge"))
    page.goto(f"{server}/review")
    expect(page.locator("#count")).to_have_text("2 pending")
    page.locator("#search").fill("Synthetic forgotten")
    expect(page.locator("#hits")).to_contain_text(secret)
    page.locator('.nodebox[data-pick="forgotten"]').click()
    page.locator('.nodebox[data-pick="safe"]').first.click()
    expect(page.locator("#slotA")).to_contain_text(secret)
    expect(page.locator("#linkbtn")).to_be_enabled()
    forget(brain, "forgotten", reason="picker refresh regression", commit=False)
    page.locator('button[data-resolve="suggestion"][data-accept="1"]').click()
    expect(page.locator("#count")).to_have_text("0 pending")
    expect(page.locator("#slotA")).to_have_text("A: empty")
    expect(page.locator("#slotB")).to_contain_text("A second idea")
    expect(page.locator("#linkbtn")).to_be_disabled()
    expect(page.locator("#hits")).to_be_empty()
    assert secret not in page.locator("body").inner_html()
    assert brain.read_node("forgotten").text == secret


def assert_inert(page):
    assert page.evaluate("() => window.__pwned === undefined")
    assert page.locator('img[src="x"]').count() == 0
    assert not page.evaluate(
        "() => [...document.scripts].some(el => el.textContent.includes('__pwned'))")


@pytest.fixture
def second_origin():
    """A real page on another loopback port, without cross-network restrictions."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<!doctype html><title>Second origin</title>")

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_second_origin_cannot_subscribe_to_private_websocket_updates(server, second_origin, page):
    page.goto(second_origin)
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")
    handshake_errors = []
    cdp.on("Network.webSocketFrameError",
           lambda event: handshake_errors.append(event["errorMessage"]))
    # Observe the real handshake and keep collecting messages after rejection.
    connect = """url => new Promise(resolve => {
        window.received = [];
        window.opened = false;
        window.socket = new WebSocket(url);
        socket.onmessage = event => received.push(JSON.parse(event.data));
        socket.onopen = () => { opened = true; resolve('open'); };
        socket.onclose = () => resolve('closed');
    })"""
    ws_url = server.replace("http://", "ws://") + "/ws"
    outcome = page.evaluate(connect, ws_url)
    # Finish mutations even if the vulnerable server accepted the socket, so
    # this regression also demonstrates the original note/edge disclosure.
    trusted = page.context.browser.new_page()
    try:
        trusted.goto(f"{server}/api/graph")
        assert trusted.evaluate(connect, ws_url) == "open"
        text = "Synthetic private browser observation"
        response = page.request.post(f"{server}/api/ingest", data={
            "text": text, "allow_duplicates": True})
        assert response.status == 200
        decision = page.request.post(f"{server}/api/edge/suggestion/accept")
        assert decision.status == 200
        trusted.wait_for_function("received.length === 2")
        events = trusted.evaluate("received")
        assert events[0]["node"]["text"] == text
        assert events[0]["edges"] == response.json()["suggested"]
        assert events[1] == {"type": "edge_resolved", "edge": decision.json(), "accepted": True}
        assert outcome == "closed", page.evaluate("received")
        # Chromium reports a denied upgrade as a frame error, not a completed
        # handshake response. Verify HTTP 403, not a browser network restriction.
        assert any("Unexpected response code: 403" in error for error in handshake_errors), handshake_errors
        assert page.evaluate("opened") is False
        assert page.evaluate("received") == []
    finally:
        trusted.close()
        cdp.detach()


def test_same_origin_ui_receives_external_ingest_and_edge_updates(server, page):
    open_graph(page, server)
    expect(page.locator("#connection")).to_have_text("Live connected")
    expect(page.locator('#cards [data-id="suggestion"]')).to_have_count(1)
    text = "Synthetic private realtime astronomy observation"
    response = page.request.post(f"{server}/api/ingest", data={
        "text": text, "allow_duplicates": True})
    assert response.status == 200
    expect(page.locator("#graph .node title").filter(has_text=text)).to_have_count(1)
    assert page.request.post(f"{server}/api/edge/suggestion/accept").status == 200
    expect(page.locator('#cards [data-id="suggestion"]')).to_have_count(0)


def test_hostile_node_text_is_inert(server, page):
    open_graph(page, server)
    # A broken or empty page must never pass the XSS assertion.
    expect(page.locator('#cards [data-action="source"] .excerpt')).to_have_text(NODE_TEXT)
    page.locator('#cards [data-action="source"]').click()
    expect(page.locator("#detail-text")).to_have_text(NODE_TEXT)
    assert_inert(page)


def test_hostile_text_in_graph_api_is_escaped_in_dom(server, page):
    open_graph(page, server)
    expect(page.locator("#graph .node title").filter(has_text=HOSTILE)).to_have_count(1)
    expect(page.locator("#cards .kind")).to_have_text(HOSTILE)
    expect(page.locator("#cards .fact-evidence")).to_have_text(HOSTILE)
    assert_inert(page)


def test_review_page_renders_hostile_content_as_text(server, page):
    page.goto(f"{server}/review")
    expect(page.locator("#count")).to_have_text("1 pending")
    expect(page.locator("#cards .kind")).to_have_text(HOSTILE)
    expect(page.locator("#cards .nodebox").first).to_contain_text(HOSTILE[:45])
    expect(page.locator("#cards p")).to_have_text(HOSTILE)
    assert_inert(page)


@pytest.mark.parametrize("action", ["accept", "reject"])
def test_review_decision_persists_and_undo_restores_suggestion(server, page, action):
    open_graph(page, server)
    page.locator(f'#cards [data-action="{action}"]').click()
    expect(page.locator("#cards .card")).to_have_count(0)
    edges = page.request.get(f"{server}/api/graph").json()["edges"]
    assert all(not edge["pending"] for edge in edges)
    page.locator("#undo").click()
    expect(page.locator("#cards .card")).to_have_count(1)
    edges = page.request.get(f"{server}/api/graph").json()["edges"]
    assert next(edge for edge in edges if edge["id"] == "suggestion")["pending"]
    page.reload()
    expect(page.locator("#cards .card")).to_have_count(1)


def test_capture_idea_persists_after_reload(server, page):
    open_graph(page, server)
    text = "Astronomy telescope Jupiter rings observation"
    page.locator("#text").fill(text)
    page.locator("#source").select_option("agent")
    page.locator("#ingest-button").click()
    expect(page.locator("#graph .node")).to_have_count(3)
    stored = page.request.get(f"{server}/api/graph").json()["nodes"]
    node = next(node for node in stored if node["text"] == text)
    assert node["source"] == "agent"
    page.reload()
    expect(page.locator("#graph .node title").filter(has_text=text)).to_have_count(1)


def test_search_uses_ranked_results_keyboard_and_lazy_safe_explanation(server, page):
    import json
    requests = []
    explanation_requests = []
    # Ranked server results differ from the local literal match (safe first).
    payload = {"results": [
        {"id": "safe", "snippet": "Semantic paraphrase", "rank": 1, "score": .02, "score_kind": "rrf"},
        {"id": "hostile", "snippet": HOSTILE, "rank": 2, "score": .01, "score_kind": "rrf"}]}
    page.route("**/api/search?**", lambda route: (
        requests.append(route.request.url), route.fulfill(json=payload)))
    page.route("**/api/search/*/explain?**", lambda route: (
        explanation_requests.append(route.request.url), route.fulfill(json={
            "rank": 2, "reason": "returned", "dense": {"rank": 2, "score": .5},
            "bm25": {"score": 0}, "rrf": {"score": .01}, "matched_terms": [HOSTILE],
            "graph_used_for_ranking": False, "final_score_kind": "rrf"})))
    open_graph(page, server)
    page.locator("#search").fill("Benign")
    expect(page.locator("#search-status")).to_have_text("Searching …")
    results = page.locator("#search-results button[data-node]")
    expect(results).to_have_count(2)
    assert results.first.get_attribute("data-node") == "safe"
    expect(results.nth(1)).to_contain_text(HOSTILE)
    expect(page.locator('#graph .node[aria-label="Open idea: A second idea about memory"]')).not_to_have_class("node dimmed")
    assert len(requests) == 1 and not explanation_requests
    page.locator('[data-explain="hostile"]').click()
    panel = page.locator('[data-result="hostile"] .search-explanation')
    expect(panel).to_contain_text(HOSTILE)
    assert len(explanation_requests) == 1
    page.locator('[data-explain="hostile"]').click()
    page.locator('[data-explain="hostile"]').click()
    expect(panel).to_contain_text(HOSTILE)
    assert len(explanation_requests) == 1  # cached until the query changes
    assert_inert(page)
    # Return to input with Shift+Tab (focusin does not schedule a new search).
    page.locator("#search").evaluate("el => el.focus()")
    expect(results).to_have_count(2)
    page.locator("#search").press("ArrowDown")
    expect(results.first).to_be_focused()
    results.first.press("ArrowDown")
    expect(results.nth(1)).to_be_focused()
    results.nth(1).press("ArrowUp")
    expect(results.first).to_be_focused()
    results.first.press("Enter")
    expect(page.locator("#detail-text")).to_have_text("A second idea about memory")
    expect(page.locator("#search-results")).to_be_hidden()
    expect(page.locator('#graph .node[aria-label="Open idea: A second idea about memory"]')).to_have_class("node selected")
    assert_inert(page)


@pytest.mark.parametrize("outside_action", ["zoom", "focus"])
def test_ranked_highlights_survive_closing_search(server, page, outside_action):
    payload = {"results": [
        {"id": "safe", "snippet": "Semantic match", "rank": 1, "score": .02}]}
    page.route("**/api/search?**", lambda route: route.fulfill(
        json=payload if "query=Benign" in route.request.url else {"results": []}))
    open_graph(page, server)
    search = page.locator("#search")
    search.fill("Benign")
    expect(page.locator("#search-results button[data-node]")).to_have_count(1)
    semantic = page.locator('#graph .node[aria-label="Open idea: A second idea about memory"]')
    literal = page.locator("#graph .node").filter(has=page.locator("title", has_text="Benign"))
    expect(semantic).not_to_have_class("node dimmed")
    if outside_action == "zoom":
        page.locator("#zoom-in").click()
    else:
        page.locator("#zoom-in").focus()
    expect(page.locator("#search-results")).to_be_hidden()
    expect(search).to_have_value("Benign")
    expect(page.locator("#search-results")).to_be_empty()
    expect(semantic).not_to_have_class("node dimmed")
    expect(literal).not_to_have_class("node dimmed")
    # A different query must discard highlights from the previous ranking.
    search.fill("unmatched")
    expect(page.locator("#search-status")).to_contain_text("No matching idea")
    expect(semantic).to_have_class("node dimmed")
    search.press("Escape")
    expect(search).to_have_value("")
    expect(semantic).not_to_have_class("node dimmed")
    expect(literal).not_to_have_class("node dimmed")


@pytest.mark.parametrize("change_query", [False, True])
def test_enter_refreshes_missing_search_hit_without_losing_selection(server, page, change_query):
    open_graph(page, server)
    graph = page.request.get(f"{server}/api/graph").json()
    graph["nodes"].append(dict(graph["nodes"][0], id="new", text="Newly added idea"))
    refresh_requests = []
    page.route("**/api/graph", lambda route: refresh_requests.append(route))
    page.route("**/api/search?**", lambda route: route.fulfill(json={"results": [
        {"id": "new", "snippet": "Newly added idea", "rank": 1, "score": .02}]}))
    search = page.locator("#search")
    search.fill("new idea")
    expect(page.locator("#search-results button[data-node]")).to_have_count(1)
    with page.expect_request(f"{server}/api/graph"):
        search.press("Enter")
    assert len(refresh_requests) == 1
    if change_query:
        search.fill("different query")
    refresh_requests[0].fulfill(json=graph)
    expect(page.locator("#graph .node")).to_have_count(3)
    if change_query:
        expect(page.locator("#detail")).not_to_be_visible()
        expect(search).to_have_value("different query")
        expect(page.locator("#search-results")).to_be_visible()
    else:
        expect(page.locator("#detail")).to_be_visible()
        expect(page.locator("#detail-text")).to_have_text("Newly added idea")
        expect(search).to_have_value("")
        expect(page.locator("#search-results")).to_be_hidden()


def test_real_http_search_and_explanation_render_hostile_text_safely(server, page):
    calls = []
    page.on("request", lambda request: calls.append(request.url))
    open_graph(page, server)
    page.locator("#search").fill("Benign")
    result = page.locator('#search-results button[data-node="hostile"]')
    expect(result).to_contain_text("Benign note <img")
    assert not any("/explain?" in url for url in calls)
    page.locator('[data-explain="hostile"]').click()
    expect(page.locator('[data-result="hostile"] .search-explanation')).to_contain_text("BM25")
    assert_inert(page)
    result.click()
    expect(page.locator("#detail-text")).to_have_text(NODE_TEXT)
    assert_inert(page)


def test_search_debounce_and_out_of_order_responses(server, page):
    pending = []
    page.route("**/api/search?**", lambda route: pending.append(route))
    open_graph(page, server)
    search = page.locator("#search")
    search.fill("m")
    search.fill("me")
    search.fill("memory")
    expect(page.locator("#search-status")).to_have_text("Searching …")
    page.wait_for_timeout(400)
    assert len(pending) == 1 and "query=memory" in pending[0].request.url
    search.fill("Benign")
    page.wait_for_timeout(400)
    assert len(pending) == 2
    pending[1].fulfill(json={"results": [{"id": "hostile", "snippet": "New result", "rank": 1, "score": .1}]})
    expect(page.locator("#search-results button[data-node]")).to_have_text("1. New resultRRF 0.100")
    pending[0].fulfill(json={"results": [{"id": "safe", "snippet": "Old result", "rank": 1, "score": .1}]})
    page.wait_for_timeout(100)
    expect(page.locator("#search-results button[data-node]")).to_have_attribute("data-node", "hostile")
    # Clearing/closing must invalidate requests before their responses arrive.
    search.fill("late")
    page.wait_for_timeout(400)
    assert len(pending) == 3
    search.press("Escape")
    pending[2].fulfill(json={"results": [{"id": "safe", "snippet": "Late result", "rank": 1, "score": .1}]})
    page.wait_for_timeout(100)
    expect(page.locator("#search-results")).to_be_hidden()
    expect(search).to_have_value("")


@pytest.mark.parametrize("status,message", [
    (401, "Authentication required"), (403, "Access denied"), (500, "Search failed")])
def test_search_authentication_access_and_error_states(server, page, status, message):
    page.route("**/api/search?**", lambda route: route.fulfill(status=status, json={"error": "denied"}))
    open_graph(page, server)
    page.locator("#search").fill("memory")
    expect(page.locator("#search-status")).to_contain_text(message)
    expect(page.locator("#search-results button")).to_have_count(0)
    expect(page.locator("#search-results")).to_have_attribute("aria-busy", "false")


def test_search_empty_state_and_retry(server, page):
    page.route("**/api/search?**", lambda route: route.fulfill(json={"results": []}))
    open_graph(page, server)
    page.locator("#search").fill("no match")
    expect(page.locator("#search-status")).to_contain_text("No matching idea")
    expect(page.locator("#search-results button")).to_have_count(0)
    page.locator("#search").fill("")
    expect(page.locator("#search-results")).to_be_hidden()


@pytest.mark.parametrize("view", ["main", "review"])
def test_fact_replacement_review_accept_reject_and_undo(server, page, view):
    def capture(text, accept=False):
        response = page.request.post(server + "/api/ingest", data={
            "text": text, "extraction": "rules", "accept_facts": accept})
        assert response.status == 200
        assert response.json()["extraction"]["status"] == "complete"
        return response.json()
    capture("Alice works at Acme.", True)
    changed = capture("Alice now works at Globex instead of Acme.")
    proposal = changed["extraction"]["proposals"][0]
    pid = proposal["id"]
    if view == "main":
        page.goto(server)
        card = page.locator(f'.card[data-id="{pid}"]')
    else:
        page.goto(server + "/review")
        card = page.locator(".card").filter(has=page.locator(f'[data-resolve="{pid}"]'))
    undo = page.locator("#undo" if view == "main" else "#undoBtn")
    expect(card).to_contain_text("Old claim")
    expect(card).to_contain_text("New claim")
    expect(card).to_contain_text("Acme")
    expect(card).to_contain_text("Globex")
    expect(card).to_contain_text("Proposed effective date: unknown")
    expect(card).to_contain_text("Alice now works at Globex instead of Acme")
    card.locator("button.ok").click()
    expect(card).to_have_count(0)
    undo.click()
    expect(card).to_have_count(1)
    card.locator('[data-action="reject"]' if view == "main" else "button.no").click()
    expect(card).to_have_count(0)
    undo.click()
    expect(card).to_have_count(1)
    assert_inert(page)


@pytest.mark.parametrize("view", ["main", "review"])
def test_structured_consolidation_evidence_is_visible_and_inert(server, page, tmp_path, view):
    from graph_engine.consolidation import ConsolidationConfig, consolidate
    from graph_engine.consolidation_protocol import PROPOSAL_PREFIX
    brain = Brain(tmp_path / "brain", mode="local")
    brain.write_node(Node(id="event", text=HOSTILE, ntype="episodic",
                          created="2020-01-01T00:00:00Z"))
    result = consolidate(brain, config=ConsolidationConfig(threshold=0, min_age_days=0),
                         structured_extractor=lambda events: dict(version=1, abstain=False,
                             facts=[dict(text="A proposed claim", evidence=[dict(
                                 node_id="event", quote=HOSTILE)])]))
    edge = next(e for e in brain.read_edges() if e.origin == "consolidator")
    page.goto(server if view == "main" else server + "/review")
    card = (page.locator(f'.card[data-id="{edge.id}"]') if view == "main" else
            page.locator(".card").filter(has=page.locator(f'[data-resolve="{edge.id}"]')))
    expect(card).to_contain_text(PROPOSAL_PREFIX.strip())
    expect(card).to_contain_text("Evidence event: " + HOSTILE)
    expect(card).to_contain_text("not factual entailment")
    expect(card).to_contain_text("remains searchable before review")
    assert_inert(page)
    card.locator("button.ok").click()
    expect(card).to_have_count(0)
    page.locator("#undo" if view == "main" else "#undoBtn").click()
    expect(card).to_have_count(1)
    assert result["created"] == 1


def decision_browser_seed(tmp_path, *, hostile=False):
    from graph_engine.decision_service import DecisionService
    from test_decision_impact import scenario, commit, change_source, comparison
    brain = Brain(str(tmp_path / 'brain'), mode='git')
    service = DecisionService(brain)
    refs = scenario(service)
    before = commit(service)
    change_source(service, 'Changed browser observation ' + (HOSTILE if hostile else ''))
    after = commit(service)
    return service, refs, comparison(before, after)


def open_decision_comparison(page, server, comp):
    page.goto(f'{server}/review?mode=decisions')
    expect(page.locator('#dm-message')).to_contain_text('No accessible pending')
    page.get_by_label('Previous revision', exact=True).fill(comp['before'])
    page.get_by_label('Current revision', exact=True).fill(comp['after'])
    page.get_by_role('button', name='Compare revisions', exact=True).click()
    expect(page.locator('#dm-queue button').first).to_be_visible()
    page.locator('#dm-queue button').first.click()
    expect(page.locator('#dm-detail')).to_contain_text('Changed evidence')


@pytest.mark.parametrize('server', [{'mode':'git'}], indirect=True)
def test_decision_impact_full_browser_flow_and_pinned_brief(server, page, tmp_path):
    service, refs, comp = decision_browser_seed(tmp_path)
    open_decision_comparison(page, server, comp)
    expect(page.locator('#dm-detail')).to_contain_text('Previous:')
    expect(page.locator('#dm-detail')).to_contain_text('Current:')
    expect(page.locator('#dm-detail')).to_contain_text('Comparable scope')
    expect(page.locator('#dm-detail')).to_contain_text('Dependency path to the decision')
    expect(page.locator('#dm-detail')).to_contain_text('Conditions')
    page.get_by_role('button', name='Open decision brief', exact=True).click()
    expect(page.locator('#dm-detail')).to_contain_text(f'Decision brief · revision {comp["after"]}')
    expect(page.locator('#dm-detail')).to_contain_text('dm.markdown/1')
    page.get_by_label('Review reason (required)', exact=True).fill('Source change warrants explicit review')
    page.get_by_role('button', name='Record finding judgment', exact=True).click()
    expect(page.locator('#dm-notice')).to_contain_text('Review recorded')
    expect(page.locator('#dm-queue button')).to_contain_text('Reviewed judgment: confirmed')
    page.locator('#dm-queue button').click()
    page.get_by_label('Review reason (required)', exact=True).fill('I own this follow-up')
    page.get_by_role('button', name='Acknowledge finding', exact=True).click()
    expect(page.locator('#dm-message')).to_contain_text('No accessible pending')
    page.get_by_label('Include acknowledged, resolved and dismissed history').check()
    page.locator('#dm-queue button').click()
    expect(page.locator('#dm-detail')).to_contain_text('acknowledged')
    page.get_by_label('Review reason (required)', exact=True).fill('Revise based on the reviewed premise')
    page.get_by_label('Decision review outcome', exact=True).select_option('revise')
    page.get_by_label('Evidence / claim basis for this outcome (select one or more)').select_option(label='claim: Graph expansion stays opt-in')
    page.get_by_role('button', name='Record decision outcome', exact=True).click()
    expect(page.get_by_role('button', name='Resolve finding with recorded outcome', exact=True)).to_be_visible()
    page.get_by_label('Review reason (required)', exact=True).fill('Resolution records the need to revise')
    page.get_by_role('button', name='Resolve finding with recorded outcome', exact=True).click()
    expect(page.locator('#dm-detail')).to_contain_text('resolved')
    page.get_by_label('Include acknowledged, resolved and dismissed history').uncheck()
    expect(page.locator('#dm-queue button')).to_have_count(0)
    assert service.inspect(refs['decision'])['state']['decision_conclusion'] == 'revise'
    assert service.inspect(refs['decision'])['state']['decision'] == 'proposed'


@pytest.mark.parametrize('server', [{'mode':'git'}], indirect=True)
def test_decision_review_result_sources_render_and_allow_review(server, page, tmp_path):
    from graph_engine.decision_service import DecisionService
    from test_decision_impact import scenario, commit, comparison, link
    from test_decision_service import save
    from test_decision_memory import check_record, result_record, draft
    service = DecisionService(Brain(str(tmp_path / 'brain'), mode='git'))
    refs = scenario(service)
    service.brain.write_node(Node(HOSTILE, id='result-source'))
    source, = save(service, draft('source', service.source('result-source'), anchor='result-source'))
    check, = save(service, check_record())
    link(service, 'checks', check, refs['decision'], None)
    result, = save(service, result_record(check, [refs['source'], source]))
    before = commit(service)
    link(service, 'result_of', result, check, None)
    comp = comparison(before, commit(service))
    open_decision_comparison(page, server, comp)
    result_box = page.locator('.dm-record').filter(has=page.get_by_text(
        f'{result["id"]}@{result["version_id"]}', exact=True))
    result_box.locator('summary').first.click()
    expect(result_box).to_contain_text(f'Source: {refs["source"]["id"]}@{refs["source"]["version_id"]}')
    expect(result_box).to_contain_text(f'Source: {source["id"]}@{source["version_id"]}')
    # The same detail also contains evidence's {ref, passage} source wrappers.
    evidence_box = page.locator('.dm-record').filter(has=page.get_by_text(
        f'{refs["evidence"]["id"]}@{refs["evidence"]["version_id"]}', exact=True))
    expect(evidence_box).to_contain_text(f'Source: {refs["source"]["id"]}@{refs["source"]["version_id"]}')
    expect(page.locator('#dm-detail')).to_contain_text(HOSTILE)
    page.get_by_label('Review reason (required)', exact=True).fill('Review the sourced check result')
    page.get_by_role('button', name='Record finding judgment', exact=True).click()
    expect(page.locator('#dm-notice')).to_contain_text('Review recorded')
    expect(page.locator('#dm-queue button').first).to_contain_text('Reviewed judgment: confirmed')
    assert_inert(page)


@pytest.mark.parametrize('server', [{'mode':'git'}], indirect=True)
@pytest.mark.parametrize('prior_outcome', [False, True])
def test_decision_review_successor_outcome_preserves_historical_target(server, page, tmp_path, prior_outcome):
    from test_decision_impact import finding_envelope
    from test_decision_service import save, review
    from test_decision_memory import draft, content_basis
    service, refs, comp = decision_browser_seed(tmp_path)
    candidate, = service.compare(comp)['candidates']
    finding, = service.record_finding(finding_envelope(service, comp, candidate), commit=False)['receipt']['refs']
    if prior_outcome:
        review(service, refs['decision'], axis='decision_conclusion', after='revise', basis=[content_basis(refs['claim'])])
    original = service.inspect(refs['decision'])
    successor, = save(service, draft('decision', dict(original['record']['payload'], rationale='Updated rationale'),
        identity=original['record']['id'], anchor=original['record']['anchor_node_id'], previous=refs['decision']))
    page.goto(f'{server}/review?mode=decisions')
    page.locator('#dm-queue button').click()
    expect(page.locator('#dm-detail')).to_contain_text('This finding targets a previous decision version')
    expect(page.get_by_role('button', name='Record decision outcome', exact=True)).to_be_hidden()
    expect(page.get_by_role('button', name='Resolve finding with recorded outcome', exact=True)).to_have_count(0)
    page.get_by_role('button', name='Review current decision version', exact=True).click()
    expect(page.get_by_label('Decision review outcome', exact=True)).to_be_focused()
    expect(page.locator('#dm-decision-outcome')).to_contain_text(f'Outcome target: {successor["id"]}@{successor["version_id"]}')
    expect(page.locator('#dm-decision-outcome')).to_contain_text('Updated rationale')
    preview = service.preview()
    reason = 'Review the current decision separately from its historical finding'
    page.get_by_label('Review reason (required)', exact=True).fill(reason)
    page.get_by_label('Decision review outcome', exact=True).select_option('revise')
    page.get_by_label('Evidence / claim basis for this outcome (select one or more)').select_option(label='claim: Graph expansion stays opt-in')
    with page.expect_response(lambda response: response.url.endswith('/api/decision-memory/reviews')) as response_info:
        page.get_by_role('button', name='Record decision outcome', exact=True).click()
    assert response_info.value.status == 200
    submitted = response_info.value.request.post_data_json
    assert submitted['expected_heads'] == preview['heads']
    assert submitted['expected_generation'] == preview['generation']
    assert submitted['events'][0]['subject'] == successor
    expect(page.locator('#dm-notice')).to_contain_text('Review recorded')
    expect(page.locator('#dm-detail')).to_contain_text('This finding targets a previous decision version')
    retained = service.inspect(refs['decision'])
    assert retained['record'] == original['record']
    assert retained['events'] == original['events']
    assert service.inspect(successor)['events'][-1]['reason'] == reason
    assert service.inspect(finding)['state']['finding_workflow'] == 'open'
    # A successor's outcome cannot resolve a finding pinned to the prior version.
    page.get_by_role('button', name='Review current decision version', exact=True).click()
    expect(page.get_by_role('button', name='Resolve finding with recorded outcome', exact=True)).to_have_count(0)
    page.get_by_label('Review reason (required)', exact=True).fill('Acknowledge the historical finding')
    page.get_by_role('button', name='Acknowledge finding', exact=True).click()
    expect(page.locator('#dm-message')).to_contain_text('No accessible pending')
    assert service.inspect(finding)['state']['finding_workflow'] == 'acknowledged'


@pytest.mark.parametrize('server', [{'mode':'git'}], indirect=True)
def test_decision_review_missing_current_version_never_falls_back_to_history(server, page, tmp_path):
    from test_decision_impact import finding_envelope
    from test_decision_service import save
    from test_decision_memory import draft
    service, refs, comp = decision_browser_seed(tmp_path)
    candidate, = service.compare(comp)['candidates']
    service.record_finding(finding_envelope(service, comp, candidate), commit=False)
    original = service.inspect(refs['decision'])['record']
    successor, = save(service, draft('decision', dict(original['payload'], rationale='Current rationale'),
        identity=original['id'], anchor=original['anchor_node_id'], previous=refs['decision']))
    def truncate_current(route):
        response = route.fetch()
        body = response.json()
        body['records'] = [item for item in body['records'] if item['record']['version_id'] != successor['version_id']]
        body['truncated'] = True
        route.fulfill(response=response, json=body)
    page.route('**/api/decision-memory/read/review-detail', truncate_current)
    page.goto(f'{server}/review?mode=decisions')
    page.locator('#dm-queue button').click()
    expect(page.locator('#dm-detail')).to_contain_text('The current decision version is unavailable in this detail')
    expect(page.get_by_role('button', name='Record decision outcome', exact=True)).to_have_count(0)
    expect(page.get_by_role('button', name='Review current decision version', exact=True)).to_have_count(0)
    expect(page.get_by_role('button', name='Resolve finding with recorded outcome', exact=True)).to_have_count(0)
    expect(page.get_by_role('button', name='Acknowledge finding', exact=True)).to_be_visible()


@pytest.mark.parametrize('server', [{'mode':'git'}], indirect=True)
def test_decision_review_stale_submission_refreshes_without_overwriting(server, page, tmp_path):
    from test_decision_impact import finding_envelope
    from test_decision_service import review
    service, refs, comp = decision_browser_seed(tmp_path)
    c, = service.compare(comp)['candidates']
    finding, = service.record_finding(finding_envelope(service, comp, c), commit=False)['receipt']['refs']
    page.goto(f'{server}/review?mode=decisions')
    page.locator('#dm-queue button').click()
    expect(page.get_by_role('button', name='Acknowledge finding', exact=True)).to_be_visible()
    old_generation = service.preview()['generation']
    review(service, finding, axis='finding_workflow', after='acknowledged')
    page.get_by_label('Review reason (required)', exact=True).fill('Stale reason must not replace newer review')
    page.get_by_role('button', name='Acknowledge finding', exact=True).click()
    expect(page.locator('#dm-notice')).to_contain_text('Stale review')
    expect(page.locator('#dm-queue button')).to_have_count(0)
    assert service.preview()['generation'] == old_generation + 1
    page.get_by_label('Include acknowledged, resolved and dismissed history').check()
    page.locator('#dm-queue button').click()
    expect(page.locator('#dm-detail')).to_contain_text('acknowledged')
    assert 'Stale reason must not replace' not in page.locator('#dm-detail').inner_text()


@pytest.mark.parametrize('server', [{'mode':'git','secure':True}], indirect=True)
def test_decision_review_restricted_evidence_is_hidden_by_real_authenticated_api(server, page, tmp_path):
    service, refs, comp = decision_browser_seed(tmp_path)
    page.set_extra_http_headers({'Authorization':'Bearer reviewer-token'})
    open_decision_comparison(page, server, comp)
    expect(page.locator('#dm-detail')).to_contain_text('Local observation')
    # Retain read access while revoking the writer role before submission.
    policy_path = tmp_path / 'browser-policy.json'
    policy = json.loads(policy_path.read_text())
    policy['graphs']['default']['roles']['reviewer'] = 'viewer'
    policy_path.write_text(json.dumps(policy))
    generation = service.preview()['generation']
    page.get_by_label('Review reason (required)', exact=True).fill('Viewer cannot publish')
    page.get_by_role('button', name='Record finding judgment', exact=True).click()
    expect(page.locator('#dm-notice')).to_contain_text('Forbidden')
    assert service.preview()['generation'] == generation
    page.set_extra_http_headers({'Authorization':'Bearer reader-token'})
    page.get_by_role('button', name='Refresh evidence', exact=True).click()
    expect(page.locator('#dm-message')).to_contain_text('No accessible pending')
    assert 'Local observation' not in page.locator('body').inner_html()
    response = page.request.post(f'{server}/api/decision-memory/read/review-queue', data={'comparison':comp}, headers={'Authorization':'Bearer reader-token'})
    assert response.status == 200 and response.json()['items'] == []
    assert refs['source']['id'] not in response.text()
    page.set_extra_http_headers({'Authorization':'Bearer invalid-token'})
    page.get_by_role('button', name='Refresh evidence', exact=True).click()
    expect(page.locator('#dm-message')).to_contain_text('Authentication required')
    expect(page.locator('#dm-queue button')).to_have_count(0)


@pytest.mark.parametrize('server', [{'mode': 'git'}], indirect=True, ids=['git'])
def test_decision_integrity_tombstone_clears_historical_ui(server, page, tmp_path):
    service, refs, comp = decision_browser_seed(tmp_path)
    open_decision_comparison(page, server, comp)
    expect(page.locator('#dm-detail')).to_contain_text('Local observation')
    service.brain.tombstone_node('source')
    page.get_by_role('button', name='Refresh evidence', exact=True).click()
    expect(page.locator('#dm-message')).to_contain_text('No accessible pending')
    page.get_by_label('Include acknowledged, resolved and dismissed history').check()
    expect(page.locator('#dm-queue button')).to_have_count(0)
    html = page.locator('body').inner_html()
    assert 'Local observation' not in html and 'Changed browser observation' not in html
    assert refs['source']['id'] not in html


@pytest.mark.parametrize('server', [{'mode': 'git', 'secure': True}], indirect=True, ids=['git-secure'])
def test_decision_integrity_second_source_revocation_clears_derived_ui(server, page, tmp_path):
    from graph_engine.decision_service import DecisionService
    from test_decision_impact import commit, change_source, comparison, link
    from test_decision_memory import claim, draft, files
    from test_decision_service import save
    service = DecisionService(Brain(str(tmp_path / 'brain'), mode='git'))
    service.brain.write_node(Node('Publicly authorized observation', id='source'))
    service.brain.write_node(Node('SECOND_SOURCE_SECRET qualifying evidence', id='private-aux'))
    public, = save(service, draft('source', service.source('source'), anchor='source'))
    private, = save(service, draft('source', service.source('private-aux'), anchor='private-aux'))
    c, = save(service, claim('SECOND_SOURCE_SECRET derived claim', inputs=[public, private]))
    d, = save(service, draft('decision', dict(action='Keep opt-in', rationale='SECOND_SOURCE_SECRET rationale',
        alternatives=[], context=None, revisit_checks=[]), inputs=[c]))
    link(service, 'depends_on', d, c, None)
    before = commit(service)
    change_source(service)
    comp = comparison(before, commit(service))
    page.set_extra_http_headers({'Authorization': 'Bearer reviewer-token'})
    open_decision_comparison(page, server, comp)
    expect(page.locator('#dm-detail')).to_contain_text('SECOND_SOURCE_SECRET')
    policy_path = tmp_path / 'browser-policy.json'
    policy = json.loads(policy_path.read_text())
    policy['graphs']['default']['nodes']['private-aux'] = {'read': []}
    policy_path.write_text(json.dumps(policy))
    original = files(service.brain)
    page.get_by_role('button', name='Refresh evidence', exact=True).click()
    expect(page.locator('#dm-message')).to_contain_text('No accessible pending')
    page.get_by_label('Include acknowledged, resolved and dismissed history').check()
    expect(page.locator('#dm-queue button')).to_have_count(0)
    assert 'SECOND_SOURCE_SECRET' not in page.locator('body').inner_html()
    for ref in (private, c, d):
        assert ref['id'] not in page.locator('body').inner_html()
    response = page.request.post(f'{server}/api/decision-memory/read/review-queue',
        data={'comparison': comp, 'history': True}, headers={'Authorization': 'Bearer reviewer-token'})
    assert response.status == 200 and response.json()['items'] == []
    assert private['id'] not in response.text() and 'SECOND_SOURCE_SECRET' not in response.text()
    assert files(service.brain) == original


@pytest.mark.parametrize('server', [{'mode': 'git'}], indirect=True, ids=['git'])
def test_decision_integrity_brief_keeps_selected_revision_after_later_edit(server, page, tmp_path):
    from test_decision_impact import change_source, commit
    service, refs, comp = decision_browser_seed(tmp_path)
    change_source(service, 'Later text outside the selected historical comparison')
    commit(service)
    open_decision_comparison(page, server, comp)
    expect(page.locator('#dm-detail')).to_contain_text('Changed browser observation')
    # Review detail deliberately includes the current successor alongside the
    # pinned comparison; the explicit historical brief must remain pinned.
    expect(page.locator('#dm-detail')).to_contain_text('Later text outside')
    page.get_by_role('button', name='Open decision brief', exact=True).click()
    heading = page.get_by_role('heading', name=f'Decision brief · revision {comp["after"]}', exact=True)
    expect(heading).to_be_visible()
    brief = page.locator('#dm-detail section').filter(has=heading).locator('pre')
    expect(brief).not_to_contain_text('Later text outside')
    expect(brief).to_contain_text(refs['source']['version_id'])
    assert service.inspect(refs['decision'])['state']['decision'] == 'proposed'


@pytest.mark.parametrize('server', [{'mode': 'git', 'fail_finding_index_once': True}], indirect=True, ids=['git-fault'])
def test_decision_integrity_published_finding_failure_preserves_receipt_and_history(server, page, tmp_path):
    from graph_engine.decision_memory import read_file
    service, refs, comp = decision_browser_seed(tmp_path)
    open_decision_comparison(page, server, comp)
    before = read_file(service.brain)
    page.get_by_label('Review reason (required)', exact=True).fill('Scripted browser recovery regression')
    page.get_by_role('button', name='Record finding judgment', exact=True).click()
    expect(page.locator('#dm-notice')).to_contain_text('Published locally; sync is incomplete')
    expect(page.locator('#dm-queue button')).to_have_count(1)
    after = read_file(service.brain)
    assert after['generation'] == before['generation'] + 1
    findings = [v for v in after['versions'] if v['kind'] == 'finding']
    assert len(findings) == 1 and len(after['receipts']) == len(before['receipts']) + 1
    assert len([e for e in after['events'] if e['subject']['id'] == findings[0]['id']]) == 1
    page.get_by_role('button', name='Refresh evidence', exact=True).click()
    expect(page.locator('#dm-queue button')).to_have_count(1)
    assert read_file(service.brain) == after
    page.locator('#dm-queue button').click()
    expect(page.locator('#dm-detail')).to_contain_text('Reviewed finding')


@pytest.mark.parametrize('server', [{'mode': 'git'}], indirect=True, ids=['git'])
def test_decision_integrity_two_browser_reviews_have_one_winner_without_duplicate_effects(server, page, tmp_path):
    from graph_engine.decision_memory import read_file
    service, refs, comp = decision_browser_seed(tmp_path)
    second = page.context.new_page()
    second_errors = []
    second.on('pageerror', lambda error: second_errors.append(str(error)))
    open_decision_comparison(page, server, comp)
    open_decision_comparison(second, server, comp)
    before = read_file(service.brain)
    held = []
    def release_together(route):
        held.append(route)
        if len(held) == 2:
            for item in held:
                item.continue_()
    page.context.route('**/api/decision-memory/findings', release_together)
    try:
        for i, tab in enumerate((page, second)):
            tab.get_by_label('Review reason (required)', exact=True).fill(f'Scripted concurrent browser request {i}')
            tab.get_by_role('button', name='Record finding judgment', exact=True).click()
        deadline = time.monotonic() + 5
        while len(held) < 2 and time.monotonic() < deadline:
            page.wait_for_timeout(10)
        assert len(held) == 2
        expect(page.locator('#dm-queue button')).to_have_count(1)
        expect(second.locator('#dm-queue button')).to_have_count(1)
        # Wait for both actual HTTP outcomes, never infer success from a click.
        expect(page.locator('#dm-notice')).to_contain_text(re.compile('Review recorded|Stale review'))
        expect(second.locator('#dm-notice')).to_contain_text(re.compile('Review recorded|Stale review'))
        notices = [tab.locator('#dm-notice').inner_text() for tab in (page, second)]
        assert sum('Review recorded' in text for text in notices) == 1
        assert sum('Stale review' in text for text in notices) == 1
        after = read_file(service.brain)
        assert after['generation'] == before['generation'] + 1
        assert len([v for v in after['versions'] if v['kind'] == 'finding']) == 1
        assert len(after['receipts']) == len(before['receipts']) + 1
        assert not second_errors
    finally:
        page.context.unroute('**/api/decision-memory/findings', release_together)
        second.close()


@pytest.mark.parametrize('server', [{'mode':'git'}], indirect=True)
def test_decision_review_untrusted_source_keyboard_and_narrow_layout(server, page, tmp_path):
    _, _, comp = decision_browser_seed(tmp_path, hostile=True)
    page.set_viewport_size({'width':375,'height':812})
    open_decision_comparison(page, server, comp)
    expect(page.locator('#dm-detail')).to_contain_text(HOSTILE)
    assert_inert(page)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.get_by_role('button', name='Refresh evidence', exact=True).focus()
    page.keyboard.press('Enter')
    expect(page.locator('#dm-queue button').first).to_be_visible()
    page.locator('#dm-queue button').first.focus()
    page.keyboard.press('Enter')
    expect(page.locator('#dm-detail')).to_contain_text('Changed evidence')
    # Legacy edge shortcuts must never accept/reject connections on this screen.
    assert page.request.get(f'{server}/api/graph').json()['edges'][0]['pending']
    assert_inert(page)


@pytest.mark.parametrize('server', [{'mode':'git'}], indirect=True)
def test_decision_review_loading_partial_and_missing_source_states(server, page, tmp_path):
    from test_decision_impact import link, commit, finding_envelope
    from test_decision_memory import claim
    from test_decision_service import save, context
    service, refs, comp = decision_browser_seed(tmp_path)
    other, = save(service, claim('Cycle premise', context=context(refs['profile'])))
    link(service, 'depends_on', refs['claim'], other, context(refs['profile']))
    link(service, 'depends_on', other, refs['claim'], context(refs['profile']))
    comp['after'] = commit(service)
    held = []
    page.route('**/api/decision-memory/read/review-queue', lambda route: held.append(route))
    page.goto(f'{server}/review?mode=decisions', wait_until='domcontentloaded')
    expect(page.locator('#dm-message')).to_contain_text('Loading')
    page.wait_for_function('document.querySelector("#dm-detail").textContent.includes("Loading")')
    # Deliver the real test server response after checking the loading state.
    assert held
    held.pop().continue_()
    expect(page.locator('#dm-message')).to_contain_text('No accessible pending')
    page.unroute('**/api/decision-memory/read/review-queue')
    page.get_by_label('Previous revision', exact=True).fill(comp['before'])
    page.get_by_label('Current revision', exact=True).fill(comp['after'])
    page.get_by_role('button', name='Compare revisions', exact=True).click()
    expect(page.locator('#dm-message')).to_contain_text('Partial / truncated')
    page.locator('#dm-queue button').first.click()
    expect(page.locator('#dm-detail')).to_contain_text('Partial / truncated')
    candidate = next(c for c in service.compare(comp)['candidates'] if c['delta']['subject_id'] == refs['source']['id'])
    finding, = service.record_finding(finding_envelope(service, comp, candidate), commit=False)['receipt']['refs']
    service.brain.node_path('source').unlink()
    page.get_by_role('button', name='Refresh evidence', exact=True).click()
    expect(page.locator('#dm-message')).not_to_contain_text('Loading')
    assert 'Local observation' not in page.locator('body').inner_html()
    response = page.request.post(f'{server}/api/decision-memory/read/review-detail', data={'reference':finding})
    assert response.status == 403

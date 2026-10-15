"""Real Chromium workflows and hostile-content regressions for the shipped UI."""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

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
def server(tmp_path):
    """Each workflow gets a fresh brain and a real HTTP/WebSocket server."""
    brain = Brain(str(tmp_path / "brain"), mode="local")
    brain.ensure_ready()
    brain.write_node(Node(id="hostile", text=NODE_TEXT))
    brain.write_node(Node(id="safe", text="A second idea about memory"))
    brain.write_edges([Edge(id="suggestion", source="hostile", target="safe",
                           kind="fact", predicate=HOSTILE, pending=True,
                           evidence=[{"node_id": "hostile", "text": HOSTILE}])])
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("IG_", "IDEAGRAPH_"))}
    env.update(IG_BRAIN_MODE="local", IG_BRAIN_PATH=str(brain.path),
               IDEAGRAPH_EMBEDDER="hash", PYTHONPATH=str(REPO))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (tmp_path / "server.log").open("w+") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "graph_engine.server:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            env=env, cwd=REPO, stdout=log, stderr=log)
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    with urlopen(f"{base}/api/graph", timeout=1):
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
        page = browser.new_page()
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


def test_forgetting_removes_text_from_graph_details_and_review(server, page, tmp_path):
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
    forget(brain, "forgotten", reason="synthetic browser regression", commit=False)
    # Reload the graph data while the detail pane still holds the old selection.
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

"""Real Chromium workflows and hostile-content regressions for the shipped UI."""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
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


def assert_inert(page):
    assert page.evaluate("() => window.__pwned === undefined")
    assert page.locator('img[src="x"]').count() == 0
    assert not page.evaluate(
        "() => [...document.scripts].some(el => el.textContent.includes('__pwned'))")


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

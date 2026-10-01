"""Browser-level XSS regression test (audit #57: the frontend had zero tests).

A single Playwright test that injects a hostile node text/kind through a
fixture brain and asserts the graph UI renders it inert. This is the test
the audit asked for by name: it would catch the entire XSS class (#8/#9).
Requires the playwright chromium cache (headless).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
# sys.executable = the interpreter running pytest (repo venv locally, the CI
# environment on GitHub Actions, where no .venv exists).
PY = sys.executable
PW = pytest.importorskip("playwright.sync_api")

HOSTILE = '<img src=x onerror=window.__pwned=1><script>window.__pwned=1</script>'


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server():
    """A uvicorn server on a fixture brain containing hostile content."""
    import tempfile
    tmp = tempfile.mkdtemp(prefix="ig-xss-")
    brain = Path(tmp) / "brain"
    env = dict(os.environ,
               IG_BRAIN_MODE="local",
               IG_BRAIN_PATH=str(brain),
               IDEAGRAPH_EMBEDDER="hash",
               PYTHONPATH=str(REPO))
    subprocess.run([PY, "-m", "graph_engine", "init"], env=env, check=True,
                   capture_output=True)
    # hostile node text via CLI ingest (escapes through the normal pipeline)
    subprocess.run([PY, "-m", "graph_engine", "ingest",
                    f"Benign note {HOSTILE}", "--source", "attacker"],
                   env=env, check=True, capture_output=True)
    port = _free_port()
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "graph_engine.server:app", "--port", str(port),
         "--log-level", "warning"],
        env=env, cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    # wait for readiness
    import urllib.request
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{base}/api/graph", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("server did not become ready")
    yield base
    proc.terminate()
    proc.wait(timeout=10)
    shutil.rmtree(tmp, ignore_errors=True)


def test_hostile_node_text_is_inert(server):
    """Hostile node text renders as TEXT, never executes (no __pwned global)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        import shutil as _sh
        chrome = os.environ.get("PLAYWRIGHT_CHROMIUM") or _sh.which("chromium")
        if not chrome:
            pytest.skip("no chromium available (set PLAYWRIGHT_CHROMIUM)")
        browser = pw.chromium.launch(executable_path=chrome)
        page = browser.new_page()
        page.goto(f"{server}/", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)  # d3 render
        pwned = page.evaluate("() => window.__pwned === 1")
        assert not pwned, "hostile node text executed in the graph UI"
        browser.close()


def test_hostile_text_in_graph_api_is_escaped_in_dom(server):
    """The node label must land in the DOM as text content, not markup."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        import shutil as _sh
        chrome = os.environ.get("PLAYWRIGHT_CHROMIUM") or _sh.which("chromium")
        if not chrome:
            pytest.skip("no chromium available (set PLAYWRIGHT_CHROMIUM)")
        browser = pw.chromium.launch(executable_path=chrome)
        page = browser.new_page()
        page.goto(f"{server}/", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        # no injected <img> / <script> ELEMENT from the hostile text
        injected = page.evaluate(
            "() => Array.from(document.querySelectorAll('img[src=\"x\"], "
            "script')).some(el => (el.textContent || '').includes('__pwned') "
            "|| el.getAttribute('src') === 'x')")
        assert not injected, "hostile text was parsed as markup"
        browser.close()

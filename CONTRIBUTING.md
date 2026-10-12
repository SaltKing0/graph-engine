# Contributing to GraphEngine

Thanks for helping out! Here are the key rules to keep things running smoothly.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,mcp]"   # engine + dev deps (pytest) + MCP extra
```

## Tests

All tests run deterministically with the HashEmbedder (no model download):

```bash
.venv/bin/python -m pytest tests/ -q
```

Before a PR: the full suite must be green (run `.venv/bin/python -m pytest
tests/ -q` and use the count it prints — the number grows with every feature;
with the `[st]` extra and Playwright installed everything runs, the embedder-
and browser-dependent tests skip without them). New features need tests — in particular the golden-set evals
(`graph_engine/evals.py`) and the intent/hygiene integrations.

CI covers the default install on Python 3.11–3.13 and the real embedder on
3.12. Dedicated MCP jobs on 3.11 and 3.14 test stdio transport, read/write
tools and access boundaries. A Chromium job on 3.12 tests rendering, XSS
protection, capture, review and undo against a real server. The MCP and
browser jobs use `--fail-on-skip`: missing optional dependencies cannot
silently turn those jobs green.

To run the browser suite locally:

```bash
.venv/bin/python -m pip install "playwright==1.58.0"
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest tests/test_frontend_xss.py --fail-on-skip -q
```

Document import has a separate PDF-extra gate on Python 3.11–3.13:

```bash
.venv/bin/python -m pip install -e ".[pdf]"
.venv/bin/python -m pytest tests/test_document_import.py --fail-on-skip -q
```

Core text/Markdown import needs no parser extra or model download.

Playwright's downloaded Chromium is used automatically; `PLAYWRIGHT_CHROMIUM`
can override its executable. CI downloads D3 before testing and passes its
path through `GRAPH_ENGINE_TEST_D3`; the tests check it against the shipped
HTML's SRI digest and serve it locally to avoid browser CDN requests.

The separate memory answer-quality benchmark has an offline CI smoke gate:

```bash
.venv/bin/python -m tools.memory_benchmark --smoke --check --output /tmp/memory-smoke.json
```

Graph retrieval tests: `.venv/bin/python -m pytest tests/test_graph_retrieval.py -q`.
For an opt-in graph on/off diagnostic, see [graph comparison](docs/memory-benchmarks.md#graph-expansion-comparison).

See [memory benchmarks](docs/memory-benchmarks.md) for full DE/EN comparisons.
Keep model calls and downloads opt-in; do not replace the engine golden-set
gates with this small diagnostic fixture.

Large performance measurements are opt-in and stay outside required CI:

```bash
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m tools.retrieval_benchmark --sizes 1000 10000 --samples 20 --output /tmp/retrieval-performance.json
```

See [retrieval performance](docs/retrieval-performance.md) for stage timings,
cached/uncached quality comparisons, freshness guarantees and measurement limits.
The full test suite includes small deterministic index invalidation checks.

## Code style

- **Python 3.11+** (uses `str | None` type hints). Type hints are required.
- **No external dependencies** beyond those listed in `pyproject.toml`.
- **Deterministic & stdlib-friendly:** heuristics (e.g. intent detection)
  should work without an NLP dependency and stay testable.
- Comments and docstrings are in English, like the rest of the repo.

## Architecture notes

- `graph_engine/` = engine logic, `graph_engine/web/` = frontend (d3, shipped as
  package data), `tools/` = pipeline scripts, `tests/` = pytest. `docs/` holds
  the README screenshot.
- **Brain and engine are separate:** the engine is generic and points to the
  user's brain via `IG_BRAIN_PATH`. No hardcoded personal remote or private
  data in the repo.
- Document env vars: add new options to the `README.md` (env table) and to
  `brain_engine.py` as a constant + `*_from_env()` helper.

## Release

Packaging via `pyproject.toml`, console script `ig`. Bump the version in
`pyproject.toml` and the git tag together. CI (GitHub Actions) runs on
push/PR and must be green.

Publishing is automated: `.github/workflows/release.yml` uploads to PyPI via
OIDC trusted publishing when a GitHub release is published, so no token lives
in the repo. Bump the version, add the changelog entry, tag, then publish the
release.

## Issues / PRs

- Bug report: reproduction steps + expected vs. actual behavior.
- Feature idea: open an issue to discuss first, then a PR.
- PR: small, focused scope; include tests; CI green.

## License

MIT — see `LICENSE`.

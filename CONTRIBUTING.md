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

CI runs two jobs: `test` (Python 3.11/3.12, default install) and `test-st`
(3.12 with the real embedder), so the skipped tests are covered too.

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

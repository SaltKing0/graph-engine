# Preparation validation — 18 October 2026

Status: local final full-suite run in progress. This is not final acceptance.
Base main: `a3ea0910a976e7035d7f4757b6b99dffb5c8ef49`.
Python 3.12.14 on macOS arm64; HashEmbedder, no model/provider calls or weights.
Commands run from the repository root; `.venv/bin/python` is the local isolated
runtime. Dependency setup: `/opt/homebrew/bin/python3.12 -m venv --clear .venv`
then `.venv/bin/python -m pip install -e '.[dev,mcp,pdf]'`.

| Command | Observed result |
| --- | --- |
| `.venv/bin/python -m pytest tests/test_decision_annotation_packets.py -q` | 23 passed; no skips. |
| `.venv/bin/python -m pytest tests/test_document_import.py --fail-on-skip -q` | 48 passed; one existing Starlette/httpx deprecation warning. |
| `.venv/bin/python -m pytest tests/test_mcp.py tests/test_access_namespaces.py tests/test_entities.py tests/test_fact_validity.py tests/test_graph_retrieval.py tests/test_decision_brief.py tests/test_decision_review.py --fail-on-skip -q` | 303 passed; one existing warning. |
| `.venv/bin/python -m tools.memory_benchmark --smoke --check --output /tmp/issue90-memory-smoke.json` | Exit 0; offline execution check, no answer-quality measurement. |
| `.venv/bin/python -m tools.decision_benchmark --split all --check --output /tmp/issue90-controls.json` | Exit 0; ten synthetic events, release readiness false. |
| `.venv/bin/python -m tools.decision_benchmark.annotation_packets --output /tmp/issue90-development-v1` | Exit 0; eight exposed development cases / 27 pairs; acceptance false. |
| Development-only `verify_git` command in README | 15 original development source records match Git bytes and timestamps; no labels/evaluation-source bytes opened. |
| `.venv/bin/python -m pip check` | No broken requirements. |
| `git diff --check` | Passed. |

The final full suite uses `.venv/bin/python -m pytest tests/ -q -rs` with local
loopback permissions. An initial run was deliberately interrupted after final
quote-hash hardening and additional regressions were added during execution;
it is incomplete, not a passing run. Its SIGINT teardown produced a pytest
stash KeyError; retain that log as an interrupted attempt, not a product gate.
The initial sandboxed dependency install could not resolve PyPI; the authorized
network retry succeeded. These attempts are not counted as passed validation.

Not run locally: Chromium, real semantic-model/embedder and local model-trust
strict suites (optional stacks absent); Ubuntu/Python-version CI and dependency
advisory matrix; large opt-in performance benchmarks. No production Decision
Memory interface changed, so a new full production diagnostic/walkthrough is
not required by CONTRIBUTING.md's conditional interface gate. The original
diagnostic, including its failed false-alert gate, remains unchanged. PR CI
remains required and is separate from these local results.

No final-corpus evaluation, reviewer calibration, independent annotation,
adjudication or controlled human session ran. Source-packet validity and green
software tests do not satisfy the missing human/corpus acceptance criteria.

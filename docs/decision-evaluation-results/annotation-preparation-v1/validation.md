# Preparation validation — 18 October 2026

Status: required local checks passed on repeat; the first full-run failure is
retained below. This is not independent corpus or product acceptance.
Implementation/test code is pinned by commit
`eb6faaa28dc997c685812bc49bdcddc8f5c1463d`; validation documentation is added later.
Base main: `a3ea0910a976e7035d7f4757b6b99dffb5c8ef49`.
Python 3.12.14 on macOS arm64; HashEmbedder, no model/provider calls or weights.
Commands run from the repository root; `.venv/bin/python` is the local isolated
runtime. Dependency setup: `/opt/homebrew/bin/python3.12 -m venv --clear .venv`
then `.venv/bin/python -m pip install -e '.[dev,mcp,pdf]'`.

| Command | Observed result |
| --- | --- |
| `.venv/bin/python -m pytest tests/ -q -rs` (full repeat without concurrent local tests) | **1972 passed, 11 skipped**, one existing warning; 285.43 s; exit 0. |
| `.venv/bin/python -m pytest tests/test_decision_annotation_packets.py -q` | 23 passed; no skips. |
| `.venv/bin/python -m pytest tests/test_document_import.py --fail-on-skip -q` | 48 passed; one existing Starlette/httpx deprecation warning. |
| `.venv/bin/python -m pytest tests/test_consolidation_protocol.py -k command_errors_leave_batch_unwritten -q -x` | 6 passed, 37 deselected, after the full-run cleanup failure. |
| `.venv/bin/python -m pytest tests/test_mcp.py tests/test_access_namespaces.py tests/test_entities.py tests/test_fact_validity.py tests/test_graph_retrieval.py tests/test_decision_brief.py tests/test_decision_review.py --fail-on-skip -q` | 303 passed; one existing warning. |
| `.venv/bin/python -m tools.memory_benchmark --smoke --check --output /tmp/issue90-memory-smoke.json` | Exit 0; offline execution check, no answer-quality measurement. |
| `.venv/bin/python -m tools.decision_benchmark --split all --check --output /tmp/issue90-controls.json` | Exit 0; ten synthetic events, release readiness false. |
| `.venv/bin/python -m tools.decision_benchmark.annotation_packets --output /tmp/issue90-development-v1` | Exit 0; eight exposed development cases / 27 pairs; acceptance false. |
| Development-only `verify_git` command in README | 15 original development source records match Git bytes and timestamps; no labels/evaluation-source bytes opened. |
| Stored-artifact verification command in README | Stored/compressed/decompressed hashes, handbook/contract and regenerated artifacts match. |
| Relative Markdown link and preserved-path diff audit | 18 relative document links resolve; original corpus, contract, workflow reports and production engine unchanged. |
| `.venv/bin/python -m pip check` | No broken requirements. |
| `git diff --check` | Passed. |

The full suite uses `.venv/bin/python -m pytest tests/ -q -rs` with local
loopback permissions. Its first complete final-code run reported **1 failed,
1971 passed, 11 skipped**, one warning, 299.64 seconds. The failing existing
case is `test_command_errors_leave_batch_unwritten[import sys;
sys.stderr.write("x" * 131073)-ValueError]`: cleanup at
`graph_engine/consolidation_protocol.py:142` raised
`PermissionError: [Errno 1] Operation not permitted` from `os.killpg`. The
six related cases passed in the targeted rerun. This does not erase the failed
full run; the complete repeat without concurrent local tests passed as recorded
above. This is consistent with an intermittent cleanup/process-permission
failure, but its exact cause has not been established. No
production cleanup behavior or timeout was changed for this annotation task.

An earlier run was deliberately interrupted after final
quote-hash hardening and additional regressions were added during execution;
it is incomplete, not a passing run. Its SIGINT teardown produced a pytest
stash KeyError; retain that log as an interrupted attempt, not a product gate.
The initial sandboxed dependency install could not resolve PyPI; the authorized
network retry succeeded. These attempts are not counted as passed validation.

The 11 local skips are one whole Chromium module (Playwright absent), two
optional model-cache tests, one real-embedder demo test and seven local
model-trust parameterizations (`[st]` absent). Skip reasons and the existing
Starlette/httpx warning are retained in `validation/full-passed.log`.

Not run locally: Chromium, real semantic-model/embedder and local model-trust
strict suites (optional stacks absent); Ubuntu/Python-version CI and dependency
advisory matrix; large opt-in performance benchmarks. No production Decision
Memory interface changed, so a new full production diagnostic/walkthrough is
not required by CONTRIBUTING.md's conditional interface gate. The original
diagnostic, including its failed false-alert gate, remains unchanged. PR CI
remains required and is separate from these local results.

All **14 GitHub CI checks succeeded** on implementation commit
`eb6faaa28dc997c685812bc49bdcddc8f5c1463d`: light installs on 3.11/3.12/3.13,
real semantic-model stack on 3.12, strict MCP on 3.11/3.14, Chromium on 3.12,
and seven dependency advisory profiles. Exact names/job links are saved in
`validation/ci-code-eb6faaa.json`. These remotely observed results cover the
optional stacks absent locally; they are not local reruns or independent
annotation evidence. Subsequent commits add documentation/logs only; final-head
CI status is reported in the PR/issue progress rather than recursively committed
as a new code revision.

`validation/run-identity.json` pins Python/platform/dependency versions and
implementation/test file hashes. Raw passed, failed, interrupted and targeted
logs are retained under `validation/`, with `validation/files.json` binding their
stored bytes. Source packet/rubric hashes remain separately bound by the
preparation manifests; no original evaluation artifact is replaced.

No final-corpus evaluation, reviewer calibration, independent annotation,
adjudication or controlled human session ran. Source-packet validity and green
software tests do not satisfy the missing human/corpus acceptance criteria.

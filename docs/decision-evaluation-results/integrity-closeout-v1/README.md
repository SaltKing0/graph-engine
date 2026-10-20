# Integrity engineering closeout — 20 October 2026

PR [#96](https://github.com/SaltKing0/graph-engine/pull/96) was squash-merged as
`57761ec81dace7c5fced47c3a8f1f095653d7022` after all 15 checks passed on the
authorized head `9f7027071a29ae4e0332fb3a13587adc66404a96`.
This follow-up is [PR #97](https://github.com/SaltKing0/graph-engine/pull/97),
for the engineering portion of [#92](https://github.com/SaltKing0/graph-engine/issues/92).
It changes tests and the engineering inventory, not production behavior.

## Review and focused completion

The implementing agent (Codex) reviewed the frozen contract, public operations,
test assertions, all 54 matrix mappings and all 13 N/A reasons. This is an
engineering judgment by the implementing agent, **not a human or independent
review**. The machine-readable [review](review.json) binds each cell to its
operation, preconditions, contract invariant, actual test observations, exact
engineering candidate, runtime/configuration and review disposition.

One material evidence gap was found: CLI/HTTP recovery and simultaneous-writer
tests primarily exercised proposals. Eight new parameter instances exercise
two-event review batches at sidecar/index/commit boundaries and concurrent
exact-target reviews through both adapters. They assert all-or-nothing event
publication, durable idempotency receipts, unchanged content versions, exact
review subjects and lossless conflict/refresh/retry. The two CLI concurrency
writers and final CLI replay are actual subprocesses. Fault-injected CLI
publication uses its real parser/output in process; HTTP uses ASGI requests,
not a claimed live TCP test. Existing Chromium cases exercise real TCP servers.

The inventory also explicitly maps existing regressions for absent/future
historical sidecar schemas, current/historical inherited ACL, no read repair,
source-write interruption, bounded exports and omission of incomplete units.
This expands evidence, not the numeric acceptance thresholds. The nine
categories, six surfaces, 54 cells, 41 applicable cells and 13 N/A cells remain.
The original inventory and reports remain available in Git history.

| Category | Service | CLI | HTTP | MCP | Browser | Exports |
| --- | --- | --- | --- | --- | --- | --- |
| ACL revocation, including a second source | test | test | test | stdio | Chromium | test |
| Tombstones | test | test | test | stdio | Chromium | test |
| Source edits | test | test | test | stdio | Chromium | test |
| Generic node merge | test | subprocess | N/A | N/A | N/A | N/A |
| Historical snapshots | test | test | test | stdio | Chromium | test |
| Stale reviews | test | test | test | N/A | Chromium | N/A |
| Guarded review undo | test | test | test | N/A | N/A | N/A |
| Interrupted publication and replay | boundaries | parser + replay subprocess | ASGI | N/A | Chromium | N/A |
| Concurrent proposals and reviews | persisted state | two processes | workers | N/A | two tabs | N/A |

N/A means the specific operation does not exist on that surface: no generic
node merge in HTTP/MCP/browser/exports; no typed review mutation in MCP or
exports; no typed assessment-event undo in the browser. It never exempts read
projections from ACL, tombstone, edit or history checks. Generic memory writes
and ordinary graph-edge undo are distinct operations. The review records the
source locations used to establish these exclusions. N/A cells are not passes.

## Evidence and reproduction

| Check | Observed result |
| --- | --- |
| Local full suite | **2,194 passed / 10 optional model skips**, one existing Starlette/httpx deprecation warning; 635.02 s |
| Strict reviewed matrix | **73/73 tests, 41/41 applicable cells**, 13 technical N/A, no skips; 136.81 s |
| Strict MCP/access | **303 passed**, no skips |
| Strict PDF | **48 passed**, no skips |
| Strict Chromium | **41 passed**, no skips |
| Focused inventory/review tests | **51 passed**; the eight new review cases also passed separately |
| Offline memory smoke and known Decision Memory controls | Both exit 0; no real-corpus/provider option |
| Matching code CI | **15/15 checks passed** on `a13685af0d55fac5fd9aa485f0f1196d13054eb1`, including 12 strict real-model trust tests, full supported-Python suites, MCP/PDF/Chromium/matrix and seven advisory profiles |

[Code CI](https://github.com/SaltKing0/graph-engine/actions/runs/39437297009)
and [advisories](https://github.com/SaltKing0/graph-engine/actions/runs/39437297017)
are retained with check/job URLs and raw CI output. The local optional model
skips are supplied by matching CI, not counted as local passes. No standalone
production diagnostic or large optional performance run was needed for these
test/inventory-only changes; commands.json records that omission explicitly.

The [command record](commands.json) distinguishes the clean Main baseline,
the first expanded inventory and the reviewed inventory. Saved raw pytest
phases/JUnit, code manifests, dependencies and environment identify actual
executions. The original full suite was started on `726de7d`; the later
`a13685a` changes only matrix wording, not executable source or test selectors.
The reviewed matrix and matching CI identify `a13685a` explicitly. Documentation
and evidence added afterward do not change the measured executable/matrix hash.

The first new-test run had **one test-authoring failure / seven passes**: the
test incorrectly expected a raw exception from the CLI, which actually reports
a plain-text error and exits 1. The assertion was corrected to the existing
public behavior; no runtime change was needed. The failed and corrected logs
are both retained. These authored tests are software checks, not fresh semantic
evaluation cases or evidence of reduced false alerts. The first saved-report
verification also found a report-authoring mistake: the cell-key lookup skipped
the nested `cell` object. That traceback is retained; the verifier was corrected
to validate the actual nested records, without changing any observed outcome.

Install the dependencies from CONTRIBUTING.md. Use fresh output directories:

```bash
GRAPH_ENGINE_TEST_D3=/tmp/decision-solo-d3.v7.min.js \
PLAYWRIGHT_BROWSERS_PATH=/tmp/decision-solo-playwright \
.venv/bin/python -m tools.decision_integrity --output /tmp/decision-integrity-reproduction
.venv/bin/python docs/decision-evaluation-results/integrity-closeout-v1/verify.py
```

The D3 file must match the shipped HTML's SRI digest; the browser must be the
Playwright 1.58.0 Chromium installation. Commands and logs retain the actual
local paths. CI installs these prerequisites independently. The verifier checks
saved hashes, real phase accounting, per-cell mappings, reviewed exclusions,
matching local/CI code and the preserved final-acceptance boundary. It does not
rerun the tests or turn the implementing agent into an independent reviewer.

## Acceptance boundary

The engineering candidate is a pinned software revision, **not #91's future
independently evaluated final candidate**. Final candidate and independent
sign-off fields stay null; `release_ready` stays false. All declared engineering
cells passing establishes the bounded software inventory, not exhaustive OS
crash testing, distributed writer safety or an independently approved final
contract. Relevant future candidate changes require affected-cell and required
integration revalidation, followed by real final-candidate sign-off.

The original #92 criteria and dependency on #91 are not silently removed or
marked passed by this report. Any engineering-only issue closure requires an
explicit scope disposition, with the deferred final sign-off retained in
#91/#73. No person's name, human approval, user session or independent score is
invented. #90, #91, #93 and epic #73 remain open. The recorded false-alert gate
is still **5/95 = 5.26% > 5%**; proposed dependencies still miss **3/3** positive
controls. Independent coverage remains **0/0/0**, and human benefit is unmeasured.
No reserved final data is used, no Y1 adoption template is added, no Y1 basis is
activated, no threshold changes and no release is published.

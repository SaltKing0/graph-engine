# Decision Memory v1 release-readiness assessment

**Decision: keep experimental; do not promote v1 as a validated improvement.**
No version bump, release tag or package publication is authorized by this report.
The [solo development and integrity inventory](decision-solo-development.md)
adds exposed development source review, bounded functional corrections and an
explicit engineering matrix. These do not complete independent annotation,
semantic comparison or final-candidate integrity sign-off. Historical results
and the failed 5/95 false-alert gate below remain unchanged.
This assessment follows [issue #81](https://github.com/SaltKing0/graph-engine/issues/81)
and retains the [original frozen gates](decision-memory-v1.md#evaluation-gates-frozen-before-tuning).

The complete offline workflow and deterministic production interfaces are
available, but independently adjudicated held-out evidence and a controlled user
exercise are absent. Execution correctness, a source-change diagnostic and
synthetic controls cannot establish real decision quality or review-time savings.
The [walkthrough](decision-workflow.md) explains intended users, explicit
activation, CLI/HTTP/MCP/UI flows, limitations and recovery.

## Evidence boundary and unresolved delivery

The frozen `project-v1` corpus has eight reconstructed actions and sixteen local
repository update events. All 57 eligible pairs, including 30 in the evaluation
split, remain pending. Independent real positive/negative/inconclusive coverage
is zero. Corpus/source bytes and labels are preserved unchanged; thresholds are
not adjusted after seeing results. The author has seen the evaluation design
and sources and is not a blind independent evaluator.

The source-only diagnostic uses the existing chronological allowlist, exact
800-character source slices, fixed task, k=5, 4000 estimated-token budget and
no provider/answer model. The original current-workflow baseline still produces
prepared prompts rather than decisions. A new unassessed basis-claim version
attaches an update to each declared changed dependency; production comparison
then follows the exact old accepted dependency. It does not interpret prose as
new support, opposition, withdrawal or typed conditions. Curated and proposed
inputs run independently, and proposed links stay unaccepted. This mapping is
pinned as `dm.source-change-diagnostic/1` in every raw report.

The historical #81 run executed available held-out inputs through production interfaces, but
**does not complete semantic held-out evaluation**. The frozen corpus lacks
independently reviewed structured proposals/conditions and accepted semantic
judgments. Inventing those after reading held-out labels would invalidate the
comparison. A new independently annotated and frozen successor is required;
retain the original sources, labels, reports and exposure disclosure.

Independent provenance correctness and unsupported-conclusion/comparability-error
judgments remain null. Exact reference/path correctness in a diagnostic is not a
substitute for these assessments. Missing provider measurements are absent, not
free successful answers; provider calls are zero and currency is unspecified.
Scripted review latency measures software work only. Human review-time savings
remain unmeasured.

## Required controlled user protocol before a savings claim

Freeze independently reviewed tasks and answers before recruitment. Use paired,
counterbalanced assignments of the same chronological source packets, task,
model/prompt (if any), budgets and settings to current-workflow, explicit-link
and Decision Memory conditions. Randomize order across participants and reserve
whole decision families to reduce learning transfer. Record active review time
with a documented timer/idle rule, completion, failures, abstentions and every
excluded trial with its reason. Freeze participant/trial counts, stopping rule,
exclusions and analysis before collecting results; do not select a sample size
or stop after seeing favorable times.

Independent reviewers blinded to condition score decision correctness, exact
provenance, unsupported conclusions, missed impacts and false alerts. Record
reviewer identity, disagreements, adjudication and all denominators. Compare
median active time only after checking no reduction in independent correctness
and no increase in unsupported claims. The original gate requires at least 20%
lower median active review time. No participants have performed this protocol;
there is no measured savings value or model self-rating standing in for it.

## Frozen gates and promotion

False alerts and misses must each be at most 5%; provenance and inconclusive
handling must be 100%; unsupported conclusions must be zero. Held-out coverage
requires at least 20 positive pairs, 20 negative pairs and 10 inconclusive cases,
plus all required failure modes. Every enumerated integrity scenario must pass.
The usability gate requires the controlled 20% median reduction with correctness
and unsupported-claim safeguards. The diagnostic's machine-readable gate
assessment marks missing observations unmeasured and inadequate independent
coverage failed. A partial integrity walkthrough cannot satisfy the complete
integrity gate.

The #81 implementation/diagnostic work package is closed. Remaining acceptance
is tracked in [#90](https://github.com/SaltKing0/graph-engine/issues/90) (independent
successor corpus), #91 (semantic/baseline assessment), #92 (integrity matrix)
and #93 (actual controlled user exercise), under open epic #73. Keep Decision
Memory experimental until these evidence gates pass. The
[annotation handbook](decision-annotation-handbook.md) prepares source-only
development packets and reviewer forms; no human calibration or final corpus
is established by that preparation. Paid calls and real corpus execution remain
opt-in. Release publishing is a separate action.

## Solo engineering follow-up (18 October 2026)

The [saved solo results](decision-evaluation-results/solo-development-v1/README.md)
add source-only notes for the eight already exposed development events / 27
pairs, three bounded production corrections and an explicit 54-cell inventory.
On code `4558232e197b0fb0e24dedc142ccc1910877251b`, all 41 declared applicable
cells passed through 55 actual tests; 13 cells have technical N/A reasons.
The matching CI matrix has the same code hash, and all 15 PR CI checks passed.
This closes the engineering inventory gap, not independent exhaustive/final
candidate sign-off. Human scenario sufficiency review and the final #91 candidate
remain absent. Original 5/95 false alerts and the empty proposed profile's 3/3
misses were reproduced, not replaced by scores from authored regressions.
All eight curated development contexts remain visibly truncated within budget.
No new final/evaluation-source bytes, independent labels or user sessions were
used in this follow-up; independent coverage and human benefit remain absent.

## False-alert development follow-up (18 October 2026)

The [no-op source-update report](decision-evaluation-results/false-alert-development-v1/README.md)
records mapping `dm.source-change-diagnostic/2`. The diagnostic retains the
original basis only for identical complete task-source text or pure CRLF
differences. Separately captured update sources and exact hashes remain in its
audit trace; no review is transferred or semantic comparability invented.
Changed or unavailable text still follows the conservative diagnostic path.

The twelve authored regression variants derive from a known development input;
they are not new independent cases. Full local validation passed 2,096 tests
with 10 optional model skips; all 15 code CI checks passed. The strict local
matrix passed 55 tests / 41 applicable cells. Initial sandbox failures and the
successful repeats are retained separately in the report.

**This does not resolve the historical semantic gate:** the known synthetic
diagnostic still emits 5/95 false alerts (5.26%), and the empty proposed profile
still misses 3/3 positives. All ten control update texts are nonidentical, so
none is hidden by the no-op rule. Typed source-grounded result, condition and
lineage handling remains implementation work. The eight real development input
hashes and all frozen inputs/labels/thresholds and historical results remain
unchanged. Independent coverage, semantic acceptance and human benefit remain
absent; #90–#93 and #73 stay open and Decision Memory stays experimental.

## Executed measurements (16 October 2026)

Raw reports, source/code/config manifests, prompts, errors, timings and baseline
comparisons are in [workflow-v1/](decision-evaluation-results/workflow-v1/README.md).
The completed runs used clean code commit
`1d9581416cba60aa991a9d626f563d8203f34025`; this report was added later.
All 26 rerun baseline events match the preserved #75 source-input hashes,
prepared-prompt hashes, configurations and explicit-dependency alerts. Corpus
freezes and labels were not modified. No paid provider calls, model downloads,
source fetches or research experiments ran.

| Bundle/split | Events | Attempted pairs per profile | Curated alerts | Proposed alerts | Execution errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Synthetic controls, all | 10 | 100 | 10 | 0 | 0/20 profile executions |
| Real development | 8 | 27 pending | 8 | 0 | 0/16 |
| Real evaluation | 8 | 30 pending | 8 | 0 | 0/16 |

The current-workflow baseline supplies prepared contexts only. Its impact,
answer quality and unsupported-conclusion scores remain unmeasured. On all
synthetic controls, compare the simple curated-dependency baseline with the
production source-change diagnostic:

| Metric (explicit numerator/denominator) | Dependency baseline | Production diagnostic | Empty proposed profile |
| --- | ---: | ---: | ---: |
| Precision on surfaced known pairs | 3/8 | 3/8 | null (0/0) |
| Recall | 3/3 | 3/3 | 0/3 |
| Missed impacts | 0/3 | 0/3 | 3/3 |
| False alerts, including no-impact pairs | 5/95 (5.26%) | 5/95 (5.26%) | 0/95 |
| Gold path correctness on emitted paths | 5/10 | 5/10 | null (0/0) |
| Explicit inconclusive handling | 0/1 | 1/1 | 0/1 |
| Explicit unanswerable handling | 0/1 | 1/1 | 0/1 |
| Explicit uncertainty on all attempted pairs | 0/100 | 10/100 | 0/100 |
| False abstentions on known pairs | 0/98 | 8/98 | 0/98 |

The production diagnostic exceeds the frozen 5% false-alert ceiling. It requests
review on formatting-only/no-impact cases, since it deliberately makes no
semantic interpretation of an attached update. The ten raw alerts and 5/10 gold
path correctness expose that burden even though cross-topic negatives dilute
the false-alert rate. Production labels **every** alert with unknown structured
comparability; its 1/1 uncertainty handling does not establish useful calibrated
semantic inference. No impact-precision or recall improvement over explicit
links was measured. The empty proposed profile misses all positives and
establishes no dependency-extraction quality.

All real precision/recall, missed-impact, false-alert, provenance and conclusive
judgment rates have zero adjudicated denominators and remain null. Real curated
explicit-uncertainty rates are 8/27 (development) and 8/30 (evaluation), while the
proposed rates are 0/27 and 0/30. These are output counts, not correct uncertainty
judgments. Unsupported conclusions and comparability-error rates are null in
both profiles; independent scoring is absent.

Every curated typed context was explicitly truncated: 10/10 control events,
8/8 development and 8/8 evaluation. None was empty, and all stayed within the
4000-token estimate. Real curated context included only one or two complete
qualified decision units per event. Proposed real contexts were untruncated,
but lack supplied dependencies. A budget-compliant output does not establish
adequate answer coverage. Context and findings retain their omission warnings.

### Costs and latency

The one complete imported-document walkthrough passed all seven recorded checks.
Its import took 104.23 ms, impact comparison 180.22 ms and agent context 110.39 ms
(n=1 each). Proposal and scripted-review timings are separately retained for
every transaction in the raw walkthrough. They include no actual human review.

For the eight real evaluation events, curated diagnostic p50 stage totals were:

| Stage | p50 milliseconds | Denominator |
| --- | ---: | ---: |
| Source-node capture (no document parser) | 74.49 | 8 events |
| Structured proposals | 1208.34 | 8 events |
| Scripted dependency review | 270.18 | 8 events |
| Impact comparison | 189.27 | 8 events |
| Review queue | 241.40 | 8 events |
| Agent decision context | 98.89 | 8 events |

Stage totals sum operations within one event before taking its median; batch
sizes differ with the available source packet. Full p50/p95/n for both profiles
and every split appear in `summary.json`; individual observations and raw
responses remain in the corresponding reports. Setup/Git overhead and source
payload preparation outside the instrumented operations are excluded. Runs shared
a workstation with other tests and diagnostics. These observations establish no
production latency guarantee or matched human-effort advantage. Human annotation,
review minutes, savings and measured provider currency costs remain absent.

### Integrity evidence and scope

The complete workflow passes **7/7 named checks**: old ordinary memory bytes
unchanged, exact original history, effective support not silently carried
forward, no automatic reversal, no inherited successor activation, forgotten
history unavailable and forgotten review queue empty. It exercises the shared
production Python service; actual CLI/HTTP/MCP/Chromium coverage comes from the
adapter regressions below.

The suite contains representative coverage for all **9 enumerated integrity
categories**, including these concrete regressions:

| Category | Representative test |
| --- | --- |
| ACL revocation | `test_current_revocation_and_tombstones_filter_historical_paths_before_analysis` |
| Tombstones | `test_revoked_evidence_and_tombstones_cannot_reappear_in_historical_context` |
| Source edit | `test_source_edit_versions_exact_bytes_and_marks_basis_changed` |
| Merge | `test_pinned_merge_refuses_before_any_changes` |
| Snapshot | `test_snapshot_sidecar_checks_legacy_historical_capture_lineage` |
| Stale review | `test_import_propose_review_changed_source_and_stale_review` |
| Undo | `test_undo_fails_after_dependent_review` |
| Crash/retry | `test_post_publication_failure_returns_durable_retry` |
| Two writers | `test_simultaneous_git_writers_have_clean_commits` |

These are category coverage and regression evidence, not an independently
adjudicated exhaustive scenario-by-adapter matrix. The full integrity release
gate remains unmeasured pending that sign-off. Browser and MCP regressions also
exercise restricted sources, inert hostile text, stale submissions and readonly
historical projections. Explicit authorized forensic snapshot APIs retain their
existing semantics; forgetting prevents live/context resurrection, not physical
erasure of every old Git object.

### Required and applicable optional validation

Local Python was 3.12.14. The exact commands and logs are retained under
`workflow-v1/validation/`; `$PY` below denotes
`/tmp/graph-engine-audit-env/bin/python` unless a different runtime is named.

| Gate | Exact invocation after `$PY` | Result |
| --- | --- | --- |
| Full suite | `-m pytest tests/ -q -rs` | **1982 passed, 10 skipped**, 1 warning; 259.72 s |
| Strict decision integrity/workflow | `-m pytest tests/test_decision_memory.py tests/test_decision_service.py tests/test_decision_impact.py tests/test_decision_review.py tests/test_decision_workflow.py --fail-on-skip -q` | **205 passed**, 1 warning |
| Evaluation boundary regressions | `-m pytest tests/test_decision_workflow.py tests/test_decision_benchmark.py -q` | **21 passed** |
| Strict MCP transport/access | `-m pytest tests/test_mcp.py tests/test_access_namespaces.py tests/test_entities.py tests/test_fact_validity.py tests/test_graph_retrieval.py tests/test_decision_brief.py --fail-on-skip -q` | **293 passed**, 1 warning |
| Strict Chromium | `-m pytest tests/test_frontend_xss.py --fail-on-skip -q` | **36 passed**, 1 warning |
| Strict PDF extra | `-m pytest tests/test_document_import.py --fail-on-skip -q` | **48 passed**, 1 warning |
| Strict local model trust | `-m pytest tests/test_model_trust.py --fail-on-skip -q` using `/tmp/graph-engine-issue-46-env/bin/python` | **12 passed**, no model download |
| Memory smoke | `-m tools.memory_benchmark --smoke --check --output /tmp/issue81-memory-smoke-frozen.json` | complete; exit 0 |
| Frozen baseline harness | `-m tools.decision_benchmark --split all --check --output /tmp/issue81-controls-frozen.json` | 10 events, complete; exit 0 |
| Complete workflow | `-m examples.decision_workflow --output /tmp/issue81-workflow-frozen.json` | 7/7 named checks; exit 0 |
| Production diagnostic | `-m tools.decision_benchmark.production --split all --output /tmp/issue81-production-controls.json` | 10 events; exit 0; release false |
| Project diagnostic | same module with `--real-corpus --split development` / `--split evaluation`, separate outputs | 8 events each; both exit 0; release false |
| Source verification | `load_bundle` then `verify_git` on `project-v1` against `.` | 27 source records verified against local Git objects |
| Advisory matrix | seven clean dry-run profiles, then `tools.dependency_audit --pip-report` | core/dev/st/mcp/pdf/legacy on 3.12 and core on 3.14: **0 advisories**, all exit 0 |

Browser/full runs set `GRAPH_ENGINE_TEST_D3=/tmp/graph-engine-d3.v7.min.js`
and `PLAYWRIGHT_BROWSERS_PATH=/tmp/graph-engine-playwright`, using existing
Chromium and the integrity-checked local D3 file. Model trust sets
`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` and generates tiny local fixtures.
The one reported warning is the existing Starlette/httpx deprecation.

The light environment's ten skips are explicitly recorded: two optional model
cache tests, the real-embedder demo test and seven model-trust parameterizations.
The separate strict real-stack model-trust suite passed, but full real-model
embedding/demo coverage was not run. No weights were downloaded. The Linux CI
matrix, other supported interpreter test jobs and large optional performance
benchmarks were not run locally. Advisory resolutions describe this macOS
platform/interpreter matrix, not Ubuntu's transitive resolution or all possible
installations. All corresponding CI gates remain required; local results do not
stand in for pending PR CI.

An initial sandboxed full-suite attempt recorded 1941 passes, 10 skips and 36
browser setup errors because loopback servers were denied. The unrestricted
rerun passed (1981 passes with four new workflow tests); the final committed-code
run above includes the fifth gold-isolation regression and passed 1982 tests.
The failed attempt is retained in `validation/full.log`, not counted as successful
coverage. Initial per-record diagnostics were explicitly interrupted to batch
proposals; their incomplete checkpoints and absent transient artifacts are
preserved/disclosed in the raw-results index. Completed measurements use only
the fixed batched commit. No thresholds or labels changed during that correction.

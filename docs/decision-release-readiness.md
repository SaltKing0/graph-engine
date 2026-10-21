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

## Project closeout (21 October 2026)

The project owner chose to conclude the current work as an **experimental
prototype** and defer independent validation. This closes the implementation
delivery scope; original overall acceptance remains incomplete.

| Issue | Current disposition | Acceptance still missing |
| --- | --- | --- |
| [#90](https://github.com/SaltKing0/graph-engine/issues/90) | Closed as `not_planned`; successor-corpus validation deferred | Calibration, separate qualified judgments/adjudication, fresh protected final families, reviewed runtime inputs and freeze/coverage sign-off |
| [#91](https://github.com/SaltKing0/graph-engine/issues/91) | Closed as `not_planned`; semantic and final integrity acceptance deferred | Fixed-candidate matched comparisons, independent scoring and exact-candidate integrity revalidation/sign-off |
| [#92](https://github.com/SaltKing0/graph-engine/issues/92) | Closed as delivered engineering work | Original criteria **3, 6, 8 and 10** remain unmet/partial, retained in #91/#73 and now deferred |
| [#93](https://github.com/SaltKing0/graph-engine/issues/93) | Closed as `not_planned`; controlled human study deferred | Actual participant sessions, independent outcome review and the frozen benefit criterion |
| [#73](https://github.com/SaltKing0/graph-engine/issues/73) | Closed as `completed` for the revised prototype-delivery scope | Original independent overall acceptance is not achieved |

PRs #94–#97 are merged. The last engineering merge, [#97](https://github.com/SaltKing0/graph-engine/pull/97),
is `93bcbde3047bea3879cb5975d914261219842425`. Its reviewed head
`0487660678374140c121e6f16ba09069d9911a44` passed 15/15 CI checks. The
[saved engineering report](decision-evaluation-results/integrity-closeout-v1/README.md)
records **73/73 matrix tests, 41/41 applicable cells, 13 technical N/A** and
**2,194 local passes / 10 optional model skips**, with matching CI model
coverage. These are historical engineering measurements, not new runs or
independent final-candidate sign-off.

Independent final coverage remains **0 positive pairs / 0 negative pairs /
0 inconclusive cases**, below the unchanged **20/20/10** minimum. The historical
synthetic source-change diagnostic retains **5/95 false alerts (5.26% >5%)**;
its empty proposed profile misses **3/3** positives. Real semantic quality,
final integrity acceptance and human review-time benefit remain unmeasured.
Issue closure does not change `release_ready=false` or turn missing evidence
into a passed gate. No Y1 activation, version bump, release or publication is
part of this disposition.

If acceptance resumes, reopen or explicitly replace the deferred work in this
order: **#90 → #91 (semantic plus retained final integrity acceptance) → #93 →
overall acceptance**. Preserve original thresholds, sources, labels, freezes,
results and exposure disclosures. Use fresh independently reviewed final cases,
a frozen candidate/protocol, actual final sign-off and real participant sessions
before claiming validated benefit. The original requirements below remain the
conditions for promotion; they are not scheduled work in the closed prototype scope.

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

The #81 implementation/diagnostic and #92 engineering work packages are closed.
The unmet acceptance requirements are retained in the deferred #90, #91 and #93
issues and the reduced-scope #73 closeout above. Final integrity acceptance,
including original #92 criteria 3, 6, 8 and 10, belongs with #91 if work resumes.
Keep Decision Memory experimental until these evidence gates pass. The
[annotation handbook](decision-annotation-handbook.md) prepares source-only
development packets and reviewer forms; no human calibration or final corpus
is established by that preparation. Paid calls and real corpus execution remain
opt-in. Release publishing is a separate action.

The dated progress entries below retain their historical status statements and
measurements. References there to open issues, draft PRs or a pending scope
decision describe the state at the time; the
[21 October closeout](#project-closeout-21-october-2026) supersedes those delivery
statuses. Versioned result directories and frozen evaluation inputs are unchanged.

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
none is hidden by the no-op rule. Authoritative semantic integration of typed
source-grounded results, conditions and lineage remains implementation work.
The eight real development input
hashes and all frozen inputs/labels/thresholds and historical results remain
unchanged. Independent coverage, semantic acceptance and human benefit remain
absent; #90–#93 and #73 stay open and Decision Memory stays experimental.

## Structured observation proposals (18 October 2026)

The [source-bound observation guide](decision-source-observations.md) and
[saved capture evidence](decision-evaluation-results/false-alert-development-v1/structured-v1/README.md)
add 24 distinct source-bound draft facts from 30 known development sources.
The complete replay covers five synthetic development events and eight project
development events, with identical original input hashes and normalized alerts.
Thirteen proposed profiles, 142 repeated evidence proposals and 992 replayed
source versions remain separate from the 24 distinct facts and from independent
coverage. There are no new observation-review events; every new profile and
evidence record remains proposed, and evidence stays unassessed.

Literal structural checks distinguish declared condition changes, equal or
different values under matching declared units, shared recorded roots and
availability statements. Missing units, environments, root identity or semantic
scope completeness remain unresolved. The official comparator returns unknown
for every proposed profile. Transcriptions never enter the original diagnostic
inputs and never filter alerts. The 5/95 false-alert gate remains failed, the
empty proposed dependency profile still misses 3/3 positives, and independent
semantic acceptance and human benefit remain unmeasured.

Full local validation on clean code `016c52c5e6ab9ffd7c04a09ae870bc15da24e6f5`
passed 2,126 tests with 10 optional model skips. Focused tests passed 61; the
strict engineering matrix passed 55 tests / 41 applicable cells; all 15 code
CI checks passed. Raw commands, source-version hashes, exact citations,
prototype failures and preserved-warning comparisons are in the saved report.
This completes bounded development capture/checking only. Explicit review and
authoritative integration, independent final comparison and actual user study
remain open under #90–#93 and #73. Decision Memory remains experimental.

## Developer-reviewed source preparation (18 October 2026)

The [reviewed development evidence](decision-evaluation-results/false-alert-development-v1/reviewed-v1/README.md)
adds an explicit implementing-agent field/completeness review for ten already
exposed fictional source documents. Exact source/fact hashes and spans, metric
units and local condition/measurement namespaces bind this trusted input.
Twelve existing JSON means are checked by full field paths and coordinates,
n=2/n=10 and original precision; missing units/environment/roots stay unknown.
Those incomplete project facts receive no runtime review. The
[guide](decision-source-observations.md#explicit-developer-field-review-and-source-preparation)
explains the boundary between this review configuration and independent gold.

On clean code `b597bc65f6c85057e570060edc93b5b3df0f17fa`, all 26 profile
executions for the same 13 known development cases completed without errors
and preserved original input hashes. Curated raw alerts change from 13 to 10:
5 to 2 in the five synthetic development events and 8 unchanged project alerts.
Verified immaterial updates retain the old basis before impact analysis; no
emitted warning is filtered. Changed values, withdrawals, unknown fields and
incomplete reviews retain the original path. All update sources, old references
and authorized version/review journals survive. No human/independent acceptance,
semantic-profile review, source-root independence or support sufficiency is
invented. All 13 curated and 5 proposed contexts remain visibly truncated while
within budget; execution completeness does not establish context coverage.

Full local validation passed 2,164 tests with 10 optional model skips and one existing warning (850.07 seconds). Focused tests passed 99; strict matrix passed 55 tests / 41
applicable cells, with 13 technical N/A and no skipped/deselected matrix cases.
All 15 code CI checks passed. Four historical evidence verifiers pass at their
original report head `fb2fff2`; the new verifier checks the new candidate,
source serialization, 2,302 journal versions, 77 original scripted dependency
events and preservation of historical bytes separately. The deliberately
interrupted initial candidate measurement and verifier corrections remain
visible in the saved evidence.

**No independent gate is passed by this development replay.** The ordinary
unreviewed diagnostic still reproduces 5/95 false alerts (5.26%) and the empty
proposed profile's 3/3 misses. Original sources, labels, frozen thresholds and
historical results remain unchanged. Independent final coverage stays 0/0/0;
matched completed agent decisions, independent final scoring, actual users and
measured benefit remain absent. No additional acceptance checkbox is completed;
#90–#93 and #73 stay open and Decision Memory stays experimental.

## Source audit of the known withdrawal (18 October 2026)

The [withdrawal audit](decision-evaluation-results/false-alert-development-v1/withdrawal-v1/README.md)
checks one already exposed fictional development event. Y1's declared recall
0.8 satisfies the stated >=0.7 fraction condition under the explicit common
context, and Y1 is declared still available. This is source-declared predicate
satisfaction, not independently reviewed measurement validity or accepted
runtime sufficiency. No statistical threshold, independent run or reviewer is
invented. X1's withdrawal still changes the old aggregate basis, and the
normative contract requires a candidate explaining loss plus remaining support.
The original runtime's one curated warning remains; no alert is suppressed.

Both original dependency profiles replay without errors and preserve the old
input hash/normalized alerts. Journals retain 71 versions and 10 scripted wiring
events; both contexts remain truncated within the unchanged budget/k. The
source assessment and 13 adversarial checks pass, as do 99 focused regressions
and five historical evidence verifiers at their appropriate report heads.
Runtime/tools/tests/CI/frozen data are byte-unchanged; this is a documentation
and source-audit delivery. Prior full-suite/matrix counts remain historical,
not newly executed measurements. Current semantic scores and human benefit
remain null; the historical 5/95 failure and 0/0/0 independent coverage persist.
No additional acceptance checkbox is completed. The next step identified by this
historical audit was explicit X1/Y1 support
and availability modeling with review of the changed basis; independent-run
credit requires human review of actual execution/dataset provenance.

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

## Separate support paths and remaining-basis versioning

The known fictional withdrawal case now has an explicit opt-in developer
configuration with separate X1/Y1 evidence and support relationships, exact
citations and a shared original document identity. The later source update
withdraws X1. The actual comparison preserves one `support_withdrawn` /
`basis_changed` candidate explaining X1 removed and Y1 remaining. Source-declared
run labels do not become independently established measurement roots.

A successor claim records only Y1 plus the availability update as new provenance
inputs. It starts unassessed/proposed with a proposed new support endpoint;
fresh scripted developer events assess only the declared 0.8 >=0.7 fraction
rule and five explicit conditions. Old versions, endpoints and reviews remain
exact; the old aggregate assessment is stale/inconclusive. After a fresh service
session the new scoped basis is supported. The successor decision and dependency
remain proposals, the old decision explicitly needs investigation, and the
confirmed/acknowledged finding remains unresolved and visibly stale after the
basis successor; resolution would need a new comparison/review. No human or independent
acceptance, run, participant or benefit is inferred.

[Versioned evidence, exact commands and reproduction](decision-evaluation-results/false-alert-development-v1/support-paths-v1/README.md)
separate the source-level assessment, software checks and missing external
acceptance. This remodeled known event is not a new independent case or an
updated false-alert score. The original standard diagnostic still fails
5/95 (5.26%) >5%, and the empty proposed profile misses 3/3 positives. All frozen
sources, labels, thresholds, earlier reports and review decisions are retained.
Independent final coverage remains 0/0/0 and product benefit remains unmeasured.
Keep #90–#93 and #73 open, the PR Draft and Decision Memory experimental;
no merge or release. Actual execution/dataset artifacts, separate reviewers and
a separately controlled final corpus/freeze remain required for acceptance.

Software validation of frozen implementation `1bddddc`: full local suite
**2,182 passed / 10 optional model skips / 1 existing Starlette warning**;
117 focused checks; strict matrix **55 tests / 41 of 41 applicable cells**,
13 technical N/A. All 15 CI checks passed, including real-model/local-trust
and seven advisory profiles. The source/path run and all 13 known development
replays complete without errors; original normalized alerts, scores, gates and
thresholds match the previous evidence. Six historical verifiers pass at their
original heads. Later audit metadata retains documentation-only dirty flags;
implementation fingerprints remain unchanged. These are bounded software and
source-consistency checks, not independent semantic or product-benefit proof.

## Source review of the proposed Y1 basis

The [Y1 source-consistency review](decision-evaluation-results/false-alert-development-v1/y1-basis-review-v1/README.md)
finds no required correction to the recorded source-qualified claim within the
known fictional rule: declared recall 0.8 >=0.7 fraction, explicit same conditions
and Y1 availability at the fictional event. Unit/context resolution is clearly
distinguished from direct measurements. Real execution/dataset provenance,
measurement independence, statistical sufficiency and general decision validity
remain unestablished. This implementing-agent document is not independent
annotation, human acceptance, a runtime outcome input or measured product benefit.

Existing content/review events remain unchanged. No new engine review, decision
activation or finding resolution is performed; the proposed successor and stale,
unresolved finding remain visible. Runtime/tools/tests/CI/frozen data are
byte-unchanged, so the earlier full-suite/matrix counts remain historical;
fresh focused checks and source/journal/reference verification are recorded
separately. The 5/95 (5.26%) >5% failure, empty-profile 3/3 misses, independent
0/0/0 coverage and missing human/final-candidate/user evidence remain open.
No additional checkbox is completed; keep #90–#93/#73 open and the PR Draft.
No merge, release or threshold change.

## Fresh Y1 comparison and finding freshness correction

The [same-case development replay](decision-evaluation-results/false-alert-development-v1/y1-refresh-v1/README.md)
now retains an offline-restorable Git bundle and maps original/replayed content
and review semantics explicitly. Fresh initial-to-Y1 and post-withdrawal
comparisons yield three and two raw candidates; a Y1 self-comparison yields zero.
Y1 remains available, but its old support endpoint is stale; its new support is
on the successor claim. Unknown-comparability/proposed-preview qualifications
remain visible, without inferring independent support or accepting a decision.

A bug omitted successor-head review events/inputs from candidate freshness
pinning, causing the writer to reject a newly regenerated finding. The fix
includes those recorded inputs within the existing bounds; stale-candidate,
source, review, support and permission guards remain enforced. Four regressions
reproduce the defect on the old snapshot and pass after correction. An explicit
synthetic finding review now appends a fresh **open** finding version, preserving
all prior versions/events. The old decision needs investigation; successor
decision/dependency stay proposed. No activation, resolution, independent
acceptance or semantic/product-benefit claim is made. The original 5/95 (5.26%)
>5% failure, 3/3 proposed-profile misses, 0/0/0 independent coverage and missing
human/final-candidate/user evidence remain open. No threshold or frozen input,
label, historical result or review is replaced. Keep #90–#93/#73 open and #96
Draft. No merge or release.

Measured frozen fix `5b53693`: **2,186 local tests passed / 10 optional model
skips / 1 existing Starlette warning**; **182 focused tests**; strict matrix
**55 tests / 41 applicable cells**, 13 technical N/A. All 15 fix CI checks pass,
including model/trust and seven advisory profiles. Eight historical verifiers
pass at their original snapshots. All 13 known development input hashes and
normalized alert outputs, and the original scores/gates/thresholds, match the
prior report. Full commands/logs and the restored-bundle proof remain separate
from independent acceptance and product benefit.

## Remaining Y1 candidates reviewed without adoption

The [claim-change and proposed-dependency review](decision-evaluation-results/false-alert-development-v1/y1-candidate-review-v1/README.md)
restores the prior exact state and records two diagnostic dispositions through
the public API: claim change **confirmed/open**, proposed dependency
**inconclusive/workflow null**. Both remain pending, alongside the unchanged open
withdrawal finding. The 16-version/17-event prefix is unchanged; the final journal
has 18 versions / 19 events. All three candidates are still emitted with their
original IDs and qualifications. The proposal's context is source-consistent;
this does not accept the dependency, activate the decision or resolve the old
investigation. No engine, tool, test, CI or threshold change was required.

Fresh checks: 32 focused tests pass with one existing Starlette warning; exact
source/version review, prior evidence verification at its original commit and
the new offline restore/idempotency/history checks are recorded. Full local
2,186/10-skip and 41/41-cell matrix results above remain historical, not new runs.
The standard 5/95 (5.26%) false-alert gate still fails; independent final coverage
is 0/0/0. No new acceptance checkbox is completed. Independent annotation/final
evaluation, real provenance, final sign-off and actual user sessions/product
benefit remain absent; successor adoption/activation remain open. PR #96 remains
Draft and Decision Memory experimental. No merge or release.

## Conditional Y1 adoption remains unsigned

The [unsigned Y1 adoption decision](decision-evaluation-results/false-alert-development-v1/y1-adoption-plan-v1/README.md)
is concrete preparation for the exact known development successor, not an
approval or activation. It identifies current/proposed versions, source hashes,
event heads, three unresolved findings, separate future dependency/successor
reviews and the required atomic lifecycle pair. The old investigation and all
reviews remain historical; no new old-version conclusion or automatic finding
resolution is proposed. All signers and actual reviewer outcomes remain null.

Read-only restoration reproduces the exact 18 versions / 19 events and the
10-delta/3-candidate comparison without writes or dry runs. Five existing
lifecycle regressions pass in disposable engineering fixtures; that is not
execution of this plan. Independent final coverage remains 0/0/0, the historical
5/95 (5.26%) false-alert gate still fails, and the empty proposed profile misses
3/3 positives. No new acceptance checkbox is completed. Existing sources, labels,
thresholds, results and reviews remain unchanged. Independent feature acceptance,
real provenance/final evaluation, user sessions/product benefit and a later
explicit authorization to activate are still open. PR #96 stays Draft and the
feature experimental. No merge or release.

## Source/protocol review of the unsigned Y1 choice

The [reviewed unsigned preparation version 2](decision-evaluation-results/false-alert-development-v1/y1-adoption-review-v1/README.md)
retains the original plan and all existing reviews, while making fictional-event
time, inherited unit/context interpretation and required positive future review
outcomes explicit. Required outcome enums are protocol conditions, not measured
or invented reviewer judgments. Actual outcomes, event IDs, scope confirmation,
authorization and owner assignments remain unfilled; execution remains forbidden.
Real present-world availability and execution/dataset validity remain unknown.

Fresh source/identity reconstruction preserves the exact 18 versions / 19 events
and three unresolved findings. Five existing lifecycle regressions pass and 11
malformed in-memory plan variants are rejected; no new cases or independent
scores are created. The original artifact verifier passes at its original head.
No engine/tool/test/dependency change or threshold adjustment was required.
The initial browser/matrix CI setup failed because `ubuntu-latest` selected
Ubuntu 26.04, unsupported by Playwright 1.58.0; only those two jobs are pinned
to compatible Ubuntu 24.04, retaining all checks and skip-failure guards.
The historical false-alert gate still fails 5/95 (5.26%) >5%; proposed profile
misses 3/3 positives and independent coverage remains 0/0/0. No acceptance checkbox
is added. Independent annotation/final evaluation, actual provenance, final
sign-off and users/product benefit remain absent. Activation, resolution, merge
and release remain unperformed; PR #96 stays Draft and the feature experimental.

## Integrity engineering closeout (20 October 2026)

[#96](https://github.com/SaltKing0/graph-engine/pull/96) was merged after all
15 checks passed. The [engineering closeout](decision-evaluation-results/integrity-closeout-v1/README.md)
for #92 reviews all 54 matrix cells and 13 technical exclusions, and closes a
specific evidence gap for review-batch publication/retry and concurrent reviews
on CLI/HTTP. The reviewed inventory executes **73 tests / 41 applicable cells**,
all passed locally and in matching CI; all 15 code CI checks are green.

This is a reviewed bounded engineering inventory by Codex, the implementing
agent. It is not a human review, an independent sign-off, or #91's future final
candidate. The matrix runner deliberately retains `final_candidate=null`,
`independent_sign_off=null`, the complete final integrity gate unmeasured and
`release_ready=false`. Relevant later candidate changes require revalidation
and actual final sign-off. An engineering-only closure of #92 requires an
explicit scope disposition while carrying that final obligation in #91/#73;
this report does not silently waive or satisfy the original criteria.

#90, #91, #93 and epic #73 remain open. Independent coverage remains 0/0/0,
false alerts remain 5/95 (5.26%, above 5%), the empty proposed profile still
misses 3/3 positives, and actual user benefit remains unmeasured. No reserved
final cases, changed thresholds, Y1 activation, release or package publication
are part of this closeout. Historical results and review decisions are retained.

# False-alert development follow-up — 18 October 2026

**The historical semantic false-alert gate is still failed: 5/95 (5.26%) > 5%.**
This is a bounded engineering correction and diagnosis for [#91](https://github.com/SaltKing0/graph-engine/issues/91), under open epic #73. [Draft PR #96](https://github.com/SaltKing0/graph-engine/pull/96) must not be described as resolving that gate. No additional acceptance checkbox is completed; independent semantic quality and product benefit remain unavailable. No merge or release is included.

## Scope and dependencies

Main started at `5d42d063a8b7076fec82dbcdd7fb3f806a0d87cd`, after #94 and #95 merged. The existing clean working copy was reused on `codex/issue-91-false-alert-development`; other worktrees were untouched. No applicable AGENTS.md was found. CONTRIBUTING.md and issues #91/#73/#90, the existing diagnostic/source-only reports, current Main and open PRs were checked.

#90 remains incomplete: no independently reviewed structured runtime proposals/conditions, calibrated reviewers, controlled successor final partition or adjudicated final coverage is available. Closed earlier implementation issues and green CI do not establish those inputs. The implementing agent has seen the original synthetic control definitions and historical results; the original evaluation controls are already exposed. Only the known development input was mutated to implement the fix. Repeating all known synthetic controls below is a disclosed historical regression, not a fresh final evaluation. No reserved successor data or new real evaluation sources/labels were opened. The real development run uses the existing source-only allowlist and no label loader.

## Cause and implemented correction

The old `dm.source-change-diagnostic/1` attaches every update as additional provenance to a new declared basis-claim version. That turns even identical source text or a pure CRLF change into a content/provenance delta with an accepted dependency path. The adapter creates a review candidate before it has any new semantic information.

Mapping `dm.source-change-diagnostic/2` adds only `complete-task-text-exact-or-crlf/1`: assemble the complete chronological task-source chunks in numeric order, validate their IDs and slice lengths, and compare exact text hashes plus CRLF-normalized hashes. Missing/malformed inputs remain unavailable; changes outside this narrowly declared rule remain changed. Completeness here refers to the task-input contract supplied by the source-only loader, not proof against an upstream source that was itself incomplete.

When equality is proved, the original claim and accepted dependency remain unchanged. The update still gets its own captured, proposed source records. The report retains both source IDs, exact chunk IDs, raw and normalized hashes, new captured references and retained basis references. No successor assessment or review is created or inherited. Impact/context/queue execution still runs. There is no ranking change, label access, automatic decision reversal, general whitespace folding, interpretation of a “formatting-only” sentence, or warning filter after comparison. The shared production engine/interfaces are unchanged.

## Why the five historical false alerts remain

All ten original control update texts are byte-distinct from their basis texts, including under CRLF normalization. The historical false alerts therefore cannot honestly be fixed by the new equality rule. Their original labels are preserved.

| Known case | Diagnosis and remaining implementation work |
| --- | --- |
| `changed-conditions` (development) | Contrary values under W2/H2 rather than W/H need source-grounded typed scope input. A topic attachment with null context cannot prove disjointness. The adapter still reports unknown comparability. |
| `time-only` (development) | A new observation repeats a value and conditions. It needs typed result/condition comparison; a generic provenance attachment alone cannot establish no changed basis. |
| `duplicate-citation` (development) | The prose identifies the same measurement lineage. Structured source/root-lineage capture must preserve the copy without inventing independent support. |
| `unrelated` and `no-review` (historical, already exposed evaluation controls) | Their update text describes a formatting change rather than supplying an identical replacement source. They were not used to design a semantic suppression rule. Treating the description itself as proof would hide an unverified change. |

A fixture-ID allowlist, regex matching those narratives, threshold change, removal of hard cases, dropping unknown-scope warnings or scoring these authored tests as new gold would not solve #91. The next technical step is source-grounded structured observation/proposal capture for the known development cases, then a generic typed result/scope/lineage comparison with positive and unknown controls. This PR does not claim to implement that remaining semantic path. Independent review is needed before any final acceptance, not to reclassify these development cases as held-out.

## Regression evidence

The first two authored execution regressions reproduced spurious review alerts for identical/CRLF-only text before correction. Four additional variants failed because the new audit field was absent; their conservative alert behavior already existed. The initial log records **6 failures**, not six newly discovered semantic errors. All regressions derive from the already exposed `comparable` development input; none is an independent new case.

The final twelve regressions cover identical/CRLF updates, a CRLF crossing an 800-character boundary, a change after chunk zero, missing/duplicate/gapped/short/empty chunks, changed metrics, negation, meaningful spaces and an unverified formatting-only narrative. The combined source-update/workflow/solo suite also checks retained original basis, separate proposed source provenance, no oracle runtime inputs and visible incomplete/error accounting.

## Validation

Exact argv, elapsed times, environment and exit codes are retained in [commands.json](commands.json) and the logs. [manifest.json](manifest.json) commits saved and decompressed hashes. The measured clean code commit is `f506e6694bbc9a9c19390c2e7c33f60216b8cf6c`; evidence files were added afterward. The initial orchestration error refused to overwrite an existing log and was resolved by using a new log path. The first strict matrix had **47 passes / 8 setup errors, 34/41 cells**, because the sandbox denied localhost bind. The first full-suite attempt recorded **1121 passed / 3 optional skips / 41 localhost setup errors**, then was interrupted (exit 2) after that environmental blocker was identified. Both are retained separately and are not claimed as successful checks. Full suite and matrix were restarted with localhost test-server permission, using new output paths.

| Check | Actual result |
| --- | --- |
| Full local suite, localhost allowed | **2096 passed, 10 skipped, 1 warning in 552.12s (0:09:12)** |
| Focused source-update/workflow/solo suite | **31 passed** |
| Strict engineering matrix, localhost allowed | **55 passed**, no skips, 41/41 applicable cells; 13 technical N/A |
| Frozen memory / Decision Memory controls | Exit 0; execution integrity only |
| Imported-document workflow | Exit 0; **7/7** checks |
| Known synthetic production controls | Exit 0; historical false-alert gate remains **fail**, 5/95 |
| Source-only real development | Exit 0; 8 events / 27 pairs per profile; no independent scoring |
| Preserved review and solo evidence verifiers | Both exit 0 |
| pip check / whitespace | Both exit 0 |


The [raw synthetic production report](production-controls.json.gz) invocation exits 0 for execution integrity while its machine-readable semantic false-alert assessment remains **fail**. Curated: 100 attempted/completed pairs, zero errors, 10 raw alerts, false alerts 5/95, missed impacts 0/3, precision 3/8, path correctness 5/10, false discovery fraction 5/10, false abstention 8/98, explicit inconclusive handling 1/1. All ten updates remain `changed`. The empty proposed profile still misses 3/3 positives; its zero false alerts is not a successful workflow. The preserved explicit-dependency baseline matches the original source inputs, prepared prompts, configuration and alerts exactly.

The [raw source-only development run](solo-development.json.gz) keeps all eight events / 27 pairs per profile. Its implementing-agent source notes remain inconclusive, are not scored and never enter runtime. Eight curated alerts and eight visibly truncated contexts are observations rather than semantic correctness. No independent score, actual human review time, participant session or product benefit is measured. Independent final coverage remains 0/0/0. The original frozen 5% ceiling, miss/provenance/uncertainty gates and all original data/labels/results remain unchanged.

All **15 CI checks passed on measured code f506e66**: [CI](https://github.com/SaltKing0/graph-engine/actions/runs/39134715363), [seven dependency audit profiles](https://github.com/SaltKing0/graph-engine/actions/runs/39134715381). The exact head and checks are retained in `ci-checks.json`; jobs and steps are in `ci-run.json`. Final documentation-only changes must retain the same runtime/tool/test code.

No new held-out comparison, paid provider, opt-in model experiment, optional large performance experiment, independent reviewer sign-off or user study was run. Matching CI supplies supported Python/Linux and strict real-model coverage; local optional skips are reported separately. Code checks and the engineering matrix cannot complete #90/#91/#92/#93 or establish product usefulness.

## Reproduction

Install the extras and Chromium described in CONTRIBUTING.md. Use new output paths and the exact commands in [commands.json](commands.json); raw UUIDs/Git timestamps and timings may differ, while source hashes, normalized paths, classification and accounting remain reproducible. `run_checks.py` documents the local orchestration. Verify preserved evidence and protected-path consistency with:

```sh
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/verify_evidence.py
```

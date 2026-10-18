# Solo development results v1 — 18 October 2026

**Engineering delivery only; no independent acceptance or validated product benefit.**
[Draft PR #95](https://github.com/SaltKing0/graph-engine/pull/95) contains the solo
work authorized for #90 and the independently possible parts of #91/#92 under
#73. It stacks on [draft PR #94](https://github.com/SaltKing0/graph-engine/pull/94),
commit `1a4d282ab46ab3141ebe933b24d9cee3fac2504e`. Main at start was
`a3ea0910a976e7035d7f4757b6b99dffb5c8ef49`. No applicable AGENTS.md was found;
CONTRIBUTING.md, current issues, main and open PRs were checked. Work uses isolated
branch `codex/decision-memory-solo-development`; other local work remains untouched.

## Delivered development work

The [guide](../../decision-solo-development.md) explains the six-stage failure
diagnosis, three production corrections and all 54 inventory cells. Regressions
cover claim-only CRLF false alerts, lost reconvergent paths and the UI brief's
incorrect HEAD selection. Original sources, labels, freezes, thresholds and old
reports are unchanged. Historical versions/reviews, permissions and the existing
200-reference persistence limit are retained; bounded path omission is explicit.

[source-notes.json](source-notes.json) records all eight previously exposed
development events / 27 eligible pairs / 54 exact UTF-8 quote references. These
are one implementing agent's source notes, not human calibration or independent
gold. All working outcomes remain inconclusive because reviewed conditions and
accepted historical semantic paths are missing. The source-only runtime never
receives these expected judgments, rationales or paths. Its eight input hashes
match the preserved #75 development baseline exactly.

The [saved solo run](solo-development.json.gz) executed both profiles for all
eight events, 27 pairs per profile: no execution errors, no incomplete impact
traversal/queue, all contexts within the 4000 estimated-token budget. Curated
outputs contain eight raw alerts and **8/8 truncated contexts**; the empty
proposed profile contains zero alerts and 0/8 truncated contexts. Completeness
of traversal and token-budget compliance do not establish adequate context or
semantic quality. No semantic scores are computed from these notes. Provider
calls are zero; human calibration, quality and review time remain null.

The unchanged synthetic production diagnostic was rerun: **5/95 false alerts
(5.26%) > 5%**, curated precision 3/8, recall 3/3 and path correctness 5/10.
The empty proposed profile misses 3/3 positives and has 0/1 explicit inconclusive
handling. These failures are not repaired by replacing their scores with the new
authored regressions. Raw outputs and both profile gate assessments remain in
[production-controls.json.gz](production-controls.json.gz).

## Validation and exact scope

The measured engineering code is clean commit
`4558232e197b0fb0e24dedc142ccc1910877251b`. Reports were copied into version
control afterward. [commands.json](validation/commands.json) records all eleven
final invocations, exit codes, elapsed times, Python 3.12.14/macOS environment
and browser/D3 paths. [manifest.json](manifest.json) records saved and decompressed
SHA-256 hashes. Raw reports retain per-operation timings, runtime code manifests,
inputs, outputs, citations, failures and bounds; IDs/timestamps may vary on rerun.
Runs shared a workstation with the full suite and diagnostics. These timings
establish no production latency guarantee or human time saving.

| Check | Direct observation |
| --- | --- |
| Full local suite: `.venv/bin/python -m pytest tests/ -q -rs` | **2069 passed, 10 skipped**, one existing Starlette/httpx warning, 525.42 s. Collection began at `2010640f81d8498d70f6d18779badfa5c8784ad1`, before the additional second-source browser case. That run is supporting evidence, not a claim of a clean full-suite run on 4558232. Production Python/JS, tools and CI configuration are identical between those commits. |
| Additional second-source browser case | **1 passed**, 40 deselected; current strict browser/matrix and matching CI also include it. Counts are not added to the earlier full-suite count. |
| Strict current integrity matrix | **55 passed**, no skips, 100.54 s; **41/41 applicable cells passed**, 13 technically declared N/A. [Actual phase reports](validation/integrity/report.json), JUnit and pytest log are retained. |
| Strict MCP/access | **303 passed**, no skips, one existing warning. |
| Strict PDF | **48 passed**, no skips, one existing warning. |
| Strict Chromium | **41 passed**, no skips, one existing warning. |
| Memory smoke / frozen Decision Memory baseline | Both exit 0; no release/quality claim. |
| Imported-document workflow / production controls | Both exit 0; walkthrough **7/7** named integrity checks. Production smoke success does not pass semantic gates. |
| Source-only solo runner | Exit 0, 8 events × 2 profiles, 27 eligible pairs/profile, no independent scoring. |
| Package consistency / whitespace | `pip check` and `git diff --check` exit 0. |

All **15 CI checks passed for head 4558232**:
[CI](https://github.com/SaltKing0/graph-engine/actions/runs/39128323673),
[seven dependency advisory profiles](https://github.com/SaltKing0/graph-engine/actions/runs/39128323571).
The [check snapshot](validation/ci/source-checks.json) and raw CI log are saved.
CI's PR merge checkout is `288dcbb1830be9c40989f32b9c5d4b477b94edd8`; its
[matrix report](validation/ci/integrity-report.json) has the **same code hash**
as the local 4558232 report and the same 41/41 cells / 55 test executions.
CI's strict local-model trust step passed **12 tests**. Full suites passed on
light Python 3.11–3.13 (1969 passed / 71 optional skips each) and the real-model
3.12 install (1979 passed / 61 optional skips); separate strict MCP, PDF,
Chromium and matrix jobs supply their explicitly required optional coverage.
Different job counts are not interchangeable or additive.

The ten local skips are two optional model-cache tests, the real-embedder demo
and seven model-trust parameterizations; `[st]` was not installed locally.
Matching CI supplies the required real-model/trust checks. Other Linux/Python
jobs and advisory profiles were observed in CI, not rerun locally. Large optional
performance experiments, paid providers, reserved successor/final data, human
calibration/adjudication and user sessions were not run. The new runner never
opens labels or evaluation-source files. Old already-exposed synthetic controls
remain separate from real development inputs.

## Reproduction and retained failures

From the repository root, use the exact final commands/environment in
[commands.json](validation/commands.json), with new output paths. Install extras
and Chromium as described in CONTRIBUTING.md. To verify hashes, saved code,
source-only notes, all quote references, original input equality, matrix accounting,
CI code equality, local file links and the unchanged failed gate:

```bash
.venv/bin/python docs/decision-evaluation-results/solo-development-v1/verify_artifacts.py
```

The [reference report](validation/reference-validation.json) records all eight
matching input hashes, quote counts, per-profile context truncation and unchanged
protected corpus/contract/old-result paths. This report's validator does not
certify independence, sign off an exhaustive matrix or turn any open gate green.

Development failures are retained under `development/`, separately from final
checks. The original five impact regressions produced **2 failures / 3 passes**.
An intermediate multi-path implementation exceeded the existing 200-reference
bound (1 failure / 59 passes); explicit bounded path clipping corrected it.
A replay using only the original PR-94 JavaScript in the current browser test
fails the selected-revision heading, while the corrected script passes. The
[test-only replay plugin](development/original_brief_plugin.py) and exact commands
are retained; it changes only that browser response, not repository production
files. Earlier broad DOM expectations incorrectly included the current-successor
panel; they were narrowed to the historical brief. Multi-tab fixture setup,
MCP-envelope/error assertions and the new test's missing API auth header also
needed correction. Their failures are test/development errors, not invented
product measurements or successful acceptance. Exploratory transient invocations
do not have a complete command transcript; no exact replay of every edit is
claimed. Final invocations and the targeted original-JS replay are recorded.

## Acceptance remains open

Independent final coverage remains **0 positive pairs / 0 negative pairs /
0 inconclusive cases**, below 20/20/10. No reviewers, participants, calibration
agreements, adjudications, final labels, human timings or product benefit are
supplied. Source notes do not complete #90's human calibration criterion.

#91's stage diagnosis/development regression work and #92's explicit inventory
and interface mapping are delivered. Independent semantic comparisons, passing
frozen quality gates, reviewed scenario sufficiency/N/A declarations and final
candidate/reviewer integrity sign-off remain outstanding. The matrix's
`software_matrix_complete=true` applies to its declared engineering scenarios;
`final_integrity_gate` remains unmeasured, sign-off/candidate null and
`release_ready=false`. #93's controlled human exercise remains unmeasured.

Next: review the stacked draft implementation and evidence. For later acceptance,
the project owner must arrange qualified separate source judgments, a second
independent final judgment/adjudication and an evaluator-controlled store for
fresh final families; record involvement/exposure and reviewed runtime conditions
before freezing and testing the final candidate. No such people or judgments are
invented here. Keep #90/#91/#92/#73 open and Decision Memory experimental.
No merge, version/tag change or release is performed.

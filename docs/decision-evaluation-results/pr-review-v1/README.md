# Draft PRs #94/#95 engineering review — 18 October 2026

Both PRs remain drafts; no PR merge, release or acceptance promotion was performed.
This is the implementing agent's engineering review, not independent semantic
annotation, reviewer sign-off of the final candidate or a human user study.

## Reproduced findings and corrections

| Finding | Correction and regression |
| --- | --- |
| #94 accepted false source provenance and incomplete eligible inventories as `packet_valid`. A source appearing only once could change revision/path/lineage/license without detection. | Bind packet origin, event cutoffs/IDs, exact source inventory, original metadata/file commitments and eligible decisions to the preserved source-only development freeze. Ten new mutations all failed before the fix; the full annotation suite now passes 33 tests. Original exported packet/form/manifest bytes are identical. See [#94 review evidence](../annotation-review-v1/README.md). |
| #95 could declare a parametrized matrix cell complete when only one instance had run. `-k`/`-m` deselections were absent from its denominator. | Capture all active **and deselected** node IDs. Every expected instance must have successful setup/call/teardown observations. A unit regression and actual pytest subprocess verify parameter accounting; the real filtered matrix rerun below is rejected. |
| #95's code fingerprint omitted the imported scenario helper `tests/test_decision_impact.py` and did not cover all transitive helpers. | Fingerprint runtime, tool and test source helpers, including the scenario constructors and corpus utility. A regression verifies helper inclusion and detects a changed helper. Local and CI code hashes match. |
| #95's solo report could record the commit of an unrelated caller checkout. Matrix selectors also assumed the caller was in this repository. | Pin Git commands to the code checkout, record invocation directory and use absolute pytest selectors with an explicit repository root. An unrelated-Git fixture and real matrix/solo executions from `/private/tmp` verify the boundary. |

The privacy/read-only adapter tests were also hardened: authorized review-queue
and context projections must return their real schemas successfully. A blanket
adapter failure cannot count as successful privacy evidence merely because no
sensitive bytes were returned. All 20 affected read scenarios pass over actual
service, CLI, HTTP, MCP and export surfaces.

The production delta/path/UI changes in the original #95 diff were reviewed
with their version/review, authorization, truncation and bounded-path invariants.
No further reproducible production defect was found in that reviewed scope.
Original source/label/freeze bytes, old result artifacts, review decisions,
permissions and thresholds are preserved. No final/successor data was acquired.

## Observations on pinned code

Clean combined code: `f76dde05c0b042ba4e1a20c5196ca00225408083`.
The later branch synchronization/report additions change documentation/artifacts
only. The measured #94 correction is `2c479b8f7d7289d877a5822e212896531e6d450c`;
its final report head is `33d45b7a13eabddc735ea41edb6c701c505c7495`.

| Check | Direct observation |
| --- | --- |
| #94 full local suite | 1982 passed / 11 optional skips / 1 existing warning; 312.78 s |
| Combined #95 full local suite | **2084 passed / 10 optional model skips / 1 existing warning; 538.27 s** |
| Annotation/tool regressions | 55 passed; this is a different suite from the 55 scenario tests below |
| Hardened privacy adapter subset | 20 passed / 13 deselected / 1 existing warning |
| Full strict matrix, invoked outside checkout | **55 expected / 55 observed, no skips or deselections; 41/41 applicable cells; 13 technical N/A** |
| Intentionally filtered strict matrix | pytest: **54 passed / 1 deselected, exit 0**. Matrix: **40/41 cells, one missing instance, CLI exit 1**. Correctly rejected, never counted as complete matrix evidence. |
| Memory smoke, frozen controls, imported-document workflow, production controls, known-development solo | All exit 0; workflow 7/7 named checks. Both matrix and solo invocations outside the checkout retain the actual code commit. |
| CI on combined code f76dde0 | All **15** checks successful, including real-model/trust, full supported-Python jobs, strict MCP/PDF/Chromium, matrix and seven advisory profiles. [CI run](https://github.com/SaltKing0/graph-engine/actions/runs/39131267910) |

The [command record](commands.json) contains exact argv, working directories,
environment overrides, expected/actual exit codes and elapsed times. The filtered
run sets `PYTEST_ADDOPTS=-k "not lineage1"`; use new output directories when
reproducing. [Validation identity](validation.json) records full/focused commands,
Python/browser configuration and scopes. CI check IDs, raw logs, actual phase
reports, expected/deselected nodes and JUnit are retained. The CI and local matrix
reports have identical code hashes and 55/55 observations. Code hashes now cover
the previously omitted helpers; do not compare the old narrower hash as though
it were the same definition.

Local #94 lacks Chromium and the optional real-model stack; #95 has Chromium,
MCP and PDF, but no `[st]` stack. Matching CI supplies strict optional coverage.
The existing warning is Starlette/httpx deprecation. No large optional performance
experiment, paid provider, independent human annotation/calibration/adjudication
or actual user session was run. Runs shared a workstation with other checks;
recorded software timings establish no speed or human-benefit claim.

## Preserved limits and reproduction

The known-development solo run covers eight already exposed events / 27 pairs,
with exactly the original runtime input hashes and zero independent scoring.
Curated contexts remain visibly truncated within budget. The synthetic diagnostic
still fails at **5/95 false alerts (5.26%) > 5%**; the empty proposed profile
misses **3/3** positives. Independent coverage remains 0/0/0. Final semantic gates,
reviewed scenario sufficiency/N/A declarations, final-candidate integrity sign-off
and controlled user benefit remain open. No additional acceptance criterion is
marked complete by this engineering review.

All saved files have hashes in [manifest.json](manifest.json); gzip files also
retain decompressed hashes. Original preparation/solo/workflow evidence remains
unchanged. From the repository root, verify saved bytes, helper identities,
CI/local equality, complete-versus-filtered accounting, original input hashes
and unchanged failed gates with:

```bash
.venv/bin/python docs/decision-evaluation-results/pr-review-v1/verify_review.py
```

Then use commands.json and validation.json on the pinned checkout with the
CONTRIBUTING.md dependencies to rerun actual checks. The intentionally rejected
matrix is a guard regression, not independent product evaluation. Subsequent
relevant changes need fresh matching validation before final sign-off.

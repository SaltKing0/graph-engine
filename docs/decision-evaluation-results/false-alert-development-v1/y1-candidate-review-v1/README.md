# Review of the remaining Y1 claim and dependency candidates

The two remaining candidates have been reviewed in the **exact restored state**
from the [fresh Y1 comparison](../y1-refresh-v1/README.md). The claim change is
recorded as **confirmed / open**: the old decision's basis materially changed.
The proposed dependency is **inconclusive / workflow null**: its exact endpoints
and source context are consistent, but it is a proposal without an accepted
decision impact. Both remain in the pending review queue, alongside the unchanged
open withdrawal finding. No dependency is accepted, decision activated or
finding resolved.

This is implementing-agent analysis of the **same previously exposed synthetic
development case**, `controls-v2/event-surviving-support`. The two new diagnostic
events are scripted developer dispositions, not human reviewers, independent
annotations, new test cases, semantic scores or evidence of product benefit.
No production engine or evaluation logic changes were needed for these reviews.

## Separate findings

| Candidate | Source and version analysis | Recorded disposition and remaining work |
| --- | --- | --- |
| Claim change, `878bcb1a…` | The old claim cites X1 and Y1; its exact successor cites Y1 plus the withdrawal update. Its text explicitly narrows the assertion to the source-declared rule after X1 withdrawal. Context, limitations and predecessor identity are preserved. The accepted old dependency still points to the old claim and decision, not their successors. Its old support endpoints are stale; X1 is withdrawn and Y1 remains available on the new claim. | **Confirmed / open** means a material old-basis change, not a refutation of Y1. The old decision remains `needs_investigation`; its old scripted approval does not transfer. |
| Proposed dependency, `2e9484ee…` | Its exact `depends_on` endpoints are the proposed new decision and Y1 claim. Context matches all five declared dimensions. The new decision retains the same fictional action and names the new claim as its provenance input. The Y1 support is accepted, available, fresh and structurally comparable. The dependency and new decision themselves have **no review events**. | **Inconclusive / workflow null** preserves uncertainty about impact on an adopted decision. The contract only exposes finding workflow for confirmed dispositions; this item remains queued and unresolved. It neither accepts the dependency nor dismisses the candidate as a false alarm. |

Both raw candidates retain `basis_changed` and `comparability_unknown`. Their
paths are single `depends_on` hops. The latter qualification says **no structured
evidential scope comparison on that path**, not that the source contexts are
proven incompatible. The separate evidence-to-claim support comparison is
`comparable`; this audit does not copy that result onto another path or filter
the warning. The dependency candidate remains `proposed_preview`, separate from
the old accepted dependency's historical path.

The [source review](../y1-basis-review-v1/README.md) is rechecked against the
actual restored references. Y1's source-declared recall is **0.8 fraction** under
the same workload W, environment E, code C, corpus H and protocol P. It meets the
sole declared **>=0.7 fraction** rule. The unit comes from that rule; the five
conditions come from the explicit same-conditions reference. The update withdraws
X1 and explicitly leaves Y1 available. Both measurements cite one original
document; run labels do not establish independence. Actual execution/dataset
validity, statistical sufficiency and general decision validity remain unknown.
The report preserves exact source hashes, field quotes/offsets and root lineage.

## Exact history and execution

The [runner](review.py) restores the prior offline bundle at its exact final
revision `b3abfb3b7da5b0d7cff74d5354f32756118f4167`. It compares the original
initial state against that restored current state, checks both candidates and
their public review details, then calls `DecisionService.record_finding` twice:
one `confirmed` claim-change disposition and one `inconclusive` proposal
disposition. Neither call submits a decision/dependency review or conclusion.
Same-key retries return their saved receipts; new-key duplicates are rejected.

The journal extends **16 versions / 17 events →18/19**, by append only. All
sixteen old content versions and seventeen events remain byte-for-byte identical;
the two new versions are findings and both new events are finding dispositions.
The old acknowledged finding history and newer open withdrawal finding retain
their exact references, reviews and freshness. There are now **three unresolved
queue entries**, zero unreviewed candidates for this comparison, and four finding
versions in history. That queue transition is explicit recording, not alarm
suppression, independent acceptance or resolution.

The comparison still emits **10 deltas / 3 candidates**, untruncated at unchanged
default limits (depth 3, objects 200, links 500, paths 20, deltas 200). Candidate
IDs, deltas, content endpoints, reasons and support summaries remain identical.
When the selected after-revision advances, the displayed path revision changes
to that exact selected commit. Both raw outputs are retained; verification allows
only that explicit old-after → new-after path-revision replacement, then compares
all remaining fields exactly. It never substitutes content/version identities.
The prior frozen comparison is also reproduced exactly without normalization.

The [report](report.json.gz), [complete Git bundle](brain.bundle) and
[verifier](verify.py) retain the **actual** successor execution, rather than
replaying new identities as historical ones. Final brain revision:
`5faf261f3d9a292c901b06f9ed45c1ff8721e60b`. Restoring it reproduces the exact
findings, journals, comparisons and queues. The archive clone's `origin` points
to a local immutable bundle, which has no `main` branch; the runner removes this
scratch-clone remote before normal local-only writes. It does not bypass writer
freshness, authorization, idempotency or schema checks.

## Validation and reproduction

Run from the repository root, using a **new** output directory:

```bash
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-candidate-review-v1/review.py --output /tmp/y1-candidate-review-new
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-candidate-review-v1/verify.py
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-candidate-review-v1/check_references.py
.venv/bin/python -m pytest tests/test_decision_review.py tests/test_decision_refresh_basis.py tests/test_decision_support_paths.py -q -rs
```

The runner has no arbitrary case, reserved-data, gold-label, provider, activation
or resolution option. Its source-read guard rejects label and evaluation-source
paths. Source review notes and predetermined diagnostic explanations are never
comparison inputs: comparisons are generated first by the unmodified public API;
review reasons are appended only to the two resulting finding dispositions.

[Exact executed commands](commands.json) and raw logs distinguish fresh checks
from historical software evidence. **32 focused tests pass** (77.19s, one existing
Starlette deprecation warning); these cover the review API,
successor freshness/history and the known separate support paths. The prior
83-file evidence verifier also passes in an isolated checkout of its exact
`08f55ea` snapshot, including restoration of its original bundle; it is not
weakened to accept this additional artifact directory. The new verifier checks
the complete inventory, source/code hashes, both exact states, all old history,
three unresolved entries and idempotency/duplicate guards. **32 local file/anchor
references** pass across the report and two appended guides.

The [authoring attempts](authoring/attempts.json) retain three failed checks:
an overstrict equality assertion before writing (selected path revision changed),
the first local-bundle sync attempt before writing (no remote `main`), and an
incorrect workflow assertion after the two diagnostic writes (inconclusive
workflow is null by contract). The latter scratch journal and all failed reports,
logs and runner snapshots are preserved. They are not successful final runs or
new independent cases. A successful preflight before the runner's type-hint
cleanup is retained separately; the final frozen runner is then executed and
verified again. The final measured run passes with the existing engine and
workflow rules unchanged.

The plain Git whitespace check reports a trailing blank line in the retained
raw `authoring/checked.log`. Its bytes are intentionally preserved. The recorded
check with only `blank-at-eof` disabled passes; no other whitespace rule is
relaxed. This formatting exception is separate from the software/audit checks.

The full local suite and strict matrix are **not rerun for this documentation
delivery**: production code, tools, tests, CI and dependencies are byte-unchanged
from the prior measured candidate. Historical results remain **2,186 passed /
10 optional model skips / 1 existing Starlette warning**, and **55 matrix tests /
41 of 41 applicable cells / 13 technical N/A**. These are not new measurements.
The [prior final CI](https://github.com/SaltKing0/graph-engine/actions/runs/39153982993)
and [advisory run](https://github.com/SaltKing0/graph-engine/actions/runs/39153982971)
passed all 15 checks on `08f55ea`; CI for this new documentation head is tracked
separately in Draft PR #96.

## Acceptance remains open

The standard historical false-alert gate still **fails 5/95 (5.26%) >5%**; the
empty proposed profile misses **3/3 positives**. No source, label, threshold,
freeze, old score, review or report is replaced. This same-case technical review
provides no new independent cases or score. Independent final coverage stays
**0/0/0**. Independent annotations/adjudication, real execution/dataset-provenance
review, protected final corpus/freeze, completed matched search-agent baselines,
final-candidate sign-off and actual user sessions/product benefit remain absent.

No additional #90–#93/#73 acceptance checkbox is completed. The scoped diagnostic
review is complete; all three findings remain unresolved, the successor decision
and dependency proposed, Decision Memory experimental and PR #96 Draft. Before
any activation, an explicitly authorized lifecycle review must establish what
decision version and dependency are adopted and how the old investigation is
handled. Source consistency alone cannot supply that authorization or independent
validation. No merge or release.

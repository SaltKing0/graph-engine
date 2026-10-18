# Unsigned decision on adopting the Y1 successor basis

**Recommendation for this request: defer execution and present conditional
adoption of the exact Y1-only successor for the known fictional development
case.** This is a concrete decision for later authorization, not an approval,
review outcome or activation. The [machine-readable decision](decision.json)
is unsigned and deliberately not a public API transaction envelope. Its selected
option, authorizer, reviewer, authorization time and actual reviewer outcomes
are null; activation authorization is false.

Proposed decision text:

> If separately authorized after fresh review, adopt the exact Y1-only successor
> below for mode A solely under the source-declared recall >=0.7 fraction rule
> and workload W, environment E, code C, corpus H and protocol P. Supersede the
> old decision and activate this successor in one transaction. Preserve all old
> reviews and the old `needs_investigation` conclusion. Keep all three findings
> unresolved pending their own fresh, exact-target reviews. This grants no
> real-world validity, independent acceptance or release readiness.

The current result is **preparation complete, execution deferred**. Decision
Memory remains experimental, the successor decision/dependency proposed and the
old decision current with an outdated basis. No choice above has been signed or
submitted. In particular, a future conditional recommendation of `accepted` or
`remains_justified` is not an actual reviewer rating.

## Exact decision and basis

The source state is the [previous candidate review](../y1-candidate-review-v1/README.md),
repository snapshot `bf27c81d7c03c6483359c979603dd56c9bd2de06`, restored brain
revision `5faf261f3d9a292c901b06f9ed45c1ff8721e60b`. The existing
[offline bundle](../y1-candidate-review-v1/brain.bundle) is reused unchanged;
there is no replay, new identity mapping or new successor state.

| Role | Exact reference | Current state and planned treatment |
| --- | --- | --- |
| Old decision | `74a5d198-ea9a-4a19-9c94-851b4875780d` / `sha256:c3466b05e8ae71bed498c06152fb672949c1df66e48ccca9aaf5ebe6a7472579` | `current`, `needs_investigation`, basis changed. Preserve existing reviews; only a later explicitly authorized atomic terminalization is proposed. |
| Successor decision | same identity / `sha256:c1768ee0ab25ec004c972d57c9df69215a5b3c2cb8bfa08ee47dae08acdc1332` | `proposed`, no review events. Conditional adoption target; no transferred approval. |
| Y1-only claim | `5a29e2e4-eaa0-4789-b57d-907c4f1b257b` / `sha256:57613a94c02a57e440b0289c74094d4b8f6cff61bc8546b4688bf66f4a0a3e93` | Existing scripted `accepted/supported`, fresh; scope and limitations retained. |
| Y1 support | `32b185f5-9dfc-4f2a-a882-58eeb7b702ca` / `sha256:a9142f8d609e706fddc980d9fdbc6b7eb327f4c7b607514b76ba41ec889f087c` | Existing accepted, fresh evidence-to-claim link; structurally comparable. |
| New dependency | `e3e8b09b-36bb-4b9c-92e0-c281c423b3d1` / `sha256:f8e0a8b236e7008db58ccdb7499404f248eaa20b077402739a70a838eeadf971` | `proposed`, no review events; exact successor-decision → Y1-claim endpoints require separate future acceptance. |

The JSON also pins Y1 and X1 evidence, old claim/dependency versions, all three
finding references, observed review-event heads, source hashes and the complete
observed preview. Those observations are **not execution tokens**. A later
mutation must obtain fresh permissions, heads, generation, predecessor events
and actual author identity; it cannot reuse this saved preview as authorization.

Y1's declared value **0.8 fraction >=0.7 fraction** meets the sole numerical rule
in the known source. The five conditions are resolved from its explicit
same-conditions reference; no new run-count or statistical threshold is added.
The update withdraws X1 and leaves Y1 available. The claim cites Y1 and the
withdrawal update, not the withdrawn X1 evidence. Source quotes, offsets and
hashes are retained in the decision JSON and rechecked against the same known
development sources. Shared document roots and distinct run labels do not
establish measurement independence. Real execution/dataset validity, statistical
sufficiency and validity outside the fictional rule remain unavailable.

Original artifact bytes and captured Markdown-body bytes have **distinct hashes**:
the existing serializer adds exactly one final newline. Both identities are
preserved. The preparer checks the original artifact hash and extraction origin,
the captured text hash against the exact raw node body, and the precise
serialization difference, without stripping either representation. The display
parser removes trailing whitespace and is deliberately not used for byte identity.

## Options and future sequence

| Option | Recommendation now | Consequence |
| --- | --- | --- |
| Defer execution | **Yes** | Keep the exact current state and unresolved findings while the unsigned proposal is available for review. |
| Adopt the bounded development successor | Conditional future option | Requires separate authorization and fresh explicit reviews, then the atomic lifecycle pair below. It supplies no independent acceptance. |
| Adopt for broader or real-world use | Unsupported by known sources | Actual execution/dataset artifacts and independent evidence are absent. Do not infer this choice from source consistency or green tests. |

The concrete future steps are prepared, **none executed or dry-run here**:

1. Before every write, refresh authorization, exact content heads, source bytes,
   availability, event predecessors and the comparison. Stop and reprepare if
   anything relevant changed. Review reasons/expected outcomes are not comparison
   inputs.
2. An authorized case reviewer separately decides whether to accept the exact
   new dependency. Basis: exact Y1 claim, evidence/support, current claim
   assessment and support-acceptance event, plus the pinned source update. The
   conditional recommendation is acceptance within the fictional scope; rejection
   or continued investigation prevents adoption. No actual outcome is filled.
3. Separately review the successor decision's workflow and conclusion using the
   returned dependency-review event and exact current basis. `remains_justified`
   is only a conditional recommendation within this scope; `needs_investigation`
   or `revise` keeps adoption deferred. Future review event IDs are null until
   actually returned by authorized API calls; no reviewer or event is invented.
4. Only after a later explicit lifecycle authorization, issue **one transaction**
   containing old `current → superseded` and new `proposed → current`, with exact
   predecessor/basis refs and actual preceding review IDs. The old lifecycle
   predecessor is currently `d9909b62-88c8-535e-a211-6785f4d4d66d`; it must still
   match at execution. The successor's `previous` must remain the exact old
   decision. Separate lifecycle writes could leave two current versions or no
   activated successor and are rejected by the existing contract.
5. Regenerate comparison and review all three finding bases after any future
   reviews. New acceptance/conclusion events can stale existing candidates and
   findings; inspect and explicitly version them rather than reusing stale IDs.
   This plan authorizes **no** disposition change, acknowledgment or resolution.

An important restriction follows from the existing writer: the old decision is
no longer the **content head**, even though its historical lifecycle is still
current. A fresh nonterminal conclusion on that old version is rejected. Do not
try to replace its `needs_investigation` with `revise` or `remains_justified`.
Preserve that conclusion and review the successor separately. Only explicitly
paired terminalization is exempt from the old-content-head guard. These rules
are in [the contract](../../../decision-memory-v1.md#immutable-reviews-and-correction)
and the pinned implementation; no guard is relaxed here.

The old-target withdrawal and claim-change findings remain confirmed/open.
The proposed-dependency finding remains inconclusive/workflow null and queued.
A conclusion about the **new** decision cannot automatically resolve findings
targeting the **old** version: the resolution contract requires the exact target
outcome, with follow-up requirements for `needs_investigation`. Resolving any of
them needs a separate fresh, authorized review; it is not part of adoption
preparation, nor automatically part of a future lifecycle transaction.

## Validation and limits

The [read-only preparer](prepare.py) restores the original bundle and blocks all
domain transaction, submission, finding-write and direct brain-write paths,
including dry runs, during analysis. [Read checks](readcheck.json) establish
**18 versions / 19 events**, three unresolved findings, unchanged preview, Git
revision and clean scratch state. The original comparison reproduces **10 deltas /
3 candidates**, untruncated, with its original IDs, qualifications and default
limits. Existing journal, source observations and all reviews remain exact.
The preparer checks permitted transition shapes, not a future signed transaction.
No actual future authorization, decision review, adoption or general validity is
claimed by a successful preparation run.

```bash
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-adoption-plan-v1/prepare.py --output /tmp/y1-adoption-plan-new
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-adoption-plan-v1/verify.py
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-adoption-plan-v1/check_references.py
```

Always use a new output directory. The preparer has no arbitrary case, reserved
data, label, provider or activation option; the existing source-read guard is
active. [Exact commands and raw outputs](commands.json) distinguish fresh checks
from earlier runs. **Five existing lifecycle regressions pass** in disposable
engineering fixtures: atomic replacement, duplicate-current rejection, source/
withdrawal staleness and fresh conclusions. Those fixture writes do not execute
this Y1 plan, create independent cases or count as user decisions. The prior
candidate-review verifier also passes in an isolated exact `bf27c81` checkout;
its manifest/scope guards are preserved. The new verifier rebuilds the entire
unsigned plan and checks the file inventory, transitive code/source identities,
unfilled approvals/outcomes and unchanged exact brain state. **33 local file and
heading references** pass across the report and two appended guides.

Two failed source-binding authoring checks are retained separately: an overly
strict original-text/captured-text equality, then use of the whitespace-stripping
display parser. Both stopped inside the read-only guard before any domain write.
The final check uses the exact raw-body reader, verifies both hashes and the
specific serializer-added newline, and succeeds. Earlier successful read-only
drafts are disclosed as preflights, not new independent cases or final outcomes.

The full local suite/matrix are not rerun for this documentation-only delivery;
production code, tools, tests, CI and dependencies are unchanged. Historical
measurements remain **2,186 local passes /10 optional model skips**, **55 matrix
tests /41 applicable cells**, 13 technical N/A. All 15 checks passed on the prior
head `bf27c81`: [CI](https://github.com/SaltKing0/graph-engine/actions/runs/39155365724),
[advisories](https://github.com/SaltKing0/graph-engine/actions/runs/39155365713).
CI on the new documentation head is reported separately in Draft PR #96.

## Open acceptance and required roles

The historical false-alert gate still **fails 5/95 (5.26%) >5%**; the empty
proposed profile misses **3/3 positives**. Frozen thresholds, sources, labels,
results and existing reviews are unchanged. This is one already exposed
fictional development case, not new independent evidence. Independent final
coverage remains **0/0/0**. No additional #90–#93/#73 criterion is checked.

The eventual bounded-case adoption needs a separately authorized decision owner
and actual explicit reviews of the exact dependency/successor. These assignments
and outcomes remain unfilled today. Independent feature acceptance is a separate
track requiring actual execution/dataset-provenance artifacts, qualified separate
source/evaluation reviewers, an evaluator/custodian controlling the protected final
store/freeze, completed matched baselines, final-candidate sign-off and actual
user sessions before benefit claims. No names, participants or results are
invented. This preparation supplies none of those missing measurements.

The next step is to review this precise unsigned choice and its bounded scope.
If later authorized, refresh and validate the actual future transaction against
then-current state before execution; retain the independent acceptance track as
open. No activation, resolution, merge or release is included here.

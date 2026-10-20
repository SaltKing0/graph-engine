# Source and protocol review of the unsigned Y1 adoption decision

**The known sources still support only the bounded fictional Y1 rule. Three
preparation gaps are corrected in [unsigned decision version 2](decision.json):
explicit event time, exact interpretation/field bindings, and explicit required
review outcomes/authority conditions.** Execution remains deferred. No source,
claim, support, decision, finding or review is changed. This is implementing-agent
analysis, not independent human acceptance.

The [original unsigned decision](../y1-adoption-plan-v1/README.md), its JSON,
manifest and raw results remain unchanged at `a02f6eb9fdc8704e38d47f97c4f32b7e1dc2a7ca`.
Version 2 revises the **preparation document**, not a Decision Memory content or
review version. All original plan fields other than the schema identifier are
retained exactly; the new information is explicit additional scope and protocol.
The existing [brain bundle](../y1-candidate-review-v1/brain.bundle) remains at
`5faf261f3d9a292c901b06f9ed45c1ff8721e60b`: **18 versions / 19 events**, three
unresolved findings, successor decision/dependency proposed, no inherited reviews.

## Findings and corrections

| Gap in version 1 | Source/protocol assessment | Version 2 correction |
| --- | --- | --- |
| Availability dates were in the source manifest, but the adoption JSON did not explicitly delimit decision time. | The update establishes source-declared availability at the **fictional event 2026-01-06T00:00:00Z**. It does not establish a real experiment's validity or Y1 availability today. | `temporal_scope` pins the event and both source-availability dates. Present-world availability and actual execution/dataset validity remain null. The scope must be confirmed in any later authorized review. |
| Unit/context qualifications were explained in prose and earlier reviews, but the JSON compressed them into predicate/dimension values. | The `0.8` measurement belongs to **Y1**, not equal-valued X1. `fraction` appears in the same recall rule, not separately in Y1. “Under the same conditions” resolves to X1's preceding **context fields**, not its withdrawn measurement. | `source_mapping` pins exact subject, metric, value, rule/threshold/unit, antecedent identifier, full context sentence and all five condition spans. It marks inherited interpretation explicitly and leaves actual artifact validity unknown. |
| The prose required positive future reviews, but JSON stage dependencies mostly required the reviews' existence. | A returned review ID alone is not acceptance. `rejected`, `needs_investigation`, `revise`, missing outcomes or unknown authorization cannot justify the planned adoption. | `adoption_gate` names required outcomes: dependency `accepted`, successor workflow `accepted`, successor conclusion `remains_justified`, each with a nonempty actual returned event ID. Scope confirmation, actual authorization, current exact source state and fresh heads are required. Actual outcomes/IDs remain null; the gate is unsatisfied and execution prohibited. |

The numerical statement remains **Y1 recall 0.8 >=0.7 fraction** under workload W,
environment E, code C, corpus H and protocol P. No numerical threshold, minimum
run count or statistical criterion is added. These are local source-declared
fictional IDs; no execution/code/dataset artifact is certified. X1 is withdrawn,
Y1 source-declared available at the event, and the two run labels do not turn
their shared original document into independent measurement evidence. Actual
measurement independence, statistical sufficiency and general decision validity
remain unknown. No correction to the already source-qualified claim is required
by these known sources.

The raw one-hop `comparability_unknown` and `proposed_preview` qualifications are
preserved. A comparable evidence-to-claim support does not itself approve a
decision dependency or resolve its uncertainty.

## Revised handoff and execution boundary

The underlying future sequence remains separate dependency/successor reviews,
then one explicitly authorized **old `current → superseded` / new
`proposed → current`** transaction. The old `needs_investigation` conclusion is
preserved; its version is not the content head, so fresh nonterminal review of
it remains rejected. There is no new old-version conclusion, undo, approval or
activation in this delivery.

The additional protocol distinguishes unplanned source/content/permission/review
changes from the planned addition of actual future review events. Unplanned
changes stop the process and require a new unsigned preparation. Planned review
additions still require actual API-returned IDs, fresh comparison, and validation
of the next stage on current state. The saved preview remains an observation,
not an execution token. No signed transaction, future writer acceptance or
authorization check has been executed or dry-run here.

Each existing finding now has an explicit handoff entry, with its exact reference
and preserved disposition/workflow. Owner assignment remains null. Withdrawal
and claim-change findings stay **confirmed/open**; the proposed-dependency finding
stays **inconclusive/workflow null** and queued. Future reviews can stale them;
their own exact-target review and separate authorization are required before
resolution. No successor conclusion automatically resolves an old-target finding.

All selected options, authorizers, reviewers, authorization times, actual outcomes
and future event IDs are unfilled. Required outcome enums are **protocol
conditions**, not fabricated reviews. The new JSON is a declarative unsigned
plan, not an executor or public API request. Preparation remains possible solo;
independent human acceptance is a separate, still missing evidence track.

## Reproduction and checks

```bash
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-adoption-review-v1/review.py --output /tmp/y1-adoption-review-new
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-adoption-review-v1/verify.py
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-adoption-review-v1/check_references.py
```

Use a new directory. The [reviewer](review.py) first reproduces the original plan
and exact read checks through its unchanged read-only preparer. Its existing
writer/dry-run and reserved-source/label guards remain active. Only the same known
`controls-v2/event-surviving-support` case is used. The new analysis then binds
source roles directly to the guarded development packet. Original artifact and
captured Markdown-body hashes and their exact serializer-added newline remain
as previously verified; neither representation is rewritten.

The [machine-readable review](review.json), [exact commands](commands.json) and
raw logs distinguish source consistency from software execution and acceptance:

- The original plan's three omissions are recorded without modifying that plan.
- **11 invalid-plan variants are rejected**: missing scope/mapping/gate, an
  unsupported present-world availability assertion, a falsely direct Y1 unit,
  the equal lexical `0.8` bound to withdrawn X1, three missing outcome predicates,
  a missing atomic old transition and implicit finding resolution. These are
  malformed in-memory protocol inputs, not source cases, reviewer ratings or
  independently scored observations. No positive reviewer outcomes are simulated.
- **Five existing lifecycle regression tests pass** in disposable engineering
  fixtures. The unchanged old plan verifier passes at exact `a02f6eb` in an
  isolated checkout. Those fixture transactions do not execute this Y1 plan.
- Exact reconstruction preserves the 18/19 journal, all old reviews,
  original proposal states, three unresolved findings and the untruncated
  **10-delta/3-candidate** comparison. No domain write or activation occurs.

One failed authoring check is retained in `authoring/`: the first span check
mistook the X1 identifier span for the full antecedent sentence. The corrected
check binds identifier and sentence separately and verifies the five context
fields inside the latter. The failure wrote no domain state and is not counted
as a successful audit or an independent case. A successful read-only preflight
preceded the final frozen validator; it supplies no separate semantic measurement.

The [verifier](verify.py) reproduces the revised JSON/review and checks the full
inventory, transitive code/source identities, unchanged original files and
append-only guides. **35 local file/heading references pass** across this report
and the two guides. Production engine, tools, tests, CI and dependencies are
unchanged. Full local suite/matrix are **not rerun** for this documentation-only
delivery; historical results remain **2,186 passes /10 optional model skips** and
**55 matrix tests /41 applicable cells**, 13 technical N/A. The prior final head
passed all 15 checks: [CI](https://github.com/SaltKing0/graph-engine/actions/runs/39156918240),
[advisories](https://github.com/SaltKing0/graph-engine/actions/runs/39156918385).
CI for the new head is reported separately in Draft PR #96.

## Open acceptance

The historical false-alert gate still **fails 5/95 (5.26%) >5%**; the empty
proposed profile misses **3/3 positives**. No label, source, freeze, threshold,
result or historical review is replaced. Independent final coverage stays
**0/0/0**. Separate annotation/adjudication, actual execution/dataset-provenance
evidence, protected final corpus/freeze, completed matched baselines,
final-candidate sign-off and actual user sessions/product benefit remain absent.
No additional #90–#93/#73 acceptance checkbox is completed.

This scoped source/protocol review is complete. The next step is review of the
revised unsigned scope and outcome conditions by an authorized case owner. Any
later execution needs a separate explicit instruction and fresh transaction
validation. Independent acceptance stays separate and needs actual qualified
reviewers/evaluator-controlled storage; no names or results are invented here.
Activation, finding resolution, merge and release remain unperformed; PR #96
stays Draft and Decision Memory experimental.

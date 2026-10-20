# Source review of the proposed Y1 basis

**Conclusion: the Y1 basis is consistent with the sole rule declared in the
known fictional development sources, within its existing limitations. No source
or claim correction is required by those sources.** This is an implementing-agent
source review, not a human judgment, independent annotation or acceptance. It
supplies no new runtime input, expected impact, semantic score or decision vote.

The reviewed snapshot is `75b319445d8976ce3f74c7875f686e12cb8eba85` in Draft PR
#96. Its [recorded support-path journal](../support-paths-v1/README.md) already
contains a source-qualified claim with scripted developer reviews; the successor
**decision and dependency remain proposed**. This additional review does not
append, revise, undo or supersede any engine review event, resolve the finding
or activate a decision. The original **15 content versions / 16 events** are
preserved, including their exact identifiers, basis and predecessor chains.
The [machine-readable review](review.json) pins the prior report's SHA-256,
canonical version/event hashes and exact claim, support, decision, dependency
and finding references. Claim ID: `ce3e1293-0eb9-464f-99ac-583980e9d6e3`;
version: `sha256:d83b6deed154008db1179d90c95299d1a265517231ea0ee4776c650015a48352`.

## Source reasoning

Only `controls-v2/event-surviving-support`, already exposed for development, is
used. The two full original texts, original hashes and exact source offsets are
bound in the [preserved source audit](../withdrawal-v1/source-audit.json); this
review validates them against the frozen source bytes. Its availability scope
is the fictional event at **2026-01-06T00:00:00Z**, not a real-world assertion
that an experiment or source remains valid today. Offsets below are zero-based,
half-open Unicode character ranges in the original basis/update text.

| Point | Finding | Exact source basis and qualification |
| --- | --- | --- |
| Decision rule | Direct statement | Basis `[11,52)`: `Choose mode A when recall >=0.7 fraction.` This is the sole declared numerical rule; no minimum run count or statistical threshold is added. |
| Y1 measurement | Direct statement | Y1 clause `[154,240)`, value `[182,185)`: `0.8`; metric `[175,181)`: `recall`. This value belongs to Y1, not the equal-valued, withdrawn X1 measurement. |
| Unit | Documented interpretation | `fraction` is declared for recall in the rule `[43,51)`. Y1 does not separately repeat a unit. The same metric declaration is used within this fictional source; no unit conversion or outside convention is assumed. |
| Conditions | Explicit reference resolved | Y1 `[186,211)`: `under the same conditions`, referring to the preceding X1 conditions: workload W, environment E, code C, corpus H, protocol P. Exact source fields, not X1's measured recall, supply the Y1 context. These are local fictional IDs, not verified execution/code/dataset artifacts. |
| Withdrawal/availability | Direct statements | Update `[39,74)` withdraws X1 support; `[75,116)` says Y1 remains available. The update does not state a blanket withdrawal of Y1, the document or the condition fields. The reason for the withdrawal and actual protocol/dataset validity remain unverified. |
| Lineage | Independent status unknown | `run-X1` and `run-Y1` are distinct source-declared tokens. Both evidence paths cite one shared original document. The update's assertion of a separate run with known provenance does not supply reviewed execution/dataset artifacts. Two paths are not independent votes. |
| Sufficiency | Conditional source consistency | `Decimal('0.8') >= Decimal('0.7')` holds with the documented unit/context interpretation. Thus Y1 suffices for the stated fictional rule. Sample size, uncertainty, measurement validity, statistical and general decision sufficiency remain unknown. |
| Review/lifecycle | Preserved and open | The successor basis references Y1 plus the update, not the X1 evidence record. Old versions, exact support endpoints and reviews remain intact. The old decision still needs investigation; the confirmed/acknowledged finding is stale after basis versioning and remains unresolved. The proposed successor has no inherited reviews. |

The remaining-basis claim already says **source-declared** and retains explicit
fictional/developer-only and missing-provenance limitations. Its scope matches
the five declared conditions; its successor decision retains the same source
action. No unsupported broadening was found **within this stated scope**. This
does not certify the truth of the fictional observations or validate mode A for
another corpus, environment, protocol or real application. If the intended
criterion is actual validated decision sufficiency, the available sources do
not establish it. That gap cannot be filled by a green software test or another
scripted review.

## Verification and reproduction

```bash
.venv/bin/python -m pytest tests/test_decision_support_paths.py tests/test_decision_reviewed_observations.py tests/test_decision_observations.py tests/test_decision_source_updates.py tests/test_decision_workflow.py tests/test_decision_solo.py -q
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-basis-review-v1/review.py
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-basis-review-v1/check_references.py
```

For a fresh, separate review output (existing paths are refused):

```bash
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-basis-review-v1/review.py --capture /tmp/y1-source-review-new.json
```

[Exact commands and results](commands.json) and raw logs distinguish fresh
checks from historical evidence. Fresh focused tests: **117 passed**. The source
review revalidates complete source hashes, exact field roles/quotes, Decimal
comparison, context dimensions, recorded version/event identities, explicit
review bases, preserved history and proposed/unresolved states. An active read
guard rejects label and evaluation-source file paths during the actual review;
no arbitrary case/final-data option is provided. This is the **same known case**,
not a new independent case, score or human calibration.

The original support-path artifact verifier also passes at its original
`75b3194` snapshot before this new audit is added. Its original Git-scope
assertion is preserved; the new sibling directory is verified separately.
The journal validator itself is reused read-only for the exact prior archive.
An early reference check correctly rejected the not-yet-collected command
inventory; [the failed authoring check](authoring.json) and raw log are retained.
The final run writes the inventory first and uses the unchanged link-check rules.
No historical manifest, result, source, transcription or review is rewritten.
The new verifier checks its complete artifact inventory and rejects runtime,
tool, test, CI, dependency or frozen-data changes relative to that snapshot.

The full local suite and strict matrix are **not rerun for this documentation
review**: implementation/tests are byte-unchanged from the previously measured
candidate. Historical evidence remains **2,182 passed / 10 optional model skips**,
strict matrix **55 tests / 41 applicable cells**; these are not presented as new
measurements. All 15 CI checks passed on reviewed head `75b3194`, including the
actual model/trust stack: [CI](https://github.com/SaltKing0/graph-engine/actions/runs/39148261416),
[dependency advisories](https://github.com/SaltKing0/graph-engine/actions/runs/39148261407).
CI on the new documentation head is tracked on PR #96 separately.

## Remaining acceptance and next action

The standard diagnostic's **5/95 false alerts (5.26%) >5%** remains a failed
historical gate; the empty proposed profile still misses **3/3** positives.
This source review does not change the diagnostic or its frozen thresholds,
labels, earlier results or reviews. Independent final coverage remains
**0/0/0**. Independent source annotation/adjudication, protected final corpus
and freeze, matched completed search-agent comparisons, final-candidate
integrity sign-off and actual user sessions/product benefit remain absent.
No additional acceptance checkbox is completed; #90–#93 and #73 remain open,
the PR remains Draft and Decision Memory remains experimental.

The scoped source review is complete. Before independent-run credit, actual
execution/dataset artifacts and separate qualified human review are required.
Before resolving the stale finding or activating a successor, prepare a fresh
comparison against the current basis and obtain an explicit review authorized
for that action. This delivery preserves the unresolved/proposed states; no
merge, release, decision activation or finding resolution is included.

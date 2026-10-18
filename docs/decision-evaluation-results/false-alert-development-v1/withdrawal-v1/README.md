# Known withdrawal: remaining source-declared support (#91)

**Y1 satisfies the only explicitly stated numerical decision condition. This is
not independent evidence acceptance, and does not make the old X1/Y1 basis
unchanged. Retain the withdrawal/basis review.** This is a source audit of one
already exposed fictional development case, not a new test corpus or study.

## What the existing sources establish

The original source says to choose mode A when recall is **>=0.7 fraction**.
X1 reports 0.8 under workload W, environment E, code C, corpus H and protocol P.
The separate Y1 statement reports **recall=0.8 under the same conditions**, with
recorded root `run-Y1`. The update withdraws **X1**, and explicitly says **Y1
remains available**. The implementing agent resolves the explicit common
conditions reference to the preceding X1 context, and the metric unit from the
rule's recall declaration; no conversion or wildcard is introduced.

Thus Y1's declared value **0.8 >= 0.7** meets the stated predicate in that local
scope. The source does not demand a minimum run count, confidence interval,
independence score or statistical threshold; none is invented. The original
0.7 source predicate and all frozen evaluation gates are unchanged.

The source's words “independent” and “separate run” are assertions, not reviewed
execution/dataset artifacts. Different `run-X1`/`run-Y1` labels or document
hashes do not prove measurement independence. Statistical sufficiency and
independent measurement validity remain **unmeasured**, not true or zero.
The old partial transcription (including its unknown Y1 fields) is preserved;
this new, explicit source interpretation does not retroactively approve it.

[source-audit.json](source-audit.json) preserves full source hashes, exact
clause/field spans, rule/measurement separation, the common-context referent,
subject-specific availability statements, recorded roots and the implementing
agent's interpretation limits. Equal text from the wrong clause is rejected.
The two source copies are byte-identical to the frozen originals, with original
MIT licensing retained. No source, label, freeze, prior result or review is
replaced.

## Why the candidate must not be hidden

The normative [dependency/lineage contract](../../../decision-memory-v1.md#directed-relationships-and-bounded-impact)
requires a candidate to explain both the loss and remaining support when one
support is withdrawn. Independent-run assertions require human review with
execution/dataset provenance. The [worked withdrawal example](../../../decision-memory-example.md#version-freshness-duplicate-supports-and-history-checks)
also retains this candidate; withdrawal is not automatic refutation.

The original diagnostic still captures only an aggregate declared basis claim.
It does **not** model X1 and Y1 as individually reviewed evidence/support links,
nor apply a per-observation availability event. Its candidate has reasons
`basis_changed` and `comparability_unknown`; its typed remaining/removed support
lists are empty. This is a representation gap, not evidence that Y1 disappeared
or that the decision is false. Silently treating the old X1/Y1 basis as unchanged
would hide X1's actual withdrawal. No old review is transferred to a new basis.

The source-level conclusion is therefore: **the remaining stated observation
meets the stated decision rule; a decision reversal is not established**.
The software/review conclusion is: **review and version the changed basis,
explain Y1, and retain the decision only through an explicit justified review**.
No new acceptance event, source-root independence credit, automatic reversal or
post-impact warning filter is introduced by this audit.

## Reproduction and observed results

From the repository root, use a new output directory:

```sh
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/withdrawal-v1/check_audit.py
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/withdrawal-v1/verify.py --replay /tmp/decision-withdrawal-new
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/withdrawal-v1/verify.py
```

The replay supplies **only the existing source-only runtime inputs and existing
field-review packet** to the original production executor. The new sufficiency
interpretation never enters it. No label/evaluation-source reads, new source
fetches, providers, answer models or paid calls are involved. A read guard checks
the existing development loader. There is no arbitrary corpus/evaluation switch.

- One known development event, **10 eligible decisions per dependency profile**,
  two completed profile executions, zero errors. Original input hash and
  normalized alerts match the previous reviewed-development report.
- Curated: **1 raw alert / 1 impact candidate**. Empty proposed profile: **0**;
  this does not establish recall or extraction quality. Both contexts remain
  visibly truncated within budget=4000, k=5.
- Journals retain **71 immutable version records**, with **10 scripted original
  curated-dependency wiring acceptances** and no new semantic/human reviews.
  Exact stored source serialization, hashes, previous-version links and original
  update/basis references remain auditable.
- The declared-rule assessment passes; **13 adversarial source/role mutations
  are rejected**: stale hashes, missing/wrong units, altered numeric values,
  threshold/measurement swaps, equal values from X1 instead of Y1, missing/swapped
  conditions, the wrong root/subject, fabricated human/independent status and
  gold fields.
- **99 focused software regressions pass**. Five previous evidence verifiers
  pass at their appropriate report heads: the first two at `fb2fff2`, the other
  three at `3090863`. Two initial wrong-head attempts correctly failed on the
  changed historical `production.py` fingerprint; their raw logs and corrected
  invocations are retained. No old verifier is weakened.

`commands.json`, raw logs and journals identify exact commands, working
directories, timings, errors and scopes. `manifest.json` binds the complete
artifact inventory. The verifier also checks that all runtime/tool files match
the previously measured code manifest from **b597bc6**, and that runtime, tests,
CI, package configuration and frozen data are unchanged from **3090863**.
This delivery changes documentation/source-audit artifacts only. The full local
suite/matrix were not redundantly rerun: the byte-identical runtime's prior
**2,164 passed / 10 optional skips** and **55 tests / 41 applicable cells** remain
historical evidence, not new run claims. New source-audit/negative checks,
production replay, focused tests and artifact/reference validation are executed
for this delivery. The new documentation head also runs the existing required CI. Local reference
validation covers 28 file/anchor links across five documents.

The initial temporary authoring script lacked the repository on `sys.path` and
failed with `ModuleNotFoundError: tools`; `PYTHONPATH=.` corrected that invocation.
An initial successful replay preceded stricter clause/field-role validation;
its packet/report/log are retained under `prototype/`, separately from the final
replay. These are development attempts, never independent cases or gate passes.

## Open gates and next action

No acceptance checkbox is completed. The historical standard diagnostic's
**5/95 (5.26%) >5%** false-alert result remains failed; no new semantic score is
computed here. The empty proposed profile's historical **3/3** positive misses,
independent coverage **0/0/0**, missing matched completed agent baseline,
independent annotations/adjudication and actual user-benefit measurements remain
visible. #90–#93 and #73 stay open, PR #96 stays Draft, Decision Memory remains
experimental. No merge, release, threshold change or review fabrication.

Next technical step: represent the source-declared rule and X1/Y1 as separate
source-bound evidence/support proposals, model X1's withdrawal explicitly, and
review/version the remaining Y1 basis. Keep the withdrawal history and explain
why the choice may remain justified. Before any **independent-run** credit,
qualified human review needs actual execution/dataset provenance; the current
fictional source assertion cannot supply that evidence. Final independent
assessment and user sessions remain separate requirements.

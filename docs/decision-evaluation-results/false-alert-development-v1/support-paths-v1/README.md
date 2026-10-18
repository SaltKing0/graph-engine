# Separate evidence paths and the remaining source-declared basis

One **previously exposed synthetic development event**,
`controls-v2/event-surviving-support`, now has separate X1 and Y1 evidence paths
through the production DecisionService APIs. The source-only
[original audit](../withdrawal-v1/README.md) remains unchanged. This is explicit
developer wiring, not independent semantic acceptance or a new false-alert
rate. The remodeled graph is different from the original aggregate diagnostic.

The clean measured implementation is `1bddddc061ed87dcae27325351dc49cfecbf8320`.
[The report](support-paths-report.json.gz) records the actual code manifest,
Python/dependencies, source-input hash, original source hashes and audit hash,
all generated references, Git revisions and complete authorized journals.
Implementation was frozen from a clean checkout. Later workflow/matrix outputs
may report `dirty=true` because evidence/documentation was being authored while
tests ran; [the recorded scope](scope-state.json) and code fingerprints retain
that fact and show no subsequent implementation change.
The runtime core, default diagnostic, frozen sources, labels and thresholds are
unchanged from `ad757775`; only the opt-in developer tool, its regressions and
guidance were added. This directory and the readiness update are later evidence
and documentation, with no further implementation change.

| Recorded stage | Evidence and basis | Review/decision state |
| --- | --- | --- |
| Initial commit | Separate X1/Y1 evidence and accepted support links to basis version 1 | Explicit synthetic initial assessment and current fictional decision |
| Withdrawal commit | Later update source; X1 availability withdrawn, Y1 available | One real comparison candidate: `basis_changed`, `support_withdrawn`; X1 removed, Y1 remaining; old basis stale/inconclusive |
| Successor proposal | Same claim identity and exact predecessor; only Y1 and update as new provenance inputs; new Y1 support endpoint | Proposed/unassessed, no inherited event |
| Fresh developer review | Declared recall 0.8 >=0.7 fraction, five explicit shared conditions | Own synthetic acceptance/assessment events; new basis supported within its stated limits |
| Final fresh session | Exact old versions, endpoints and reviews retained; successor decision/dependency recorded | Successor decision/dependency remain proposed; old decision remains current with `needs_investigation`; finding confirmed/acknowledged, unresolved |

X1/Y1 cite exact separate passages in **one original document**. Both retain its
shared `document-sha256` identity. The claimed run labels remain recorded source
assertions, not independently reviewed execution artifacts or independent votes.
No `result` records, experiments, reviewers, participants or measurements are
invented. Y1's inherited conditions cite the five condition fields, without
importing X1's withdrawn measurement. The unit is resolved from the recall rule
without conversion. There is no invented minimum run count or statistical gate.

The stored withdrawal finding itself also reports `basis_changed=true` after
publication of the successor basis. Its old confirmed/acknowledged review is
historical, not a fresh resolution of the new basis; a new comparison/review
is required before resolving it.

The final journal has **15 immutable content versions / 16 scripted developer
review events**. The report retains the initial, withdrawal, successor-proposal
and final journals, before/after comparison and exact historical reconstruction.
UUIDs, review timestamps and Git identities vary on re-execution; reproduction
checks structure, source binding, predecessor chains, current states and exact
preservation within each run, not equality of new UUIDs with this recorded run.
The temporary brain is removed only after these authorized records are exported.

## Reproduction and observed validation

Use a NEW output directory, from the repository root:

```bash
.venv/bin/python -m tools.decision_benchmark.support_paths --output /tmp/decision-support-paths-new
.venv/bin/python -m pytest tests/test_decision_support_paths.py -q
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/support-paths-v1/verify.py
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/support-paths-v1/check_mutations.py
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/support-paths-v1/check_references.py
```

The [command runner](run_checks.py), [commands](commands.json), raw logs and
compressed JSON outputs retain exact executable, arguments, working directory,
environment, exit status and timing. The only local optional gap is the absent
real-model `[st]` extra; the mandatory remote semantic-model/local-trust job is
reported separately. No model download/provider call was enabled locally.
The full historical synthetic harness is rerun only as an already exposed
regression; it is never counted as new final data. The new tool and its source
verifier never open labels or evaluation-source files.

Observed on the frozen implementation:

| Check | Actual result |
| --- | --- |
| Full local suite | **2,182 passed / 10 optional `[st]` skips / 1 existing Starlette deprecation warning**, 831.69s |
| Focused source/path/workflow checks | **117 passed**, including the 18 new instances |
| Strict local integrity matrix | **55 passed; 41/41 applicable cells**, 13 declared technical N/A; final independent integrity gate remains unmeasured |
| New X1/Y1 execution | Complete, no error; 15 versions / 16 scripted events; one withdrawal candidate, untruncated comparison |
| Known reviewed development replay | 13/13 cases completed; all original inputs and normalized alerts identical |
| Smoke / controls / workflow / production / dependency consistency | All five commands exit 0; execution success does not make semantic release gates pass |
| Historical verifiers | Six pass at their appropriate original heads |
| CI on `1bddddc` | All **15 checks pass**, including real-model/local-trust and seven advisory profiles: [CI](https://github.com/SaltKing0/graph-engine/actions/runs/39147111415), [advisories](https://github.com/SaltKing0/graph-engine/actions/runs/39147111429) |

The 18 new regression instances include 13 rejected source/role mutations.
The recorded-artifact checker separately rejects 13 mutations to source meaning,
review inheritance, history, support membership and claimed acceptance. These
are guard checks on the same known development input, not new independent
cases, semantic scores or measured benefit. Two successful pre-freeze
[authoring runs](prototype-attempts.json) of that same event are retained with
actual dirty-code metadata. The initial license-copy path error and correction
are retained in [the authoring note](authoring-note.txt).

Six [historical checks](historical-commands.json) pass in isolated checkouts at
their original heads: no-op/structured at `fb2fff2`, reviewed development/PR
review/solo at `3090863`, and the original withdrawal audit at `ad757775`.
Historical manifests, reports and fingerprint checks are preserved unchanged;
those passes are explicitly historical evidence, not reruns of old tools against
the new implementation.

## Acceptance and next step

Delivered for this development step: separately cited paths; explicit withdrawal
with remaining support; a versioned Y1-only basis; fresh bounded developer
review; proposed successor decision; preserved history and review decisions.

**The historical standard source-change diagnostic still fails 5/95 false
alerts (5.26%) >5%; the empty proposed profile misses 3/3 positives.** The new
representation preserves a withdrawal warning and supplies its missing support
explanation; it does not make that gate pass. The earlier 13-case reviewed
development replay remains a development observation. It cannot replace the
frozen gate or independent labels. Existing context truncation stays visible.

Independent final coverage is **0 positive / 0 negative / 0 inconclusive**;
independent source judgments/adjudication, execution/dataset-provenance review,
final corpus/freeze/candidate sign-off and actual user sessions/product benefit
remain absent. Statistical sufficiency and independently reviewed validity of
Y1 are unknown. The synthetic new-basis review establishes only the stated
fictional rule, not independent acceptance. No additional #90–#93 or #73
criterion is marked complete; the PR remains Draft and Decision Memory
experimental. No merge, activation of the successor decision, threshold change
or release occurs.

Next: a qualified human can inspect the cited conditions and remaining-basis
proposal. Independent-run credit requires actual execution/dataset artifacts
and separate review; the project owner still needs two qualified independent
reviewers and a custodian with separate evaluator-controlled storage for final
acceptance. Until then retain the unresolved finding and proposed successor;
continue only disclosed development work.

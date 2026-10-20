# Source-bound development observations

This is an engineering tool for [#91](https://github.com/SaltKing0/graph-engine/issues/91), not independent semantic acceptance. It captures and checks selected source-derived conditions, measurements and measurement-root identifiers from the already exposed development cases. The [saved report](decision-evaluation-results/false-alert-development-v1/structured-v1/README.md) preserves commands, raw proposals, errors and limits.

## Run and inspect

From the repository checkout with CONTRIBUTING.md dependencies, select a new output directory:

```sh
.venv/bin/python -m tools.decision_benchmark.structured_development --output /tmp/decision-observations-new
.venv/bin/python -m tools.decision_benchmark.structured_development --capture --output /tmp/decision-observations-capture-new
.venv/bin/python -m pytest tests/test_decision_observations.py -q
```

The first command validates the fixed development transcription and writes structural comparisons. The second additionally exercises public production proposals and both unchanged dependency-profile diagnostics. There is no final/evaluation split switch or arbitrary bundle path. Existing output directories and destinations within preserved corpus data are refused. No provider, model, network source fetch or user Brain is needed.

The output includes `report.json`, `transcriptions.json` and MIT notices. The report retains all thirteen known cases (five synthetic, eight actual repository development cases), source/input/code hashes, metadata, attempted profiles, errors, missing transcriptions, proposed records and complete immutable source-version records. Actual runtime identifiers/timestamps vary on rerun; deterministic input hashes, values, comparisons and normalized alert paths should match.

## Draft transcription contract

`tools/decision_benchmark/development_observations.json` is a separate, versioned implementing-agent draft. It does not replace original corpus files or contain expected impacts, valid decision paths or reviewer votes. Its author declaration explicitly remains non-human, non-independent and pending review.

Each source entry binds the exact source SHA-256 and selected facts. Atomic bindings contain a type, canonical value and exact original character offsets/quote. Measurements keep name, value, unit and sample count separate; missing units/counts remain null. Source availability, actual observation dates, reported execution code identity and applicability conditions are separate concepts. Git/source lineage is not automatically a measurement root.

The validator rejects changed quotes/hashes/values, omitted or invented sources, duplicate facts, extra gold fields, wrong types and fabricated reviewer status. Canonical decimal strings preserve numeric equality without rounding, while raw source lexemes remain available. Literal binding checks do not validate semantic role, completeness or truth. A selected quote could still be interpreted incorrectly; the draft needs review.

## Comparison and capture limits

The structural comparison reports exact declared-condition equality/differences, same or changed values under matching declared units, shared recorded root tokens and availability statements. It performs no unit conversion, does not infer independence from different root names and does not count repeated citations as independent confirmation. Missing fields remain unknown. It never emits a case-level gold outcome or proves that omitted constraints are absent.

Production capture proposes source records, a typed profile and evidence records in a separate test Brain. Profiles remain `proposed`; evidence remains `proposed` / `unassessed`; the capture path submits no review events. The official production comparator consequently reports unknown comparability. The original runtime diagnostics receive only their original source/task/dependency allowlist: transcriptions and structural conclusions never become runtime expected outcomes, accepted dependencies or alert filters.

The real graph-report artifact is a pre-existing repository document about known small synthetic retrieval fixtures. Its twelve selected means and actual n=2/n=10 counts are not new measurements or independent real-world evidence. Units, environment and measurement-root gaps remain explicit; unavailable `answer_correct_exact` is not zero.

The historical 5/95 false-alert result remains failed and the empty proposed dependency profile still misses 3/3 positives. Passing capture/schema tests is not passing independent semantic gates or demonstrating product benefit. Independent final coverage stays 0/0/0. #90–#93 and #73 remain open; Decision Memory stays experimental. Review source roles, complete conditions, units and root identity before developing authoritative integration, then retain independent final evaluation and user study as separate requirements.

## Explicit developer field review and source preparation

The separate opt-in runner now supplies a checked field mapping to the production diagnostic. The [saved field-review evidence](decision-evaluation-results/false-alert-development-v1/reviewed-v1/README.md) retains exact commands, raw outputs, source/version journals and remaining context/acceptance limits:

```sh
.venv/bin/python -m tools.decision_benchmark.reviewed_development --output /tmp/decision-reviewed-development-new
.venv/bin/python -m pytest tests/test_decision_reviewed_observations.py -q
```

`development_field_reviews.json` records the implementing agent's full-source field/completeness review for the ten already exposed synthetic basis/update documents. It binds exact source hashes, full original fact objects, fact hashes, local vocabulary namespaces and review explanations. This is an explicit trusted interpretation/configuration input, supplied separately from source documents; it is not automatic extraction, human review, independent gold or acceptance of the earlier proposed profiles. Ordinary production diagnostics and the structural capture command receive no field review and retain their original behavior. A source document cannot grant itself this review.

The review distinguishes the basis rule `recall >=0.7 fraction` from the observed `X1: recall=0.8`; the rule declares the metric's unit, not its observed value. Current X2 values are distinguished from quoted previous X1 values. The five applicability dimensions use the fictional experiment's local vocabulary. Source hashes identify exact text, while `run-X1` identifies only the explicitly referenced measurement within its reviewed namespace. Different roots do not prove independence. Y1's omitted individual fields remain unknown; its continuing availability does not prove sufficient support.

Before impact analysis, `production.execute(..., observation_review=...)` validates the exact complete chronological task sources and the reviewed fields. It retains an existing basis only when **every** statement in a reviewed complete update is established as the same declared value/sample under matching conditions and units, a measurement under explicitly different conditions with matching metric/units, or a citation of the same subject/root in the same reviewed namespace. Every applicable old measurement must be accounted for. No conversion, inferred unit, source-hash-as-root, automatic decision reversal or post-impact alert filter is used. An incomplete review, unknown unit/scope/root, changed value/sample, or availability change preserves the normal changed-basis review path. Updates are still captured as separate source proposals; existing basis references, dependencies and review history remain intact. Invalid or stale reviews fail explicitly and are retained as run errors.

The runner separately verifies all twelve existing JSON means by full dataset/adapter/metric paths, exact scalar/key coordinates, original decimal precision, sample counts and condition/code/protocol paths. Equal numeric text at another field is rejected; duplicate JSON keys are rejected. Missing units, environment and measurement roots remain null. Those report facts and the untranscribed project updates receive no runtime field review. No new measurements, answer scores or product benefit are inferred.

The output retains all thirteen known development cases and both dependency profiles, input/code/review/source hashes, raw production impact/queue/context outputs, retained basis and captured update references, and all errors. It has no final/evaluation option and no semantic scoring. Independent acceptance/coverage and user measurements remain absent. Historical reports and frozen thresholds remain unchanged; a development reduction in raw alerts does not replace the still-failed historical gate or satisfy the independent final gates.

The reviewed replay journals preserve every authorized immutable version and original scripted dependency event. Original input hashes and stored-node hashes stay separate: the existing Markdown serializer adds a terminal LF to each chunk. The verifier reconstructs that exact serialization; it does not normalize text or infer measurement roots from either hash.


## Known withdrawal and remaining support

The [source-bound withdrawal audit](decision-evaluation-results/false-alert-development-v1/withdrawal-v1/README.md)
resolves Y1's explicit same-conditions reference and declared metric unit:
0.8 >=0.7 meets the sole condition stated in that fictional source, and the
update says Y1 remains available. It does not prove reviewed measurement
independence, statistical validity or general decision sufficiency. No original
transcription/proposal is changed or accepted retroactively.

The contract retains a candidate that explains the loss and remaining support;
it does not silently preserve the old X1/Y1 basis after X1's withdrawal. The
current aggregate diagnostic lacks individual X1/Y1 evidence/support paths and
reports unknown comparability. Its warning remains. The separate opt-in
configuration below now supplies explicit per-observation support/availability
and review/versioning of the remaining basis. Independent human/provenance
acceptance stays open. The historical audit/replay itself remains unchanged;
only the new explicit configuration consumes its source-bound interpretation.

## Separate paths and a versioned remaining basis

The fixed, already exposed `controls-v2/event-surviving-support` case can now be
remodeled through the public proposal, review, compare and historical-read APIs:

```bash
.venv/bin/python -m tools.decision_benchmark.support_paths --output /tmp/decision-support-paths-new
.venv/bin/python -m pytest tests/test_decision_support_paths.py -q
```

Use a new output directory. This is an explicit synthetic developer wiring
configuration, not a general extraction feature or a replacement for the
original production diagnostic. It has no case, final-data or outcome option.
The immutable [source audit](decision-evaluation-results/false-alert-development-v1/withdrawal-v1/source-audit.json)
is validated against the frozen development sources before any brain write.
Its field-role validator is retained separately in the new tool so the original
audit and historical verification remain byte-for-byte reproducible.

X1 and Y1 have separate evidence and `supports` relationships to the original
basis. Both cite exact passages in the same complete original source. Their
source-declared `run-X1` and `run-Y1` labels remain interpretations; both paths
retain the **shared document identity**, with measurement independence explicitly
not inferred. No execution/result record is invented. Y1's condition citations
refer only to the five explicitly shared condition fields, not X1's measurement.
The unit comes from the same recall rule without conversion.

The later update creates an explicit X1 `availability=withdrawn` review event.
The actual comparison reports `basis_changed` and `support_withdrawn`, with X1
removed and Y1 remaining. It preserves the warning rather than declaring the
original aggregate basis unchanged. A confirmed, acknowledged finding and
`needs_investigation` decision conclusion retain the review requirement.

The claim successor has the original identity, exact predecessor and only Y1
plus the availability update as its new provenance inputs. It starts proposed
and unassessed; its new Y1 support starts proposed. Fresh scripted developer
events then assess the **source-declared** `0.8 >=0.7 fraction` predicate within
the five declared conditions. This establishes no real-world/statistical validity
or human acceptance. The old content, exact relationship endpoints and all old
reviews survive unchanged. After a fresh service session the old aggregate
assessment is visibly stale/inconclusive, while the newly reviewed scoped basis
is supported. A successor decision and dependency are **proposals**; they are
not activated and do not inherit the previous decision's reviews. The finding
is not resolved and is visibly stale after the successor basis; resolving it
would require a new comparison/review.

The report retains initial, withdrawal, successor-proposal and final journals,
exact references, comparison and historical reconstruction. This one remodeled
known event is not a new independent case or a comparable false-alert-rate
measurement; its graph differs from the original aggregate diagnostic. Frozen
thresholds, sources, labels, previous results and independent acceptance remain
unchanged. See [versioned execution evidence](decision-evaluation-results/false-alert-development-v1/support-paths-v1/README.md)
for commands, observed checks and remaining limits.

## Source review of the Y1 successor

The [source review](decision-evaluation-results/false-alert-development-v1/y1-basis-review-v1/README.md)
checks the exact recorded successor against the two known development texts.
It finds the **source-qualified fictional rule** consistent: Y1's declared 0.8
meets 0.7 fraction under the explicit shared conditions, and the update leaves
Y1 available at the fictional event. The unit is derived from the same metric
rule and the conditions from an explicit reference, not separately repeated
measurements. Those interpretations are recorded, not hidden as direct quotes.
Local condition IDs and run labels do not establish actual execution/dataset
provenance, statistical sufficiency or general decision validity.

No claim/source correction is required within this bounded scope. The source
review is an additional implementing-agent document, never independent gold
or a new runtime input. It does not change the existing 15 versions / 16 review
events or append an engine review. The successor decision/dependency remain
proposals; the stale finding remains unresolved and the old decision needs
investigation. Independent acceptance and the original failed/unmeasured gates
remain open. A fresh comparison and explicit authorized review would be needed
before any resolution or activation.

## Fresh comparison and open withdrawal finding

The [fresh comparison](decision-evaluation-results/false-alert-development-v1/y1-refresh-v1/README.md)
replays the same known case, explicitly maps its new references to the immutable
prior archive, and preserves the replay's actual Git state in a bundle. It
exposed and corrects missing successor review inputs in candidate freshness
pinning; the freshness/permission guards and all evaluation thresholds remain
unchanged. New assessments, source versions and support withdrawals still
invalidate the refreshed finding.

The initial-to-Y1 comparison yields three raw candidates; the post-withdrawal
interval yields two; the identical-Y1 interval yields zero. Old Y1 support is
stale at the old claim endpoint, while Y1 evidence remains available on the new
claim. Existing unknown-comparability/proposed-preview qualifications remain
visible. An explicit synthetic diagnostic review appends a fresh finding
version with workflow **open**; its old confirmed/acknowledged version remains
historical. The replay has 16 versions / 17 events, with the prior 15/16 prefix
unchanged. The successor decision and dependency stay proposed, the old decision
needs investigation, and activation, resolution and independent acceptance stay
open. This is not a new independent case, false-alert score or human sign-off.

## Review of the remaining claim and proposed dependency

The [two-candidate source and version review](decision-evaluation-results/false-alert-development-v1/y1-candidate-review-v1/README.md)
continues the exact restored Y1 state. The claim change is **confirmed/open** as
a material old-basis change. The proposed dependency is **inconclusive**, with
workflow null under the existing contract; it remains in the pending queue.
Its exact endpoints/context match the source-qualified Y1 basis, but neither it
nor the successor decision is accepted or activated. Raw `comparability_unknown`
and `proposed_preview` qualifications are preserved. A direct dependency path
without an evidential scope comparison is not proof of a source contradiction.

Exactly two scripted developer finding dispositions extend the journal from
16 versions / 17 events to 18/19, retaining the old prefix and withdrawal finding
unchanged. All three pending findings remain unresolved. The report, exact Git
bundle and source/read/retry guards are reproducible. Fresh focused verification:
32 tests passed, with one existing Starlette warning. This same known synthetic
case supplies no new independent case, semantic score or human judgment. Frozen
thresholds and the failed historical gate remain unchanged; independent
acceptance, decision/dependency adoption and activation remain open.

## Unsigned Y1 adoption decision

The [concrete adoption preparation](decision-evaluation-results/false-alert-development-v1/y1-adoption-plan-v1/README.md)
pins the exact successor decision, Y1 claim/support, proposed dependency, old
decision and all three unresolved findings. Recommendation now: defer execution
and present conditional adoption only within the known fictional rule and its
five conditions. Selected option, authorizer, reviewer and actual outcomes remain
unfilled. The JSON is a non-executable plan, not a signed API transaction.

Future authorization would require fresh dependency/successor reviews, followed
by one atomic old-current-to-superseded/new-proposed-to-current transaction.
The old `needs_investigation` conclusion is preserved: fresh nonterminal reviews
of that old content version are rejected by the existing writer. New outcomes
cannot automatically resolve old-target findings. All domain writes/dry runs are
blocked during preparation; the exact 18-version/19-event state remains intact.
Original artifact and captured-node hashes are checked separately with the exact
serializer-added newline retained. Independent acceptance, activation, resolution
and measured benefit remain open; no threshold or historical review is changed.

## Reviewed Y1 adoption scope and outcome conditions

The [source/protocol review and unsigned version 2](decision-evaluation-results/false-alert-development-v1/y1-adoption-review-v1/README.md)
address three preparation gaps without changing the archived original plan:
explicit scope at the fictional 2026-01-06 event, exact Y1 metric/unit/context
bindings, and explicit required future review outcomes with actual returned
event IDs. The unit comes from the same rule; condition fields come from the
explicit reference to the preceding context, not withdrawn X1 measurement data.
Current real-world availability and actual execution validity remain unknown.

The gate requires accepted dependency/successor workflow, a source-bounded
`remains_justified` conclusion, scope confirmation, actual authorization and fresh
heads. None is fabricated as an actual future review; all outcome/ID/authority
slots remain unfilled and execution prohibited. Unplanned changes stop the
process; planned review additions still require live comparison/revalidation.
Three explicit finding handoffs preserve their exact unresolved states and leave
owner assignments null. Five existing regressions pass and 11 malformed-plan
variants are rejected; these are engineering checks, not new independent cases.
The exact 18-version/19-event brain, sources, old reviews and thresholds remain
unchanged. Independent acceptance, activation, resolution and benefit stay open.

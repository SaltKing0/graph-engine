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
reports unknown comparability. Its warning remains. Next is explicit
per-observation support/availability and review/versioning of the remaining
basis, with independent human/provenance acceptance still open. The audit and
replay are documentation checks, never an alert filter or new runtime input.

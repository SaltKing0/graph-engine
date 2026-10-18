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

# Structured development observations — 18 October 2026

**Source-bound proposals and structural checks only. No independent semantic acceptance or passed false-alert gate.** This continues [#91](https://github.com/SaltKing0/graph-engine/issues/91) in [Draft PR #96](https://github.com/SaltKing0/graph-engine/pull/96), after the [no-op development correction](../README.md). The original diagnostic still fails at **5/95 false alerts (5.26%) > 5%**. No source, label, frozen threshold or historical report is replaced.

## Delivered scope

The implementation loads only the five known synthetic development events and the eight known real project development events. It never calls a label loader or opens evaluation-source files. There is no arbitrary bundle/final-split CLI option. The source-only boundary tests reject access to both bundles' labels and evaluation bytes. Independent successor data remains outside this workspace.

`tools/decision_benchmark/development_observations.json` is a new, disclosed implementing-agent transcription, outside preserved benchmark data. It inventories **30 known sources and 24 distinct facts**: 12 from fictional development sources and 12 from the already exposed real graph-report artifact. Eleven sources have selected transcribed facts; the other nineteen remain explicitly untranscribed. No selected set is claimed to be complete semantic extraction.

Every atomic subject, condition, metric name/value/unit, sample count, date, availability statement and measurement-root token has its own exact source character span and quote. Every source is pinned by SHA-256, original metadata and chronological availability. JSON numbers become exact canonical decimal strings without rounding; the original lexemes remain in the bindings. The old sources, labels and freezes stay byte-identical.

Validation checks schema/field types, source inventory, exact hashes/quotes/positions, numeric equality, required condition keys, date availability and the pending non-human/non-independent author declaration. It rejects gold outcome/path fields, missing/invented sources and fabricated reviewer status. **These checks validate the transcription's literal bindings; they do not establish that the implementing agent chose the correct semantic role, complete scope or sufficient evidence. Those still require review.**

## What the checks distinguish

| Known development input | Structural observation, not a scored semantic verdict |
| --- | --- |
| Comparable update | Different declared metric value under the same declared conditions/unit. No refutation or decision reversal is inferred. |
| Changed conditions | Explicit workload/corpus differences are retained, including any still-unknown dimensions. They cannot silently become comparable evidence. |
| Time-only update | Same declared value under the same declared conditions; the observation timestamp is separate from applicability conditions. No assertion about omitted time-validity constraints is made. |
| Citation copy | The same recorded measurement-root token is found in the selected old/new statements. It is not an additional independent confirmation. |
| Surviving-support example | X1 withdrawal and Y1 availability statements are bound separately to their literal source subjects and recorded old roots. They do not apply an actual withdrawal or prove Y1 independence. |
| Real graph report | Twelve pre-existing mean values from the report’s synthetic retrieval fixtures and their actual **n=2 or n=10** are retained. Unit/environment/measurement-root gaps remain unknown. `answer_correct_exact` is null/unmeasured and is never converted to a zero result. The dirty-source warning and recorded execution code hash remain explicit. |

The comparison uses exact declared identities and units, with no unit conversion, ranking rule, fixture-ID outcome lookup or natural-language truth inference. Missing fields and incompatible units remain unknown. Different root names do not prove independence; repeated names do not become independent votes. Multiple measurements remain separate rows rather than being collapsed into a favorable case outcome.

## Production capture and preserved warnings

The complete capture run first executes the existing production diagnostic independently for both curated and proposed dependency profiles, using the exact old source/task/dependency allowlist and budgets. **The transcriptions and their structural comparisons never enter that runtime input. No emitted alert is filtered.** The new report has no semantic `scores` field; it does not score its own proposals.

A separate dedicated test Brain uses the public `DecisionService.source`, proposal submission and inspection interfaces to capture exact source versions, a typed condition profile and evidence proposals. Original user Brains, source histories and review decisions are untouched. Source artifacts retain original locator/version/license metadata, measurement-root transcriptions are distinct from Git/source lineage, and MIT notices accompany the exported report.

Every new profile/evidence remains `proposed` and evidence remains `unassessed`. The capture path submits no review events. The official production context comparator therefore returns **unknown** even where the sidecar's literal field comparison finds a match. No profile is script-accepted to disguise missing human review. The original diagnostic's existing scripted acceptance of curated wiring links remains separately disclosed in its raw outputs; it is not human review of these new observations.

The report keeps the full immutable captured source-version records alongside the profile/evidence records, exact content references and source citations. This permits canonical version-hash/text-hash and quote verification after the temporary test Brains are removed. Source Git commits and runtime UUIDs/timestamps differ on rerun; deterministic source hashes, declared fields and normalized original alert paths remain reproducible.

## Validation and evidence

Measured final clean code: `016c52c5e6ab9ffd7c04a09ae870bc15da24e6f5`. All exact argv, return codes, durations and local environment are in [commands.json](commands.json) and [environment.json](environment.json). [manifest.json](manifest.json) binds stored/decompressed bytes and measured code. [Raw complete report](capture-report.json.gz) contains all attempted cases, raw runtime output/errors, proposed records, comparisons, source manifests and omissions. [Original transcriptions](transcriptions.json) remain unreviewed input drafts rather than expected outcomes.

| Check | Actual result |
| --- | --- |
| Full local suite, Python 3.12.14 | **2126 passed, 10 skipped, 1 warning in 672.05s (0:11:12)** |
| Focused observation/no-op/workflow/solo tests | **61 passed** |
| Strict engineering matrix | **55 passed / 41 applicable cells**, 13 technical N/A, no skips/deselections |
| Complete capture replay | **13 cases × 2 unchanged dependency profiles**, no runtime/capture errors |
| Memory smoke / frozen Decision Memory controls | Exit 0; execution integrity only |
| Complete imported-document workflow | Exit 0; **7/7** checks |
| Known synthetic production controls | Exit 0; false-alert gate still **fail 5/95**, empty proposed profile still misses 3/3 |
| Package consistency / three previous evidence verifiers | All exit 0 |


The final complete capture executes **13 already exposed cases × 2 dependency profiles**. Synthetic controls account for 50 eligible pairs per profile; real development accounts for 27. These strata are never combined into a semantic score. Each context-specific replay is a repeat, not new independent coverage. Repeated proposal counts do not turn the 24 unique source facts into additional independent evidence.

The final replay retains **13/13 original input hashes and normalized alert outputs** (verified independently against the preserved no-op run). It writes **13 proposed profiles / 142 context-specific evidence proposals / 992 replayed source versions**, with no capture errors or review events. There are still **13 curated raw alerts and zero alerts in the empty proposed profile**. Official comparability remains unknown in every capture. These replay counts are not independent cases, new experiments or human judgments.

All **15 CI checks passed on measured code 016c52c5e6ab9ffd7c04a09ae870bc15da24e6f5**: [CI](https://github.com/SaltKing0/graph-engine/actions/runs/39138369551), [seven dependency audit profiles](https://github.com/SaltKing0/graph-engine/actions/runs/39138369563). Exact checks and jobs are retained as `ci-checks.json` / `ci-run.json`. Later changes add documentation/evidence only; runtime, tools, data and tests must remain byte-identical to this measured code.

Prototype failures are retained separately: an initial test incorrectly assumed all real samples were n=2 (the transcription correctly contained n=2 and n=10); a multi-chunk capture test detected incorrect indentation trimming in the new prototype's quote-coordinate mapping. Both were corrected. The earlier c857997 capture completed all 13 cases before the full source-version journal was added. Its local full-suite attempt was interrupted when that audit gap was identified and is not claimed as a final full pass. Complete final runs use a new output directory and the final clean commit above. No preserved prior report was rewritten.

Here “real project” denotes an actual repository artifact; the graph report itself uses the known small synthetic retrieval fixtures. It is not an independent real-world semantic evaluation.

The environment metadata was corrected before publication using the actual `.venv` interpreter used by every command. The initial system-interpreter metadata writer is retained separately; it does not describe the test runtime.

The local optional model skips are separate from strict real-model/trust CI coverage. No paid provider, reserved successor case, independent annotator/adjudication, frozen final comparison, exhaustive final-candidate sign-off or user session was supplied. Human review time, independent semantic correctness, unsupported-conclusion judgments and product benefit remain unmeasured. The empty proposed profile still lacks accepted dependencies; zero alerts there are not successful extraction or recall.

## Reproduction and next boundary

From a checkout with CONTRIBUTING.md dependencies, create a new output directory:

```sh
.venv/bin/python -m tools.decision_benchmark.structured_development --capture --output /tmp/decision-structured-new
.venv/bin/python -m pytest tests/test_decision_observations.py -q
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/structured-v1/verify_evidence.py
```

Without `--capture`, the CLI exports and validates the fixed development transcription and computes structural comparisons only; it does not claim a production run. Existing output directories and destinations inside preserved corpus data are refused. Report license notices and source manifests travel with exported results.

The next boundary is explicit review of the proposed field roles, scope completeness, units and root identity before using them as authoritative runtime interpretations. A reviewed profile and source-grounded generic integration can then be developed and tested while keeping gold impacts separate. Final acceptance still requires #90's qualified independent reviewers/corpus custody, fresh controlled final cases/adjudication, the frozen matched comparison and separate user study. #90–#93 and #73 remain open; no additional acceptance checkbox is completed by these implementing-agent proposals. Decision Memory stays experimental. No merge or release is included.

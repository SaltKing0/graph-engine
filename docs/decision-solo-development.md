# Solo Decision Memory development and integrity inventory

Status: **engineering development only; keep experimental**. This is the solo
work authorized on 18 October 2026 alongside [#90](https://github.com/SaltKing0/graph-engine/issues/90),
[#91](https://github.com/SaltKing0/graph-engine/issues/91) and
[#92](https://github.com/SaltKing0/graph-engine/issues/92), under epic #73.
It does not replace the [frozen acceptance gates](decision-memory-v1.md#evaluation-gates-frozen-before-tuning).

## Source review with no invented reviewers

The [versioned source notes](decision-evaluation-results/solo-development-v1/source-notes.json)
cover all **eight previously exposed development events and 27 eligible pairs**.
They contain 54 exact source/version/UTF-8-byte quote references, source relevance,
the observed implementation change, remaining-support limits and missing facts.
Their author is the implementing agent. They are not human calibration, separate
reviewer judgments, adjudication or independent new evidence. Prior exposure to
the original design, sources and aggregate diagnostics is disclosed.

All working outcomes remain inconclusive: the source packets do not supply
independently reviewed condition profiles or accepted historical dependency
paths. A code patch or absent cross-family link cannot establish a semantic
contradiction or a conclusive negative. The notes distinguish implementation
relevance from impact, and original documentation from actual historical review.
These eight cases must not count toward independent inconclusive coverage.
Original project-v1 labels, freezes and sources remain unchanged.

| Development event | Source-only observation | Remaining decision-review question |
| --- | --- | --- |
| graph-1 | Strict MCP CI adds graph retrieval tests. | No new real-document benchmark or general graph benefit is reported. |
| graph-2 | Search CLI accepts intermixed arguments. | Parser behavior is not evidence of answer-quality improvement. |
| documents-1 | Retry rejects conflicting capture linkage and repairs derived indexing. | Does the exact recovery/receipt dependency change the documented import justification? |
| context-1 | Authorization builds operation-local derivation/provenance views. | Which context decisions actually depend on the changed authorization behavior? |
| documents-2 | Incomplete capture blocks retrying extraction. | The missing recovery preconditions need source-grounded review. |
| cache-1 | Raw vectors are distinguished from validated model-bound cache entries. | Which freshness assumptions and consumers are affected? |
| cache-2 | Empty-corpus model initialization is avoided; query text is normalized. | The patch supplies no new performance or answer-quality measurement. |
| context-2 | Filtered corpora bypass ordinary indexes before scoring. | Temporal filtering changes scope/cache inputs; indirect decision paths remain unreviewed. |

Reproduce the bounded diagnostic using **only exposed development sources**:

```bash
.venv/bin/python -m tools.decision_benchmark.solo --output /tmp/decision-solo-development.json
```

Use a new output path. The tool opens no label file or evaluation-source bytes.
It verifies all notes/references and reconstructs the exact original
chronological source/chunk/task/dependency allowlist. Both curated and proposed
profiles still use production proposal/review/impact/context interfaces. Old
manual topic attachments are script-accepted for wiring only; no historical
human acceptance is invented. Proposed inputs stay separate and empty unless
actually supplied. Expected outcomes, rationales and paths from the notes never
enter runtime inputs. A canary regression checks that boundary.

The run preserves source/code/configuration hashes, raw outputs, failures and
stage timings, with semantic quality, human calibration and user time null.
It does not score its own notes. Independent final coverage remains 0/0/0.
No final-corpus or provider option is added.

## Diagnosis and bounded production corrections

The original synthetic diagnostic still reports **5/95 false alerts (5.26%)**,
above the frozen 5% ceiling. Its old sources, labels and reports remain intact.
The five known negative controls are changed conditions, unchanged observation
at another time, duplicated measurement lineage, unrelated palette spacing and
formatting-only source change. The diagnostic attaches each update to a basis
claim without interpreting its semantics. In that representation the engine
sees a changed, explicitly linked basis with unknown scope. Guessing negative
scope, removing warnings or tuning by case ID would not repair this input gap.

| Stage | Engineering finding and disposition |
| --- | --- |
| Source/proposal preparation | Real packets lack independently reviewed semantic proposals. Preserve exact chronological sources; do not fabricate interpretations. |
| Condition/comparability | Missing typed profiles remain unknown. No fuzzy whitespace, unit conversion, workload equivalence or hidden comparability inference is introduced. |
| Dependency capture | Original curated links are manual draft topic attachments; proposed dependencies remain separately supplied. No gold path is inserted. |
| Delta classification | A pure CRLF→LF change in claim text incorrectly produced an impact candidate. The existing named CRLF rule now covers claim text too, only if all other payload/provenance fields are identical. The informational delta remains. |
| Impact propagation | Traversal keyed only by record discarded a second path when dependencies reconverged. Bounded distinct routes now survive and are grouped into one candidate per decision version. All retained path qualifications and support remain visible. |
| Context/UI | A historical comparison's brief button requested HEAD. It now requests the comparison's exact after revision. Current review detail may still display current successors alongside pinned objects; this is labelled separately from the historical brief. |

Content versions and review histories remain immutable. Cosmetic handling does
not accept a successor or transfer prior review. Real wording, conditions and
provenance changes still generate candidates. Aggregated paths retain the same
finding series and old exact reviewed payloads; a new version does not inherit
an acknowledgment. Legacy single-path findings remain readable.

Alternative paths must also fit the unchanged **200-reference storage bound**.
If necessary, complete paths are omitted as units and `candidate_refs` marks
the comparison incomplete. A candidate that cannot fit even one path is omitted
with that warning; the delta remains. Retained path counts and existing object,
link/depth/path limits remain bounded. Truncation cannot establish no impact and
must remain visible in scoring. No threshold or persistence limit is relaxed.

These are functional development regressions, not evidence that semantic
held-out gates or user-benefit gates passed. The source-change diagnostic's
false-alert result is not replaced by scores from the new authored tests.

## Explicit scenario-by-interface inventory

The [machine-readable matrix](decision-integrity-matrix-v1.json) enumerates nine
concrete scenario families across six surfaces: **54 cells, 41 applicable and
13 declared not applicable**. Each cell records its operation, preconditions,
expected invariant, actual evidence selectors and scope. Inapplicability has a
technical reason; it is not recorded as a successful execution.

| Scenario | Service/storage | CLI | HTTP | MCP | Browser | Context/brief exports |
| --- | --- | --- | --- | --- | --- | --- |
| Current ACL revocation, including a second derivation source | test | test | test | stdio test | UI test | test |
| Tombstone before live/historical typed projections | test | test | test | stdio test | UI test | test |
| Source successor and unchanged old versions/reviews | test | test | test | stdio test | UI test | test |
| Explicit merge of a version-pinned node | test | test | N/A | N/A | N/A | N/A |
| Historical payload/brief after later edits | test | test | test | stdio test | UI test | test |
| Stale review generation/source basis | test | test | test | N/A | UI test | N/A |
| Fresh versus dependent review correction/undo | test | test | test | N/A | N/A | N/A |
| Interrupted publication and durable retry | storage boundaries | CLI parser/output | HTTP 502/receipt | N/A | finding publication failure | N/A |
| Concurrent writers and conflict/retry | persisted generations | two processes | synchronized workers | N/A | two tabs | N/A |

MCP exposes typed Decision Memory **reads**, with generic memory remember/forget
as separate tools; no typed proposal/review/undo mutation is implied. HTTP and
browser have no explicit generic node-merge operation. Context/brief exports
are read-only. The decision UI does not expose raw assessment-event undo.
These are operation-specific reasons, not permission to omit read projections;
ACL, tombstone, edit and history reads are separately exercised on every surface.

CLI read/write tests use actual subprocesses, except the documented injected
CLI publication-failure case, which uses its real parser/output in process.
MCP reads use actual CLI stdio JSON-RPC sessions. HTTP adapter cases use ASGI
request/response and middleware; browser cases add real local TCP/Chromium DOM
interaction. Shared service tests are not labelled transport coverage.

Recovery tests cover pre-sidecar interruption, durable index/commit failures,
and a real browser finding-review failure after publication. Concurrency uses
explicit start barriers for two CLI processes, HTTP workers or browser requests.
The browser requests/responses are not mocked. Assertions check actual stored
generations, immutable review targets, receipts and histories. Scripted role
names and browser actions are test fixtures, not participants or reviewer sign-off.

Run the declared inventory with all required transports installed:

```bash
GRAPH_ENGINE_TEST_D3=/tmp/graph-engine-d3.v7.min.js \
PLAYWRIGHT_BROWSERS_PATH=/tmp/graph-engine-playwright \
.venv/bin/python -m tools.decision_integrity --output /tmp/decision-integrity
```

Use a new directory. The runner validates all cell references, invokes exact
pytest selectors with `--fail-on-skip`, and records actual setup/call/teardown
outcomes, JUnit, commands, dependencies, platform and code/configuration hashes.
Missing tests, empty observations, skips and teardown failures cannot pass a
cell. The dedicated CI job uploads that report.

This is a **bounded engineering inventory**, not an independently approved
exhaustive definition of every failure scenario. Scenario sufficiency and the
N/A declarations still need review. `software_matrix_complete=true` means all
declared applicable cells have executed successfully. Final integrity sign-off
remains null because #91's independently evaluated final candidate is absent.
Relevant later changes require revalidation on that candidate. No OS-level
failure at every machine instruction is claimed.

## Handoff and remaining acceptance

See the [saved development results](decision-evaluation-results/solo-development-v1/README.md)
for exact runs and limitations. #90 remains open: no second reviewer,
adjudication or fresh final family is invented. #91 final matched semantic
comparisons and #92 final-candidate sign-off remain open. #93's controlled
human exercise and product benefit remain unmeasured. Decision Memory stays
experimental. Merge, version/tag changes and releases remain separate actions.

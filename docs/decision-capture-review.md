# Source-grounded capture and decision review

Issue #77 exposes `DecisionService(brain)` through `ig decision` and HTTP. It
uses the [v1 contract](decision-memory-v1.md) and
[versioned store](decision-memory-storage.md). These operations need no provider,
embedder, model, network evidence fetch or research-code execution. There is no
configured extraction adapter in this surface. Users and agents supply the same
bounded structured envelope; interpretation and rationale remain proposals.
`tools/ig_cycle.py` retains its existing protections. The separate typed path
accepts legitimate negative findings, including “nicht” and “falsch”.

## Local sources and the shared service

Import existing local documents first, without extraction:

```sh
ig import notes.md --json
ig import benchmark.json --extensions .json --json
ig decision source doc-RECEIPT-ID > source-payload.json
ig decision preview > preview.json
```

JSON is an explicit UTF-8 text import option; its contents are inert, including
commands, URLs, floats and errors. The default extension selection stays `.md`
and `.txt`. Import receipts preserve the raw-file SHA-256, parser, chunk/page,
character and line locations. `source` returns the exact stored node body,
including trailing newlines, plus its body SHA-256 and import metadata in
`artifact.extraction`. Evidence offsets refer to this returned body, in Unicode
code points with an exclusive end. Imported chunk offsets refer separately to
the original document. The raw-file hash is a recorded import identity, not a
claim that the original file remains available. No source locator is opened.

For Python, construct `DecisionService` with the existing namespace-selected
`Brain`/`SecuredBrain`. `preview()`, `source(node_id)`, `pending()`, `inspect(ref)`
and `result_draft(envelope)` are read-only. `submit(envelope, dry_run=False,
commit=True)` is the sole mutation method. It holds the same-brain writer guard
through validation and publication, including inherited authorization and sync.

## Capture envelope

```json
{
  "schema": "dm.proposal/1",
  "idempotency_key": "capture-unique-key",
  "expected_generation": 0,
  "expected_heads": {},
  "versions": [{
    "id": "00000000-0000-4000-8000-000000000001",
    "kind": "claim",
    "anchor_node_id": "claim-diagnostic",
    "previous": null,
    "provenance": {"method": "manual", "inputs": []},
    "payload": {
      "text": "This diagnostic does not establish production readiness.",
      "context": null,
      "limitations": ["Scope is unknown until reviewed"]
    }
  }]
}
```

Copy the actual generation/heads from `preview`; these are optimistic concurrency
preconditions, including current policy and source hashes. Content draft fields
and kinds are the storage contract's `decision_schema.PAYLOADS`: source, profile,
claim, evidence, check, result, decision and relationship. New content is proposed,
claims/evidence are unassessed, and decisions are proposed. Submission never
accepts a support/opposition/dependency link or supplies an epistemic judgment.

```sh
ig decision propose proposal.json --dry-run
ig decision propose proposal.json
ig decision pending
ig decision inspect ref.json
```

An evidence payload includes `interpretation`, `context`, `sources`, `lineage_ids`
and `limitations`. Each source entry is `{"ref": exact_ref, "passage":
{"start": 0, "end": 10, "quote": "Der Ansatz"}}`. A null passage cites the pinned
artifact locator or result as a whole. Quotes must match the exact source version;
validation alone grants no support. Multiple source entries remain separate.
Shared `lineage_ids` expose common lineage; empty lists mean unknown independence.
Inspection reports source lineage and `independence: "not inferred"`, never a
citation-count confidence score.

A single atomic envelope can include multiple new records. Use an explicit
`{"local": "UUID-of-an-earlier-draft"}` in place of an exact version reference
inside later payloads/provenance. Forward references and cycles fail. This lets
source → evidence → relationship be submitted together despite server-assigned
version hashes. The receipt returns exact refs in draft order. Dry-run refs use
preview time and must not be treated as published refs. References to existing
records must pin their exact current versions; obsolete sources or claims fail.

To edit content, reuse its logical `id` and anchor, and set `previous` to its exact
last ref. New versions start with fresh review state. Reviews never retarget old
evidence or transfer an assessment to the new wording/scope.

## Explicit review, correction and freshness

```json
{
  "schema": "dm.review/1",
  "idempotency_key": "review-unique-key",
  "expected_generation": 1,
  "expected_heads": {},
  "events": [{
    "subject": {"id": "00000000-0000-4000-8000-000000000001", "version_id": "sha256:REPLACE_WITH_RECEIPT_HASH"},
    "axis": "workflow", "from": "proposed", "to": "accepted",
    "previous_event_id": null, "basis": [],
    "reason": "Acknowledged the captured claim; truth has not been assessed.",
    "supersedes_event_id": null
  }]
}
```

```sh
ig decision review review.json --dry-run
ig decision review review.json
```

Use fresh preview heads and inspect the subject before constructing the event.
Reviewer identity and UTC time come from the authenticated brain, never a
client-supplied actor or timestamp. Independent contract-defined actions are:

| Axis | Explicit action |
| --- | --- |
| `workflow` | `proposed → accepted/rejected`: acknowledge/accept or dismiss the capture/link. This does not assess a claim. |
| `epistemic` | Record `supported/opposed/mixed/inconclusive` with exact evidence and rationale. |
| `availability` | Withdraw evidence/link, or restore it with a fresh review. |
| `decision` | Activate a proposed decision, withdraw it, or atomically supersede it while activating its exact successor. |
| `decision_conclusion` | Record `remains_justified/needs_investigation/revise`; “revise” does not activate another decision. |

Basis entries are `{"type":"content_ref","ref": exact_ref}`,
`{"type":"event_ref","event_id": "UUID"}` or a pinned `source_ref` as documented
by storage. Pin the acceptance/assessment **event** when relying on a judgment;
a content reference alone does not assert its acceptance or assessment. An
activated decision's justification should pin its necessary claims, dependency
links and the enabling judgment events. Changed evidence makes the old support
inconclusive; it never manufactures positive counterevidence or reverses a choice.

Support/opposition relationships capture the proposed judgment in `explanation`
and `context`. Inspection reports computed `comparable/disjoint/unknown` with
reasons. Acceptance requires a currently accepted profile (pin its acceptance event in the
review basis), comparable typed conditions and a relationship context restricted to their exact intersection.
Unknown profiles/conditions and known disjoint observations can reach review;
they cannot be accepted as support/opposition. Claim assessments other than
inconclusive also require evidence/results in comparable scope. Failed or
inconclusive runs cannot establish support/opposition or a conclusive assessment.
No similarity score or matching quote can substitute for explicit review.

Undo is another event, preserving the exact original basis, with
`supersedes_event_id` and `previous_event_id` equal to the event being corrected,
`from` equal to its `to`, and `to` equal to its `from`. The store rejects undo of
an event already used by a dependent review, changed content/basis, or a stale
chain. Use a new content version and review when guarded undo no longer applies.
Multiple supersession events belong in one review envelope.

When a review adds sources to a previously referenced claim, the writer also
adds the inherited source restrictions to existing dependent anchors. The entire
publication requires write authorization to those affected records and sources;
it fails without partial review publication when a dependency cannot be written.
Pre-existing missing lineage/tampering is never repaired by this propagation.

## Benchmark JSON mapping and strict result envelope

The generic adapter validates a manually mapped, versioned result envelope:

```json
{
  "schema": "dm.result-import/1",
  "id": "00000000-0000-4000-8000-000000000002",
  "anchor_node_id": "run-1", "previous": null,
  "payload": {
    "check": {"id": "CHECK_UUID", "version_id": "sha256:CHECK_HASH"},
    "outcome": "error", "context": null,
    "metrics": [{"name": "recall_at_k", "unit": "fraction", "value": null,
                 "denominator": null, "reason": "Run failed before measurement"}],
    "metrics_reason": "Execution failed", "errors": ["Recorded runner error"],
    "sources": [{"id": "RAW_SOURCE_UUID", "version_id": "sha256:RAW_SOURCE_HASH"}],
    "execution": {
      "code": null, "data": null, "environment": null, "configuration": null,
      "command": null,
      "raw_outputs": [{"id": "RAW_SOURCE_UUID", "version_id": "sha256:RAW_SOURCE_HASH"}],
      "observed_at": null
    },
    "limitations": ["No completed measurement; no refutation"], "hypothetical": false
  }
}
```

`ig decision result-draft result.json` returns a validated result content draft;
insert it in a proposal envelope to publish. The HTTP equivalent is read-only too.
The check and raw source refs must exist and be accessible. Both `sources` and
`execution.raw_outputs` must be nonempty. Preserve all artifact chunks when the
report is split; do not invent a complete raw artifact from one truncated chunk.
Metric values are canonical decimal **strings**, including `"0"`; null requires a
specific `reason`. Zero must never substitute for unmeasured data. A positive
`denominator` is optional. `errors` is a bounded list; missing execution identity
remains null. Commands are inert strings. Existing records without null metrics
or `errors` retain their meaning.

Map existing GraphEngine reports as follows. This is a documented explicit
mapping, not an automatic schema guesser or a benchmark executor:

| Existing report | Mapping into the strict envelope |
| --- | --- |
| `tools.memory_benchmark`, `report_schema_version=1` | `metadata.code_sha256` → `execution.code`; `metadata.dataset_sha256` → `execution.data`; preserve `source_commit/source_dirty` as context dimensions/limitations. Select each question/adapter row and its metrics, denominator and units explicitly. Copy row errors. `prepared/running` → inconclusive; row failure → error; complete successful row → completed. `completed_with_errors` never means all rows succeeded. |
| `tools.decision_benchmark`, `schema=dm.eval.report/1` | `metadata.code_sha256` → code; `metadata.freeze_sha256` → data (identify it as the corpus freeze hash). Preserve corpus version, split, `kind`, frozen files, configuration and limitations. Scoring ratios retain numerator/denominator; null scores stay unmeasured. Draft-label/project-corpus results do not become measured extraction quality, human effort or release readiness. |
| `tools.retrieval_benchmark`, `schema_version=1` | `environment.code_sha256` → code; preserve environment, synthetic fixture ID, mode, seed, corpus size, operation, warm/cold definition and sample counts as conditions. Copy each selected timing/statistic with its unit, e.g. milliseconds. Missing dataset hash stays null. Correctness mismatches and measurement errors stay explicit; latency is not answer quality. |
| `docs/graph-retrieval-benchmark.json` | `source.code_sha256` → code; each dataset's dataset hash → data; preserve its per-run configuration, paired graph setting, workload and exact aggregation method. Dirty source state stays explicit. Its synthetic diagnostics never establish real-document readiness. |

For all formats, `execution.configuration` records the SHA-256 of the explicitly
selected configuration's stable JSON serialization (document the serialization,
e.g. `json.dumps(config, sort_keys=True, separators=(',', ':'), allow_nan=False)`);
retain the original configuration in the pinned raw source and typed conditions.
Copy an existing supplied configuration hash verbatim when present rather than
silently replacing its hashing scheme. Preserve known code/data/environment
identifiers verbatim, recording hash kind in the condition name or value. Never
claim a hash was independently verified or fill unknown metadata from this
machine. Convert finite JSON numeric measurements with `Decimal(str(value))` to
fixed-point canonical decimal strings without exponent, padding or negative zero.
Reject NaN/infinity. Keep nulls, denominator definitions, errors, unanswerable
cases and partial runs distinct. Raw artifact refs preserve all original fields,
including code/config manifests that exceed the display/condition limits.

## HTTP and failure behavior

HTTP uses the server's existing graph selection, bearer authentication and
`SecuredBrain` policy when `IG_ACCESS_POLICY` is configured. The local unprotected
server retains its existing trusted-local behavior; configure policy before
exposing HTTP. No endpoint constructs the model-bearing engine.

| Method and path under `/api/decision-memory` | Shared operation |
| --- | --- |
| `GET /preview`, `GET /pending` | Preview or list inspectable pending heads |
| `GET /sources/{node_id}` | Capture source payload without writes |
| `POST /inspect` | Inspect the exact ref supplied as JSON |
| `POST /result-draft` | Validate/convert `dm.result-import/1` |
| `POST /proposals`, `POST /reviews` | Submit the respective envelope; `?dry_run=true` validates only |

Responses are `Cache-Control: no-store`. Malformed input is 400, unavailable or
unauthorized references are 403 without hidden payloads, stale previews are 409,
and a busy writer is 503. Envelope parsing rejects duplicate keys, floats,
unknown fields, oversized/nested structures and unsupported versions. Bounds are
64 MiB, 200 drafts/events per submission, 200 references per record and 32 nesting
levels, plus the store's total-item bounds. Dry runs validate source locations,
permissions, refs, proposed effects and review preconditions without initialization,
pull, model calls, writes or publication. Authentication auditing follows existing
policy.

Retry the **identical** envelope and key, including the old preview, to get the
durable receipt; a changed envelope with the same key conflicts. Retries recheck
current permissions and cannot duplicate evidence or reopen rejected assessments.
A failure after publication returns `published_locally: true` and its receipt
(HTTP 502 / CLI nonzero). Retry to recover that receipt, then inspect and explicitly
sync using the existing brain operations. Source changes are not silently retried
against a new basis. The focused no-provider regression scenario is in
`tests/test_decision_service.py`; it runs imported source → multi-record proposal →
explicit decision review → changed evidence → stale-review rejection.

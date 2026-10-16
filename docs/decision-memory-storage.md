# Decision Memory storage

Issue #76 adds an opt-in Python storage boundary, `brain.decision_memory()`.
Its data contract is [Decision Memory v1](decision-memory-v1.md). It does not
change default recall, convert legacy facts, execute commands, fetch evidence,
or invoke a model. Proposal/review adapters, comparison rules, classified deltas,
impact candidates and briefs belong to the subsequent work packages.

## First record

```python
from uuid import uuid4
from graph_engine.brain import Brain
from graph_engine.decision_schema import SCHEMA

brain = Brain('/absolute/path/to/your/brain', mode='local')
store = brain.decision_memory()
preview = store.preview()  # No initialization or file writes.
request = {
    'schema': SCHEMA,
    'idempotency_key': str(uuid4()),
    'expected_generation': preview['generation'],
    'expected_heads': preview['heads'],
    'versions': [{
        'id': str(uuid4()),
        'kind': 'claim',
        'anchor_node_id': str(uuid4()),
        'previous': None,
        'provenance': {'method': 'manual', 'inputs': []},
        'payload': {
            'text': 'This observation applies only to the supplied workload.',
            'context': None,  # Unknown scope, never inferred from text.
            'limitations': ['Not a production result'],
        },
    }],
    'events': [],
}
receipt = store.transact(request, commit=False)
view = store.get(receipt['refs'][0])
assert view['effective_assessment'] == 'unassessed'
```

Production callers should use the same `Brain` / `SecuredBrain` selected by the
existing namespace/authentication boundary. Constructing an unprotected `Brain`
is trusted local filesystem access, not an alternative authorization adapter.
`commit=True` is the default; Git-mode commits/sync follow the existing brain
configuration. Local mode has version history but no Git revision snapshots.

`preview()` returns generation and opaque expected heads, including exact
current source-body hashes and, in protected mode, a policy fingerprint. Pass
these values back unchanged. Content drafts supply the six fields above;
server time, authenticated actor and SHA-256 version identity are assigned by
the store. IDs are canonical UUID strings. Updating a logical record reuses its
ID and anchor and sets `previous` to its exact last `{id, version_id}`. New
versions start with their own initial review state. Recording source versions
before consumers permits exact immutable input references without circular
content hashes.

Use `source_payload(node_id, locator=..., lineage_ids=..., artifact=...,
revision=...)` to capture a node's exact UTF-8 Markdown body, including trailing
whitespace and newlines. The source draft's anchor must equal that node ID.
A supplied full Git revision must resolve locally and match the exact committed
body; no fetch occurs. Evidence `sources` entries are
`{'ref': source_or_result_ref, 'passage': {'start': 0, 'end': 5, 'quote': 'exact'}}`.
Offsets are Unicode code points, end exclusive. A null passage cites a source's
artifact/display locator or an exact result. Locators are labels; they never
authorize opening a file or executing code. Supplied artifact hashes are recorded
provenance, not a claim of independent verification or current availability of
external bytes. Empty lineage lists mean unknown independence.

The strict payload field sets are in `decision_schema.PAYLOADS`. A check's
`metrics` contains `{name, unit}` definitions; a result's `metrics` contains
`{name, value, unit, denominator}`, with canonical decimal strings. Execution
identity fields are `code`, `data`, `environment`, `configuration`, `command`,
`raw_outputs` (exact source refs) and `observed_at`; unknown values remain null.
`outcome` is `completed`, `inconclusive` or `error`; empty metrics require
`metrics_reason`. `hypothetical` is mandatory and propagates through content
inputs. A hypothetical basis cannot establish support or justify a real choice.
None of these fields causes execution.

## Review storage and freshness

Event drafts supply `subject`, `axis`, `from`, `to`, `previous_event_id`,
`basis`, `reason`, and `supersedes_event_id`. A basis entry is a tagged
`content_ref` with `ref`, `event_ref` with `event_id`, or `source_ref` with `ref`.
The store assigns reviewer/time and event identity. Event UUIDs use UUIDv5 over
the canonical event envelope excluding `event_id`; this detects manual event
edits without introducing a mutable review flag. Event previews persist only
the relevant heads, so unrelated private record IDs cannot leak in explanations.

Epistemic, workflow, decision and availability events have independent chains.
A link's acceptance does not assess its target. Assessments need explicit basis;
corrections reference the chain head, restore its exact prior state and basis,
and fail if a later review has used that event. A stale basis requires fresh
content and review. Terminalizing an older current decision is permitted;
supersession must activate the exact successor in the same transaction. Two
versions of one logical decision cannot both be current.

`get(ref)` returns the immutable record, authorized events, recorded state,
`basis_changed`, `effective_assessment` and a hypothetical-input label. Changed
source bytes, content heads, withdrawal or enabling basis events make old support
inconclusive in the current view. The original event remains historical evidence
of what the reviewer judged. An old decision lifecycle is not reversed by
freshness metadata. Source edits through `Brain.write_node()` append source
successors without retargeting consumers. Manual edits are detected through
source hashes or immutable content/event identities. Source metadata writes
preserve pinned whitespace. Recall counts, tiers and storage promotion do not
write assessments.

## Publication and recovery

One optional brain-root `decision-memory.v1.json` is authoritative. Arrays are
append-only through this API; the file is atomically replaced, with its receipt,
under `brain.write_guard()` from authorization/pull through commit/sync. Drafts
and all references are validated before anchors are written. Anchors contain
labelled identifiers and conservative source lineage, never an asserted current
assessment. Publication rechecks actual anchors, source freshness and policy.

If interrupted before sidecar replacement, labelled unused anchors or extra
source restrictions can remain. Retry the identical request; these anchors are
reusable. No review is published against absent anchors. If source editing is
interrupted between node and sidecar writes, reads mark old support stale;
writing the current node again records the successor. Reads never repair it.

If index/commit/push fails after publication, `RecordPublished` carries the
authorized receipt and reports local completion. An identical retry returns
that durable receipt without pulling, writing, incrementing generation or
retrying sync. Complete Git synchronization explicitly using the existing brain
sync operation after inspecting local state. The same key with a different
request conflicts, including after restart. A retry rechecks today's access to
all its recorded inputs before returning anything.

`RecordError`, `UnsupportedSchema`, `RecordConflict` and `BasisUnavailable`
distinguish invalid input, unsupported formats, stale previews and unavailable
basis. Unavailable errors contain no hidden IDs or source bodies. Limits are
64 MiB, 50,000 total stored items, 200 inputs per content item, 200 entries per
bounded list, 4,000-character reasons and 32 nesting levels. Authoritative data
is rejected, never truncated. Delta/candidate arrays must currently be empty;
future work must add their strict validators before accepting them.

## Access, forgetting, merge and history

Every read/export follows anchor permissions and all transitive content,
source and event-basis references, including rejected and corrected events.
Missing/cyclic node provenance fails closed even for local-mode record views.
Review/source restrictions remain conservative across versions. Hidden records
and events are omitted as whole items; exports never include retry receipts.

Tombstoned/missing source nodes hide dependent live content and reviews without
requiring a sidecar event. Pinned tombstones cannot be promoted or recreated by
ordinary node writes. Generic text merge refuses both pinned source nodes and
record anchors before mutation; no version-aware merge/alias operation is
provided yet. Unrelated legacy notes retain their existing merge behavior.

`snapshot(brain, revision)['decision_memory']` reads the committed sidecar from
Git objects without checkout, recall, cache, repair, or fetching. Old commits
without the file produce an empty view; unsupported/corrupt schemas fail
explicitly. Historical and current source lineage and current ACLs all apply.
Explicit authorized historical snapshots may retain forgotten reviews, as with
existing node/edge snapshots; this is not physical erasure from Git. Fact-valid
filters select legacy facts and do not manufacture or rewrite review history.

The same record guard must be used by future CLI, HTTP and MCP adapters. Older
binaries cannot honor these rules: mixed-version writers are unsupported once
a brain uses Decision Memory. Whole-file storage bounds scale; distributed
writers and automatic Git conflict reconciliation are outside this boundary.

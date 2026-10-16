# Decision Memory v1 contract

Status: specification for [#74](https://github.com/SaltKing0/graph-engine/issues/74),
under [#73](https://github.com/SaltKing0/graph-engine/issues/73). This document
specifies the complete v1 behavior. The [Python storage boundary](decision-memory-storage.md)
implements versioned persistence and access checks; proposal adapters and automatic
impact analysis remain future work. The [worked example](decision-memory-example.md)
is a complete paper walkthrough. Normative terms **must**, **must not** and
**may** apply to the dependent implementation issues.

## Outcome and first flow

A developer asks: “Why did we choose this, what exact evidence was reviewed,
and does this local update warrant another review?” The first flow is:

1. Select a separate example brain and import existing local project documents
   and benchmark artifacts. Capture exact bytes and locators; no source fetching.
2. Submit a structured proposal containing a claim, evidence/result, decision,
   typed context and explicit relationships. A deterministic no-model path must
   support the entire flow. Optional extraction produces proposals only.
3. A human reviews grounding, scope, relationships and the decision separately.
   Store the exact reviewed versions, reviewer, reason and time.
4. Import a changed source/result. Show the informational delta and any bounded
   dependency paths to decisions, including unknown comparability and limits.
5. Review a finding; acknowledge it, investigate, retain the decision or revise
   it. Reconstruct both the original basis and this review from history.

The engine remains generic. Public GraphEngine documents are example inputs,
never built-in project policy or private brain data. v1 excludes active web
research, autonomous experiment execution, agent swarms, cross-domain analogy
discovery, unrestricted inference, mandatory brain migration, a new graph
database and a large visualization redesign. No dependency or model download,
model call, benchmark execution or code execution is implied by importing a
record. A recorded command is inert provenance.

## Objects, identities and clocks

| Object | Role; what it does not establish |
| --- | --- |
| Source version | Exact local node text or imported artifact bytes plus locator and capture provenance. A citation is not a verification. |
| Claim | A scoped proposition that can be assessed; does not assert its own truth. |
| Evidence | An interpretation of a particular source/result version bearing on a claim, with scope and source lineage. Does not inherit credibility from retrieval rank. |
| Decision | A chosen action, rationale, alternatives and revisit condition, explicitly dependent on claims. A choice can remain current while its justification needs investigation. |
| Check | A recorded question/protocol, required context, expected metric and comparison rule. A plan to check is not evidence that it was executed. |
| Result | An imported observation for an exact check version: values, context, artifacts and execution provenance, or an explicit inconclusive/error outcome. An imported result is not independently reproduced by the engine. |
| Relationship | A directed assertion between exact object versions, itself versioned and reviewed. |
| Assessment | An immutable review event about exact versions, with its complete basis. Not a mutable truth flag. |
| Delta / candidate / finding | Respectively a recorded change, a possible consequence, and a reviewed reason to consider an impact. None is a decision reversal. |

Every object/relationship has a stable brain-local logical `id` (opaque UUID)
and immutable `version_id`. A reference is `{id, version_id}` within one brain;
cross-brain references are not traversed in v1. New wording, scope, values,
provenance, lineage or rationale creates a successor version with `previous`
pointing to the exact prior version. Changing any of these bytes cannot reuse
the version ID. Cosmetic source edits still produce a new source version but
need not create a semantic impact. Review events do not change content versions.
New heads never transfer old assessments or accepted links to new versions.

`version_id` is `sha256:` plus the lowercase digest of a canonical JSON content
envelope containing `schema`, `id`, `kind`, `anchor_node_id`, `previous`,
`recorded_at`, `recorded_by`, `provenance` and `payload` (exclude `version_id`).
Canonicalization is UTF-8 JSON, keys sorted, separators `,` and `:`,
`ensure_ascii=True`, no NaN/Infinity, no duplicate keys; reject invalid Unicode
surrogates. Metrics use decimal strings, not floating-point JSON values.
Within a transaction, content refs must form a constructible DAG: sources and
profiles first, then their consumers, then relationship versions. Link endpoints
may form logical graph cycles without circular content hashes. An identical
retry returns the existing version. Distinct logical IDs with
identical content remain distinct; lineage rules prevent evidence inflation.

`recorded_at` and review time are server-supplied UTC instants, separate from
observation time, validity interval and Git commit time. Local actors are
`local`; protected mode records the authenticated principal, never a
client-supplied impersonation. Provenance records capture method
(`manual|import|extractor`), source refs/locators, optional tool/model/prompt
identities, and all supplied inputs, including uncited model inputs. A model's
self-reported confidence is optional provenance only. Git author/committer is
not a substitute for the reviewer.

Source refs pin `node_id`, `text_sha256` of exact UTF-8 text (no normalization),
and an optional full Git revision; imported artifacts additionally pin byte
SHA-256, local display locator, media type, and extraction tool/version if used.
Quotes pin Unicode code-point `[start,end)` offsets into that text; validation
requires exact equality. No fuzzy quote matching. Large artifact bytes may stay
outside the brain; their absence makes reinspection unavailable, not verified.
The imported text and hashes remain pinned. Path strings never authorize reads.
An imported source node is its source version's anchor; it must not name itself
in `derived_from`. Other anchors reference the actual input source nodes. Anchor
summaries must remain labelled as decision-memory records, with assessment and
freshness obtained from the sidecar; a static summary cannot assert fresh support.

## Four independent state axes

| Axis | Values / interpretation |
| --- | --- |
| Epistemic assessment (claim/evidence) | `unassessed`, `supported`, `opposed`, `mixed`, `inconclusive`; always scoped to a target version and reviewed basis. `supported` means supported within that review, not universal truth. |
| Review workflow (proposal/link/finding) | `proposed`, `accepted`, `rejected` for proposals/links; finding workflow below. Acceptance confirms a recorded interpretation/relationship, not entailment. |
| Decision lifecycle | `proposed`, `current`, `superseded`, `withdrawn`; a separate review conclusion is `remains_justified`, `needs_investigation` or `revise`. |
| Existing storage lifecycle / tier | Node `probation|active|stale|tombstone` and `main|recall|archival` remain unchanged. They govern storage/retrieval, not belief or decision validity. |

Evidence availability is a further explicit property: `available|withdrawn` via
events, and derived `unavailable` when sources cannot be used. Withdrawal means
“do not use this as current evidence”; it does not mean the claim is false.
Maintenance promotion, decay, usage, feedback, similarity, reranking and model
confidence must never write epistemic assessments or decision review outcomes.
An accepted link can coexist with an inconclusive claim assessment. Pending
legacy facts do not become accepted decision-memory evidence automatically.

## Typed context and comparability

Each claim, evidence, check and result pins a `context`:

```json
{
  "schema": "dm.context/1",
  "profile": {
    "id": "00000000-0000-4000-8000-000000000001",
    "version_id": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  },
  "dimensions": {
    "metric": {"type": "enum", "value": "evidence_recall_at_k"},
    "unit": {"type": "enum", "value": "fraction"},
    "k": {"type": "integer", "value": 5},
    "workload": {"type": "id", "value": "synthetic-graph-fixture"},
    "data_sha256": {"type": "unknown", "reason": "not supplied"},
    "code_revision": {"type": "unknown", "reason": "not supplied"},
    "environment": {"type": "id", "value": "hash-no-reranker-no-answer"},
    "context_budget": {"type": "integer", "value": 256}
  },
  "notes": "Illustrative profile ref only; replace with a stored profile's actual hash. Unknown conditions cannot pass comparability."
}
```

A profile is an immutable, versioned, user-reviewed record defining required
dimension names/types, units, allowed enum values, and comparison mode per
dimension. Supported types are `enum`, `id` (opaque exact identity), `integer`,
`decimal` (canonical decimal string), `range` (typed bounds with inclusive flags),
`time_window` (UTC half-open bounds), and `unknown` with reason. Units are exact
tokens; v1 has no implicit unit conversion. Omitted required dimensions are
unknown. No wildcard, embedding or free-text equality. `notes` is never compared.
Unrecognized profiles/types/units are unknown for comparison; malformed records
are validation errors. A profile change does not reinterpret past records.
Profiles start proposed and require an acceptance event before their rules can
enable accepted impact paths. Sources, checks and results record inputs/outcomes
without an implied truth assessment; claim/evidence start unassessed, links
proposed and decisions proposed. Accepting a capture proposal publishes content
only; it never accepts its links or supplies an epistemic judgment.

A profile payload has a display name/version, `dimensions` keyed by dimension
name with `{type, unit, required, compare, allowed_values}`, and explicit paired
interventions. All fields are required; use null unit/allowed_values when
inapplicable. Scalar conditions use `{type,value}` as above. A range's `value`
is `{lower,upper,lower_inclusive,upper_inclusive}` with finite bounds of the
profile's integer/decimal type. A time window's `value` is `{from,to}` in UTC.
Unknown/open bounds are represented as `unknown` in v1, not guessed infinities.
Canonical decimals have no exponent, leading/trailing zero padding or negative
zero. Empty/backward ranges/windows are invalid. Comparison-rule changes need
a new profile version and new reviews, including for intervention dimensions.

The profile declares dimensions as `equal` or `overlap`; measurements themselves
are values, not equal-constrained conditions. `equal` requires identical typed
values; `overlap` requires a nonempty intersection of compatible ranges/windows.
A fully known mismatch gives `disjoint`, with dimension/reason. Otherwise a
missing/unknown dimension gives `unknown`, listing the unresolved dimensions;
otherwise return `comparable` plus the exact intersection. Check known
disjointness first: an unknown host does not erase a known different metric.
Comparisons across different profile refs are unknown in v1, even when their
display names resemble each other. A future explicit mapping would need its
own versioned/reviewed representation; v1 never infers one from text.

Comparability is per relationship/question, not global equivalence. A check
names exactly which dimensions may vary and how: e.g. a paired graph on/off
comparison permits `graph_hops` as the intervention while holding code, data,
embedder, budget and workload fixed within each pair. A longitudinal check
may admit newer code revisions but must record both revisions and the reviewed
rule. It cannot silently ignore changed code/data/environment. Partial scope
overlap licenses conclusions only on the intersection. A claim with no context
remains capturable but all condition-dependent conclusions are inconclusive.

An unknown comparison may create a labelled comparability-review candidate
on an explicit dependency path; it must not be called a contradiction. A known
disjoint update cannot oppose the out-of-scope claim. A decision can depend on
both synthetic diagnostics and a real-document readiness check without those
two workloads being declared equivalent.

## Directed relationships and bounded impact

All endpoints below are exact version refs. Each link has a context/profile,
provenance, explanation and independent proposal review history.

| Kind | Source → target; meaning and impact direction |
| --- | --- |
| `supports` | Evidence or result → claim. Source provides a reviewed reason for the proposition within the link's scope. |
| `opposes` | Evidence or result → claim. Source provides a reviewed reason against it in overlapping scope; requires comparability. |
| `depends_on` | Claim or decision → claim. Target is a necessary premise/assumption of source's rationale. A target change travels backwards to dependents. |
| `checks` | Check → claim or decision. Records which proposition or revisit condition the check examines; no execution implied. |
| `result_of` | Result → check. Pins the protocol answered, with `completed|inconclusive|error` outcome. |
| `supersedes` | New decision version → old decision version. Only an explicit decision review activates succession. |
| `similar_to`, `analogous_to` | Object → object, discovery annotations only. Never traversed for impact or treated as identity/dependence. |

Existing edges such as `extends`, `linked`, `fact`, `supports`, `contradicts`
and `fact_replacement` retain their existing meaning. No name-based conversion
to this contract. Legacy `derived_from` is access provenance, not automatically
a logical `depends_on`. Reviewed `depends_on` links may explain assumptions;
ordinary text and source co-occurrence may not invent them.

Only accepted, non-retracted links on their exact endpoint versions participate
in current impact traversal. Proposed links appear in review previews only;
rejected/retracted links remain historical. An update of an old endpoint seeds
an impact check through links pinned to that old version; a path records
old→new substitutions without pretending those links already endorse the new
version. A new source/result must be explicitly attached to a claim/check
(initially proposed) before it can be a review preview; no global similarity
search creates impacts. Acceptance/withdrawal of an attachment itself is a delta.

Multiple independent supports are retained. Each evidence record lists
`lineage_ids` rooted in an original artifact/measurement, with source refs.
Copies, repeated quotes, reimports and summaries of one experiment share a
lineage even if text hashes differ. Different hashes do not prove independence.
Unknown lineage is labelled unknown and must not count as independent support.
Independent-run assertions require a human review with execution/dataset
provenance. No vote counting, summed confidence, or automatic truth propagation.
Withdrawal of one of two independent supports leaves the other available;
the candidate explains both loss and remaining support. Withdrawing every
support still requires a new assessment, never automatic opposition.

Traversal starts from changed refs and follows accepted evidential/check paths
and reverse `depends_on`, preserving direction and relationship/version IDs.
A changed source seeds its explicitly recorded provenance consumers first;
the explanation includes that exact source-ref step, which counts as a hop.
This reverse input lookup does not invent a logical support/dependency link.
Following evidence still requires an accepted evidential/check path. Proposed
previews use the same bounds but retain their proposed status throughout.
Default hard limits: 3 hops, 200 distinct object versions, 500 examined links,
20 retained explanation paths; callers may lower but not raise these in v1.
Sort adjacency by link ID/version ID; use a visited-version set and retain
bounded shortest paths. Dependency cycles may be recorded with a warning;
they cannot justify themselves or multiply evidence and cannot generate an
assessment. Provenance cycles remain invalid/fail closed under existing ACL
rules. Return `truncated` and the hit limits; incomplete traversal cannot
establish “no impact”. Permission filtering precedes traversal and counts;
no hidden IDs, hidden counts or secret-path explanations are returned.

## Change, candidate and finding

An immutable **delta** pins old/new refs (old may be null for creation), changed
fields, change class, actor/time and classification rule version. Classes are
`content`, `context`, `provenance`, `availability`, `relationship`, `review`,
or `cosmetic`. Any source bytes/head change, withdrawal, link acceptance,
retraction or correction is informational; usage/cache/tier changes are outside
this stream. “Cosmetic” is restricted to exact deterministic formatting rules
named by version, never a model's judgment of irrelevance. Ambiguous semantic
change is labelled unknown rather than suppressed.

An immutable **impact candidate** pins its seed delta, affected claim/decision
version, exact bounded paths, comparison result, remaining/removed supports,
rule version and completeness. Reasons include `basis_changed`,
`support_withdrawn`, `comparable_opposition`, `revisit_check_result`,
`comparability_unknown`. Its identity/dedup key is the hash of seed delta ID,
target ref, rule version and sorted path link refs. Also include basis event
heads and comparison output, so a changed withdrawal/review cannot reuse the
old identity. Recomputing the same inputs is idempotent. A changed basis
produces a successor candidate, not an overwrite of a dismissed one. Unrelated
updates produce deltas only.

A **finding** is created by explicit human candidate review: `confirmed`,
`dismissed` or `inconclusive`, with reason and exact candidate/basis refs.
`confirmed` means “this warrants decision review”, not “the decision is wrong”.
Confirmed findings have workflow `open → acknowledged → resolved`; direct
`open → resolved` is allowed. Resolution pins a decision review outcome, owner,
reason and follow-up refs when needed. `needs_investigation` may resolve triage
with an explicit follow-up check/owner; it does not imply that investigation
finished. Reopening appends a new event. Dismissed/inconclusive findings can be
reopened by review; no event erases the original candidate, basis or rationale.
Acknowledgment changes neither epistemic state nor decision lifecycle.
The first disposition event uses axis `finding_disposition`,
`unreviewed → confirmed|dismissed|inconclusive`; a confirmed disposition initializes
the computed workflow to open. Later workflow events use axis
`finding_workflow`. Reopening a resolved finding restores open; reconsidering
a dismissed/inconclusive disposition requires a fresh disposition event/basis.

## Immutable reviews and correction

Every review event contains `event_id` (UUID), `schema`, `subject` exact ref,
`axis`, `from`, `to`, `previous_event_id` (null only initially), `basis` (exact
refs plus source refs), `reviewer`, `reason` (nonempty), `reviewed_at`,
`expected_heads`, and `supersedes_event_id` (null unless correction/undo).
Events are immutable; current state is the validated fold, not last timestamp
wins. Assessment is conditional on the entire basis, including accepted link
review event IDs and withdrawal state, not only target content.
Schemas are `dm.content/1`, `dm.event/1`, `dm.delta/1` and `dm.candidate/1`.
Basis entries are tagged `content_ref`, `event_ref` (`event_id`), `source_ref`
or `candidate_ref`, never ambiguous strings. Deltas/candidates also have content
hash version IDs using the same canonicalization over all their fields except
`version_id`. Their references use `{id, version_id}`; delta old/new entries may
instead be tagged event refs for review/availability changes. Availability is
`available|withdrawn` for both evidence and links; a withdrawn accepted link is
displayed as retracted without inventing another review state.

| Axis | Permitted transition / guard |
| --- | --- |
| Epistemic | `unassessed` to any assessed value; any assessed value to any assessed value with a fresh basis/reason. Reset to `unassessed` only by explicit correction/undo. No maintenance transitions. |
| Proposal/link | `proposed → accepted|rejected`; either decision → `proposed` by guarded undo. Accepted link → retracted by an availability event; reactivation requires fresh review. |
| Evidence availability | `available → withdrawn`; restoration to `available` requires explicit fresh review of unchanged source/version and current permissions. |
| Decision | `proposed → current|withdrawn`; `current → superseded|withdrawn`. Supersession must atomically activate a reviewed successor. Terminal versions cannot become current except a guarded undo; a new choice normally gets a successor version. |
| Decision conclusion | An explicit review can record any of `remains_justified|needs_investigation|revise`; `revise` alone does not activate a new decision. |
| Finding | Candidate → reviewed disposition; workflow transitions as above. No system-generated confirmation. |

Before mutation, under the same-brain writer guard, re-read content heads,
prior event IDs, source hashes, source availability and current access. Compare
them with `expected_heads` supplied by the review preview. Any changed target,
basis, link state, permissions or predecessor causes a conflict with no review
write; the caller refreshes. This protects against two reviewers and against
an old tab accepting edited evidence. Retrying an identical idempotency key
returns the original result; reuse with different payload is a conflict.

An old assessment remains historically valid as a record of what was judged.
If its basis changes, the current view must mark `basis_changed=true` and
`effective_assessment=inconclusive` (or `unassessed` for a new target version),
while showing the recorded assessment separately to authorized readers. This
is freshness metadata, not a newly authored epistemic assessment. A current
decision stays current until reviewed; its justification is labelled out of
date and linked to candidates. Unknown/hidden basis cannot appear fully supported.

Correction appends an event referencing the erroneous event with explanation.
Undo is a compensating event restoring the exact prior state only if the
event is still the head, all before/after target and basis refs match, and no
dependent decision/review has used it. Otherwise reject undo and require a
fresh review/corrective successor. Never restore forgotten data, transfer
assessments to edited content, or delete an assessment to simulate undo.
Even no-op conclusions such as “remains justified” record a new basis/event.

## Storage and shared API representation

Choose one optional brain-root file, `decision-memory.v1.json`, containing a
versioned JSON envelope. No database or bulk migration. Logical objects have
ordinary semantic Node anchors (existing `ntype`, no new taxonomy); anchors
carry only a labelled identifier/summary and `decision-memory-v1` tag.
Existing `edges.jsonl` remains the legacy graph, not a second authoritative
copy of decision relationships/reviews. All new semantics live in the sidecar.
Read views may join them, explicitly labelled. No automatic expansion ranking
of decision relationships is part of this contract.

```json
{
  "schema": "graph-engine.decision-memory/1",
  "generation": 1,
  "versions": [],
  "events": [],
  "deltas": [],
  "candidates": [],
  "receipts": []
}
```

`versions` contains the content envelopes above; `kind` selects the required
payload below. `events` holds review/availability/finding events. Findings are
event chains whose subject is a candidate ID (candidate schema/version supplies
the immutable reference); they are not content rewrites. `deltas` and
`candidates` use the exact fields defined above and have UUID IDs, schema and
recorded time. Every referenced item must exist in this file or a pinned source
version. Arrays are append-only in normal operation; generation increments once
per accepted transaction. Heads and derived states are recomputed, not trusted
from client input. Reject forks/missing predecessors, unknown schema versions,
duplicate immutable version/event/item IDs, invalid hashes, invalid states and
unsupported fields explicitly. Repeated logical IDs are expected only along a
validated predecessor chain.
`receipts` durably records each idempotency key, canonical request hash, actor,
created refs/event IDs and resulting generation in the same atomic write.
A replay authorizes the current caller/basis before returning the receipt;
it must not leak previously accessible data after revocation. Replays perform
no writes or generation increment, and a different request with the same key
conflicts even after restart.

| `kind` | Required payload |
| --- | --- |
| `source` | Pinned source ref, captured text, artifact metadata if present, locator, lineage IDs. |
| `profile` | Dimension definitions and permitted comparison/intervention rules. |
| `claim` | Proposition text, context, explicit limitations. |
| `evidence` | Interpretation, context, source/result refs, lineage IDs, limitations. |
| `decision` | Action, rationale, alternatives, context, revisit check refs. Dependencies are separate reviewed links. |
| `check` | Question, context/profile, protocol ID/version, required inputs/metrics/units, comparison/revisit rule, rule limitations. Targets are pinned by separate `checks` links to avoid circular content hashes with a decision's revisit refs. |
| `result` | Check ref, outcome, context, metric values/units/denominators (empty with reason for errors/inconclusive), source/artifact refs, execution provenance, limitations, `hypothetical` boolean. |
| `relationship` | Kind from the direction table, ordered endpoint refs, context, explanation. |

Every version also records an anchor and full provenance. Sources/checks/results
are descriptive; availability/review is represented by events. Candidate paths
reference relationships and the exact review events enabling them. All input
results marked `hypothetical=true` must retain an example-only label throughout
dependent assessments, candidates, findings and briefs. They cannot be admitted
as measured evidence for a real decision. All strings/arrays/records need bounded
validation; v1 file limits are 50,000 total versions/events/deltas/candidates/receipts
and 64 MiB UTF-8, with 4,000-character reasons,
200-character logical IDs and maximum 200 refs per item. Oversized writes fail
before mutation; no silent truncation of authoritative data.

Expose this same envelope/ref/state vocabulary through future Python, CLI,
HTTP and MCP adapters. Logical operations are `propose`, `preview_change`,
`review`, `withdraw`, `correct`, `get`, `brief`, and `snapshot`; these are
operation contracts, not existing commands. Writes require `schema`,
`idempotency_key`, expected generation/heads and payload; return exact created
refs/event IDs and resulting generation. Reads return recorded state, effective
freshness, comparison reasons, exact accessible basis and traversal limits.
Errors distinguish invalid input, unsupported schema, conflict and unavailable
basis without revealing inaccessible record existence. Read operations write
no brain files/vectors/recalls; existing external security audit logging remains.

Compatibility requirements before #76 enables writes:

- **Writer:** use `brain.write_guard()` from authorization/pull through checks,
  sidecar replacement, Git commit and sync. Write the complete sidecar with
  `_atomic_write`; content plus its events/deltas publish together. Create
  required anchors and conservative provenance first; an interrupted write
  may leave labelled unreferenced anchors, never a published review with
  missing inputs. Do not publish until every anchor exists and is authorized.
  The sidecar is authoritative if index rebuilding/sync fails; report local
  completion, preserve it, and retry idempotently. This adds no multi-file
  filesystem transaction or distributed writer guarantee.
- **ACL:** every item must pass its anchor ACL AND the transitive permissions
  of every source/input/basis ref, including copied quotes, old versions,
  rejected links and undo payloads. Anchors persist the union of actual input
  node IDs in `derived_from` before publication; later rejection cannot relax
  it. Logical dependency cycles must not be copied into ACL derivation cycles:
  restrict by the underlying source nodes, not by all graph neighbors. New
  reads must also validate sidecar refs themselves. Missing/cyclic provenance
  fails closed. Redacting text while retaining secret IDs/counts is insufficient.
- **Forget:** existing tombstones/receipt handling remains authoritative for
  live visibility. A forgotten source hides affected sidecar bodies, quotes,
  derived briefs and candidates from live surfaces, even if an event wasn't
  appended before a crash. Other independently supported claims may be shown
  only in a freshly computed view without the hidden basis; no silent carryover
  of the old assessment. Explicit authorized history can retain tombstones and
  historical reviews under current permissions, as existing snapshots do.
  Forget is not physical erasure from Git or prior exports.
- **Merge/edit:** generic text merge must refuse decision-memory anchors and
  pinned source nodes used by the sidecar until a version-aware merge path is
  available. That path may create successor content/alias mappings but cannot
  rewrite pinned IDs or accepted endpoints, collapse assessment events or
  claim independent lineages. Ordinary source edits create new source versions;
  sidecar reads check hashes so out-of-band edits cannot retain fresh support.
- **Snapshots:** extend `snapshots.py`'s explicit path/schema allowlist to load
  the sidecar at the selected commit, without checkout or fetching. Missing
  sidecar means an empty decision-memory view; incompatible sidecar is an
  explicit error, never silently dropped. Apply historical AND current lineage
  and current policy; no present permission bypass via old bytes. Snapshot
  commit selects the review state; fact-valid-at filters do not fabricate
  historical assessment events. Local mode supports version refs/events but
  still has no Git revision snapshots.
- **Legacy:** absent sidecar leaves existing brains/default memory behavior
  unchanged. No auto-conversion of nodes/facts/reviews. New surfaces must not
  claim support in older binaries; mixed-version writers are unsupported for
  a decision-memory-enabled brain. Fail before writes when capability checks
  cannot preserve the sidecar/ACL/forget rules. Gate all new write surfaces on
  the completed shared boundary, not on a UI-only opt-in.
  Older executables cannot be made to honor a future capability marker; this is
  an operational limit, not a backward-enforced lock. Upgraded readers detect
  changed/missing anchors/sources and fail closed rather than trust old support.

Tradeoffs: an atomically replaced sidecar gives one coherent review publication
and immutable history within a local-mode brain. Whole-file rewrite and retained
versions bound scale; conflicts require refresh and Git merge conflicts require
explicit reconciliation, never last-writer wins. Separate anchors reuse existing
ACL/provenance but require adapter/forget/merge/snapshot work. Overloading
`fact_replacement`, adding nested metadata to today's Markdown parser, or using
Git SHA alone would respectively confuse semantics, risk lossy round trips, or
exclude local-mode immutable history. None is the v1 representation.

## Evaluation gates frozen before tuning

These are prospective release gates, not measurements. #75 must freeze bytes,
hashes, annotation protocol, split, baseline commands/model/prompt identities and
case IDs before #78 tuning; #81 reports results without changing thresholds.
Use independently annotated source→change→decision cases, including the small
worked example as a conformance fixture, not the held-out product corpus.
Annotators see source scope and exact versions, label expected paths/outcomes
independently, then adjudicate disagreements before evaluating the system.
Unresolved labels belong in a declared inconclusive stratum, never the negative
set. Any corpus change gets a new version and a new, disclosed evaluation.

| Gate / metric | Denominator and pass requirement |
| --- | --- |
| Access/history integrity | All enumerated ACL revocation, tombstone, source-edit, merge, snapshot, stale-review, undo, crash/retry and two-writer scenarios across applicable adapters. 100% pass; zero unauthorized bytes/IDs, retargeted reviews, partial accepted transactions or read-side brain writes. Report scenario count, not just percentage. |
| Provenance correctness | All source/version/quote/path refs emitted in cases and briefs. 100% resolve to the exact authorized reviewed version; missing refs are failures, not omitted denominators. |
| False alerts | Negative case–decision pairs annotated as unrelated, disjoint or cosmetic, with complete known scope. Numerator: pairs surfaced as warranting impact review (including spurious “unknown” warnings). Rate ≤5%; also report raw false candidate count and false discovery fraction over all surfaced pairs. |
| Missed impacts | Positive case–decision pairs annotated as requiring review through an explicit accepted path. Numerator: pairs with no correctly explained candidate. Rate ≤5%. Truncated traversal, runtime errors and incorrect paths count as misses, not exclusions. |
| Unsupported conclusions | All emitted assessment/decision-bearing statements in candidates, findings and briefs, independently judged against pinned scope/basis; report statement and case counts. Zero fabricated support, automatic reversals, synthetic→production generalizations or similarity→dependence assertions. No statements means rate unavailable, not 100% success. |
| Inconclusive handling | All cases with genuinely unknown comparability, missing/withdrawn inputs, uncertain lineage or unresolved gold labels. 100% explicitly labelled with reason and no unsupported conclusion; report count/total cases. Also report false abstention over known positive/negative pairs, without moving them into this stratum. |
| Coverage / errors | At least 20 positive pairs, 20 negative pairs and 10 inconclusive cases in the frozen held-out corpus, with each required failure mode represented. Report every attempted/completed/error/abstained pair, overlap by stratum and all denominators. Empty/undersized strata fail readiness. |

Deduplicate evaluation alerts by `(case_id, decision_version_ref)` so repeated
paths do not inflate recall; report raw path/alert burden separately. Proposed
link previews are scored separately from accepted-path impact; no oracle links
may be added from test labels. A negative case falsely marked inconclusive
still counts as a false alert if surfaced; a positive falsely marked unknown
counts as missed unless its candidate still correctly requests and explains
the required review. Errors must remain visible in the attempted denominator.

Technical gates establish contract correctness only. To claim user benefit,
compare the fixed corpus against the current search-plus-agent workflow with
the same source access, task instructions and pinned model/configuration (or
no-model path), using counterbalanced task order and recorded participants.
Prespecify success as ≥20% lower median active review time with no decrease in
independently scored correct decision reviews and no increase in unsupported
conclusions. Report participant/task counts, paired times, uncertainty, latency
p50/p95, context/token usage, alert burden and exclusions. Unmeasured usability
stays unmeasured; a small synthetic diagnostic cannot satisfy this claim.
If product gates fail, keep v1 experimental and publish the failure/limits.

## Delivery boundary

#75 freezes evaluation; #76 implements storage, source identity, shared access
and writer boundaries; #77 implements proposals and immutable review; #78
implements classified deltas and bounded impacts; #79/#80 expose briefs/UI;
#81 evaluates. Implementers must preserve this contract across those surfaces.
The worked example below resolves scope and transition ambiguities before
those issues add execution behavior.

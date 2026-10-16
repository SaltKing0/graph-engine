# Decision Memory revision comparison and impact review

Issue #78 adds an experimental, deterministic, read-only comparison service to
[Decision Memory v1](decision-memory-v1.md). It explains recorded changes and
requests decision review through explicit, accepted versioned dependencies.
It does not infer truth from text or automatically change a decision.

## Compare two committed revisions

Use the same selected brain/namespace and authentication as
[capture and review](decision-capture-review.md). A Git-mode brain with local
committed history is required. Ref names are resolved once to full commit IDs;
use those returned IDs in repeat comparisons and finding reviews. Nothing is
fetched, checked out, repaired, embedded or recalled. Local-mode immutable
records remain supported by storage; local-mode Git comparisons are unavailable.

Save this JSON as `comparison.json`, replacing the revisions:

```json
{
  "schema": "dm.compare/1",
  "before": "FULL_BASELINE_COMMIT",
  "after": "FULL_UPDATED_COMMIT",
  "limits": {"depth": 3, "objects": 200, "links": 500, "paths": 20, "deltas": 200}
}
```

```bash
ig decision compare comparison.json
```

Python: `DecisionService(brain).compare(envelope)`.
HTTP: `POST /api/decision-memory/compare` with the same JSON; responses use
`Cache-Control: no-store`. This operation uses the brain without constructing a
model-bearing engine. The existing bearer and graph selection policy applies.

The response records both resolved commits, commit times, sidecar generations,
server UTC evaluation time and classification rule `dm.impact-rules/1`. Content,
conditions, provenance, availability, relationship and review changes are
verified record deltas. Review events remain separately labelled judgments by
their original reviewer, time, reason and exact basis. A missing sidecar is an
empty view; incompatible historical data fails explicitly.
Each changed field includes bounded before/after JSON excerpts and exact-value
hashes; clipping is labelled. Candidates also name the affected action/rationale.
Use their exact version citations to inspect complete source and record bodies.

JSON key ordering/indentation, recall counters, storage tiers and retry receipts
are outside the epistemic stream. Equal payload/provenance or a source-only CRLF
to LF change with otherwise equal metadata is cosmetic under the named rule.
Other free-text edits remain ambiguous; no model declares them irrelevant.

## What an impact candidate means

A candidate names the seed delta, exact affected decision version, old-to-new
substitutions, relationship/version citations, directions, source-input steps,
structured comparisons, relevant basis heads/events and remaining/removed support.
An old accepted relationship continues to explain its original endpoint; it
never becomes acceptance of a successor version.

Only accepted `supports`, `opposes`, `checks`, `result_of` and reversed
`depends_on` relationships form dependency paths. Exact source/provenance
consumers seed traversal first and cost a hop. A result's `check` field alone
cannot substitute for an accepted `result_of` attachment. Similarity, legacy
edges and shared topic words never prove a dependency. New proposed attachments
can yield separately labelled `proposed_preview` paths through accepted downstream
dependencies. Their opposition remains unreviewed, even with comparable scope.

The existing reviewed profile rules compare exact typed conditions and scoped
intersections. Units are exact tokens; different profiles or missing conditions
are unknown. Known disjoint units, versions, environments, workloads or half-open
time windows cannot establish opposition. A proposed out-of-scope attachment
produces no impact candidate. A formerly accepted support whose successor moves
out of scope requests review of the lost basis, with `scope_changed`, rather than
claiming a contradiction. Arbitrary prose is never parsed into a truth judgment.

Evidence/attachment withdrawal reduces support; it does not establish the
opposite proposition. Surviving support retains exact source citations and root
lineage. Copies share roots; unknown roots stay unknown. Distinct recorded roots
are descriptive, not verified independent runs or votes. No summed confidence,
majority count or automatic refutation is emitted.

Hard limits may only be lowered: three hops, 200 visited object versions, 500
examined links (including graph construction), 20 retained shortest explanations
and 200 deltas/judgments. Adjacency, seeds and output are sorted deterministically.
Visited versions prevent cycle expansion; detected cycles are warnings. Support
output is separately bounded to 20 attachments, 20 source citations per attachment
and 200 lineage labels; hitting these limits is disclosed too. All candidates
carry completeness metadata. Truncation cannot establish absence of impact.
Only one shortest path per seed and decision is retained; surviving supports are
listed separately. This bounds explanation burden without multiplying votes.

Both revisions use their own committed text, sidecar, reviews and lineage under
current permissions. Current ACL/source lineage is captured before analysis and
rechecked before returning. Changes during the read cause a retryable conflict.
Missing or tombstoned current sources and all affected intermediate records are
omitted before classification, counts and paths, including in old revisions.
Omission is not an inferred withdrawal or a count of hidden records. Authorized
explicit `snapshot` inspection retains its existing historical tombstone policy.

## Persist only by explicit review

Candidates are ephemeral. `candidate_id` hashes material versions, the seed
change/review, path identities, comparisons, support and relevant basis events.
Evaluation time, unrelated commits and output completeness do not duplicate it.
A candidate is not a reviewed finding until a person explicitly dispositions it.

Get `ig decision preview`, then save a finding review envelope:

```json
{
  "schema": "dm.finding-review/1",
  "idempotency_key": "a-unique-retry-key",
  "expected_generation": 12,
  "expected_heads": {},
  "comparison": {
    "schema": "dm.compare/1",
    "before": "FULL_BASELINE_COMMIT",
    "after": "FULL_UPDATED_COMMIT"
  },
  "candidate_id": "sha256:RETURNED_CANDIDATE_DIGEST",
  "disposition": "confirmed",
  "reason": "This changed basis warrants a decision review."
}
```

Pass the preview's actual generation and complete opaque heads unchanged.
`ig decision finding finding-review.json --dry-run` prepares a review without
writing; omit `--dry-run` to publish. Python is
`DecisionService(brain).record_finding(envelope)`; HTTP is
`POST /api/decision-memory/findings?dry_run=true` or the same route without the
query flag. The server regenerates the candidate from the pinned revisions;
callers cannot supply explanation paths. Stale current basis fails publication.
The ordinary proposal endpoint cannot introduce finding records.

Disposition is `confirmed`, `dismissed` or `inconclusive`. Confirmed means
"warrants decision review", not "the decision is wrong"; its workflow starts
`open`. Use ordinary `dm.review/1` events on the returned finding content ref,
axis `finding_workflow`, for `open → acknowledged → resolved` or direct
`open → resolved`. Resolution must cite an exact `decision_conclusion` event
for the affected decision; `needs_investigation` also requires a follow-up check
content ref. The authenticated reviewer owns the resolution and supplies its
reason. Acknowledgment and resolution address the recorded candidate without
changing its evidence, claim assessment or chosen action.

Identical retries return the durable receipt without another event. A new key
for the same candidate conflicts; it cannot duplicate or reopen a finding.
Materially new input creates a successor in the same finding series with its
exact predecessor and former candidate identity. Prior disposition/workflow
history remains inspectable. A resolved version cannot reopen from the same
input. Generic storage limits still apply: an oversized candidate cannot be
persisted if its complete reference envelope exceeds the 200-input limit.

## Validation and remaining evaluation

Deterministic regressions cover the source-only development families frozen by
#75, unrelated changes, scoped opposition, unknown/disjoint conditions, multiple
supports, withdrawal/retraction, duplicate roots, cycles, limits, current
revocation, hidden intermediates, tombstones/missing evidence, repeat comparison,
read-side file/HEAD integrity and explicit finding lifecycle across CLI/HTTP.
The frozen development sources remain prose with unknown scope; tests supply
explicit fixture dependencies and do not infer historical reviews or accuracy.
Held-out labels are unused for feature tuning. Existing offline control harnesses
remain required. Independent annotations, held-out product gates and user review
time are still unmeasured and remain #81 work; this feature makes no release
readiness or usability claim.

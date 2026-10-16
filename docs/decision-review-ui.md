# Decision impact review

Open **Decision impact review** from the cockpit, or visit
`/review?mode=decisions`. The existing `/review` connection inbox remains available.
This screen reads existing local Decision Memory records. It does not extract
claims, fetch sources, run research code, call models or change ordinary memory.

The default queue contains accessible open findings, including inconclusive
judgments that still need triage. To generate ephemeral candidates, enter two
explicit Git revisions and select **Compare revisions**. Branch names resolve to
full commit IDs; every candidate review regenerates that exact comparison.
The queue is capped at 50 entries, with explicit partial/truncated messaging.
The comparison retains the existing depth/object/link/path/delta limits.
No accessible entries does not prove that a decision is settled.

Select an entry to read the change reason, old/new claim and source versions,
conditions, supporting/opposing passages, remaining/removed support, comparison
status, exact dependency path and review history. Detail retains up to 200
records and a bounded typed neighborhood. Proposed judgments, recorded reviewer
judgments, changed basis and unresolved comparisons have separate labels.
Quotes and source locators are inert text, including inside the brief.

Every review requires a nonempty reason. A candidate can be confirmed (warrants
decision review), dismissed or left inconclusive through `dm.finding-review/1`.
A confirmed finding can be acknowledged through `dm.review/1`. Acknowledgment
removes it from the default queue without changing the decision or its assessment.
Enable **Include acknowledged, resolved and dismissed history** to inspect it.
A materially new candidate remains eligible even when the earlier finding was
acknowledged or dismissed. History includes earlier finding versions.

A decision outcome requires explicitly selected claim/evidence/check/result basis:
**Remains justified**, **Needs investigation**, or **Revise decision**. Resolution
then pins that recorded decision-outcome event. Investigation also requires an
existing follow-up check; the authenticated reviewer owns the resolution. Checks
can be connected through the decision's revisit checks or explicit relationships.
The revise outcome records the review conclusion; use the existing explicit
`ig decision propose` contract to prepare a successor decision, then activate and
supersede it with the required review basis. No choice automatically reverses a
decision, and no bulk truth-acceptance control is provided.

The detail response supplies the exact generation, content heads, source hashes,
authorization fingerprint and event heads used by the existing review service.
The browser submits those preconditions without fetching a newer preview first.
A conflict clears the stale form and reloads evidence; the user must enter a fresh
reason and explicitly submit again. A locally published but incompletely synced
response is surfaced separately and history is refreshed before another action.
No request is silently replayed with changed preconditions.

**Open decision brief** uses the #79 shared Markdown renderer and displays the
full returned commit ID. The renderer's qualifications, support/opposition,
conditions and completeness remain together. The browser displays Markdown as
plain text so source instructions and HTML stay inert.

All requests use the server's existing authenticated same-origin API. Current
role, graph, source-lineage and forgetting restrictions apply before queue
entries or details are returned, including historical candidates. A refresh
clears old detail/brief content immediately; forbidden, authentication,
missing-source, loading, empty, stale and truncated states are explicit.
There is no token store or browser cache of evidence. Native labelled controls
support keyboard input, and the list/detail layout stacks on narrow screens.

## Shared read adapters

These read-only projections also run through the CLI and MCP. They do not create
new mutation rules; writes use the existing proposal/finding/review contracts.

```bash
# queue.json: {"history":false}
ig decision review-queue queue.json
# Optional comparison: {"schema":"dm.compare/1","before":"<commit>","after":"<commit>"}
# detail.json: {"reference":{"id":"<finding UUID>","version_id":"sha256:<hash>"}}
# Or: {"comparison":{...},"candidate_id":"sha256:<hash>"}
ig decision review-detail detail.json
```

MCP exposes `decision_review_queue(envelope)` and
`decision_review_detail(envelope)` with read-only annotations.
HTTP exposes `POST /api/decision-memory/read/review-queue` and
`POST /api/decision-memory/read/review-detail`, taking the same envelopes.
`POST /api/decision-memory/read/brief` exposes the shared #79 brief and its
server-rendered `markdown`. All responses use `Cache-Control: no-store`.

Validation includes real-server Chromium source → candidate → finding →
acknowledgment → decision outcome → resolution/history, conflict refresh,
authenticated source restriction, hostile source rendering and narrow-screen
keyboard controls in the existing strict browser gate.

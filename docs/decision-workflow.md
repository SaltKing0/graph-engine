# Decision Memory: offline workflow and measured limits

Decision Memory is **experimental and explicitly activated**. It serves developers
and agents who need to preserve the exact local evidence and review behind a
technical choice, then investigate changes to that evidence. It cannot establish
that an imported result is true or that a decision should reverse. The
[release assessment](decision-release-readiness.md) records missing measurements
and the decision to keep v1 experimental.

Existing unstructured brains need no migration. Ordinary search, context,
ingestion and memory maintenance retain their existing behavior. Typed records
are created only through explicit Decision Memory proposals. Agent decision
context is a separate opt-in call; ordinary memory context does not silently
include it. No provider, source fetch, research execution or model download is
required by this workflow.

## Complete reproducible walkthrough

From a source checkout with the development dependencies installed:

```bash
python -m examples.decision_workflow --output /tmp/decision-workflow.json
# Retain the demonstration brain for CLI/HTTP/UI inspection:
python -m examples.decision_workflow --brain /tmp/new-decision-brain \
  --output /tmp/decision-workflow-persistent.json
```

The dedicated brain path must be empty. Both commands import one local text
artifact, preserve a pre-existing ordinary memory, submit structured sources,
evidence, a scoped claim, support and a decision, then explicitly review the
support, claim, dependency and activation. A fresh session changes the source.
The production writer creates an immutable source successor; old evidence
continues to reference its original version and the claim's effective assessment
becomes inconclusive. The decision remains current. The walkthrough compares
local commits, records and acknowledges a finding, records an investigation
outcome, builds agent context, reads UI review detail/history and reconstructs
the original source. It creates a new decision version and checks that it is
proposed rather than inheriting activation. Finally it forgets the source and
checks that historical reads and the review queue cannot reveal it.

**The final brain intentionally contains forgotten source content**, so its
history views are restricted. To explore an intact pair of sessions and UI
candidates, use the complementary example:

```bash
python -m examples.decision_memory --brain /tmp/another-empty-decision-brain
```

That example supplies synthetic comparable opposition, then confirms an impact
finding and prints a qualified brief/context. Neither example is a human review
exercise or real experiment. Review events say `local`; scripted acceptance is
not independent review. Raw inputs, envelopes' publication receipts, returned
records, per-operation wall time and failed operations are preserved in the
workflow JSON. Import, proposal, scripted review, impact and context timings are
separate. Git commit and setup overhead are not included in those stage times.
Provider calls are zero; human review time and savings remain null.

## CLI, HTTP, MCP and browser

Use the preserved brain from the second example:

```bash
export IG_BRAIN_PATH=/tmp/another-empty-decision-brain
export IG_BRAIN_MODE=git
export IDEAGRAPH_EMBEDDER=hash
ig decision preview
ig decision pending
# review-queue.json: {"history":true}
ig decision review-queue review-queue.json
# brief.json: {"reference":{"id":"...","version_id":"sha256:..."},"revision":"HEAD"}
# Copy the exact reference from the example output.
ig decision brief brief.json --format markdown
# context.json: {"query":"expansion opt-in","budget":8000,"revision":"HEAD"}
ig decision context context.json
python -m uvicorn graph_engine.server:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/review?mode=decisions`. Select history to inspect the
recorded finding, its exact dependency path, source conditions, support and
opposition. Opening a brief pins its returned full Git revision. Acknowledgment
clears a pending item without resolving its underlying question. A resolution
requires explicit decision-outcome and follow-up-check basis. The browser does
not activate another decision when a reviewer chooses “revise”.

The shared HTTP routes are `GET /api/decision-memory/preview`,
`POST /api/decision-memory/proposals`, `/reviews`, `/compare`, `/findings` and
`/read/{review-queue,review-detail,brief,context}`. Bodies match the documented
[capture](decision-capture-review.md), [impact](decision-impact.md) and
[agent read](decision-briefs.md) envelopes. Review writes require fresh generation,
heads, exact references, a reason and a unique idempotency key. Responses use
`Cache-Control: no-store`. Configure the existing access policy and bearer
authentication before exposing private brains beyond trusted local use.

Install the optional `[mcp]` extra and run `ig mcp` for agent reads:
`decision_inspect`, `decision_compare`, `decision_findings`, `decision_brief`,
`build_decision_context`, `decision_review_queue` and `decision_review_detail`.
These are read-only tools, including in write mode. Typed proposal/review writes
use CLI or HTTP; MCP's general memory write switch does not turn a read into a
Decision Memory approval. The [UI guide](decision-review-ui.md) describes the
same review projections and authenticated transport.

## Recovery, history and evidence limits

A stale generation, head, source, policy or review basis requires a refresh and
explicit reconstruction of the intended review. Never silently retry against a
new basis. Replaying an identical envelope/key recovers its receipt without
creating another assessment. A locally published sync failure carries
`published_locally: true`; recover the receipt and explicitly sync the brain.
Undo is a guarded corrective event; when dependent reviews prevent undo, create
a new content version and review it separately.

Git revisions reconstruct the exact original basis, subject to **current**
permissions, source lineage and forgetting rules. Historical access never grants
a right to forgotten/private content. A missing sidecar is an empty typed view;
invalid or unsupported history fails explicitly. Inaccessible evidence is not
an assertion that no opposition exists.

Comparisons require a Git brain and committed local history. They traverse
bounded, explicit accepted dependencies. Proposed previews remain unreviewed;
lexical similarity is not a dependency. Free text does not establish opposition,
withdrawal, source independence or comparable conditions. Typed conditions need
an accepted profile and explicit scoped review. Missing inputs, results, metrics
and errors remain unknown. Budgeted context can omit an entire qualified unit;
empty/truncated context is not a successful answer. See the
[frozen evaluation protocol](decision-evaluation.md) for the original thresholds.

## Reproduce the diagnostic evaluation

```bash
# Synthetic controls only; this never promotes the feature.
python -m tools.decision_benchmark.production --split all \
  --output /tmp/decision-production-controls.json
# Explicit opt-in to the local frozen project corpus, after implementation freeze.
python -m tools.decision_benchmark.production --real-corpus --split evaluation \
  --output /tmp/decision-production-project.json
```

The command also saves a `*-baseline.json` using the original current-workflow
and explicit-dependency baselines. It preserves their chronological allowlist,
800-character source slices, task, k=5, 4000 estimated token budget, HashEmbedder
baseline and no answer model/provider. Corpus hashes, code manifests, settings,
raw production responses, exact brain revisions and source-to-record mappings
are pinned. Source-change diagnostic mapping `dm.source-change-diagnostic/1`
versions an **unassessed basis claim** to attach the exact current update;
it never replaces a source artifact with patch text or invents semantic labels.
Only verified accepted dependency paths are normalized to frozen pair paths.
Curated and supplied proposed dependencies run in separate brains. Proposed links
are never auto-accepted. No extraction ability is inferred from an empty profile.

This additional typed representation and scripted review are recorded treatment
costs. They cannot support a matched answer-quality comparison with a prepared
agent prompt. The corpus lacks independent structured semantic annotations, so
the diagnostic deliberately requests conservative source-basis review. Do not
interpret that as completed semantic evaluation. False alerts, abstentions,
errors and unscored pending pairs retain their denominators. Running controls
is an offline execution/budget check; release gates remain separate and failing
or unmeasured. A full user exercise and independently frozen successor corpus
remain required before promotion.

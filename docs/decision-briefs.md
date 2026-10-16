# Decision briefs and opt-in agent context

Decision Memory v1 exposes a shared, read-only service through CLI and optional
stdio MCP. It reads committed local Git history without loading an embedder,
recording recalls, filling vector caches, pulling, repairing or changing the
brain. Existing `ig context`, MCP `build_context` and memory-only Python behavior
remain unchanged. This feature is experimental; it establishes prompt wiring,
not independently measured answer quality or a release-readiness result.

## Shared reads

`DecisionService(brain).read(operation, envelope)` supports these envelopes:

| Operation | Required fields | Optional fields |
|---|---|---|
| `brief` | `reference`: exact `{id, version_id}` decision | `revision` (default `HEAD`) |
| `context` | `query` (1–500 characters) | `revision`, `budget` (0–8000, default 2000), `k` (1–20, default 5) |
| `findings` | none | `revision`, `decision_id`, `unresolved_only` (default true) |
| `inspect-revision` | `reference`, `revision` | none |

Revisions select **both content and review events**. The returned full commit
SHA, `dm.brief/1` schema and `dm.markdown/1` renderer pin the explanatory export.
There is no evaluation clock in briefs; identical committed state under the
same current authorization and lineage renders identically. Current ACLs,
inherited source lineage and tombstones still filter old commits. Thus a prior
export is reproducible only while the caller retains access to its evidence;
revoking access must take precedence over reproducing private text.

```bash
# request.json: {"reference":{"id":"<UUID>","version_id":"sha256:<HASH>"},"revision":"HEAD"}
ig decision brief request.json
ig decision brief request.json --format markdown > decision.md
# reference.json contains just the exact {id, version_id} reference
ig decision inspect reference.json --revision HEAD
# findings.json: {"revision":"HEAD","unresolved_only":true}
ig decision findings findings.json
# context.json: {"query":"expansion opt-in","budget":8000,"k":5,"revision":"HEAD"}
ig decision context context.json
```

All JSON input commands accept `-` for stdin. Existing `ig decision inspect`
without `--revision` continues to inspect live storage. Existing `compare`
uses the [#78 comparison envelope](decision-impact.md), with bounded classified
deltas and explained ephemeral review candidates. Findings are explicitly
recorded reviewer judgments, separate from those comparison candidates.

MCP read tools (also present in write mode):

- `decision_inspect(reference, revision=None)`; supply `revision` for a pinned read.
- `decision_compare(envelope)` reuses the #78 comparison service.
- `decision_findings(revision="HEAD", decision_id=None, unresolved_only=True)`.
- `decision_brief(reference, revision="HEAD", format="json")`; `format="markdown"`
  returns the same deterministically rendered brief in a `markdown` field.
- `build_decision_context(query, budget=2000, k=5, revision="HEAD")`.

All five have `readOnlyHint=true`. This change exposes no new MCP mutation.
Existing MCP remember/recall/forget still require `ig mcp --write`. Explicit
Decision Memory proposals and reviews continue through the #77 CLI/HTTP
service, including its strict authorization, preconditions and idempotency
contract. Findings cannot be authored by simply submitting arbitrary paths.

## Qualifications and citations

Brief records retain exact logical/version IDs, conditions, limitations,
recorded workflow/epistemic state, effective assessment, stale-basis flags,
hypothetical status, reviewer reasons and review history. Explicit relationships
identify assumptions, supporting and opposing evidence and revisit checks.
Checks/results pinned by payloads or review basis are also included. Support and
opposition are collected together regardless of lexical ranking, including
proposed and rejected relationships with their recorded state. They never
silently become accepted evidence. Unresolved opposition and findings add
explicit warnings even when a prior recorded assessment says `supported`.

Only typed `depends_on`, `supports`, `opposes`, `checks` and `result_of` links
extend the dependency neighborhood. Similarity/analogy/connectivity and lexical
relevance never become truth confidence. Source lineage IDs are descriptive,
not independent-vote counts. Structured scope comparisons may be comparable,
disjoint or unknown; free-text reasoning remains unresolved.

Exact payload and review-basis dependencies seed that same typed neighborhood:
claims cited by a review retain linked opposition, and checks pinned in
`revisit_checks` retain linked results. Exact-reference closure consumes the
record bound; the depth bound counts typed relationship hops from those inputs.

A brief retains at most 200 records, 500 relevant link steps and three typed
hops. It closes the selected dependencies over exact source/profile and review
basis references subject to that record bound. Findings return at most 200
heads and expose truncation. Exceeding a bound produces an explicit incomplete
warning; it cannot establish absence of opposition. Explanatory paths use
exact relationship references. Source payloads include source node IDs, hashes,
locators and exact text; passage citations remain pinned. Nothing fetches a
locator or executes a recorded command.

Use `decision_inspect(reference, revision=brief.revision)` to resolve a cited
record. `get_node(source_ref.node_id)` reads the current live node; use pinned
inspection for historical source text. `included_refs`/`included_ids` identify
record objects actually rendered, not every embedded reference, and
`included_event_ids` accounts for actually displayed review events. A clipped
brief can contain references to records outside its bounded output; the pinned
inspection operation resolves them subject to current permissions.

Unreadable evidence is excluded before output. No hidden source IDs, counts,
quotes or review reasons are added as omission metadata. Every brief cautions
that the accessible view cannot establish absence of opposition. A concurrent
policy or current-lineage change rejects the read, rather than returning a
mixture. Read-only ACL checks retain the existing policy audit behavior outside
the brain; they never record memory usage.

## Budgeted context

This separate builder requires explicit opt-in. It ranks accessible live decision
heads by deterministic lexical overlap of query words with decision payloads,
then stable IDs. Superseded/withdrawn decisions and rejected decision heads are
excluded from prompts, while explicit historical briefs keep their state.
There are no model calls or relevance-to-confidence conversions.

Each selected decision is rendered as one atomic qualified unit. Context keeps
full conditions, limitations, epistemic/review state, reasons, IDs and citations.
Source excerpts cap at 300 characters with an explicit truncation marker;
findings retain reasons and a bounded exact reference to their full paths in
pinned inspection. Full JSON/Markdown briefs retain the source text and paths.
If an entire qualified unit cannot fit, or its dependency closure exceeded the
hard bounds, the builder omits that unit. It never prefix-trims a conclusion
separately from an essential qualification. An empty string is a valid result
for tiny budgets. `truncated`, `omitted`/`abbreviated` with reasons and included-ID accounting
make this explicit. `k` clipping also sets `truncated`.

The estimate is one token per CJK character plus ceil(other characters / 4).
It counts the complete rendered context: headings, stable IDs, conditions,
review reasons, warnings, source excerpts, separators and citations. It excludes
the JSON response envelope and the rest of the caller's prompt. **It is not an
exact tokenizer cap.** Callers must budget their full model prompt separately
and must not substitute omitted conclusions from response metadata.

## Runnable no-provider two-session example

```bash
python -m examples.decision_memory
# Optional persistence, using an empty dedicated path:
python -m examples.decision_memory --brain /tmp/decision-demo
```

Session one records a scoped observation, support, a reviewed claim and a current
justified decision. Session two uses fresh service instances, adds explicitly
structured contrary evidence, compares local commits, explicitly confirms an
explained review finding and renders a qualified brief/context. The finding
includes the reviewer reason and exact dependency paths. The example makes no
provider calls/downloads, executes no experiment and fetches no external source.
The observations are supplied synthetic data, not real research results.

Optional real-model usage remains separately configured in
`examples.agent_memory --model <MODEL>`; it is not enabled here and its latency,
cost and answer quality are not measured by this example. Exports remain
explanatory briefs: prose-to-linter compilation and generated experiment
execution are outside v1.

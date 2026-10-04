# GraphEngine 🕸️

**A self-maintaining, self-improving knowledge graph engine.**

Ingest ideas as Markdown nodes into your own private git repo (the "brain"),
let the engine embed, link, and consolidate them — then steer research with
coverage gaps and grow the engine itself through an eval-gated feedback loop.

![GraphEngine — demo brain in the web UI](docs/screenshot.png)

## Quickstart

```bash
# 1) set up the engine (Python 3.11+) — lightweight core, HashEmbedder works
#    out of the box; add the real embedder with: pip install -e ".[st]"
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 2) create a brain — `--demo` seeds it with an example graph
ig init --demo     # 13 nodes, 19 edges, 2 pending suggestions,
                   # 1 island (ig status), 1 near-dup pair (ig near-dup)

# 3) see it in the web UI
uvicorn graph_engine.server:app --port 8000   # → http://localhost:8000
```

Or install from PyPI (recommended — versioned releases):

```bash
pip install graph-engine
# with the real (semantic) embedder — pulls PyTorch:
pip install "graph-engine[st]"
```

Or install straight from the repository (latest main):

```bash
pip install git+https://github.com/SaltKing0/graph-engine.git
# with the real (semantic) embedder — pulls PyTorch:
pip install "graph-engine[st] @ git+https://github.com/SaltKing0/graph-engine.git"
```

The web UI ships inside the package, so a pip install serves it out of the
box. Without the `[st]` extra the engine falls back to the deterministic
HashEmbedder (lower quality, zero model download) with a notice on first use.

Start from scratch instead with `ig init` (empty brain), connect a private
remote with `ig init --remote <url>`, or auto-clone an existing brain on
first use via `IG_BRAIN_REMOTE=<url>`. Every ingest is a git commit — the
graph grows as visible history.

## How it works

```
┌──────────────┐   git commit+push   ┌────────────────────┐   git pull   ┌─────────────────┐
│ your agent   │ ──────────────────▶ │ your brain repo    │ ◀──────────▶ │ Live Engine     │
│ (CLI/API)    │   (knowledge)       │ (private, Markdown)│  (sync)      │ Ingest→Embed→   │
└──────────────┘                     └────────────────────┘              Suggest→Viz+HITL │
                                                                          └─────────────────┘
```

- **Nodes** — one Markdown file per idea (`nodes/<id>.md`, YAML frontmatter:
  `type: semantic|episodic|procedural|entity`, `status: probation|active|tombstone`).
  Episodic nodes carry `observed_at` (when the event happened) and `context`
  (where/how it was observed) — they are raw observations, not deduplicated.
- **Edges** — `edges.jsonl`, typed (`similar`, `extends`,
  `contradicts`, `supersedes`, `continues`, `same_as`),
  bi-temporal (`valid_from`/`valid_to`) with confidence + provenance
- **vectors.jsonl** — embedding cache · **INDEX.md** — generated TOC
- **Human in the loop** — similarity edges ≥ 0.95 auto-accept, the rest go
  pending for review (CLI `ig pending`/`ig accept` or the web UI)

## Connect your agent

The engine is built for agents — the web UI is the human side, the CLI/API is
the agent side. Any agent that can run shell commands can own a brain:

```bash
# the agent ingests what it learns (source is logged per node)
ig ingest "User prefers short answers over long essays" --source agent
cat research-note.md | ig ingest - --source research   # from stdin

# suggestions pile up in pending; the human reviews when they feel like it
ig pending                     # what needs a decision
ig accept <edge_id>            # or in the web UI, with one click
```

Because the brain is a git repo, the agent and the human can work from
different machines: point the brain at a private remote (`ig init --remote`)
and every ingest pulls, commits, and pushes — the graph syncs itself, and the
git history shows exactly what the agent learned and when.

Prefer HTTP? Run the server and `POST /api/ingest` with
`{"text": "...", "source": "agent"}` — same dedupe, same pending flow,
live updates in the web UI over WebSocket.

A realistic loop: the agent ingests findings as it works, `ig gaps` tells it
which topics are thin, `ig status`/`ig near-dup` flag hygiene work — the
self-evolving pipeline below automates exactly that cycle.

## The self-evolving loop (`tools/`)

The engine doesn't just store knowledge — it improves itself, in three tiers:

1. **Measure** (`ig_cycle`) — safe mechanical ingest runs (marker-scan →
   dry-run → real ingest) record per-run metrics: nodes added, islands,
   duration, acceptance.
2. **Adapt** (`ig_adapt`) — an adaptive controller reads the metrics and
   steers the next runs: research topics with the thinnest coverage get
   higher weight, batch size adapts to timeout history.
3. **Extend** (`ig_evolve`) — brain research becomes engine features via
   red-spec eval cases in the roadmap harness, flipped to the golden set
   only after implementation (first self-extension: `IG_EDGE_CONF_FLOOR`).

## CLI

```bash
ig init [--remote <url>] [--demo]  # create a brain (empty / connected / demo)
ig ingest "New idea ..."           # ingest (duplicates are merged)
ig entities "Alice works at Acme. She uses Python." [--dry-run] [--json]
                                  # typed entities + pending fact triples
ig entities --node <node_id>       # extract from an existing note/event
ig observe "Event ..."              # store raw episodic event (no dedupe)
ig extract <episodic_id> ["text"]   # extract semantic fact from episodic node
ig consolidate [--dry-run] [--json] # automatically extract eligible episodic nodes
ig timeline [--since X] [--until Y] # query episodic nodes by time range
ig valid-at <ISO-8601>             # graph as it was at a point in time
ig history <node_id>               # how a node's edges evolved over time
ig when <ISO-8601> <query>         # retrieval restricted to what was known then
ig context <query> [--budget N]     # build a context window for a prompt
ig search "attention"              # hybrid search (dense + BM25 via RRF)
ig explain <node_id> --query "attention" [--json]
                                   # explain scores/ranks for a fresh query;
                                   # read-only, including graph context
ig pending / accept / reject       # review edge suggestions
ig accept-pending [--max-intent-per-source 2] [--dry-run]
                                   # accept pending suggestions in ONE commit,
                                   # but hold intent edges beyond the cap
                                   # (contradicts/supersedes fan-out) for review
ig gaps [--min 10] [--json]        # coverage report + under-covered areas
ig communities [--min-size 15] [--top 10] [--json]
                                   # topology: communities, god nodes, structural gaps
ig report [--since 24h|--top 5] [--json] [--write]
                                   # one-page BRAIN_REPORT digest (deltas, intent
                                   # review queue, hubs, hygiene, research next);
                                   # --write regenerates the tracked BRAIN_REPORT.md
ig status / near-dup               # hygiene: islands, orphans, near-dup pairs
ig recall [--top 10] [--aggregate] # what the memory is actually asked for
                                   # (--aggregate folds the local recall ledger
                                   #  into the node counters, one commit)
ig dream                           # dream plan (read-only): promotion/decay
                                   # candidates, near-dup review list, distillable
                                   # communities, what a refresh would change
ig dream --refresh                 # deterministic maintenance, one commit
ig dream --consolidate             # episodic → semantic extraction (env gates)
ig dream --distill [--llm]         # one abstraction node per community
                                   # (extractive by default; --llm needs
                                   #  IG_DREAM_LLM_CMD)
ig dream --lifecycle               # promotion/decay from the recall signal:
                                   # used + connected -> active, unused + weak +
                                   # old -> stale (a demotion, never a deletion;
                                   # gates are flags, see the section below)
ig merge <survivor> <deletee>      # consolidate a near-duplicate pair
ig mcp                             # read-only MCP server over stdio (AI assistants)
ig mcp --write                     # + remember/recall/forget (agent memory, opt-in)
```

## Extract entities and facts

`ig entities` creates an entity subgraph linked to the semantic or episodic
evidence. Each entity is a node with `type: entity`, `entity_name`,
`entity_type` (`person`, `org`, `concept`, `location`, `product`, `unknown`)
and explicit `aliases`. A fact is a directed edge with `kind: fact`:
its `source` is the subject entity ID, `predicate` names the relation, and
`target` is the object entity ID. `evidence` retains exact quotes and their
source node IDs. Accepted `mentions` edges link the evidence node to its
entities. These are ordinary graph nodes/edges: search can retrieve entities,
and the web graph shows their relationships and fact predicates.

```bash
ig entities "Alice works at Acme. She uses Python." --dry-run --json
ig entities "Alice works at Acme. She uses Python."
# person Alice, org Acme, concept Python;
# Alice --works_at--> Acme, Alice --uses--> Python
cat note.txt | ig entities - --source research --json
ig entities --node <semantic_or_episodic_node_id> --json
ig pending                         # review extracted fact edges
ig accept <fact_edge_id>            # accept in CLI or web UI
```

The default extractor needs no model download or new dependencies. It recognizes
a small grammar of complete English/German sentences: `works at` / `works for`
/ `arbeitet bei`, `founded` / `gründete`, `lives in` / `wohnt in`,
`is based in`, and `uses` / `nutzt`. Names must consist of capitalized words,
or match an already known name/alias. Explicit declarations such as
`Alice is a person`, `Python is a concept`, or `Berlin ist ein Ort` create
typed entities without asserting a relation. Relation roles suggest entity
types; `uses` assigns an otherwise unknown subject type and a concept object,
preserving a known object's explicit type (for example, `product`).
These are heuristic labels, not a general named-entity recognition model.
Unsupported prose can yield no extraction; it does not create an empty graph
or an evidence node. Ordinary `ig ingest` does not extract automatically.

`International Business Machines (IBM)` declares an acronym alias. Later
`Alice works at IBM` reuses that organization. Names/explicit aliases are
matched by Unicode normalization, whitespace and case, **within the same
entity type**. No similarity or surname matching is used. Different people
with the same name require distinguishing names; name matching alone cannot
prove identity. Ambiguous alias matches abort the batch before writing.
`he`/`she`/`er`/`sie` and `it`/`es` resolve only if there is exactly one
compatible person/organization earlier in the current input; otherwise that
sentence is skipped. Cross-document pronouns are never guessed.

Raw input, with outer whitespace trimmed, is stored in an exact-text-deduplicated
semantic evidence node;
`--node` uses a live semantic, episodic or procedural node unchanged. Entity
identities are excluded from ingest/dedup consolidation and cannot be merged
with `ig merge`. Identical typed entities and fact triples are reused across
inputs, adding source evidence to existing facts. An unchanged repeat writes
nothing; a changed pass commits once. Rejected/invalidated facts stay decided,
and a forgotten matching entity causes an error instead of being recreated.
`--accept-facts` accepts **new** fact edges immediately; the default is pending
review, including for model output. The web review card shows the predicate
and quoted evidence. Existing decisions are preserved.

### Optional model extraction

For free prose or richer coreference, configure `IG_ENTITIES_LLM_CMD` and pass
`--llm`. The shell command receives a JSON request on stdin containing `text`,
`known_entities`, an extraction `instruction`, `entity_types` and a `schema`.
It must print one JSON object on stdout (no Markdown):

```json
{
  "entities": [
    {"name": "Alice", "type": "person", "aliases": []},
    {"name": "Acme", "type": "org", "aliases": []}
  ],
  "facts": [
    {"subject": "Alice", "predicate": "works_at", "object": "Acme",
     "evidence": "Alice works at Acme", "confidence": null,
     "valid_from": null, "valid_to": null}
  ]
}
```

Fact endpoints refer to canonical names in that response. Aliases, confidence
and dates are optional. The engine validates types, references, literal entity
mentions, exact evidence quotes, finite confidence in `[0, 1]`, and ordered
ISO-8601 validity windows before writing. Aliases can anchor a canonical name
that is absent from the input. Quote validation checks provenance; it does
not verify the model's interpretation or identity claims. Negation, hypothetical
claims and ambiguous coreference should be declined by the extractor and still
require review. Predicate names are normalized to lowercase with underscores.
Failure, malformed output or a 300-second timeout aborts extraction.

Without a validity date, `valid_from` records extraction time; no event date is
inferred. Explicit dates are normalized to UTC (timezone-free dates use UTC),
and `valid_to` requires a preceding `valid_from`. Explicitly different validity
windows remain separate edges. New observations do not automatically invalidate
conflicting facts. Use the existing temporal API to inspect accepted facts by
validity. `--dry-run` never syncs or writes the brain, but **with `--llm` it does
invoke the configured model command** so it can show the actual extraction.
Preview node/edge IDs are temporary until a real pass writes them.

```bash
export IG_ENTITIES_LLM_CMD='your-json-extraction-command'
ig entities --node <node_id> --llm --dry-run --json
ig entities --node <node_id> --llm --json
```

Python callers can use `engine.entities(text, ...)` or
`extract_entities(brain, text, extractor=...)` from `graph_engine.entities`.
An extractor callable receives `(text, known_entities)` and returns the same
JSON-compatible structure.

## Explain a search result

`ig explain <node_id> --query "your search"` recomputes the search against the
current brain and embedder. The query is required: a node ID alone cannot
explain a query-dependent ranking. Use `--json` for structured output,
`--top N` for the result count (default 5), and `--rerank-k N` for the candidate
limit (default 30), matching the search defaults.

The explanation shows raw BM25 and dense cosine scores, each channel's
one-based rank and RRF contribution (`1 / (60 + rank)`), the fused score/rank,
matched lexical terms, and the final score. With the cross-encoder enabled,
the final score is its model prediction, labelled `reranker`, and is distinct
from the RRF score. `retrieval_score` retains the score returned by search;
`reranker_score` exposes the model prediction even for a scored candidate
outside the final top-k. Ordering-only or legacy rerankers without separate
predictions retain the `rrf` label and have a null `reranker_score`. Dense scores
are `null` when the cached vector is incompatible with the query dimension.
A node outside the results is explained too: `no_overlap`,
`outside_candidate_limit`, or `outside_top_k`.

Accepted, live edges connecting the node to other returned results appear as
`graph_context`, with their direction, type, confidence and provenance.
Hybrid search currently uses text and vectors; these connections are context
and do not contribute to the ranking. Pending, rejected, invalidated edges and
connections to tombstoned nodes are excluded. Unknown or tombstoned target
nodes produce a clear error.

Explain does not record a recall, persist vectors, or modify the brain. It
explains a fresh search, rather than reconstructing a past result after the
corpus, embedder or reranker has changed. RRF scores are rank-fusion scores,
not confidence values or similarities.

## MCP server (AI assistants)

Expose the brain to MCP-capable assistants (Claude Desktop, Claude Code, …)
as a **strictly read-only** tool surface:

```bash
pip install 'graph-engine[mcp]'
ig mcp   # or: ig-mcp — stdio JSON-RPC, nothing else touches stdout
```

Register it in `claude_desktop_config.json` / `.mcp.json`:

```json
{
  "mcpServers": {
    "graph_engine": {
      "command": "ig-mcp",
      "env": { "IG_BRAIN_PATH": "~/graph-engine-brain" }
    }
  }
}
```

Four tools, all annotated `readOnlyHint`:

| Tool | Purpose |
|---|---|
| `search_brain` | hybrid search (dense + BM25, RRF-fused); `score` is a rank-fusion score, **not** a similarity |
| `get_node` | one node: full text (capped at 2000 chars) + its live edges |
| `neighbors` | undirected graph neighborhood, 1–2 hops — the question vector search cannot answer |
| `brain_status` | cheap orientation: size, connectivity, pending-review load |

### Agent memory: `ig mcp --write` (opt-in)

```bash
ig mcp --write   # or IG_MCP_WRITE=1 — adds three write tools
```

| Tool | Purpose |
|---|---|
| `remember` | store one note; recorded with `source="agent"`, dedupe-aware (a near-duplicate merges into the existing node) |
| `recall` | search whose hits **count as use** (`recall_count`) — the promotion signal the dream pass consumes; use `search_brain` for pure exploration |
| `forget` | remove a node from every live view — it **tombstones and invalidates, it never deletes**, and a mandatory `reason` lands in the commit message |

Write mode keeps the same discipline as the rest of the engine: **provenance**
(so "what did a model write?" stays a query), **never destructive**, **one commit
per write**. The write tools are registered only in write mode and carry
`readOnlyHint: false`, so a client asks its user before letting a model write into
the private brain. In read-only mode they return a `write_disabled` envelope.

Design guarantees: the read-only default stays strict — ingest commits and pushes
to a private repo, so model-initiated writes are an explicit operator decision,
not a default; the engine loads lazily (first search, not import),
response payloads are capped and escaped in one place (`graph_engine/mcp/format.py`),
and by default even the derived vector cache is **never written** — a search on
a cold clone does not dirty the private repo (`IG_MCP_CACHE_VECTORS=1` opts
back in; measured cold-search cost: see CHANGELOG). `brain_status` returns the
brain path basename only. Optional opt-in prompt snippet for your
`CLAUDE.md`/`AGENTS.md`: `graph_engine/mcp/agent/instructions.md`.

## Memory lifecycle (promotion and decay)

`ig dream --lifecycle` is what makes the dual buffer mean something. The gates are
**derived from your brain's measured distribution**, not from another project's
numbers — `ig dream` (read-only) prints the candidates under any gate before you
apply anything:

| Transition | Gate | Default |
|---|---|---|
| `probation → active` | used **and** connected | `recall_count >= 1`, degree >= 2 |
| `probation/active → stale` | unused, weak, old | `recall_count == 0`, degree <= 2, age >= 30 d |
| `stale → active` | used again | same as promotion — decay is reversible |

`stale` is a **demotion, never a deletion**: the node keeps its file, stays
searchable, and leaves the promotion pool. `recall` (MCP write mode) and
`ig search` feed the signal it reads. Override the gates with
`--min-recall / --min-degree / --stale-days / --max-degree`.

## Automatic episodic consolidation

`ig consolidate` selects live episodic observations and derives semantic nodes
without changing the original events. Defaults are conservative: the event must
have an **aggregated recall count >= 1** and be **at least one day old**. These
are selection gates, not a confidence score or proof that an observation is true.
Age uses `observed_at`, falling back to `created`; timestamps without a timezone
are interpreted as UTC, and malformed or future timestamps are held back.

```bash
ig recall --aggregate              # fold search/recall usage into node counters
ig consolidate --dry-run --json    # preview source IDs and gates; no writes/LLM calls
ig consolidate                    # extract up to 50 eligible events, one commit
ig dream --refresh --consolidate   # fold usage, then extract, in the dream pipeline
ig dream --json                    # read-only plan includes extraction candidates
```

The default extractor copies the observation's text, matching `ig extract`:
it preserves evidence without generating an abstraction or inferring new facts.
New semantic nodes have `status="probation"`, `source="consolidator"` and an
`episodic-extraction` tag. An accepted `extends` edge points from the fact to
each episodic source. Exact semantic matches (case and whitespace normalized)
are reused; episodic/procedural nodes and community summaries are never used
as semantic matches.
Existing extraction links, including manually created, rejected or invalidated
links, prevent repeat extraction. Community-summary links do not count as fact
extraction. Tombstoned facts are never resurrected or recreated from matching
text. An unchanged second pass writes nothing.

Configure the time gate with `--min-age-days`, the recall threshold with
`--threshold`, and the minimum **eligible, unprocessed** pool size with
`--min-count`. Gates combine; the count check runs before the per-pass `--limit`
(oldest first within each round), so a remaining pool below `--min-count` waits
for more events. Bounded passes save their position in `consolidation-cursor.json`
inside the brain and resume after the last examined event, wrapping back to the
oldest. Skipped or declined events remain retryable without blocking newer
candidates. Dry runs read this position but never advance it.
CLI flags override the environment. For a deliberate pass over fresh, unused
events, use `ig consolidate --threshold 0 --min-age-days 0`.

Fact IDs are independent of text. Editing or merging a fact keeps its identity;
a later extraction reuses an exact current-text match or creates a new fact.

The command does not start a daemon: run `ig dream --refresh --consolidate` from
your scheduler for time-based checks, or invoke it manually. Completed ingest
cycles in `tools/ig_cycle.py` now include `--consolidate`; cycles that abort before
the dream step still perform no extraction. `ig dream` without action flags
remains read-only. Dream accepts the same gate flags, using `--consolidate-limit`
for extraction because its existing `--limit` controls community distillation.

For optional refinement, set `IG_CONSOLIDATE_LLM_CMD` to a command that reads an
evidence prompt on stdin and prints **one grounded fact** on stdout, then run
`ig consolidate --llm` or `ig dream --consolidate --llm`. Blank stdout declines
extraction and leaves the event eligible for a later run. Nonzero exit status or
a 300-second timeout aborts the extraction batch before any facts are written.
The model's output still requires review; no automatic grounding check is made.
Dry runs never invoke the command and report candidate events rather than
model-dependent output counts. When dream combines `--distill --consolidate --llm`,
distillation also requires its separate `IG_DREAM_LLM_CMD`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `IG_BRAIN_PATH` | `~/graph-engine-brain` | path to the brain clone |
| `IG_BRAIN_REMOTE` | *(none)* | remote brain URL — auto-clones on first use |
| `IG_BRAIN_MODE` | `git` | `local` = filesystem only (tests) |
| `IDEAGRAPH_EMBEDDER` | `st` | `hash` = deterministic test embedder |
| `IDEAGRAPH_AUTO_ACCEPT` | off | `1` = auto-accept all suggested edges |
| `IG_MCP_CACHE_VECTORS` | `0` | `1` = MCP search may fill the on-disk vector cache (default: strictly read-only) |
| `IG_MCP_MAX_SNIPPET_CHARS` | `200` | search-result snippet cap |
| `IG_MCP_MAX_NEIGHBORS` | `20` | neighbors result cap (hard max 50) |
| `IDEAGRAPH_INTENT_PENDING` | off | `1` = intent edges become pending (HITL) |
| `IDEAGRAPH_RERANKER` | none | optional cross-encoder rerank pass |
| `IG_BOT_NAME` / `IG_BOT_EMAIL` | graph-engine-bot | git commit author |
| `IG_CONSOLIDATE_THRESHOLD` | `1` | minimum aggregated recall count (integer >= 0) |
| `IG_CONSOLIDATE_MIN_AGE_DAYS` | `1` | minimum observation age in days (finite number >= 0) |
| `IG_CONSOLIDATE_MIN_COUNT` | `1` | minimum eligible, unprocessed events before a pass (integer >= 1) |
| `IG_CONSOLIDATE_LIMIT` | `50` | maximum events per pass (integer >= 1) |
| `IG_CONSOLIDATE_LLM_CMD` | *(none)* | optional stdin/stdout fact extractor, invoked only with `--llm` |
| `IG_ENTITIES_LLM_CMD` | *(none)* | optional JSON stdin/stdout entity and triple extractor for `ig entities --llm` |

Dedupe: near-duplicate ingests (cosine ≥ 0.92) merge into the existing node
(`sources:` provenance); opt out with `allow_duplicates: true`.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q   # prints the current suite count
```

## Status

Core features, the hygiene loop, the topology/digest reports, the MCP server
(read-only by default, `--write` for the agent memory path), the dream pass
(maintenance, distillation, status lifecycle) and the self-evolving pipeline are
implemented; release `v0.5.4` is published — see [CHANGELOG.md](CHANGELOG.md).

### Known limitations

- **The intent heuristics are marker-based, not semantic.** `contradicts` /
  `supersedes` / `continues` edges come from marker words plus a similarity gate;
  measured on real prose, **every** live intent edge created so far turned out to
  be a false positive (168 created, all invalidated by hand — the marker usually
  sits in an EXISTING node's descriptive text, not in the new one). Mitigations:
  intent edges are born pending under `IDEAGRAPH_INTENT_PENDING=1`, the fan-out
  cap (`ig accept-pending`, max 2 per source) stops mass-firing, and
  `scripts/intent_edge_cleanup.py` triages a batch. Treat a live intent edge as a
  claim to verify, not as a fact.
- **Promotion/decay is a usage signal, so it measures who asked.** A node is
  promoted for being recalled, not for being important; a young brain with few
  searches promotes almost nothing, and decay (30 days of silence) cannot fire
  before the corpus is that old.
- **Distillation is extractive by default.** `--llm` needs `IG_DREAM_LLM_CMD`;
  the summaries are structured evidence, not prose abstractions.
- **`ig near-dup` flags related-but-distinct pairs.** The 0.78–0.92 band is a
  review list; the top pairs on a mature brain are demonstrably distinct topics,
  and nothing merges automatically.

## Open source / privacy

The **engine is generic** (this public repo) — the **brain is your private
repo** with your data. The engine contains no brain data.

## License

MIT — see `LICENSE`.

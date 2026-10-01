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
  `type: semantic|episodic|procedural`, `status: probation|active|tombstone`).
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
ig observe "Event ..."              # store raw episodic event (no dedupe)
ig extract <episodic_id> ["text"]   # extract semantic fact from episodic node
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

## Explain a search result

`ig explain <node_id> --query "your search"` recomputes the search against the
current brain and embedder. The query is required: a node ID alone cannot
explain a query-dependent ranking. Use `--json` for structured output,
`--top N` for the result count (default 5), and `--rerank-k N` for the candidate
limit (default 30), matching the search defaults.

The explanation shows raw BM25 and dense cosine scores, each channel's
one-based rank and RRF contribution (`1 / (60 + rank)`), the fused score/rank,
matched lexical terms, and the final score. With a reranker enabled, the final
score is labelled `reranker` and is distinct from the RRF score. Dense scores
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

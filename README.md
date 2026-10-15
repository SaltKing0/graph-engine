# GraphEngine 🕸️

**A Git-backed knowledge graph for agents and humans.**

Store knowledge as Markdown in your own private repository. GraphEngine adds
search, relationships, memory maintenance and a web UI, with every change
recorded in Git.

![GraphEngine — demo brain in the web UI](docs/screenshot.png)

- Search with embeddings and BM25; explain results and graph connections.
- Extract entities and facts with source evidence and a review queue.
- Consolidate observations, organize memory into tiers and learn from feedback.
- Connect agents through the CLI, HTTP API or optional MCP server.
- Keep separate graphs with optional role and node access control.

## Quickstart

Requires **Python 3.11+** and **Git**. These instructions use current `main`;
published packages may have fewer features.

```bash
git clone https://github.com/SaltKing0/graph-engine.git
cd graph-engine
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"

export IG_BRAIN_PATH="$PWD/demo-brain"
export IDEAGRAPH_EMBEDDER=hash
ig init --demo
python -m uvicorn graph_engine.server:app --host 127.0.0.1 --port 8000
```

Open <http://localhost:8000>. The demo uses deterministic hash embeddings with
no model download. For semantic search, install `python -m pip install -e ".[st]"`
and set `IDEAGRAPH_EMBEDDER=st` before starting a fresh brain.
Embedding and reranker models must use built-in modules: custom Python model
code is disabled, including for local model directories.

Browser realtime connections use a same-origin policy: `/ws` checks the page's
scheme, hostname and port before accepting. Native clients may omit `Origin`;
protected mode disables WebSockets. See [realtime access](docs/guide.md#web-ui-realtime-access).

On Windows, activate with `.venv\Scripts\Activate.ps1` and set environment
variables using PowerShell's `$env:NAME="value"` syntax.

For a released package, use `python -m pip install graph-engine-memory` in a virtual
environment. Optional extras: `[st]` for semantic embeddings, `[mcp]` for MCP,
`[pdf]` for local PDF import.

Version 0.6.1 is the first PyPI release under the `graph-engine-memory` package name
(previously `ideagraph-live`). Install it in a fresh virtual environment and
point `IG_BRAIN_PATH` at your existing brain. The `ig` commands remain;
Python imports and the uvicorn module now use `graph_engine` instead of
`ideagraph`.

## Everyday use

```bash
ig ingest "User prefers short answers" --source agent
ig search "answer preferences"
ig entities "Alice works at Acme." --dry-run --json
ig ingest "Alice works at Acme." --extract-entities --json
ig import ./notes --recursive --extensions .md .txt --dry-run --json
ig import ./notes --recursive --extensions .md .txt --source-prefix my-library
ig pending
ig accept <edge_id>
ig explain <node_id> --query "answer preferences"
ig dream                          # preview memory maintenance
```

For your own brain, set `IG_BRAIN_PATH` and run `ig init` without `--demo`.
The default path is `~/graph-engine-brain`. Connect a private remote with
`ig init --remote <url>`; Git mode commits changes and syncs with that remote.
CLI, HTTP and MCP writers on the same local brain now share a bounded write
guard, including Git sync. `IG_WRITE_LOCK_TIMEOUT=30` sets the maximum wait in
seconds (0–3600; `0` fails immediately when busy). See
[local writer coordination](docs/guide.md#local-writer-coordination) for filesystem,
crash and read-snapshot limits. Keep one writer where clients bypass this guard,
on network filesystems, or across separate clones/machines.

To connect an MCP client, install the MCP extra and run `ig mcp`.
It is read-only by default; `ig mcp --write` enables remember, recall and forget.
See the [MCP setup](docs/guide.md#mcp-server-ai-assistants) for client configuration.

Entity extraction during capture is explicit: use `--extract-entities` for rules
or `--extract-model` with `IG_ENTITIES_LLM_CMD` for the configured JSON adapter.
HTTP ingest and MCP remember accept `extraction: "rules"` or `"model"`.
Facts stay pending by default. Capture and extraction use two commits; exact
input receipts make retries safe even when ingestion merges a similar note.
See [capture options and retry behavior](docs/guide.md#extract-during-ingestion).
Local document import captures bounded chunks with source IDs, hashes and text
locations (or PDF pages). Basic import needs no embedder; `--ingest`,
`--extract-entities` and `--extract-model` opt into the existing pipeline.
Retries preserve manual edits and earlier versions. Stored provenance includes
absolute filenames/paths by default; use `--source-id` or `--source-prefix` to
control it. See [document import](docs/guide.md#local-document-import).
Explicit fact replacements create separate pending proposals; review both
claims, evidence and event dates before accepting, rejecting or undoing them.
See [replacement review](docs/guide.md#review-fact-replacements).

Use `ig snapshot HEAD~1 "attention" --json` to search historical committed text,
or `ig snapshot <commit-or-ref> --json` to inspect historical records and review
state. Optional `--valid-at <ISO-8601>` filters that snapshot by fact validity.
Snapshot queries apply current permissions and leave the active brain unchanged.
See [Git snapshots](docs/guide.md#git-revision-snapshots) for semantics and limits.

Forgetting removes a node and edges supported by it from live graph, direct
node, neighborhood and review views. Explicit history and Git snapshots retain
records under current permissions. See [live views and history](docs/guide.md#live-views-and-history).

For structured episodic consolidation, explicitly run `ig consolidate --structured`
or `ig dream --consolidate --structured`. Exact quotes and event IDs are validated
before one batch commit. Proposed semantic nodes are labelled and searchable;
their evidence links require individual review. Quote matching proves provenance,
not factual entailment. Copy mode and legacy `--llm` remain available.

| Variable | Default | Meaning |
|---|---|---|
| `IG_EDGE_CONF_FLOOR` | `0.0` | Minimum confidence for similarity suggestions; finite number from 0 through 1. Invalid values reject ingest before storage changes. |
| `IG_CONSOLIDATE_STRUCTURED_CMD` | *(none)* | Opt-in JSON stdin/stdout proposal command for `--structured`; 300-second timeout, 128 KiB output limit. Separate from legacy `IG_CONSOLIDATE_LLM_CMD`. |

See the [structured protocol and publication policy](docs/guide.md#structured-consolidation-proposals).

Background maintenance requires explicit startup (Linux/macOS):

```bash
ig maintenance --once --actions refresh lifecycle consolidate
ig maintenance --interval 900 --actions refresh lifecycle consolidate --limit 50
```

The packaged worker needs no embedder or model download. It shares the local
writer guard, requires an admin principal in protected mode, keeps new evidence
pending and prints JSON summaries without node text or tokens. Model extraction
requires its own `--extract-model` flag. See [worker limits, failures and local
deployment](docs/guide.md#background-maintenance-worker).

## Documentation

- [CLI reference](docs/guide.md#cli) and [configuration](docs/guide.md#configuration)
- [Entities and facts](docs/guide.md#extract-entities-and-facts)
- [Memory lifecycle](docs/guide.md#memory-lifecycle-promotion-and-decay),
  [storage tiers and feedback](docs/guide.md#storage-tiers-and-retrieval-feedback)
- [Isolated graphs and access control](docs/guide.md#isolated-graphs-and-access-control)
- [Opt-in graph retrieval and scoring](docs/graph-retrieval.md)
- [Memory answer-quality benchmarks](docs/memory-benchmarks.md)
- [Retrieval performance and disposable indexes](docs/retrieval-performance.md)
- [Budgeted agent context and two-session example](docs/guide.md#budgeted-context-and-a-complete-agent-turn)
- [Known limitations](docs/guide.md#known-limitations)
- [Changelog](CHANGELOG.md) and [contributing](CONTRIBUTING.md)

The engine is public; your brain is a separate repository under your control.
Extracted facts and heuristic relationships are claims to review, not verified truth.

## Development

```bash
python -m pip install -e ".[dev,mcp]"
python -m pytest tests/ -q
```

MIT — see [LICENSE](LICENSE).

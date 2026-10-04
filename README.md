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

On Windows, activate with `.venv\Scripts\Activate.ps1` and set environment
variables using PowerShell's `$env:NAME="value"` syntax.

For a released package, use `python -m pip install graph-engine` in a virtual
environment. Optional extras: `[st]` for semantic embeddings, `[mcp]` for MCP.

## Everyday use

```bash
ig ingest "User prefers short answers" --source agent
ig search "answer preferences"
ig entities "Alice works at Acme." --dry-run --json
ig pending
ig accept <edge_id>
ig explain <node_id> --query "answer preferences"
ig dream                          # preview memory maintenance
```

For your own brain, set `IG_BRAIN_PATH` and run `ig init` without `--demo`.
The default path is `~/graph-engine-brain`. Connect a private remote with
`ig init --remote <url>`; Git mode commits changes and syncs with that remote.
Use one writer process per brain.

To connect an MCP client, install the MCP extra and run `ig mcp`.
It is read-only by default; `ig mcp --write` enables remember, recall and forget.
See the [MCP setup](docs/guide.md#mcp-server-ai-assistants) for client configuration.

## Documentation

- [CLI reference](docs/guide.md#cli) and [configuration](docs/guide.md#configuration)
- [Entities and facts](docs/guide.md#extract-entities-and-facts)
- [Memory lifecycle](docs/guide.md#memory-lifecycle-promotion-and-decay),
  [storage tiers and feedback](docs/guide.md#storage-tiers-and-retrieval-feedback)
- [Isolated graphs and access control](docs/guide.md#isolated-graphs-and-access-control)
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

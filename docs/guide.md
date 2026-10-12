# GraphEngine guide

[Back to the README](../README.md)

## Quickstart

Requires **Python 3.11+** and **Git**. This README describes the current source
checkout; published packages can lag behind the features on `main`.

```bash
git clone https://github.com/SaltKing0/graph-engine.git
cd graph-engine
python3 -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

# Keep the demo brain separate from any existing brain.
export IG_BRAIN_PATH="$PWD/demo-brain"  # PowerShell: $env:IG_BRAIN_PATH="$PWD/demo-brain"
export IDEAGRAPH_EMBEDDER=hash         # PowerShell: $env:IDEAGRAPH_EMBEDDER="hash"
ig init --demo                        # seed an example graph
ig status
python -m uvicorn graph_engine.server:app --host 127.0.0.1 --port 8000
```

Open <http://localhost:8000> for the packaged web UI. The demo uses the
deterministic HashEmbedder: no model download, suitable for trying the workflow.
For semantic embeddings, install the optional dependency and select it before
starting the CLI or server (the model downloads on first use):

```bash
python -m pip install -e ".[st]"       # installs sentence-transformers and PyTorch
export IDEAGRAPH_EMBEDDER=st
```

Without `[st]`, the default `st` setting falls back to HashEmbedder with a notice.
Hash embeddings use word overlap and have lower semantic quality. Use a fresh
brain when comparing embedders so existing similarity edges and dedupe decisions
do not reflect a different model.

### Install a released package

In an activated Python virtual environment:

```bash
python -m pip install graph-engine-memory
# Optional extras (can be combined, for example graph-engine-memory[st,mcp]):
python -m pip install "graph-engine-memory[st]"   # semantic embeddings
python -m pip install "graph-engine-memory[mcp]"  # MCP server
python -m pip install "graph-engine-memory[pdf]"  # optional local PDF parsing
```

To install current `main` without a checkout:

```bash
python -m pip install git+https://github.com/SaltKing0/graph-engine.git
```

The CLI and web UI ship in the package. The development scripts in `tools/`
and the test suite require a source checkout.

### Use your own brain

Set `IG_BRAIN_PATH` to your chosen directory before running commands. Its default
is `~/graph-engine-brain`. Run `ig init` for an empty brain, or
`ig init --remote <url>` to connect one to a private remote. For an existing
remote brain, set `IG_BRAIN_REMOTE=<url>` and an unused local brain path to clone
it on first use. Configure Git credentials for private remotes beforehand.

Git mode is the default: mutations commit locally and sync when an origin is
configured. `IG_BRAIN_MODE=local` uses files without Git. CLI, server and MCP
writes to the same local brain are serialized by a shared guard; see
[local writer coordination](#local-writer-coordination) for its boundaries.

Jump to [CLI](#cli), [entity extraction](#extract-entities-and-facts),
[MCP](#mcp-server-ai-assistants), [configuration](#configuration),
[storage tiers and feedback](#storage-tiers-and-retrieval-feedback), or
[isolated graphs and access control](#isolated-graphs-and-access-control).

## How it works

```
┌──────────────┐   git commit+push   ┌────────────────────┐   git pull   ┌─────────────────┐
│ your agent   │ ──────────────────▶ │ your brain repo    │ ◀──────────▶ │ Live Engine     │
│ (CLI/API)    │   (knowledge)       │ (private, Markdown)│  (sync)      │ Ingest→Embed→   │
└──────────────┘                     └────────────────────┘              Suggest→Viz+HITL │
                                                                          └─────────────────┘
```

- **Nodes** — one Markdown file per idea (`nodes/<id>.md`, YAML frontmatter:
  `type: semantic|episodic|procedural|entity`, `status: probation|active|stale|tombstone`).
  Episodic nodes carry `observed_at` (when the event happened) and `context`
  (where/how it was observed). They skip cosine deduplication, but identical
  stripped text reuses an existing episodic node unless `ig observe --allow-dup`
  is used to record a distinct occurrence.
- **Edges** — `edges.jsonl`, typed (`similar`, `extends`,
  `contradicts`, `supersedes`, `continues`, `same_as`, `mentions`, `fact`),
  with validity timestamps (`valid_from`/`valid_to`), confidence and provenance.
  Fact edges also store a relation predicate and quoted evidence.
- **vectors.jsonl** — embedding cache · **INDEX.md** — generated TOC
- **Human in the loop** — similarity suggestions ≥ 0.95 auto-accept; lower
  confidence suggestions go pending. Extracted facts are pending by default.
  Intent heuristics have a separate acceptance cap; set
  `IDEAGRAPH_INTENT_PENDING=1` to require review for all intent suggestions.
  Review with `ig pending`/`ig accept` or the web UI.
- **Memory organization** — independent storage tiers (`main`, `recall`,
  `archival`), explicit retrieval feedback, and optional named graphs with
  separate Git histories and access policies.

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

The source checkout includes scripts for an operator-driven improvement loop.
They do not start automatically with the server or install as `ig` subcommands;
run them with `python tools/<script>.py --help` for their options:

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
ig graph list                      # list isolated graphs (requires IG_GRAPH_HOME)
ig graph create <name>             # create a graph
ig graph switch <name>             # persist the selected graph
ig init [--remote <url>] [--demo]  # create a brain (empty / connected / demo)
ig ingest "New idea ..."           # ingest (duplicates are merged)
ig import ./notes --recursive --extensions .md .txt --dry-run --json
                                  # preview local document chunks without brain writes
ig entities "Alice works at Acme. She uses Python." [--dry-run] [--json]
                                  # typed entities + pending fact triples
ig entities --node <node_id>       # extract from an existing note/event
ig observe "Event ..." [--allow-dup] # raw event; flag preserves identical repeats
ig extract <episodic_id> ["text"]   # extract semantic fact from episodic node
ig consolidate [--dry-run] [--json] # automatically extract eligible episodic nodes
ig timeline [--since X] [--until Y] # query episodic nodes by time range
ig valid-at <ISO-8601>             # filter current records by validity at a time
ig history <node_id>               # how a node's edges evolved over time
ig when <ISO-8601> <query>         # search current text, filter by creation time
ig snapshot <commit-or-ref> [query] [--valid-at ISO-8601] [--json]
                                  # read/search committed historical records
ig context <query> [--budget N]     # build a context window for a prompt
ig search "attention"              # hybrid search (dense + BM25 via RRF)
ig infer "How does Alice relate to Acme?" [--json]
                                   # recorded relations, transitive proofs, contradictions
ig explain <node_id> [--max-depth 2] [--limit 20] [--json]
                                   # current graph paths and their supporting edges
ig explain <node_id> --query "attention" [--json]
                                   # explain scores/ranks for a fresh query;
                                   # read-only, including graph context
ig pending                        # list edge suggestions
ig accept <edge_id>                # accept a suggestion
ig reject <edge_id>                # reject a suggestion
ig link <node_a> <node_b> --kind same_as  # add an explicit relationship
ig accept-pending [--max-intent-per-source 2] [--dry-run]
                                   # accept pending suggestions in ONE commit,
                                   # but hold intent edges beyond the cap
                                   # (contradicts/supersedes/continues) for review
ig gaps [--min 10] [--json]        # coverage report + under-covered areas
ig communities [--min-size 15] [--top 10] [--json]
                                   # topology: communities, god nodes, structural gaps
ig report [--since 24h] [--top 5] [--json] [--write]
                                   # one-page BRAIN_REPORT digest (deltas, intent
                                   # review queue, hubs, hygiene, research next);
                                   # --write regenerates the tracked BRAIN_REPORT.md
ig status                         # node status, islands and orphans
ig near-dup                       # near-duplicate review candidates
ig tier <node_id> [main|recall|archival|auto]  # inspect/set storage tier
ig tier --rebalance [--dry-run] [--json]      # apply automatic tier policy
ig feedback "query" <node_id> relevant       # or: irrelevant
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

### Local document import

Import selected local files or directories with `ig import`. Markdown (`.md`)
and UTF-8 text (`.txt`) are selected by default. Directories are shallow unless
`--recursive` is supplied. Extension selection is case-insensitive; use
`--extensions .md .txt .pdf` to include PDF, or `.pdf` alone for a PDF collection.
Symlink files/directories and non-regular files are reported and never followed.
No URL fetching, OCR or background watching is performed.

```bash
ig import ./notes --recursive --extensions .md .txt --dry-run --json
ig import ./notes --recursive --extensions .md .txt --source-prefix research --json
python -m pip install "graph-engine-memory[pdf]"   # source checkout: pip install -e ".[pdf]"
ig import ./paper.pdf --extensions .pdf --source-id paper-2026 --json
ig import ./meeting.md --source-id meeting-2026 --extract-entities --json
```

Basic import stores semantic notes without loading an embedder, generating
edges, invoking a model or generating vectors. Search can build their vectors
later under its normal cache rules. `--ingest` enables existing embedding,
semantic deduplication and edge suggestions for **new** chunks.
`--extract-entities` additionally extracts rule-based entities/facts;
`--extract-model` uses the configured `IG_ENTITIES_LLM_CMD` adapter with its
existing timeout. These three options are mutually exclusive. Facts remain
pending and follow existing review/rejection rules. Repeating an import with
extraction enabled can extract from previously captured chunks; it does not
rerun embedding/edge suggestions for existing receipts. Extraction uses the
receipt's original input, including when its note body was manually edited.

The default per-file limit is 10 MiB. `--max-bytes N` accepts 1–104857600 bytes;
the actual read is bounded even if a file grows while importing. Selection is
bounded to 1000 file/error entries and 1000 visited directories, including
excluded files and traversal errors. Each
document is bounded to 10000 chunks. `--chunk-chars N` accepts 1–20000 Unicode
characters (default 2000), with deterministic paragraph/heading boundaries,
then line/word boundaries, then hard splits for oversized words. Boundary
whitespace is omitted, with every non-whitespace character preserved. Markdown
syntax is retained as text. Chunk size counts characters, not tokens.

PDF support uses the optional lightweight `pypdf` extra. It extracts each page
independently, limits PDFs to 1000 pages and 10000000 extracted characters, and
reports malformed/encrypted documents explicitly. PDFs with no extractable
text are reported as empty and create no nodes. Scanned/image-only pages need
external OCR. Page text order and whitespace depend on the PDF and parser;
these limits bound input/output sizes, not all internal parser memory usage.

Each chunk node has a JSON `document` frontmatter object (also available in
node API/MCP output) recording the source identifier, SHA-256 of the exact
file bytes, parser/version, chunk size/index/count, PDF page (one-based, or
null for text), text offsets and line range. Character offsets are zero-based,
end-exclusive into the UTF-8 decoded text or the extracted PDF page text;
lines are one-based. An exact-input `capture` receipt links to the survivor
when semantic deduplication reuses a similar note. Each source retains its
own receipt and original chunk, so deduplication cannot substitute another
source's claim. Duplicate receipts inherit their survivor's current access
policy; forgetting a survivor also tombstones its receipts.

**Privacy:** the stored source identifier defaults to the canonical absolute
`file:` URI, which includes directories and filenames and travels with brain
Git history. `--source-id LABEL` replaces it for exactly one selected file.
`--source-prefix LABEL` accepts one directory/file selection and stores only
`LABEL/relative-name`, still exposing relative names. Use a unique opaque
`--source-id` for each file if filenames must stay private. Provenance stores
no other original path, but the terminal/JSON summary includes local paths.
Changing the source identifier intentionally creates an independent source.

Receipts have deterministic IDs based on source ID, file hash, parser version,
chunk settings and location. An identical retry reuses existing nodes and
preserves manual text/tag edits; it never revives tombstones. A changed file,
chunk size or PDF parser version creates a new set of receipts and keeps all
prior knowledge. No automatic replacement/deletion is implied. Restoring an
earlier file version reuses its original receipts. Use review/forget tools to
manage superseded information explicitly.

`--dry-run` parses files and reports planned/reused/tombstoned chunk IDs and
provenance without initializing a brain, locking, syncing, committing,
embedding, extracting or writing caches/recall records. Protected dry runs
still enforce reads (and may append the separate security audit). Each real
file holds the shared writer guard across its chunks; capture commits each
chunk, and extraction commits separately. There is no all-or-nothing batch
transaction. Already written chunks survive failures; identical retries reuse
them, finish pending commits and retry idempotent extraction. Commit/push
failures retain local data and are reported; resolve Git conflicts before retry.

`--json` returns per-file `status`, source ID/hash, chunk count and chunk
results with node/survivor IDs, provenance, reused/manual-edit/tombstone state
and optional extraction counts. `failed`/`partial` files include error codes
and make the command exit 1; processing continues for other files. Unsupported
or unselected extensions are `skipped`. Missing/unreadable files and parsing
errors are reported individually. An invalid option or oversized selection
fails before capture. An empty document creates no records.

## Relationship inference and explanations

`ig infer "A -> B"` accepts exact node IDs, entity names, aliases, or complete
node text. It also accepts `"How does A relate to B?"` and `"what is the
relationship between A and B?"`. Ambiguous names require an explicit ID.
Results include recorded relations in their original direction, a shortest
connection path, and additional proof paths for transitive conclusions.
`--max-depth` bounds traversal (default 4; maximum 20). `--json` includes node
IDs, edge IDs, traversal directions, provenance and stored evidence quotes.

Only homogeneous directed `is_a` and `part_of` **fact predicates**, plus
explicit symmetric `same_as` chains, support transitive conclusions. Other
predicates, `similar`, `extends`, and mixed paths establish connectivity only.
The engine reports recorded `contradicts` edges and opposing `p` / `not_p`
facts within the returned evidence, including conflicts with transitive
proofs. Contradictions never propagate transitively. These are explanations
of accepted graph assertions, not independent verification of their truth;
a missing bounded path means no connection was found within that bound.
Pending, rejected, expired, future, invalidated, dangling, and tombstone-linked
edges are excluded. Inference needs no LLM and never writes inferred edges.

`ig explain <node_id>` shows one shortest current graph path per reachable
node (default depth 2, limit 20) and supporting edges. It reports truncation
when the result limit is reached. These paths are contextual: hybrid retrieval
does not traverse graph edges by default. Explicit `--graph-hops 1..3` enables
bounded accepted graph relevance; see [graph retrieval](graph-retrieval.md).
Add `--query "..."` to recompute the existing
BM25/dense/RRF/reranker score explanation for a fresh query; that mode retains
its `--top` and `--rerank-k` options. Both modes and `infer` are read-only and
do not update recall statistics or vector files.

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
or an evidence node. Ordinary `ig ingest` does not extract automatically;
the explicit capture options below retain the input even with no entities.

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

### Review fact replacements

Different objects alone do not imply a contradiction: Alice may work for both
Acme and Globex. Explicit replacement language can instead create a separate
pending `fact_replacement` record referencing the old and new fact IDs:

```bash
ig entities "Alice works at Acme." --accept-facts
ig entities "Alice now works at Globex instead of Acme as of 2027-01-01."
ig pending                         # both claims, all evidence, date and reason
ig accept <replacement_id>         # one coherent decision/commit
ig undo <replacement_id>           # restore the exact original facts
```

The dependency-free grammar supports `Alice [now] works at/for Globex instead
of Acme [as of YYYY-MM-DD]`. The model adapter may return an optional `replaces`
field naming the old object, which must be an extracted entity mentioned in the
quoted evidence. That quote must contain explicit replacement/negation language
(such as `instead of` or `no longer`); its interpretation still requires review.
For predicates your application declares exclusive, use the repeatable
`ig entities --exclusive-predicate works_at` flag, or the Python
`exclusive_predicates=("works_at",)` argument. No predicates are exclusive by
default; declarations apply to that extraction only.

Creating a proposal leaves existing facts unchanged. `--accept-facts` keeps a
new fact pending when it has a replacement proposal. `ig accept-pending` holds
proposals and their new claims for individual review. CLI `ig pending`, the web
inbox and `/review` show old/new claims, original extracted windows, every evidence quote
and source ID, the proposed effective date and reason. CLI accept/reject and the
existing HTTP `/api/edge/{replacement_id}/accept|reject|undo` routes review these
records. The web review page provides an Undo last decision button.

Acceptance accepts the new fact and marks the old fact's `superseded_by` with
the proposal ID. A known effective date closes the old fact's real-world
`valid_to`; `reviewed_at` separately records decision time, so a future change
leaves the old fact live until its effective date. An unknown date stays null
in the proposal and `extracted_validity`: acceptance retires the old assertion
using `invalidated_at` at review time, without inventing an event date or an
extracted end date. The legacy top-level `valid_from` fallback on undated facts
is a storage timestamp, not an inferred event date. Original extraction windows
remain unchanged as identity keys. Nonoverlapping or backwards windows do not
produce proposals.

Rejection changes neither fact. A competing proposal can still be dismissed
after another replacement is accepted, provided its endpoints and evidence
remain live and authorized. Repeated extraction reuses the proposal and
preserves its decision. Git retains each decision; undo restores both saved
before-states only when neither fact has changed since acceptance and all their
endpoints/evidence are live. Forgetting, rejecting or adding later evidence can
block undo; it never revives forgotten claims or discards later edits. An
accepted replacement must be undone through its proposal ID rather than one
fact. Review and undo require write access to both facts and every evidence
node; a proposal is hidden when any referenced fact/evidence is unreadable,
including evidence added after proposal creation. Proposal records do not
participate in live relationships or temporal fact queries.

### Extract during ingestion

CLI ingest, HTTP ingest and MCP remember share `engine.capture()`. With no
extraction option, their existing deduplication and response behavior remains
unchanged. Rules and the configured model are separate opt-ins:

```bash
ig ingest "Alice works at Acme." --extract-entities --json
cat observation.txt | ig ingest - --source agent --extract-entities --json
export IG_ENTITIES_LLM_CMD='your-json-extraction-command'
ig ingest "Alice works at Acme." --extract-model --json
# Optional existing policy: accept NEW extracted facts immediately.
ig ingest "Alice founded Acme." --extract-entities --accept-facts --json
```

```bash
curl -X POST http://127.0.0.1:8000/api/ingest \
  -H 'Content-Type: application/json' \
  -d '{"text":"Alice works at Acme.","extraction":"rules","accept_facts":false}'
# Add your Authorization: Bearer header in protected mode.
```

In an MCP client, enable write mode and call
`remember({"text":"Alice works at Acme.","extraction":"rules"})`.
Use `"model"` to invoke the command configured by the operator; requests
cannot supply shell commands. `accept_facts: true` is optional on both APIs
and requires an extraction mode. `IDEAGRAPH_AUTO_ACCEPT` does not accept
extracted facts. Rejected/invalidated decisions, validity windows, aliases,
exact typed identities and forgotten entities follow `ig entities` rules.
The model receives only entities readable by the current principal; writes
require permission on linked entities and evidence.

Python: `node, edges, duplicate, extraction = engine.capture(text,
extraction="rules")`; `agent_memory.remember(engine, text, extraction="rules")`
returns its usual dictionary plus `extraction`. `engine.ingest()` remains the
compatible three-value API without extraction.

Capture and extraction use **two commits**, under one shared local writer guard:

1. Capture performs ordinary ingestion and stores an exact input receipt.
   Its `capture.input` JSON field preserves all original whitespace and text.
   If cosine deduplication returns an existing survivor, a separate
   evidence note holds the receipt in this same commit. Fact quotes and
   mentions reference this evidence note, never the survivor's older wording.
2. Extraction validates and authorizes its complete plan, then stores the
   subgraph in a second commit. New facts remain pending by default.

In protected mode, a duplicate evidence note inherits its survivor's current
read/write permissions, together with any additional restrictions on the
evidence note itself. Changes to the survivor's ACL also apply to existing
copies, their vectors and quoted fact supports.

`forget` on the returned note ID also tombstones its capture receipts and
invalidates facts that reference their evidence. The complete plan requires
write permission before any tombstone is stored. Cosine consolidation preserves
receipts and their survivors; they can still be promoted, but their IDs are not
merged away. Later ingests deduplicate against ordinary notes, not evidence
copies.

The `extraction` response includes `status` (`complete` or `failed`), `mode`,
`source_node_id`, `captured`, `retried`, `created_entities`, `reused_entities`,
`created_facts`, `reused_facts`, and `pending_facts` (distinct undecided,
non-invalidated facts returned by this pass, including reused pending facts).
A successful pass can have all zero counts for unsupported prose.

If extraction fails, the input remains captured. CLI exits 1, HTTP returns
502 with the captured node and extraction status, and MCP returns `ok: false`
with the same capture/extraction information. Failure counts are null because
a storage/sync failure may leave some writes on disk. Safe error codes avoid
returning model stderr or hidden entity names. Missing model configuration or
invalid options fail before capture. The command's existing 300-second timeout
applies on every surface.

Retry the **identical original text, source and memory type** with extraction
enabled. The receipt skips repeat ingest and evidence creation, even with
`allow_duplicates: true`; changed tags/relations on such a retry are not
reapplied. A corrected model command or a switch to rules can resume extraction.
Existing facts/supports are reused, and existing decisions are preserved.
Unchanged retries add no Git commit. A failed commit/push can leave local
writes or commits intact; retries commit outstanding writes and retry sync.
Capture errors themselves retain the existing ingest error behavior. There is
no rollback across the two phases. Receipts are scoped to accessible live
notes and do not revive tombstones. Both phases hold the same writer guard.

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
validity. A dated fact remains reviewable even if its window is past or future;
accepted facts appear in live views only within `[valid_from, valid_to)`.
Invalidation is recorded separately as `invalidated_at`, so it cannot change
the original extraction window or allow a repeat to recreate that fact.
New facts store this original window in `extracted_validity` (including null
dates). Legacy edges without that metadata retain their old interpretation:
a set `valid_to` means invalidated; reads do not migrate or revive them.
`--dry-run` never syncs or writes the brain, but **with `--llm` it does
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

## Search in the web UI

The search field uses the engine's hybrid dense + BM25 retrieval with RRF
fusion and optional reranking, so paraphrased questions can find ideas without
literal word matches. Results arrive after a short typing pause; older
responses are ignored. Arrow keys move between results, Enter opens an idea,
and Escape clears the search. Both ranked hits and literal text matches stay
highlighted in the graph.

Use **Why this result?** to load a read-only explanation for that idea. It
shows the dense/BM25 scores, ranks, RRF contributions, fused score and any
reranker prediction. Explanations are computed only on demand and reused
while the query stays open. They describe the current corpus, not a saved
historical search. RRF scores rank relevance, **not factual confidence**;
they are not comparable across queries. Optional reranking changes result
order while the search score remains labelled `rrf`.

HTTP clients can call `GET /api/search?query=...&k=12` and
`GET /api/search/<node_id>/explain?query=...&k=12`. Queries must contain
non-whitespace text and are limited to 500 characters; `k` defaults to 12
and must be 1–20. The candidate limit is 30. Search returns `id`, a plain-text
snippet capped at 200 characters, one-based `rank`, `score`, and `score_kind`.
Both endpoints send `Cache-Control: no-store`.

With access control enabled, both endpoints require the existing Bearer
header and return only accessible, non-tombstoned nodes. Use the existing
authenticated proxy setup for the browser; no browser token-login flow is
provided. Missing/invalid authentication returns 401; access denial returns
403. Search records recall only for writable hits and may fill vector caches
in unprotected mode. Protected searches never persist vectors, viewer
searches never record recall, and explanations never write either.

## Explain a search result

`ig explain <node_id> --query "your search"` recomputes the search against the
current brain and embedder. Supply `--query` for ranking explanations;
without it, `ig explain <node_id>` explains current graph paths instead.
Use `--json` for structured output,
`--top N` for the result count (default 5), and `--rerank-k N` for the candidate
limit (default 30), matching the search defaults.

The explanation shows raw BM25 and dense cosine scores, each channel's
one-based rank and weighted RRF contribution (`weight / (60 + rank)`), the
fused score/rank, matched lexical terms, and the final score. Channel weights
default to 1; explicit feedback can adjust them and expand the query. The
explanation also includes the feedback adjustment and storage-tier priority:
matching main memories precede recall, then archival, even after reranking.
With the cross-encoder enabled,
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

Expose the brain to MCP-capable assistants (Claude Desktop, Claude Code, …).
The tool surface is **read-only by default**; agent memory writes are opt-in:

```bash
python -m pip install 'graph-engine-memory[mcp]'  # source checkout: pip install -e '.[mcp]'
ig mcp   # or: ig-mcp — stdio JSON-RPC, nothing else touches stdout
```

Register it in `claude_desktop_config.json` / `.mcp.json`. Replace the example
command with the absolute path to your installed `ig-mcp` executable (on
Windows, `.venv\Scripts\ig-mcp.exe`); desktop clients may not inherit your
activated shell's `PATH`:

```json
{
  "mcpServers": {
    "graph_engine": {
      "command": "/absolute/path/to/graph-engine/.venv/bin/ig-mcp",
      "env": { "IG_BRAIN_PATH": "~/graph-engine-brain" }
    }
  }
}
```

Five tools, all annotated `readOnlyHint`:

| Tool | Purpose |
|---|---|
| `search_brain` | hybrid search; optional `graph_hops=1..3` / exact `focal_id` adds accepted graph context and evidence; scores are relevance, **not** confidence |
| `explain_search` | read-only score/path recomputation with the same query, k and graph options |
| `build_context` | citation-bearing prompt context by persisted tier; `query` 1–500 chars, `budget` 0–8000 estimated tokens, `k` 1–20 memories per tier, optional `include_metadata` (default true) |
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
per ordinary write**; opt-in entity extraction uses the two-phase capture
workflow described above. The write tools are registered only in write mode and carry
`readOnlyHint: false`. Client approval behavior depends on the MCP client;
the annotation itself does not enforce a confirmation. In read-only mode,
write handlers also reject direct calls with a `write_disabled` envelope.

Design guarantees: the read-only default stays strict — ingest commits and pushes
to a private repo, so model-initiated writes are an explicit operator decision,
not a default; the engine loads lazily (first search, not import),
response payloads are capped and escaped in one place (`graph_engine/mcp/format.py`),
and by default even the derived vector cache is **never written** — a search on
a cold clone does not dirty the private repo (`IG_MCP_CACHE_VECTORS=1` opts
back in; measured cold-search cost: see CHANGELOG). `brain_status` returns the
brain path basename only. Optional opt-in prompt snippet for your
`CLAUDE.md`/`AGENTS.md`: `graph_engine/mcp/agent/instructions.md`.

### Budgeted context and a complete agent turn

`ig context "answer preferences" --budget 500 --json` and Python
`build_context(engine, query, budget=500, k=5)` assemble **persisted** main,
recall and archival sections, in that order. Up to `k` visible important main
memories are selected even without query overlap: manually pinned main nodes
first, then main nodes with at least three recalls, ordered by descending
recall count and stable ID. Remaining slots in each tier are filled from
hybrid retrieval order, using a `3*k` candidate pool **per tier** before
optional reranking. Both candidate and result limits apply independently to
each tier, so a populated main tier cannot crowd recall/archival out. This is
a bounded selection, so it may not include every stored main memory. Node
types and lifecycle status do not determine section membership. Tombstones
and nodes hidden by the caller's graph/node permissions are excluded throughout.

The assembler packs individual entries, prefix-truncating oversized bodies
with `… [truncated]` and trying later entries if one cannot fit. Main bodies
start with full text; recall/archival bodies start with 200/300-character
snippets. `nodes` lists exactly the memory bodies present in `context`;
`memories` records their tiers, selection reason and per-body truncation.
`omitted` counts selected entries that cannot fit a citation plus non-empty
body. `truncated` is true when any selected body is shortened or omitted.

Each entry has a stable `[memory:ID]` citation and available provenance labels,
even with `include_metadata=False` (which only hides type/status). Accepted,
current edges add `edge_id@evidence_node_id` references when their endpoints
and evidence sources are visible and live. Evidence references identify
supporting nodes; fetch those nodes for full evidence text. Labels and
evidence lists are capped at five per entry, labels at 200 characters.

`tokens` counts the **complete rendered context**, including section headers,
citation metadata, escaped characters, truncation markers and separators. The
estimate is CJK characters plus `ceil(other characters / 4)`. It is an
approximation, **not an exact tokenizer limit**: leave headroom and use your
model's tokenizer for a hard limit. The JSON envelope, system instructions,
user question and answer reserve are outside this budget. The result's
`token_estimate` and `truncation` explain these rules. A zero or too-small
budget returns empty context and no IDs. `context_stats` uses the same packing
path; tier estimates cover each section, while the total also counts separators.

All context interfaces are read-only: no tier changes, recall ledger updates,
or vector cache writes. MCP `build_context` remains strictly read-only even
with `IG_MCP_CACHE_VECTORS=1`; protected reads retain the existing authorization
audit beside the policy file. It uses the same `ok`/error envelope and access
guard as other read tools. Example MCP arguments:

```json
{"query": "answer preferences", "budget": 500, "k": 5}
```

Run the [framework-neutral two-session example](../examples/agent_memory.py)
from a source checkout after installing `.[dev]`:

```bash
python -m examples.agent_memory
# Keep the demo brain instead of using a temporary directory:
python -m examples.agent_memory --brain /tmp/agent-memory-demo
```

Session one calls `remember` for an explicit user preference: concise answers
in German. Session two constructs a fresh brain and engine, retrieves the
persisted preference, and inserts the returned context into a system message
alongside the new user question. The script prints the complete messages and
a deterministic German answer with a memory citation. It uses HashEmbedder,
no model download, no API key and no provider call. The answer is a stand-in
to demonstrate wiring, not a model-quality evaluation. This demo uses a local
brain; production callers should construct the engine through
`graph_engine.runtime.make_engine()` to honor configured graphs and permissions,
and only capture memories the user authorized storing.

For an optional real-model path, choose a chat-completions-compatible model
and set `OPENAI_API_KEY`, then run:

```bash
python -m examples.agent_memory --model YOUR_MODEL_ID
```

That explicit flag sends the same printed messages to the provider. The
default base URL is `https://api.openai.com/v1`; set `OPENAI_BASE_URL` for
another compatible endpoint. No additional SDK is required. Only synthetic
demo memory is sent. Real responses can vary; reserve output tokens and
account for the entire prompt with the provider's tokenizer in your own agent.

## Memory lifecycle (promotion and decay)

`ig dream --lifecycle` promotes used, connected memories and demotes old,
unused ones. The defaults are fixed, configurable gates; they do not retune
themselves to each brain. `ig dream` (read-only) shows candidates before you
apply a pass:

| Transition | Gate | Default |
|---|---|---|
| `probation → active` | used **and** connected | `recall_count >= 1`, degree >= 2 |
| `probation/active → stale` | unused, weak, old | `recall_count == 0`, degree <= 2, age since creation >= 30 d |
| `stale → active` | used again | same as promotion — decay is reversible |

`stale` is a **demotion, never a deletion**: the node keeps its file, stays
searchable, and leaves the promotion pool. `recall` (MCP write mode) and
`ig search` feed a local recall ledger. Run `ig recall --aggregate` or
`ig dream --refresh --lifecycle` to fold that usage into node counters before
applying lifecycle decisions. Lifecycle decay uses creation age and zero total
recalls; storage-tier aging uses its separate inactivity policy below.
Override the gates with
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

The command does not start a daemon. For a packaged, explicitly started service,
use [the maintenance worker](#background-maintenance-worker), or run
`ig dream --refresh --consolidate` manually/from your own scheduler. Completed ingest
cycles in `tools/ig_cycle.py` now include `--consolidate`; cycles that abort before
the dream step still perform no extraction. `ig dream` without action flags
remains read-only. Dream accepts the same gate flags, using `--consolidate-limit`
for extraction because its existing `--limit` controls community distillation.

For **legacy free-text** refinement, set `IG_CONSOLIDATE_LLM_CMD` to a command that reads an
evidence prompt on stdin and prints **one grounded fact** on stdout, then run
`ig consolidate --llm` or `ig dream --consolidate --llm`. Blank stdout declines
extraction and leaves the event eligible for a later run. Nonzero exit status or
a 300-second timeout aborts the extraction batch before any facts are written.
The model's output still requires review; no automatic grounding check is made.
Dry runs never invoke the command and report candidate events rather than
model-dependent output counts. When dream combines `--distill --consolidate --llm`,
distillation also requires its separate `IG_DREAM_LLM_CMD`.

### Structured consolidation proposals

For machine-checked provenance, configure a separate JSON command and explicitly
select the structured protocol:

```bash
export IG_CONSOLIDATE_STRUCTURED_CMD='your-json-consolidation-command'
ig consolidate --structured --dry-run --json  # selection only; never runs the command
ig consolidate --structured --json          # one bounded batch, one commit
ig dream --consolidate --structured         # same protocol in dream
ig pending                                 # inspect claim, exact quotes and dates
ig accept <edge_id>                         # individual evidence-link decision
ig reject <edge_id>
ig undo <edge_id>                           # restore the decision to pending
```

`--structured` and `--llm` are mutually exclusive. There is no fallback between
protocols. Dream requires `--consolidate` with `--structured`; it does not change
community distillation into a structured extractor.

The command receives a JSON object containing `version: 1`, `instruction`,
`schema`, `limits`, and an `events` array of `{node_id, text, observed_at}`.
Each event is a selected live episodic node; `text` is its current stored text,
not another event's similar text. `observed_at` falls back to `created`.
Return exactly this versioned envelope with one or more concise facts:

```json
{
  "version": 1,
  "abstain": false,
  "facts": [
    {
      "text": "Alice works at Acme.",
      "evidence": [{"node_id": "event-id-from-request", "quote": "Alice works at Acme."}],
      "valid_from": null,
      "valid_to": null
    }
  ]
}
```

Explicit abstention is `{"version":1,"abstain":true,"facts":[]}`. Empty stdout
is an error in this protocol. Each fact requires nonempty `text` and `evidence`;
only `valid_from` and `valid_to` are optional. Every evidence object has exactly
`node_id` and `quote`. IDs must reference selected events, and quotes must match
their text exactly, including whitespace. Dates use the entity extractor's
ISO-8601 validation, normalize to UTC (naive dates mean UTC), and describe a
half-open fact-validity window. An end requires an earlier start. Unknown dates
stay null; they are not filled from event or publication time.

Limits are 256 KiB of JSON input, 128 KiB of stdout/stderr and validated serialized
output, 32 facts, 4,000 characters per fact, 1–16 quotes per fact, and 8,000
characters per quote. Lower the selection `--limit` if input is too large.
Nonzero exit, a 300-second timeout, duplicate JSON keys, invalid schema/dates,
or unsupported quotes abort the entire extraction batch before node, edge or
cursor writes. On POSIX a failed/timed-out command's process group is terminated;
on Windows the directly launched process is terminated. No provider SDK is added.

**Publication policy:** new nodes are probationary semantic nodes with an
`episodic-extraction` and `consolidation-proposal` tag and a visible
`Consolidation proposal (not reviewed truth):` text prefix. They are immediately
searchable and may appear in agent context. Pending or rejected evidence links
do **not** hide a semantic node. Treat the labelled text as a proposal and consult
its evidence/review state before relying on it. Rejection preserves the labelled
node for inspection; explicitly forget it to remove it from live retrieval.
Validity windows are stored on evidence links; ordinary semantic search does
not apply those windows to the proposal's node text.
The prefix remains after acceptance: an edge review is not an entailment proof.
Automatic dedup, text evolution, lifecycle promotion and community distillation
exclude these proposal nodes so maintenance preserves their claim identity and
cannot silently remove the label or publish them as ordinary truth.
`ig accept-pending` holds their evidence links for individual
review, regardless of similarity confidence.

Each fact has a stable node ID and a pending `extends` link to each cited event,
with exact quote objects in `edge.evidence` and the normalized dates in
`edge.extracted_validity`. CLI JSON and the web review inbox expose the proposals
and their evidence. Existing review/undo and Git history preserve decisions;
review timestamps and the configured principal (or `local`) are recorded on
structured links. Original events remain unchanged.
Exact structured claim text (case/whitespace normalized) and validity windows
reuse a proposal; different windows remain separate. Rejected/invalidated
structured claims and forgotten matching semantic text are not recreated from
later events, including by deterministic copy and legacy free-text passes.
Existing provenance, including pending/rejected/tombstoned links,
marks cited events processed. Explicit undo makes review possible again without
duplicating extraction. Abstained or uncited events remain retryable using the
existing round-robin cursor.

**Validation proves provenance, not factual entailment.** A real quote can still
be misinterpreted or accompanied by unsupported added claims. Ambiguous pronoun
resolution is a model/human judgment, not a claim made by the validator. The
command instruction asks the model to abstain when evidence is ambiguous;
structurally valid interpretations remain pending proposals for review.
Dream's dry-run report distinguishes selection eligibility, extraction not run,
and stored evidence review counts. JSON returns `protocol`, `extraction_ran`,
`proposals`, `pending_proposals` (new pending evidence-edge count), and the
publication policy; `review` is the stored edge-state count before the pass.

## Background maintenance worker

`ig maintenance` (also `ig-maintenance` and `python -m graph_engine.maintenance`)
ships in the package. Only explicitly running this command starts a worker;
package imports, ingest, the web server and MCP never start it. Initialize the
brain with `ig init` first. The worker requires no embedder or model download.
Current support is **Linux/macOS on local filesystems**; Windows users can run
individual maintenance commands manually. The shared guard's network filesystem,
multi-host and read-snapshot limitations still apply.

```bash
export IG_BRAIN_PATH="$HOME/graph-engine-brain"
ig maintenance --once --actions refresh lifecycle consolidate
ig maintenance --interval 900 --actions refresh lifecycle consolidate --limit 50
```

Default actions are `refresh lifecycle`, in that order. `--actions` selects and
orders passes. Refresh folds recall usage, rebalances unpinned tiers, repairs
similarity kinds and regenerates the index/report. Lifecycle promotes/revives or
marks old unused nodes stale; it never removes them. Consolidation reuses the
existing age/recall/count gates and preserves exact observation text by default.
Worker-created evidence links stay **pending** (including copy mode); existing
accept/reject/forget decisions survive retries. The worker never accepts pending
assertions, merges or deletes knowledge. Community distillation and legacy
free-text model commands are intentionally absent from its action list.

| Flag | Default | Bound/behavior |
|---|---|---|
| `--interval` | `900` seconds | 0.01–604800; fixed delay after the previous cycle finishes, first cycle immediately |
| `--graph` | startup graph selection | named graph under `IG_GRAPH_HOME`; selection remains fixed even if another CLI switches graphs |
| `--pass-timeout` | `120` seconds | 0.01–3600; whole individual pass including lock wait, planning, model, writes and Git sync |
| `--lock-timeout` | `30` seconds | 0–3600; shared writer wait; the pass deadline can expire first |
| `--limit` | `50` | 1–1000 lifecycle transitions or selected consolidation source events per pass |
| `--max-records` | `10000` | 1–1000000; input ceiling separately for node files, edges, vectors and recall-ledger lines |
| `--max-input-bytes` | `67108864` | 1–1073741824; combined node/edge/vector/recall input bytes |
| `--threshold`, `--min-age-days`, `--min-count` | `1`, `1`, `1` | consolidation eligibility, explicit worker settings |
| `--extract-model` | off | requires the consolidate action and configured `IG_CONSOLIDATE_STRUCTURED_CMD` |
| `--model-timeout` | `30` seconds | positive, shorter than the pass deadline when enabled; one structured batch call |
| `--once` | off | one cycle; exit status 1 if any pass fails |

Refresh reads and can update a whole bounded corpus; `--limit` does not truncate
recall aggregation or an index/report. Oversized inputs fail before maintenance
writes, so raise the input ceilings deliberately after inspecting workload.
Structured model output retains its existing 32-fact/16-evidence-per-fact and
128 KiB limits; `--limit` bounds input events rather than output facts. Git pull
runs under the same guard before input checks; pulled files can exceed the
ceiling, in which case maintenance stops before processing them.
Each pass pulls once, then checks and processes that same corpus under the guard.
Remote updates arriving afterward are checked by the next pass.

In protected mode, configure `IG_ACCESS_POLICY` and `IG_PRINCIPAL` for an admin
of the selected graph. Each pass constructs a fresh secured brain and checks
admin authorization again; policy revocation takes effect on subsequent access.
The worker uses CLI identity, never bearer tokens or an authorization bypass.

For model-backed extraction, startup **and** the model flag are explicit:

```bash
export IG_CONSOLIDATE_STRUCTURED_CMD='your-json-consolidation-command'
ig maintenance --actions consolidate --extract-model --model-timeout 30 --pass-timeout 120
```

Setting a model command alone does not enable it. The existing structured
protocol validates the whole batch before writes; failed, malformed, oversized
or timed-out model output leaves that consolidation batch unwritten.

### Logs, retries and shutdown

Stdout is newline-delimited JSON: `worker_started`, `pass_started`,
`pass_completed`, `pass_failed`, `worker_stopped` (and `cycle_skipped` for a
concurrent invocation of the same worker object). Pass summaries identify the
graph/action and duration, and completed summaries include only numeric counts.
Failed summaries use safe error codes and an empty count map: partial counts
are unknown. They exclude node text, evidence, IDs, model stdout/stderr, command
strings, tokens and raw exception messages. Git diagnostics and hook output are
captured for internal handling or discarded; they never inherit worker stdout
or stderr. Save logs **outside the brain**:

```bash
ig maintenance --actions refresh lifecycle consolidate >> "$HOME/graph-engine-maintenance.jsonl"
python -c 'import json,sys; [print(r) for line in sys.stdin if (r:=json.loads(line)).get("event")=="pass_failed"]' < "$HOME/graph-engine-maintenance.jsonl"
```

One worker runs passes sequentially without catch-up queues; additional worker,
CLI, HTTP and MCP processes serialize through the same brain guard. A failed
pass skips remaining actions that cycle. `writer_busy`, pre-write access/input
failures and model failures have `retryable: true` and retry at the next interval
without a tight retry loop. A completed no-op consolidation or lifecycle pass
creates no duplicate records. Fix missing initialization, permissions, oversized
inputs or the configured model before expecting a successful retry.

SIGINT/SIGTERM interrupt the idle wait immediately and request shutdown after the
current bounded pass; later actions do not start. A pass deadline interrupts
processing and cleans up active Git/model process groups. The writer guard is
released during unwinding. Like the underlying storage, a pass is **not a
multi-file transaction**. POSIX deadlines interrupt Python processing and
subprocess waits; they cannot preempt an uninterruptible filesystem/native call.
Interruption or storage/sync failure during mutation
may leave partial files, an interrupted Git operation or a local commit whose
push failed. These failures have `retryable: false`; the worker exits 1 and
requires inspection before restart. This avoids replaying a possibly partially
folded recall ledger. Do not delete lock files, reset the brain or blindly enable
automatic restart. Inspect `git status`, the affected files/ledger and local
commits; resolve any Git operation and reconcile partial work first. Safe model
failures can retry automatically because validation precedes file writes. This
includes pass deadlines that expire during model extraction or its validation.

### Local Linux deployment

For a user systemd service, save this as
`~/.config/systemd/user/graph-engine-maintenance.service`, replacing `USER` and
the virtual-environment path. It runs the installed command, not checkout tools:

```ini
[Unit]
Description=GraphEngine local memory maintenance

[Service]
Type=simple
Environment=IG_BRAIN_PATH=/home/USER/graph-engine-brain
# Protected brains also need IG_ACCESS_POLICY and IG_PRINCIPAL=an-admin.
ExecStart=/home/USER/.venvs/graph-engine/bin/ig-maintenance --actions refresh lifecycle consolidate --interval 900 --limit 50 --pass-timeout 120
Restart=no
TimeoutStopSec=130

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now graph-engine-maintenance
journalctl --user -u graph-engine-maintenance -f
systemctl --user stop graph-engine-maintenance
```

The journal retains JSON failures for inspection. This example deliberately
leaves fatal failures stopped; safe failures already retry inside the worker.
On macOS, run the same command in a terminal or configure launchd with equivalent
environment, log paths and a shutdown grace longer than `--pass-timeout`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `IG_BRAIN_PATH` | `~/graph-engine-brain` | path to the brain clone |
| `IG_BRAIN_REMOTE` | *(none)* | remote brain URL — auto-clones on first use |
| `IG_BRAIN_MODE` | `git` | `local` = filesystem only, without commits or remote sync |
| `IG_WRITE_LOCK_TIMEOUT` | `30` | maximum local writer wait in seconds, finite 0–3600; `0` fails immediately when busy |
| `IG_GRAPH_HOME` | *(none)* | opt into named graphs under `<home>/graphs/<name>`; takes precedence over `IG_BRAIN_PATH` |
| `IG_GRAPH` | persisted selection or `default` | per-process graph override; requires `IG_GRAPH_HOME` |
| `IG_ACCESS_POLICY` | *(none)* | trusted JSON policy path; setting it enables fail-closed authorization |
| `IG_PRINCIPAL` | *(none)* | trusted CLI/MCP process identity in protected mode; never used to authenticate HTTP |
| `IDEAGRAPH_EMBEDDER` | `st` | `hash` = deterministic test embedder |
| `IDEAGRAPH_EMBEDDER_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model override |
| `IDEAGRAPH_AUTO_ACCEPT` | off | `1` = auto-accept similarity suggestions; intent and entity-fact review have separate controls |
| `IG_EDGE_CONF_FLOOR` | `0.0` | discard similarity suggestions below this confidence |
| `IG_INTENT_AUTO_ACCEPT_MAX` | `2` | maximum accepted intent edges per source during ingest and bulk review |
| `IG_NO_RECALL_TRACKING` | off | `1` = disable recording retrieval usage |
| `IG_MCP_WRITE` | `0` | `1` = enable MCP remember/recall/forget tools |
| `IG_MCP_MAX_REMEMBER_CHARS` | `20000` | maximum text length for MCP remember |
| `IG_MCP_CACHE_VECTORS` | `0` | `1` = MCP search may fill the on-disk vector cache (default: strictly read-only) |
| `IG_MCP_MAX_SNIPPET_CHARS` | `200` | search-result snippet cap |
| `IG_MCP_MAX_NEIGHBORS` | `20` | neighbors result cap (hard max 50) |
| `IDEAGRAPH_INTENT_PENDING` | off | `1` = intent edges become pending (HITL) |
| `IDEAGRAPH_RERANKER` | `none` | `st` or a model name/path enables the cross-encoder; requires `[st]` |
| `IG_BOT_NAME` | `graph-engine-bot` | Git commit author name |
| `IG_BOT_EMAIL` | `bot@graph-engine.local` | Git commit author email |
| `IG_DREAM_LLM_CMD` | *(none)* | stdin/stdout summary command for `ig dream --distill --llm` |
| `IG_STRUCTURAL_PATH` | *(none)* | optional precomputed structural report; unavailable in protected mode |
| `IG_CONSOLIDATE_THRESHOLD` | `1` | minimum aggregated recall count (integer >= 0) |
| `IG_CONSOLIDATE_MIN_AGE_DAYS` | `1` | minimum observation age in days (finite number >= 0) |
| `IG_CONSOLIDATE_MIN_COUNT` | `1` | minimum eligible, unprocessed events before a pass (integer >= 1) |
| `IG_CONSOLIDATE_LIMIT` | `50` | maximum events per pass (integer >= 1) |
| `IG_CONSOLIDATE_LLM_CMD` | *(none)* | optional stdin/stdout fact extractor, invoked only with `--llm` |
| `IG_CONSOLIDATE_STRUCTURED_CMD` | *(none)* | separate JSON proposal command, invoked only with `--structured`; 300-second timeout; exact quotes/IDs/dates checked; 128 KiB output bound |
| `IG_ENTITIES_LLM_CMD` | *(none)* | optional JSON stdin/stdout entity and triple extractor for `ig entities --llm`, `ig ingest --extract-model`, and HTTP/MCP `extraction: "model"`; 300-second timeout; never enabled automatically |

Dedupe: near-duplicate ingests (cosine ≥ 0.92) merge into the existing node
(`sources:` provenance); opt out with `ig ingest --allow-dup` or the
HTTP/Python option `allow_duplicates: true`. Entity identities and raw episodic
observations are excluded from cosine deduplication.

## Tests

```bash
python -m pip install -e ".[dev,mcp]"   # in the activated source-checkout venv
python -m pytest tests/ -q
```

Tests use deterministic embeddings for core coverage. Optional real-embedder
and browser tests can skip when their dependencies are absent. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for the contribution workflow.

## Status

The current source includes entity/fact extraction, episodic consolidation,
relationship inference, graph and search explanations, storage tiers, retrieval
feedback, isolated graphs and opt-in access control, alongside the CLI, web UI,
MCP server and dream maintenance. The package version in `pyproject.toml` is
`0.7.0`; do not use that version alone to infer which `main` features are in a
published package. See [CHANGELOG.md](../CHANGELOG.md) for release notes and
unreleased changes.

### Known limitations

- **Intent heuristics use marker words and a similarity gate.** They can
  produce false positives. Set `IDEAGRAPH_INTENT_PENDING=1` to require review;
  `ig accept-pending` caps `contradicts`/`supersedes`/`continues` fan-out but does not verify
  the claims. Inspect a bulk-review dry run before accepting suggestions.
- **Lifecycle promotion measures use and connectivity.** A frequently retrieved
  memory is not necessarily important or true. With the default gates, only
  never-recalled, weakly connected nodes at least 30 days old become stale.
- **Distillation is extractive by default.** `--llm` needs `IG_DREAM_LLM_CMD`;
  the summaries are structured evidence, not prose abstractions.
- **`ig near-dup` flags related-but-distinct pairs.** The 0.78–0.92 band is a
  review list, and the command does not merge nodes. Review pairs before using
  `ig merge`; ingest deduplication uses its separate 0.92 threshold.
- **Temporal queries filter current records.** `ig valid-at` applies stored
  creation/validity timestamps and current review/tombstone state; `ig when`
  filters a bounded search of current text by creation time. Neither restores
  old node text or past review decisions from Git. Use `ig snapshot` for
  historical committed records; see [Git snapshots](#git-revision-snapshots).

## Git revision snapshots

`ig snapshot` reads an explicit commit from the selected Git-mode brain without
changing its checkout. This restores historical note text, edges, review
decisions and tombstone state, even after those records have changed today:

```bash
ig snapshot HEAD~1 --json
ig snapshot main "Alice uses Python" --k 5 --json
ig snapshot <sha> --valid-at 2021-06-01T00:00:00Z --json
```

Every result contains `revision` (the resolved full SHA), `commit_time` (Git's
committer timestamp) and `fact_valid_at` (the optional fact-validity filter).
These are separate clocks: an accepted fact in a 2026 commit can describe a
relation valid during 2021. `commit_time` is repository metadata, not proof of
when something happened or an exact wall-clock knowledge snapshot.

Without `--valid-at`, inspection returns all readable committed node records,
including tombstones, and edges including pending/rejected review state. With
`--valid-at`, it returns nodes created by that time and live in the chosen
commit, plus accepted, non-rejected edges valid at that time. Validity intervals
are half-open (`valid_from <= T < valid_to`), with stored invalidation times
also respected. This never reconstructs review decisions inside a commit:
the chosen commit supplies the decision state. Naive timestamps mean UTC.

An optional query ranks live historical text using the configured embedder,
BM25/RRF, persisted tier ordering and optional reranker. JSON adds `hits` as
`[node_id, score]` pairs in ranking order, `query`, and `score_kind: "rrf"`.
RRF scores are ranking signals, not factual confidence; a reranker can change
their order. Query responses include only matching nodes and snapshot edges
whose endpoints both match. Inspection is the way to obtain the complete
authorized snapshot graph. Current retrieval feedback and graph expansion are
not used. Python callers can use `engine.snapshot(revision,
fact_valid_at=...)` and `engine.snapshot_query(revision, query, k=5,
fact_valid_at=...)`; nodes/edges are `Node`/`Edge` objects, as in `valid_at`.

Accepted revision syntax is a SHA, ASCII branch/tag/ref or `HEAD`, optionally
followed by up to four `~N`/`^N` ancestry selectors (each number up to four
digits). Revisions are limited to 200 characters; reflog/date expressions,
path expressions and command options are rejected. Resolution uses only
objects already present locally and never fetches history. For date selection,
choose a branch and resolve one candidate explicitly, then pass its SHA:

```bash
git -C "$IG_BRAIN_PATH" rev-list --first-parent --max-count=1 \
  --before='2026-10-01T00:00:00Z' main
ig snapshot <returned-sha> --json
```

This selects a reachable commit using Git's timestamp/ancestry rules. It cannot
recover uncommitted knowledge, unseen remote commits or a precise wall-clock
state, and timestamps can be backdated. Pin the returned SHA for repeatability.

The brain must be the Git repository root. Local mode, missing history/objects,
non-commit objects, missing `edges.jsonl`, unsupported record paths, symlinks,
malformed records and incompatible metadata produce explicit errors. Legacy
optional fields supported by today's node/edge schema remain readable; unknown
metadata is rejected rather than silently coerced or dropped. Reads are capped
at 50,000 records / 64 MiB of node and edge content, with 30 seconds per Git
read. Queries are limited to 1–4,000 characters and `--k` to 1–100.

Snapshot queries use the **current** selected graph's policy, principal and
node ACLs, including present and historical capture-parent chains, edge evidence
and replacement/undo evidence. Historical grants never override present
revocation. ACL entries for removed IDs still apply. ACLs cannot retract
information already copied, exported or read earlier, and they do not encrypt
Git history against an OS user who can read the repository.

No checkout/reset/stash, temporary brain, historical vector writes, recall
updates, initialization, pull or push occurs. Vectors are computed in memory
from historical text; current stored vectors are not reused. HEAD, index,
working files (including dirty/untracked files) and the recall ledger remain
unchanged. Protected reads retain the normal audit log beside the policy.
Existing `valid-at`, `when` and `history` continue to operate on current records.

## Storage tiers and retrieval feedback

Storage tier is independent of `type` (semantic, episodic, procedural, entity)
and lifecycle `status` (probation, active, stale, tombstone). The persisted
`storage_tier` frontmatter field is `main`, `recall`, or `archival`; older nodes
without it default to `recall`. All tiers keep stable `nodes/<id>.md` paths.
They are logical storage classes, with no deletion or change to graph identity.
Retrieval orders matching main memories first, then recall, then archival,
preserving relevance order within each tier. This priority applies before the
candidate limit and after optional reranking; archival memories remain searchable.

```bash
ig tier <node_id>                         # inspect tier and automatic/manual mode
ig tier <node_id> main                    # set and pin main (also recall/archival)
ig tier <node_id> auto                    # unpin and apply automatic policy
ig tier --rebalance --dry-run --json      # preview automatic tier changes
ig tier --rebalance                       # apply them
ig feedback "query text" <node_id> relevant
ig feedback "query text" <node_id> irrelevant
```

Automatic tier maintenance runs with `ig recall --aggregate`, including when its
ledger is empty, and `ig dream --refresh`. At least three aggregated recalls and
a recall in the last seven days promote a memory to main. Main memories remain
there until 30 days idle, then move to recall. Any unpinned memory idle for 90
days moves to archival; age is measured from last recall, or creation when never
recalled. A newly recalled archival memory returns to recall, or main if it
meets the promotion gate. Manual choices remain pinned until `auto`; tombstones
are excluded. Searches and read-only explanations never rebalance or write tiers.

Explicit relevance judgments are persisted in tracked `feedback.json` and sync
with the brain. The latest judgment for each case/whitespace-normalized query
and node replaces earlier judgments, so repeated votes do not amplify learning.
Retrieval adapts dense/BM25 RRF weights within 0.5–1.5 from the baseline channel
ranks of judged results. Exact-query judgments also apply a relevance boost or
penalty. Similar successful queries (at least 0.5 token-set overlap) supply up
to five expansion terms from their relevant memories. Irrelevant judgments do
not teach expansion terms. Feedback for inaccessible or tombstoned memories is
excluded from learning. These bounded, deterministic heuristics need no model
or external service; without feedback, the existing equal-weight RRF is retained.
`ig explain <node_id> --query "query text" --json` includes tier priority, expanded
query, learned weights, weighted channel contributions, and feedback adjustment.
Use explicit feedback to teach preferences; recall counts alone are not relevance
judgments. The policy does not claim measured ranking improvements on every corpus.

## Isolated graphs and access control

Named graphs have separate nodes, edges, embeddings, recall ledgers and git
histories. With no `IG_GRAPH_HOME`, existing single-brain behavior is unchanged.

```bash
export IG_GRAPH_HOME="$HOME/graph-engine-graphs"
ig graph create work
ig graph create personal
ig graph list
ig graph switch work
ig ingest "A work note"
IG_GRAPH=personal ig search "a personal note"
```

`switch` persists the selection in `<IG_GRAPH_HOME>/selected`; `IG_GRAPH`
overrides that selection for a process. Graph commands do not load a model.
Names accept letters, digits, underscores and hyphens, up to 64 characters;
path traversal and symlink graph directories are rejected. Named graphs do
not inherit `IG_BRAIN_REMOTE`: configure each initialized graph's git origin
separately. No cross-graph search is performed. For a long-running service,
set `IG_GRAPH` explicitly to pin its graph instead of following CLI switches.

Access control is **opt-in**. Configure a JSON file outside every brain repo,
owned by the trusted service account, and set `IG_ACCESS_POLICY` to its path.
Use `default` as the policy graph key for a legacy single brain. Example:

```json
{
  "graphs": {
    "work": {
      "roles": {"owner": "admin", "alice": "editor", "bob": "viewer"},
      "nodes": {
        "confidential-node-id": {"read": ["owner", "alice"], "write": ["owner"]},
        "shared-readonly-id": {"write": []}
      }
    }
  },
  "tokens": {"SHA256_HEX_OF_RANDOM_HTTP_BEARER_TOKEN": "bob"}
}
```

Graph roles grant admin (all operations), editor (read and write) or viewer
(read only). Missing principals and unknown graphs are denied. Per-node
`read` and `write` principal lists restrict the graph role; `[]` denies everyone
except admins, `"*"` in a list allows any principal with the corresponding graph
role, and an omitted list inherits the role. Writing also requires reading.
Admins bypass node ACLs. Edit this trusted file to grant/revoke roles or change
node ACLs; each protected operation checks the current policy. Pre-provision
an admin role for a new graph before `ig graph create` in protected mode.
Invalid/missing policy files fail closed.

CLI and stdio MCP use `IG_PRINCIPAL=alice`, supplied by the trusted launcher.
HTTP requires `Authorization: Bearer <token>` on every request and maps the
SHA-256 digest of the token through `tokens`. Generate a strong random token
and place its SHA-256 hex digest in that mapping; keep the original token with
the client. HTTP ignores identity headers and `IG_PRINCIPAL`; it uses a
request-local identity, including threadpool work. Deploy behind TLS if
accessing beyond localhost. The shipped browser UI has no token login flow;
use an authenticated API client or a trusted proxy that injects the bearer
header. Protected WebSockets are disabled to avoid broadcasting another
principal's data. Unprotected WebSocket broadcasts are scoped to their graph.

Authorization filters node reads, search, vector caches, edges, embedded
edge evidence, reports, MCP tools and graph listings. Editors cannot mutate
restricted nodes or edges touching them. Automatic ingest links consider
writable targets. Bulk edge/vector rewrites preserve records hidden from the
caller. Protected searches do not persist embedding caches; viewer searches
do not write recall events. Global maintenance (merge, dream mutations,
consolidation, recall aggregation and saved reports) requires admin access.
External precomputed structural-report files are not exposed in protected
mode because they lack namespace/permission provenance.

Allow/deny decisions append JSON lines to `<policy-stem>.audit.jsonl` beside
the policy, including timestamp, principal, graph, action and optional node ID;
node text and bearer tokens are not logged. New audit files use mode `0600`.
Keep this directory writable to the service: inability to append the audit
record fails the operation. Logs are separate from brain git commits. They
record authorization decisions, not transactional mutation success, and are
not tamper-proof against the OS account.

**Trust boundary:** this controls application access, not local filesystem
access or arbitrary Python execution. Protect the policy, logs, brain files,
git remotes and process environment with OS permissions. Direct `Brain(...)`
construction and maintenance scripts are trusted local APIs; untrusted clients
must use the protected runtime/HTTP/MCP entry points. A node ACL governs that
stored node; it cannot retract information already copied into another node,
derived summary, git history or external export. Policy updates and brain
mutations are not a multi-file transaction. Policy changes and namespace selection
are outside the per-brain guard; coordinate those separately with the service
operator.

## Local writer coordination

CLI, HTTP and MCP use `Brain.write_guard()` for a complete mutation, from its
first read through filesystem writes, index/report generation, and any Git
pull/commit/push. This is enabled in both `git` and `local` mode. The guard
coordinates processes using **the same brain directory on the same machine**;
it does not coordinate separate clones or remote machines.

| Mutation family | Guarded boundary |
|---|---|
| Init/clone and demo seeding | Storage init/clone; complete CLI init command |
| Ingest, capture, observe, extract | Engine operation; capture retains the guard across its two commits |
| Entity/fact extraction | Complete extraction plan, validation and write |
| Review, undo, manual links and bulk acceptance | Read/decision/write/commit chain |
| Manual merge and engine consolidation/demotion | Complete mutation, including index/vector updates |
| Episodic consolidation and dream refresh/distill/lifecycle | Whole pass; combined CLI dream actions also hold one outer guard |
| Tier and feedback changes | Read/modify/write/commit chain |
| Recall tracking | Both ledger append and aggregation/rotation; append cannot race with truncation |
| Persisted vector fill and saved reports | Cache read/fill/write; report render/write; CLI report includes pull and commit |
| Trusted origin/kind migrations | Entire read/rewrite (including backup and any commit) |

The canonical identity resolves relative paths, `..`, `~` and symlinks.
On macOS and Windows it also conservatively folds case and Unicode spelling.
Do not retarget directories/symlinks while writers run. Bind-mount aliases and
hard-linked record layouts are outside this identity contract.

Lock ordering is the existing process-wide thread `RLock` first, then the
per-brain OS lock. Calls on the same thread are reentrant, including another
`Brain` or `SecuredBrain` for the same directory; nested calls reuse the held
file descriptor. Nesting writes to different brains is rejected. The existing
`BRAIN_LOCK` alias is a thread lock only: custom writers must use the shared
guard instead. Process-wide thread serialization remains in place, so a busy
write can also delay another brain in the same process.

`IG_WRITE_LOCK_TIMEOUT` bounds acquisition of both locks, with a default of
30 seconds and a finite allowed range of 0–3600. It does not bound the operation
itself, model execution or Git network commands. A timeout makes no brain
changes and asks the CLI/MCP caller to wait and retry or increase the limit.
HTTP returns `503` and `Retry-After: 1`, without exposing the local brain path.

The permanent `.graph-engine-write-<identity hash>.lock` file sits **beside**
the brain, outside its working tree, so brain commits never contain it. The
parent directory must be writable by the trusted OS account; all cooperating
writers should run as that account. Do not remove the file: deletion can split
writers across different lock inodes. Kernel locks release on normal exit or
process death; an existing file does not mean a writer is active. On POSIX,
Git children inherit the held descriptor so killing their Python parent does
not admit another writer while Git is still changing the repository. Other
subprocesses do not inherit it; forked Python children discard inherited guard
state and acquire their own lock.

**Platforms/filesystems:** local Linux/macOS filesystems with working advisory
`flock` are supported and covered by separate-process tests. Windows uses
stdlib byte-range locks, but parent-death coordination with a surviving Git
child is not provided there; use one writer and allow Git to finish before
recovery on Windows. Windows paths are not exercised by the Linux/macOS test
suite. Do not rely on this guard for NFS/SMB/cloud-synced folders or other
filesystems whose locking/atomic replacement semantics differ. Use one writer
where filesystem locking is unsupported, for older engine versions, external
editors/Git commands, or custom scripts that bypass the contract.

**Crashes and sync failures:** this is serialization, not rollback or a
multi-file transaction. A crash can leave complete atomic files from an
unfinished operation on disk; inspect `git status`/`git log`, rebuild derived
artifacts and commit or repair before resuming. If an abruptly killed Git
command leaves its own `index.lock`, inspect for live Git processes before
repairing that Git artifact; it is separate from the writer guard. A failed
pull stops the operation before mutation. A failed push leaves the successful
local commit intact; retry sync after fixing credentials/connectivity or
resolving a real remote conflict. Local edits/commits are never silently reset.
Separate machines can still conflict on JSONL or node edits, and the guard
makes no promise of automatic distributed merging.

**Reads:** ordinary graph/search/report reads stay unlocked and can observe
pieces of different points in a multi-file batch. Strictly read-only MCP paths
still do not fill vectors, record recalls or acquire/create writer artifacts.
For a consistent local read/copy, a trusted caller can hold the same guard
while reading or copying all relevant files; a versioned Git snapshot or an
offline copy is needed for independent stable reads. Advisory write locking
alone does not turn live reads into snapshots.

Custom Python batches must hold the guard from the first read through their
final sync. Low-level `write_node`/`write_edges`/`write_vectors` guard their own
writes, but cannot repair a stale object read before acquisition. Likewise,
`commit=False` calls release at return; callers batching them must add an outer
guard:

```python
with brain.write_guard():
    brain.ensure_ready()
    brain.pull()
    node = brain.read_node(node_id)
    node.tags.append("reviewed")
    brain.write_node(node)
    brain.rebuild_index()
    brain.commit_and_push("tag: reviewed")
```

Source-checkout cycle scripts invoke guarded CLI operations one at a time.
Their preflight copies and external metrics are not one guarded transaction;
run one cycle when its decision must use a stable copy, or coordinate the copy
explicitly. Access-policy/audit files and persisted namespace selection are
also outside the brain storage guard.

## Memory answer-quality benchmarks

The source checkout includes a separate DE/EN experiment runner with GraphEngine,
BM25 and vector adapters. Run `.venv/bin/python -m tools.memory_benchmark --smoke
--check --output /tmp/memory-smoke.json` for deterministic retrieval/evidence
checks without network or model downloads. Answer scores require opt-in model
calls or replayed predictions. See [memory benchmarks](memory-benchmarks.md) for
full comparisons, metric definitions, local semantic embeddings, cost limits,
and the LongMemEval import path. Existing engine regression oracles stay separate.

## Open source / privacy

The **engine is generic** (this public repo) — the **brain is your private
repo** with your data. The engine contains no brain data.

## License

MIT — see [LICENSE](../LICENSE).

## Retrieval performance

Unprotected engines retain disposable parsed/BM25/dense search snapshots in
memory and check file metadata on every query. Protected reads continue to
apply current authorization on every call. See [retrieval performance](retrieval-performance.md)
for reproducible 1k/10k-node measurements, cache freshness/recovery, read-only
behavior, and the optional larger/local-model runs.

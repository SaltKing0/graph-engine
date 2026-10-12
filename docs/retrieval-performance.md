# Retrieval performance and disposable indexes

Hybrid search now retains a parsed node snapshot, BM25 statistics, and the
normalized exact dense matrix in memory for an unprotected engine. Query
embedding, scoring, feedback, tier ordering, graph expansion and reranking
still run for each query. Markdown and Git remain the knowledge store; no
search database, approximate index or persisted search snapshot is introduced.

## Repeat the measurement

On macOS or Linux (the harness uses `resource` for peak RSS), from a source
checkout with the development dependencies installed:

```bash
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m tools.retrieval_benchmark \
  --sizes 1000 10000 --samples 20 --output /tmp/retrieval-performance.json

# Optional larger corpus; deliberately outside required CI.
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m tools.retrieval_benchmark \
  --sizes 50000 --samples 20 --output /tmp/retrieval-50k.json

# Local Git commit costs, without a network remote.
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m tools.retrieval_benchmark \
  --sizes 1000 10000 --samples 20 --mode git --output /tmp/retrieval-git.json

# Optional installed [st] extra and an already downloaded model directory.
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m tools.retrieval_benchmark \
  --sizes 1000 10000 --samples 20 --embedding-model-path /path/to/local/model \
  --output /tmp/retrieval-semantic.json
```

The runner creates temporary brains and removes them afterwards. Default
embedding is deterministic 64-dimensional HashEmbedder; no model download or
network call occurs. A local semantic model is content-pinned and loaded with
network access disabled. Model load and fixture creation are reported
separately. This is a source-checkout tool, not a packaged console command.

Reports include source commit, code and harness hashes, Python/NumPy/platform,
CPU count, thread settings, seed, embedder settings and dataset hash. Search
reports p50 and nearest-rank p95 over identical queries with indexes disabled,
a cold snapshot, and an immediate warm repeat. Cold means clearing the
application snapshots and vector memo, **not flushing the operating system's
page cache**. Uncached search still uses the existing vector-file path and the
same scoring algorithm; only the new search snapshot is disabled.

The synthetic fixture has 19-word records and repeats 97 topics and seven
language terms. Corpus creation writes source records and precomputed vectors
in bulk; that setup is distinct from measured single-record ingestion.
Ingest samples exercise `BrainEngine.ingest(..., allow_duplicates=True)` in
cold/warm pairs, allowing a guaranteed new record each time. Each pair adds
two nodes to the initial corpus; the report records the growth. Thus these
numbers cover the write/suggest/index pipeline with deduplication explicitly
disabled, not the latency of every possible capture/extraction workflow.

Search stage timings separate file freshness scans, Markdown parsing, query
embedding, vector loading/missing-vector embedding, dense matrix construction,
BM25 construction, and both scoring channels. Reranking is disabled and shown
as zero; production cross-encoder latency needs a separate measurement with
that model. The difference between total and reported stages includes
feedback, fusion, graph/tier handling and Python overhead. Ingest stage
measurements are **inclusive**: for example `rebuild_index` includes its nested
`read_nodes` calls, so stage timings must not be added together. Git-mode
measurements include local commit costs; local-mode pull/commit calls are
no-ops. Network pull/push latency is not measured or promised.

A separate memory probe avoids tracemalloc overhead in latency samples. It
reports traced retained/peak allocations (including NumPy allocations visible
to tracemalloc) and process peak RSS. RSS is the cumulative process high-water
mark across sizes, not incremental index memory or a portable capacity limit.

## Measured example

The initial three-sample diagnostic on macOS ARM64 with HashEmbedder attributed
about 381 ms of a 483 ms warm 10k-node query to Markdown parsing, 32 ms to BM25
construction and 16 ms to dense matrix construction. That supports retaining
these three structures; it does not justify changing ranking or adding an
approximate index.

Measured locally on 13 October 2026 (Europe/Berlin), macOS ARM64, Python 3.12.14, NumPy 2.3.1, 8 logical CPUs, HashEmbedder, local mode,
`OPENBLAS_NUM_THREADS=1`, 20 samples per path, default k=5, no reranker.
These are shared desktop measurements, not isolated hardware results.

| Nodes | Uncached search p50/p95 (ms) | Cold snapshot p50/p95 (ms) | Warm snapshot p50/p95 (ms) |
| ---: | ---: | ---: | ---: |
| 1,000 | 105.3 / 125.0 | 122.5 / 149.3 | 12.9 / 16.6 |
| 10,000 | 1254.5 / 1460.2 | 1481.6 / 1759.1 | 175.7 / 226.2 |

| Initial nodes | Cold ingest p50/p95 (ms) | Warm ingest p50/p95 (ms) | Traced retained / peak (MiB) | Peak process RSS (MiB) |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 448.3 / 464.4 | 449.4 / 470.4 | 5.5 / 6.9 | 63.8 |
| 10,000 | 4751.5 / 5025.0 | 4798.0 / 5022.5 | 56.0 / 71.3 | 256.5 |

Warm snapshots improve this workload, while cold construction costs more than
the uncached path because it validates source metadata before publication.
Ingest still uses fresh reads and is not accelerated by the search snapshot.
All 40 cached synthetic search checks (cold/warm × 20) at each size and all
12 DE/EN questions matched the uncached IDs, order and scores exactly.

The [complete report](performance-results/hash-macos-arm64.json) includes stage
p50/p95 distributions and source hashes; the
[initial diagnostic](performance-results/diagnostic-before.json) records the
three-sample pre-cache breakdown. The separate [1k-node Git sample](performance-results/hash-macos-arm64-git.json)
measured local commit-call p50/p95 of 72.2/74.2 ms across
three cold ingests, with no network remote; treat this small sample as a diagnostic.

Timing depends on record length, vector dimension, filesystem, CPU, BLAS
threads, permissions, graph expansion, feedback and model/reranker choices.
This fixture is not a universal service latency or scaling limit. Ingest and
cold search still parse the corpus; freshness scans are O(N) and exact dense
scoring is O(N × dimension). Warm speed comes at the cost of retained memory.

## Correctness and freshness

Every query compares a sorted node-file inventory and each file's inode,
size, nanosecond mtime and ctime, plus the vector-file stamp and canonical brain
path. There is no time-to-live window: completed local changes are detected on
the next query. This covers ingest, node edits/removal, tombstones, review or
tier updates that change nodes, external editor saves, and Git pulls that
change the corpus. Feedback and graph edges are read again on every query
rather than retained in the snapshot. Changing persist mode or per-tier mode
also rebuilds it.

Snapshots include the embedder object identity, model name, dimension and
loaded model identity. Custom mutable embedders must change their `cache_key`
attribute when replacing weights/configuration in place. The runtime engine
key now includes the model override, so changing `IDEAGRAPH_EMBEDDER_MODEL`
constructs a fresh engine. No index is shared between engines/graphs/models.
The existing vector memo also fingerprints node files, separates writer/read-only
modes and completes missing IDs in partial memos; it retains at most eight
entries. The runtime retains at most eight engines, each with one snapshot.

The index uses the existing `vectors.jsonl` contract: persisted vectors remain
preferred and foreign-dimensional vectors remain excluded from dense scoring.
This change does not infer provenance for legacy stored vectors or rewrite
stored embeddings when a user edits text or changes models. Regenerate that
existing disposable vector file when changing the embedding model or when
stored embeddings no longer describe edited text. Clearing only a search
snapshot rebuilds from the current node/vector files, exactly like uncached
retrieval.

Metadata freshness relies on the local filesystem reporting changes. A writer
that deliberately preserves every metadata field, or a filesystem with stale
metadata, is outside this guarantee. Reads are not a transactional filesystem
snapshot: a concurrent writer can change records during a query, as before.
The shared writer guard coordinates writes, not multi-file read isolation.
A snapshot is published only when the node/vector/model inventory stays stable
during construction. A query that fills disk vectors skips publication; the
next stable query can publish the snapshot.

## Access, read-only use, and recovery

Protected `SecuredBrain` instances and custom Brain subclasses bypass the new
snapshot entirely, including a snapshot accidentally attached from an
unprotected engine. Every search uses current authorized node/vector reads;
revocation and evidence ACLs remain at the storage boundary. There is no cache
of principals or permissions. Consequently the unprotected timing improvement
does not predict protected search performance.

`persist=False` only allocates memory. It creates no disk index, modifies no
vectors, performs no Git sync, and records no recall unless explicitly
requested by the caller. MCP's vector-cache opt-in remains unchanged. Switching
to a writer search still fills missing disk vectors after a read-only search.

Restart the process (or call `runtime.reset_engine_cache()` for runtime-created
engines) to discard snapshots. A stale stamp or malformed in-memory index is
rejected and rebuilt. The underlying readers retain their existing skip-broken
record behavior. No disk search index can become corrupt; canonical knowledge
is never migrated. For an explicit comparison in Python, set
`engine.search_cache_enabled = False`; to discard a manually constructed
engine's snapshot, call `engine.clear_search_cache()`. The constructor also
accepts `search_cache_enabled=False` for a consistently uncached engine.

The harness compares exact ordered `(node_id, score)` pairs for every synthetic
query and all 12 DE/EN quality questions under identical settings. It exits
nonzero on any difference. This checks ranking consistency, not new answer
quality claims. Keep using the independent [quality benchmark](memory-benchmarks.md)
and golden-set tests as well. Small equivalence/invalidation tests run in the
required suite; large timing measurements do not run in CI.

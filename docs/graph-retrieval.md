# Opt-in graph retrieval

Ordinary search keeps its existing dense/BM25 fusion, feedback, tier and
reranker behavior. Explicit graph expansion can recover accessible memories
with little query overlap by following accepted relationships from strong
hybrid hits. Connectivity is retrieval context, **not logical entailment**.
A path `Alice --likes--> Cedar --based_in--> Oslo` never asserts that Alice
is based in Oslo. No inferred facts, review decisions or edges are written.

## CLI, HTTP and MCP

```bash
ig search "launch" --graph-hops 2 --json
ig explain TARGET_ID --query "launch" --graph-hops 2 --json
# An exact known entity/node ID anchors expansion; names are never guessed.
ig search "opening date" --graph-hops 2 --focal-id ENTITY_ID --json
```

HTTP search and explanation accept `graph_hops=0..3` (default 0) and optional
`focal_id` (1–200 characters); existing bearer authentication applies:

```text
GET /api/search?query=launch&graph_hops=2
GET /api/search/TARGET_ID/explain?query=launch&graph_hops=2
```

MCP `search_brain(query, k=5, graph_hops=0, focal_id=None)` uses the same
options. `explain_search(id, query, k=5, graph_hops=0, focal_id=None)`
recomputes one explanation. Match the query, k and graph options between
search and explain. Query length remains bounded to 500 characters and MCP
and HTTP k to 1–20. A focal ID requires graph expansion, and must identify an
accessible live node. Access denial stays an authorization error; missing or
tombstoned anchors produce an invalid-input error.

Graph-enabled CLI/HTTP/MCP search is exploration: it fills no disk vector
cache and records no recall use, including with `IG_MCP_CACHE_VECTORS=1`.
Explain is always read-only. Protected-mode authorization still writes the
existing separate security audit log beside the policy; brain files, HEAD,
Git index and recall ledger are unchanged. Ordinary CLI/HTTP search keeps its
existing recall behavior. The web search UI continues to request ordinary
hybrid search; graph options are available through the API.

## Eligibility and bounds

Traversal is undirected for discovery, but every path records the original
edge direction as `out` or `in` **at each step**. Both endpoints and every
referenced evidence node must be accessible, present and not tombstoned.
Edges must be accepted (not pending or rejected), not invalidated, and valid
at the recorded UTC evaluation time. This also excludes future legacy edges
and malformed dates. Legacy `valid_to` means invalidated, as elsewhere in
the engine; extracted facts use their half-open validity intervals.

Default eligible kinds are `fact`, `mentions`, `extends`, `related`, `linked`.
`contradicts`, `supersedes` and unknown kinds never carry relevance.
Accepted `similar`, `supports` and `refines` can be explicitly selected
through Python options; similarity suggestions are excluded by default.
Edge confidence and fact predicates are retained as evidence, never treated
as truth probabilities or composed into new assertions.

| Option | Default | Allowed range / meaning |
| --- | --- | --- |
| `hops` | 2 | 1–3; expansion depth |
| `seed_limit` | 3 | 1–10; strongest positive hybrid scores after feedback, before tier priority |
| `candidate_limit` | 50 | 1–200; distinct recipients of graph contributions, including existing hybrid candidates |
| `max_degree` | 20 | 1–50; skip nodes with more distinct eligible neighbors, including as targets |
| `visit_limit` | 500 | 1–5000; adjacency entries examined across all seeds |
| `weight` | 0.5 | finite (0, 1]; initial seed strength multiplier |
| `decay` | 0.5 | finite (0, 1]; multiplier after the first hop |
| `focal_id` | none | explicit accessible live node ID; replaces expansion seeds, while ordinary hybrid candidates remain |

Bounds cap traversal and retained paths. The existing filesystem corpus and
edge scan is still proportional to corpus size, and is not a large-corpus
latency guarantee. The final `rerank_k` candidate limit (default 30) and top k
still apply. Relevance does not override persisted tier priority: main,
recall, archival. An ordering/model reranker runs on the combined candidate
pool once, preserving tier priority and its existing score contract.

## Contributions and explanations

Seeds use hybrid RRF with learned channel weights and explicit feedback.
A focal anchor uses `max(its adjusted hybrid score, 1/61)` so an exact known
entity can expand even without text overlap. It does not itself become a
result without hybrid overlap.

For each seed, deterministic BFS keeps the first shortest path to each
recipient (neighbors sorted by node ID, edge ID, direction). Parallel edges
and cycles cannot multiply contributions from one seed. At each step,

```text
factor = (1 for hop 1, otherwise decay) / sqrt(degree_from * degree_to)
raw contribution = seed_score * weight * product(step factors)
candidate contribution = min(sum(seed path contributions), weight * max(seed_scores))
combined relevance = base dense/BM25 RRF + candidate contribution + feedback
```

Degrees count distinct visible eligible neighbors; inaccessible records
cannot affect them. Over-degree hubs cannot receive or propagate relevance.
Feedback is applied once to combined relevance, clamped at zero as before;
its adjusted score also decides seed eligibility. The graph addition happens
before tier sorting and candidate cutoff. Graph expansion can improve a
candidate's relevance but does not guarantee it a place in top k.

`retrieve_with_evidence` returns one scoring pass with `hits`, `graph` summary
and per-result `evidence` paths. HTTP/MCP/CLI graph results expose these as
`graph_evidence`. Path steps contain edge IDs, from/to IDs, local directions,
degrees, factors and original allowed edge/evidence records. Each path records
seed ID/score, hop count, raw contribution and the applied contribution after
the shared cap. The summary records options, evaluation time, seed IDs,
contribution cap, visits and any seed/hop/candidate/degree/visit truncation.

Explain includes the same paths, candidate contribution, learning adjustment,
channel RRF contributions, final rank and reranker score. The existing `rrf`
container holds the combined retrieval score (including graph and feedback);
`final_score_kind` is `rrf_graph` when graph relevance participates, or
`reranker` when real model scores are available. Search returns the combined
retrieval score even after reranking, as before. `graph_used_for_ranking`
means graph contributions were applied, not that graph was merely requested
or that the explained node necessarily received a boost. All these scores
rank relevance and are not factual confidence.

Explain recomputes against current files/access/validity/model settings; it
is not a historical search log. Reordering edge files alone preserves paths
and scores, while edits, revocations or expiration can change the result.

```python
from graph_engine.graph_retrieval import GraphOptions
from graph_engine.retrieval import retrieve_with_evidence, explain

options = GraphOptions(hops=2, seed_limit=3, candidate_limit=50,
                       max_degree=20, visit_limit=500, weight=0.5, decay=0.5)
result = retrieve_with_evidence(engine, "launch", graph=options)
trace = explain(engine, "TARGET_ID", "launch", graph=options)
```

The low-level `retrieve`/`retrieve_candidates` functions also accept
`graph=options`; their existing `persist`/`track` arguments remain caller
controlled. Use `persist=False, track=False` for read-only Python exploration.

## Evaluation

See [graph comparison commands and measured limits](memory-benchmarks.md#graph-expansion-comparison).
The synthetic fixture checks retrieval/evidence and latency; it does not
measure real answer correctness, extraction quality or general graph benefit.
Expansion remains opt-in.

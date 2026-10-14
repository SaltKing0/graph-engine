# Memory answer-quality experiments

Run this separate source-checkout tool alongside the deterministic engine
oracles in `graph_engine/evals.py`. Those regression gates remain unchanged.
The bundled `de-en-memory-v1.0.0` dataset contains 26 synthetic conversation
turns and 12 questions, six each in German and English: preferences, changes
over time, entity ambiguity, two-hop questions, irrelevant facts, and missing
information requiring abstention. It is a compact diagnostic fixture, **not
equivalent to LoCoMo or LongMemEval**, and cannot establish production quality.

## Reproduce an offline comparison

From the repository root with Python 3.11+:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m tools.memory_benchmark --output /tmp/memory-comparison.json
.venv/bin/python -m tools.memory_benchmark --smoke --check --output /tmp/memory-smoke.json
.venv/bin/python -m pytest tests/test_memory_benchmark.py -q
```

The default compares `graph-engine`, `lexical` (BM25), and `vector` (cosine).
It uses HashEmbedder, requires no network/model downloads, makes no answer
calls, and leaves answer metrics and actual token usage **null**. HashEmbedder
is a deterministic bag-of-words projection, not a semantic model. CI runs only
the four-question smoke selection with a retrieval/evidence gate; paid calls
and semantic models are never selected by CI. The full diagnostic command
reports misses without requiring every backend/question to pass.

Select a backend with repeated `--adapter` options, or individual questions
with repeated `--question` options. All runs support `--k`, `--context-budget`
(estimated tokens), and `--seed`. The defaults are k=5, budget=256, seed=0.
The smoke gate requires complete retrieval and packed-context evidence for
its two answerable preference questions. Its two unanswerable questions have
no positive retrieval oracle; abstention requires an actual/replayed answer.

## What the experiment measures

Every backend imports the same **whole dated turns** into a fresh isolated
corpus for each conversation. The GraphEngine adapter writes stable turn IDs
as active recall-tier nodes and uses the production hybrid retriever. This
storage adapter intentionally bypasses fact extraction, deduplication, automatic
links, tier maintenance, and learning history. It does not test their quality.
It does not access your private brain. The default adapters do not traverse
graph edges; their report records `graph_used_for_ranking=false`. These default
comparisons cannot demonstrate a graph traversal benefit. The explicitly
selected `graph-engine-expanded` adapter uses optional source-declared
relationships; see [graph comparison](#graph-expansion-comparison). Do not
change production rankings to fit either fixture.

Ingestion/indexing, retrieval, context assembly, generation, and scoring are
separate stages. Context assembly packs ranked whole turns under the same
budget for every backend, skips oversized turns, and counts evidence only
when that turn's text actually enters the context. IDs, timestamps and roles
count toward the budget. This common experimental policy is distinct from
production hierarchical context assembly. Gold references/evidence never
enter the ingestion adapter, retrieval query, or answer prompt.

The JSON report stores all questions, references, expected turn IDs, ranked
hits and scores/text, packed contexts, full prompts and their hashes, answers,
raw model content, errors, and per-stage latencies. Ingestion latency is stored
once per backend/conversation, separate from per-query latency. Reports are
atomically checkpointed after each question; an interrupted run keeps the
completed questions and a `running` status. Errors produce
`completed_with_errors` and a nonzero CLI exit, rather than a success score.

| Metric | Definition and limitations |
| --- | --- |
| `recall_at_k` | Fraction of annotated evidence turns retrieved in the top k. Null when there is no known positive evidence. |
| `mrr` | Reciprocal rank of the first relevant turn within top k; zero for a miss. For multi-hop questions this does not require every hop. |
| `evidence_coverage` | Fraction of annotated evidence turns present in the packed context; separate from retrieval recall. |
| `answer_correct_exact` | Unicode/case/punctuation-normalized exact match to one accepted reference; correct abstention for unanswerable questions. Free-form paraphrases need separate human or upstream semantic scoring. |
| `abstention_correct` | Whether the answer's abstention decision matches answerability. An abstention must have empty text and citations. |
| `false_memory_detected` | Limited proxy: a non-abstention on an unanswerable question, an exact match to an annotated obsolete/wrong reference, or a citation absent from the supplied context. It is not a comprehensive semantic hallucination detector. |
| `invalid_citations` | Citation IDs absent from the supplied context. A valid ID alone does not prove the cited text supports the claim. |
| `latency_ms` | Wall-clock time separately for retrieval, context, generation, scoring; ingestion is reported separately. Timings vary by machine and are not deterministic gates. |
| `tokens` | Estimated context/prompt/completion counts are separate from provider-reported actual prompt/completion counts. The estimator is characters-based, not a tokenizer. Missing actual usage stays null. |

Summaries are macro means with explicit denominators (`n`); unanswerables and
missing evidence annotations do not inflate retrieval scores. Failed or absent
answers are unscored and counted as errors where appropriate: compare error
counts and scored denominators, not only the mean. Inspect the per-question
results by language/category. No paid model judge is part of this tool.

Each report pins the dataset version and exact bytes (SHA-256), git source
commit, working-copy dirty flag, code-file manifest/hash, Python/dependency
versions, embedder, reranker (disabled), model, prompt/scoring versions, seed,
selected question IDs, ingestion/context policy, top k and context budget.
Commit source changes for a clean reproducibility record. Change the dataset
version when changing a released fixture; use its hash to distinguish bytes.

## Optional local semantic embeddings

Install `[st]` separately and prepare a complete, pinned SentenceTransformer
model directory yourself. Selecting it explicitly enables local model execution:

```bash
.venv/bin/python -m pip install -e ".[st]"
.venv/bin/python -m tools.memory_benchmark \
  --embedding-model-path /absolute/path/to/pinned-model \
  --output /tmp/memory-semantic-retrieval.json
```

The loader uses CPU, an explicit seed, empty encode prompts, and
[`local_files_only=True`](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html).
It never downloads a missing model and sets `trust_remote_code=False`.
The `[st]` extra pins Sentence Transformers 6.1.0, which rejects custom Python
modules in local model directories as well as Hub repositories. Models that
require custom code are unsupported; use a model with built-in modules.
Model-file hashes and ST/Torch versions are recorded. The graph and vector
adapters share this embedder; the lexical backend remains BM25. Semantic
models cannot be selected for `--check`; they are optional experiments with
runtime and dependency costs outside the default deterministic gate.

## Optional answer generation and cost limits

Use an explicitly selected Chat Completions compatible endpoint, with a pinned
model snapshot/revision served there. The endpoint must support JSON-object
responses, `temperature`, `seed`, and `max_tokens`. The requested model and the
returned model/fingerprint are recorded; if the server uses a moving alias or
ignores seed, reruns are not guaranteed deterministic. API credentials, if
needed, come from `MEMORY_BENCHMARK_API_KEY` and are never recorded. This is a
tool-specific variable; it does not configure production GraphEngine.

```bash
# Start your own compatible server first; replace the model with its pinned ID.
.venv/bin/python -m tools.memory_benchmark --adapter graph-engine --smoke \
  --allow-model-calls --endpoint http://localhost:8001/v1/chat/completions \
  --model reader-pinned-revision --max-requests 4 --max-output-tokens 128 \
  --max-total-estimated-tokens 4096 --output /tmp/memory-answers.json
```

Without `--allow-model-calls`, no answer HTTP calls occur. The entire selected
run is checked before the first request: default limits are 6 requests, 128
output tokens per request, 8192 **estimated** total prompt plus maximum-output
tokens, and a 30-second timeout per request. There is one call per question per
backend and zero retries. A full 12-question/3-backend comparison requires
36 calls and explicit higher limits; selecting fewer questions/backends is
usually a better first experiment. Attempts that fail still consume the request
limit. Interrupted experiments retain results; there is no automatic paid resume.

These request/output/estimated-token limits control workload, not a hard dollar
ceiling. Compute a planning estimate using your provider's input/output rates:
`estimated_input_tokens * input_price + requests * max_output_tokens * output_price`
(with prices expressed per token). Actual prompt usage may differ, including
protocol overhead or provider-specific billing. Set a provider-side spending
limit for a hard monetary cap and use provider-reported usage for accounting;
the runner does not infer current prices or label estimates as actual costs.

## Offline replay and inspection

Prepare contexts with the default command, generate/annotate answers separately,
and score them with `--predictions /path/to/predictions.json`. The file schema is:

```json
{
  "dataset_sha256": "copy from the prepared report metadata",
  "model": "pinned answer model or human annotation revision",
  "predictions": [
    {
      "adapter": "graph-engine",
      "question_id": "en-preference",
      "prompt_sha256": "copy from this backend/question result",
      "text": "green tea without sugar",
      "abstained": false,
      "citations": ["en-t00"],
      "usage": {"prompt_tokens": 240, "completion_tokens": 20}
    }
  ]
}
```

Provide one record for every selected backend/question. `usage` is optional;
omit it when provider counts are unknown, rather than inserting estimates.
Replay checks dataset and prompt hashes before scoring, so answers from a
different context budget or backend cannot silently be reused.

## LongMemEval adapter path

Download the upstream data yourself and pin its release/revision, licensing,
and dataset checksum. The importer reads local official-format JSON; no
benchmark data or models are downloaded by the runner.

```bash
.venv/bin/python -m tools.memory_benchmark \
  --import-longmemeval /path/to/longmemeval_s_cleaned.json \
  --dataset-version longmemeval-your-pinned-release \
  --output /tmp/longmemeval-turns.json
.venv/bin/python -m tools.memory_benchmark --dataset /tmp/longmemeval-turns.json \
  --adapter lexical --question YOUR_QUESTION_ID --output /tmp/longmemeval-diagnostic.json
```

The converter follows the
[official format](https://github.com/xiaowu0162/LongMemEval#-dataset-format):
all user/assistant turns, session dates, question dates and original question IDs
are preserved; `has_answer` labels map to stable turn evidence IDs; `_abs`
questions require abstention. Upstream answer session IDs are preserved but
are not used to label every turn of those sessions as relevant. If turn evidence
is unavailable, its metrics are null. Original answers/annotations and the
source-file checksum remain inspectable. This conversion is a diagnostic
adapter, not reproduction of the official scorer. Export each generated answer
as `{"question_id": "...", "hypothesis": "..."}` JSONL and use the upstream
scoring procedure for published LongMemEval comparisons; do not call local
exact-match scores official LongMemEval scores. Supporting another upstream
release/schema requires validating and versioning its conversion first.

For custom datasets, follow `tools/memory_benchmark/data/de_en_v1.json`:
`schema_version=1`, pinned `version`, conversations with unique safe IDs and
dated user/assistant turns; questions with conversation ID, DE/EN language,
category, text, accepted `answers`, turn `evidence_ids` (null for unknown),
boolean `unanswerable`, and optional exact `forbidden_answers`. Evidence IDs
must exist in that question's conversation. No reference fields go to adapters.

## Fair comparisons

Competitor comparisons require **identical datasets, source/ingestion policy,
answer models/prompts, context budgets, top k, and scoring**. Record all versions
and cost/latency settings. Do not import vendor marketing scores as comparable
results, and do not infer that graph features help from the engine's brand name
or from this small fixture. The
[issue's evaluation reference](https://docs.mem0.ai/core-concepts/memory-evaluation)
is context for experiment design, not a comparable score source.

## Graph expansion comparison

`graph-engine-expanded` explicitly selects production `GraphOptions()`
(two hops, three seeds, weight/decay 0.5, degree 20, candidates 50, visits 500).
The default three adapters and smoke gate remain unchanged. Each report row
records the actual graph-used flag, all options and retained paths/evidence.
The configuration records expansion selection separately from whether any
contribution was actually applied.

The separately versioned `graph-expansion-de-en-v1.0.0` fixture has two DE/EN
conversations with five turns each, one two-hop query and one unknown query
per language. Its accepted `linked` relationships are explicit source
annotations, written independently of question/reference/evidence labels.
Both engine adapters ingest identical nodes, vectors and relationships;
lexical/vector baselines receive the same source documents and ignore edges.
There is no extraction oracle or relationship generation from answer labels.
This fixture is deliberately small and synthetic, and does not test whether
an extractor or curator correctly identifies relationships.

```bash
.venv/bin/python -m tools.memory_benchmark \
  --dataset tools/memory_benchmark/data/graph_expansion_v1.json \
  --adapter graph-engine --adapter graph-engine-expanded --adapter lexical \
  --output /tmp/graph-comparison.json
# Also compare unchanged behavior on the original fixture (which has no edges).
.venv/bin/python -m tools.memory_benchmark \
  --adapter graph-engine --adapter graph-engine-expanded \
  --output /tmp/graph-existing-fixture.json
```

Custom conversation records may optionally contain `relationships` with
unique `id`, source/target turn IDs, `kind`, optional `predicate` and
`evidence_ids` referencing source turns. Unknown endpoints/evidence are
rejected. These are accepted source annotations, not gold answer labels.
Upstream imports keep relationships absent unless separately annotated.

Measured locally on 12 October 2026, Python 3.14, macOS arm64, HashEmbedder,
no reranker/answer model, k=5 and context budget=256. Ten runs alternated
adapter order in one warmed process, after discarding one warm-up per
dataset. p50 is the median and p95 the nearest-rank percentile of all query
retrieval timings (including unknown queries); ingestion/context are separate.
[Recorded metadata and sample results](graph-retrieval-benchmark.json) pin
source commit, modified-source hash/manifest, dataset hashes and settings.

| Dataset / adapter | Recall@5 | MRR | Context evidence | Retrieval p50 / p95 (ms) |
| --- | --- | --- | --- | --- |
| Graph fixture / disabled | 0.00 | 0.00 | 0.00 | 0.676 / 1.205 |
| Graph fixture / enabled | 1.00 | 0.333 | 1.00 | 0.772 / 1.509 |
| Original fixture / disabled | 1.00 | 0.950 | 1.00 | 0.693 / 1.612 |
| Original fixture / enabled | 1.00 | 0.950 | 1.00 | 0.772 / 1.891 |

Retrieval/evidence denominators are two answerable graph questions and ten
answerable original questions; latency denominators are respectively 40 and
120 queries per adapter. Unknown-query recall remains null and answer quality
is unmeasured (no model calls). Both graph targets have no lexical query match;
the lexical baseline has zero evidence recall on that fixture. Scores/context
on the original fixture remain unchanged. Small absolute timings vary with
startup, filesystem caches and concurrent machine work; they establish no
production latency promise or general quality win. These results support
keeping graph ranking **opt-in**, not changing the default.

To reproduce the warmed protocol and retain all individual reports:

```python
from pathlib import Path
from tools.memory_benchmark.dataset import DEFAULT_DATASET
from tools.memory_benchmark.runner import run

out = Path('/tmp/graph-warm-runs')
names = ('graph-engine', 'graph-engine-expanded')
for label, dataset in [('graph', DEFAULT_DATASET.with_name('graph_expansion_v1.json')),
                       ('original', DEFAULT_DATASET)]:
    run(dataset_path=dataset, output=out / f'{label}-warmup.json', adapters=names)
    for i in range(10):
        run(dataset_path=dataset, output=out / f'{label}-{i}.json',
            adapters=names if i % 2 == 0 else tuple(reversed(names)))
# Aggregate each row's latency_ms.retrieval by adapter; omit warmup reports.
```

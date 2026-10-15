# Decision Memory evaluation freeze v1

Status: evaluation infrastructure and **provisional source corpus** for
[#75](https://github.com/SaltKing0/graph-engine/issues/75), following the
[v1 contract](decision-memory-v1.md#evaluation-gates-frozen-before-tuning).
This adds no runtime decision types, propagation or UI. Project sources are
real; annotations are source-only **Codex drafts**, not independent gold.
Independent review and adequate held-out coverage remain delivery requirements.
Do not close #75 or claim release readiness from these baseline runs.

## Frozen inputs

`tools/decision_benchmark/data/project-v1/` bundles 27 source records: eight
documented action reconstructions, sixteen actual later changes, and three
original graph benchmark artifacts. The full repository snapshot revision is
in `inputs.json`. No private audit files, architecture conversations, personal
brain data, external issue/PR text or research were imported. This bounded
repository-history corpus does not represent real user discussions.

| Family | Documented choice | Split |
| --- | --- | --- |
| graph | Keep graph expansion opt-in | development |
| context | Assemble budgeted, citation-bearing context by persisted tier | development |
| documents | Import documents with bounded chunks and source provenance | development |
| cache | Use disposable search caches with freshness checks | development |
| temporal | Filter current records by temporal validity | evaluation |
| models | Disable custom Python in offline benchmark models | evaluation |
| forget | Tombstone forgotten memories and exclude them from live views | evaluation |
| writer | Serialize cooperating local brain writes | evaluation |

These are reconstructions from pinned documentation, not fabricated historical
reviews or assertions of accepted dependencies. Later code patches are actual
observations. Their topic attachments are manually supplied drafts, not proof
that a fix contradicts a decision or improves measured performance. Independent
review must check indirect dependencies too.

The source manifest pins full Git revisions, first parents for diffs, blob OIDs,
whole-blob SHA-256, exact excerpt byte offsets, UTC commit timestamps, local
capture date, paths, permalinks, lineage, conditions and redistribution limits.
`sources/` contains exact UTF-8 sections or deterministic first-parent patches.
`freeze.json` hashes all bundled sources, inputs, labels, license and a copy
of the normative contract; the file-map hash binds them. Commit timestamps
are availability proxies, not measured publication/review times. The loader
rejects out-of-order events and updates preceding their basis.

Every selected revision has the same MIT license text, bundled as `LICENSE`;
redistribution must retain it. No external text is mirrored under an assumed
license. Complete original benchmark artifacts preserve the original protocol,
two positive synthetic graph questions, original dirty execution revision/code
manifest, and absence of measured answer quality. Repeated timings and copied
prose are not independent evidence. No experiment was run to fill a shortage.

`controls-v1/` is a separate **synthetic** bundle. Ten fictional events cover
comparable opposition, changed conditions, non-contradictory time changes,
duplicate lineage, surviving independent support, withdrawn evidence, unknown
comparability, unrelated updates, formatting-only/no-review and an unanswerable
artifact. Paired decisions and cross-topic negatives exercise denominators.
Observation text is separate from gold review rationales. These authored labels
are neither independent human gold nor real product evidence.

## Annotation protocol

Before seeing feature or baseline outputs, an annotator reads exact sources
and the contract and records:

1. Claim wording, exact source locators, supporting/opposing/irrelevant
   evidence, source lineage and typed conditions (unknown when unavailable).
2. Directed dependencies and exact source/decision versions, separately
   recording curated links and proposed links. Retrieval similarity is not a
   dependency. Empty lists in the current drafts do not prove absence.
3. Every event–decision pair as positive, negative, inconclusive or unanswerable,
   with valid explanation paths, surviving/removed support, conditions and a
   source-grounded rationale. A patch is not a benchmark result or reversal.
4. A distinct reviewer repeats this without predictions, records identity,
   review time and disagreements, then adjudicates. Record resolved disagreements
   too; unresolved gold remains inconclusive rather than becoming negative.
5. Publish a **new version and freeze** before evaluating. Preserve this draft
   and its runs; never silently relabel a difficult held-out case.

All real pairs currently have `outcome=pending`, a draft suggestion/rationale,
annotator `Codex`, reviewer/time null, and disagreements null (not “none”).
Claims remain unassessed. Scoring real labels requires `status=adjudicated`,
distinct annotator/reviewer identities and recorded disagreements. The schema
records provenance; human review must authenticate the review itself.

The held-out families and gold must remain unavailable to feature tuning.
This author has read/prepared the bundle and is not a blind independent
evaluator. For #81 use an independent reviewer and disclose this exposure,
or reserve additional independently prepared held-out families.

## Availability and baselines

Splits are frozen by complete decision family. Inputs, dependencies and events
cannot cross splits. Each event gets a fresh temporary brain; ingestion includes
only sources available by that event's UTC timestamp and in its split. Earlier
versions remain historical sources, not independent experiments. Exact
800-character slices have stable source/chunk IDs and a manifest mapping.

`visible_inputs` builds a source-only allowlist. Label validation is outside
the execution boundary; neither draft/gold rationales, expected impact lists
nor expected paths reach retrieval, context or prompts. A canary regression
changes gold and verifies identical prompts, retrieval and alerts. Scoring
happens after execution. This boundary is not an ACL protecting local files
from their owner.

```bash
# Bounded offline CI; no model, HTTP call, download or Git history required.
.venv/bin/python -m tools.decision_benchmark --split all --check \
  --output /tmp/decision-controls.json

# Explicit opt-in to the real local-source bundle; no source fetching.
.venv/bin/python -m tools.decision_benchmark --real-corpus --split development \
  --output /tmp/decision-project-development.json

# Use evaluation only after implementation/configuration freeze.
.venv/bin/python -m tools.decision_benchmark --real-corpus --split evaluation \
  --output /tmp/decision-project-evaluation.json

# Optional byte/date verification against an existing full local clone.
.venv/bin/python -m tools.decision_benchmark --real-corpus --verify-git . \
  --split all --output /tmp/decision-project-verified.json
```

The baseline explicitly records **graph expansion disabled**, zero imported
retrieval edges, HashEmbedder, no reranker and no answer model. It runs existing
hybrid retrieval and the actual current `graph_engine.context.build_context`,
k=5, estimated source context budget=4000, with its per-tier selection and
recall truncation. Top-k hits and the context function's own selection are
both recorded. Fixed task/system templates, decision inventory, prompt hashes,
context and source/chunk IDs are saved. The budget excludes fixed task and
inventory overhead; future comparisons must preserve this overhead too.

The search-plus-agent baseline is **prepared contexts only**: no decision-impact
or answer score is inferred from rank. A separate simple explicit-dependency
baseline alerts whenever a declared direct basis changes, retaining its exact
source→dependency→decision path. It performs no semantic/condition/lineage
analysis. Curated and separately supplied proposed inputs are scored separately.
The proposed profile is currently empty, so its missed impacts remain visible.
Neither profile measures extraction; manual preparation effort is unmeasured.

There is no provider integration or ambient model selection in this runner.
Future model experiments need explicit authorization and a new recorded config:
model revision, provider-returned model ID, prompt hash/version, request/token
limits, usage/errors and measured cost. Preserve identical availability, source
policy, tasks, budgets and scoring. Import never executes research code or
fetches sources. This no-model run establishes no answer quality or user savings.

The preparation helper `python -m tools.decision_benchmark.freeze_sources
--repository . --output /tmp/new-project-corpus` reads local Git objects only.
It is not part of evaluation/CI. Changed recipes/annotations require a new
version. Normal source verification needs only bundled bytes; report metadata
still requires a Git source checkout to record actual code revision/dirty state.

## Scoring and frozen release requirements

The bundled normative contract and `freeze.json` preserve false alerts ≤5%,
misses ≤5%, 100% provenance/inconclusive handling, zero unsupported conclusions,
and 100% of enumerated integrity scenarios. Held-out coverage requires ≥20
positive pairs, ≥20 negative pairs and ≥10 inconclusive **cases**, with all
required failure modes. A usability claim requires ≥20% lower median active
review time without reduced independent correctness or increased unsupported
claims. Thresholds are not adjusted after seeing baseline results.

The unit is `(event_id, decision_id)`; this fixture pins one decision version
per logical ID. Raw paths/alerts are retained, but duplicates cannot inflate
pair recall. All eligible pairs are attempted, including errors. Pending
annotations are counted with quality metrics null. Inconclusive and unanswerable
strata are separate from positive/negative denominators.

* Recall = correctly explained positives / all positive pairs. Missing alerts,
  incorrect paths and runtime errors are misses.
* Precision = correctly explained positives / surfaced known positive/negative
  pairs. A positive alert with an incorrect explanation is not a true positive.
* False alerts = surfaced known negatives / all known negatives. Spurious
  “unknown” warnings count too. False discovery fraction = negative-stratum
  false alerts / all surfaced scored pairs.
* Inconclusive/unanswerable handling requires explicit uncertainty and a valid
  source/dependency path, with separate denominators. Omission is not success.
* False abstention = explicit uncertainty on known pairs / all known pairs.
  An ordinary negative prediction with no alert is not abstention. Omitted
  positive pairs are separately counted as missed impacts.
* Gold path correctness is reported for scored paths. It is not an independent
  judgment of generated prose or the complete provenance/ACL integrity gate.

The runner generates no assessed claims or answers. Answer quality, independent
rationale judgment, unsupported conclusions and review-time savings are null,
not 100% success. Real retrieval evidence gold also awaits independent review,
so retrieval quality is null. Provider calls/cost are zero with no currency
claim; human annotation/review effort is unmeasured. Per-event p50/p95 latency
includes ingestion/context; retrieval/context timings are also saved. One local
run establishes no production latency guarantee or controlled usability result.

`--check` establishes successful offline execution and budget integrity only;
it does not require the deliberately simple baseline to pass product gates.
Release readiness remains false pending #81's independent coverage, statement,
integrity and usability evaluations. Existing engine, memory, optional model/
MCP/PDF/browser and advisory gates remain in place.

## Saved runs and remaining delivery

`docs/decision-evaluation-results/` saves source commit/clean state, actual code
manifest, environment/dependency versions, corpus/label/source hashes, configs,
prompts, timings, errors and missing outcomes. Report commits can differ from
the executed code commit: reports are copied into version control after running
against that clean snapshot.

The real bundle contains eight action reconstructions and sixteen events but
**zero independently adjudicated pairs**. Independent claim/evidence/condition/
dependency review and disagreements remain missing. No real positive/negative/
inconclusive release stratum is established; extraction, answer and user-time
outcomes are unmeasured. Synthetic controls establish harness coverage only.
Freeze an independently reviewed successor before #78 tuning/#81 evaluation.

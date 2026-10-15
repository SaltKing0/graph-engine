# Decision Memory v1: graph expansion walkthrough

This [contract](decision-memory-v1.md) walkthrough is specification data, not
an installed brain, new command, executed experiment or real human review.
Only the initial public documentation/benchmark facts below are measured.
All review actors, IDs, transitions and later results are illustrative.

## Measured starting point and limits

Pin public repository revision
`a0a41fb4b7f82ca13a7c57579fb4f7b42bb9b7f0` when preparing the separate example
brain. Capture these local files as source nodes and immutable source versions:

| Alias | Local public input and exact locator |
| --- | --- |
| `S-policy@1` | `docs/graph-retrieval.md`, Evaluation paragraph ending “Expansion remains opt-in.” |
| `S-bench@1` | `docs/memory-benchmarks.md`, Graph expansion comparison: measured protocol, result table and following denominator/limits paragraphs. |
| `S-report@1` | `docs/graph-retrieval-benchmark.json`, complete JSON artifact. |
| `S-data@1` | `tools/memory_benchmark/data/graph_expansion_v1.json`, complete fixture. |

An importer computes actual source text/artifact hashes and exact quote offsets
from those bytes. These aliases abbreviate full `{id,version_id}` refs, never
floating filenames or runtime hashes to be guessed. The private analysis-workspace
audit is background only and is not an input required by the public example.

The public benchmark reports Python 3.14/macOS arm64, HashEmbedder, no reranker
or answer model, k=5, estimated context budget=256, ten alternating warmed runs.
On the synthetic graph fixture, Recall@5 and context evidence coverage were
0.00 without expansion and 1.00 with it. Positive retrieval/evidence denominator:
**two answerable questions**, not forty independent confirmations. Latency
denominator: forty queries per adapter; repeated timings share the same fixture.
On the original synthetic fixture, Recall@5/context evidence were 1.00 with
and without expansion (ten answerable questions). No answer correctness was
measured. This is a retrieval diagnostic, not a production default-quality gate.
See the [recorded protocol and limits](memory-benchmarks.md#graph-expansion-comparison).
The input-document revision above is not the benchmark's executed code revision:
the report records `c1a670329f252be3e4f41fdb5d233e417c1d4f70` with
`source_dirty=true` and code manifest SHA-256
`981928c3b2f8de3bbdf5c19e96244525f666b4776755e98e948ca56de9cd8f9f`.
`P-synth`/`R-synth` must pin that manifest, not substitute today's clean main.

## Complete initial record inventory

Notation `X@1` means one immutable content version; `aX` is its ordinary semantic
Node anchor. Every object below gets its own anchor. Every relationship `Lx@1`
also gets an anchor. Every new content version starts with no assessment;
links/decisions start proposed. `P-*` profiles are content records too.

| Ref | Required content, context and provenance |
| --- | --- |
| Four `S-*@1` above | Source versions with captured text, SHA-256, locators, import identity and pinned repository revision. `S-bench` and `S-report` share measurement lineage `run-graph-20261012`; the data fixture is a separate input, not an independent run. |
| `P-synth@1` | Profile `synthetic-pair/1`: equal workload/fixture hash/code revision/Python/platform/embedder/reranker/answer mode/k/budget/protocol; graph enabled/disabled is the declared intervention. Metric and unit must match. |
| `P-real@1` | Profile `real-pair/1`: equal frozen real-project corpus/annotation hashes, source snapshot, code revision, environment, embedder, k=5, budget=256 and paired graph on/off protocol within a run. Time is recorded, not evidence of equivalence. A check may accept successive runs only if these identities match. |
| `C-synth@1` | “Expansion improves retrieval/evidence coverage for the two answerable questions in this synthetic fixture under the recorded protocol.” Context `P-synth`, exact pinned inputs; no generalization to real documents or answer quality. |
| `K-synth@1` | Recorded check of Recall@5/context evidence for that paired synthetic fixture; protocol and limitations from `S-bench@1`, dataset from `S-data@1`. |
| `R-synth@1` | Imported completed result of `K-synth@1`: off=0, on=1 fraction for each metric, positive n=2, ten warmed repetitions; artifacts `S-report@1`, `S-bench@1`. `hypothetical=false`. |
| `E-synth@1` | Interpretation of `R-synth@1`: limited synthetic support for `C-synth@1`; same lineage `run-graph-20261012`, same context; no independent confirmation from the prose/table. |
| `C-ready@1` | “Expansion meets this project's proposed real-document readiness rule for reconsidering the default.” Context `P-real`; initially no result/support, effective assessment unassessed. This is a proposed example criterion, not a measured project commitment. |
| `K-real@1` | Example revisit check for `C-ready@1`/`D-opt@1`: on a frozen real corpus, compare paired on/off Recall@5 and packed evidence coverage. Revisit when each improves by ≥0.10 absolute, with known positive n≥20 and complete provenance. No answer-quality assertion. These thresholds are hypothetical policy, separate from v1 evaluation gates. |
| `D-opt@1` | Action: keep graph expansion opt-in. Rationale: the observed benefit is limited to a small synthetic diagnostic; review new real-document evidence before reconsidering. Alternatives: enable by default, remove expansion. Revisit check `K-real@1`. Provenance `S-policy@1`, `S-bench@1`; no claim that `C-ready` is false. |

`P-real` uses fixture identities `real-corpus-A/1`, `annotations-A/1`,
`snapshot-A/1`, `code-A/1`, `environment-A/1`, `paired-retrieval/1`. These are
explicit fictional opaque IDs, not measured datasets or real Git SHAs. All later
numeric results in this walkthrough have `hypothetical=true`. In an executable
example they must live in a labelled synthetic example namespace, and must not
be admitted to a production assessment as measured evidence. Missing actual
hashes in a real import would make comparison unknown.

| Link ref | Ordered endpoints; accepted interpretation |
| --- | --- |
| `L1@1` (`result_of`) | `R-synth@1 → K-synth@1` |
| `L2@1` (`checks`) | `K-synth@1 → C-synth@1` |
| `L3@1` (`supports`) | `E-synth@1 → C-synth@1` |
| `L4@1` (`depends_on`) | `D-opt@1 → C-synth@1`; the documented choice uses this limited observation as part of its rationale. |
| `L5@1` (`checks`) | `K-real@1 → C-ready@1` |
| `L6@1` (`checks`) | `K-real@1 → D-opt@1`; a future result can trigger review without opposing `C-synth`. |

There is deliberately no `supports` link from “no real result” to “expansion
does not work”, and no dependency asserting that real results must match the
synthetic workload. `D-opt` refers to a check as its revisit condition, avoiding
circular evidence. Source references are provenance, not extra support votes.

All content envelopes pin `recorded_by=local`, an illustrative server UTC
`recorded_at`, `previous=null` and the source/input refs described above;
hashing the complete envelope determines each version ID. Anchors record the
union of source-input IDs through `derived_from`. Profiles with manual content
have manual provenance and no invented source inputs. All anchors may remain
storage `probation`/tier `recall` throughout: the review below does not promote
them. No `edges.jsonl` assertion is needed or auto-accepted.

## Initial transactions and exact review basis

`T0`, `T1`, etc. below are explanatory transaction labels and stand in for caller
idempotency keys. Each publishes one new sidecar generation and one receipt
pinning its request hash, actor and returned refs. Every creation also emits
a `content` delta `Δ<ref>` with null old ref and that exact new ref; each link
acceptance emits a `relationship` delta. These deltas need no impact when no
current dependent decision exists. No implicit records beyond the stated
anchors, content versions, events, deltas, candidates and transaction receipts
are required. Profiles are created before content that references them; checks
name their targets only through the later `checks` links, avoiding circular
version hashes with decision revisit refs.
Each metric is a separate typed observation with its own metric/unit and positive
denominator; the paired check evaluates both. No result averages unlike units.

1. **T0 (generation 1):** create all initial anchors/content records and their
   creation deltas. Proposed `D-opt@1` and `L1..L6@1` are not current/accepted.
2. **T1 (generation 2):** illustrative reviewer `local` accepts the two exact
   profiles with `A-P-synth/A-P-real`, reason “rules reflect the declared example
   scope”, and creates `A-L1..A-L6`, one `proposed → accepted` event per exact
   link. Each event's basis includes both endpoint refs, context profile ref
   and source refs. Link acceptance
   also pins the applicable profile acceptance event. Profile reviews emit
   review deltas; link acceptance reasons state the table's interpretation.
   Accepting `L3` is not a claim truth judgment. No model executes.
3. **T2 (generation 3):** `A-synth` assesses `C-synth@1`,
   `unassessed → supported`, basis `E-synth@1`, `R-synth@1`, `K-synth@1`,
   `P-synth@1`, `L1..L3@1`, `A-L1..A-L3` and the pinned four source versions.
   Reason: the diagnostic supports only the stated two-question scope.
4. **T3 (generation 4):** `A-D0` activates `D-opt@1`, `proposed → current`,
   with conclusion event `A-D0-review=remains_justified`; basis includes
   `C-synth@1`, `A-synth`, `L4@1/A-L4`, `K-real@1`, `L5..L6@1/A-L5..A-L6`,
   `P-real@1` and `S-policy@1/S-bench@1`. Reason: retain the documented opt-in
   default; the real-document check is open. `C-ready@1` stays unassessed.

All events include nonempty reasons, server reviewer/time, previous event IDs
(null initially) and expected generation/content/event heads. Same-target
conclusion and lifecycle events have independent axis chains. Review deltas
`ΔA-synth`, `ΔA-D0`, `ΔA-D0-review` preserve these changes without manufacturing
performance findings. The source of this illustrative policy review is manual,
not an attributed historical review by a project maintainer.

## Hypothetical later results: three independent branches

Each branch starts at generation 4; they are alternatives, not cumulative
evidence. Aliases such as `S-real@1` refer to new imported example source nodes
and versions with hashes of the labelled fictional artifact bytes. A check is
never executed by GraphEngine.

### A. Comparable real-document update

**All numbers here are hypothetical, not measurements.** A manually supplied
example artifact reports twenty annotated positive questions: paired off/on
Recall@5 0.60/0.80 and packed evidence 0.55/0.75. The artifact explicitly declares
all identities in `P-real@1`, plus actual run time, command/tool identity and
limitations. It satisfies the example revisit threshold, not proof that changing
the default improves real use.

| Transaction | Stored records / exact refs / resulting state |
| --- | --- |
| `T4-A` | Create `S-real@1`, `R-real@1` (result of `K-real@1`, completed, hypothetical), `E-real@1` and anchors/deltas. Add proposed `L7@1: R-real@1 result_of K-real@1` and `L8@1: E-real@1 supports C-ready@1`; each pins `P-real@1` and the exact result/source. |
| `T5-A` | Append `A-L7/A-L8` accepting those links after source/scope review, plus relationship deltas `ΔA-L7/ΔA-L8`. The paired conditions are comparable to `K-real@1` under its pinned profile; no comparison to `P-synth` is licensed. |
| `T6-A` | Persist candidate `I-A` seeded by `ΔA-L7`, target `D-opt@1`, path `R-real@1 —L7/A-L7→ K-real@1 —L6/A-L6→ D-opt@1`, reason `revisit_check_result`, comparable, complete, no truncation. Candidate for `C-ready@1` uses `L7/L5`. `ΔA-L8` can generate its own distinct claim-basis candidate; group it in the same review card without deleting either seed. `C-synth@1/A-synth` is unchanged; `D-opt@1` is still current. |
| `T7-A` | `F-A` human review of exact `I-A` confirms a reviewable finding, workflow open. Its basis pins `I-A`, `S-real@1/R-real@1/K-real@1`, `L7/L6` and their acceptance events. Reason: the explicit revisit rule was met in the fictional example. Append `F-A-ack: open → acknowledged` with owner `local`. No decision lifecycle change. |
| `T8-A` | Append `A-ready`, `C-ready@1: unassessed → supported` within the hypothetical example, basis `E-real/R-real/S-real@1`, `P-real@1`, `L7/L8` and acceptance events; label hypothetical. Append decision conclusion `A-D1=needs_investigation`, previous `A-D0-review`, full old and new basis. Reason: check corpus representativeness, extraction quality, latency and real answer quality before changing defaults. |
| `T9-A` | Create follow-up `K-follow@1` and anchor/delta: manually planned answer-quality/representativeness review owned by `local`; no result. Append `F-A-resolve: acknowledged → resolved`, resolution `A-D1`, reason “triaged; follow-up K-follow@1 remains open”. `D-opt@1` stays current/opt-in. Finding and hypothetical evidence remain historical. |

A substantive revision would instead create `D-opt@2` with `previous=D-opt@1`,
new action/rationale and freshly proposed dependencies; after reviewing them,
one transaction records `D-opt@1: current → superseded`,
`D-opt@2: proposed → current` and an accepted `supersedes` link. No `A-synth`
or `A-D0` transfers to `@2`. This is an allowed next flow, not a transition
that occurs in branch A.

### B. Incomparable or unknown update

Create `S-other@1`, `R-other@1`, `E-other@1`, anchors and creation deltas. The
fictional artifact uses the same `P-real@1` profile and retrieval metrics but
reports a different workload/corpus ID, with an unknown environment. The result
outcome is inconclusive for the requested check; its observed values remain
source data. Store a proposed `L-other@1` attachment to
`K-real@1` only because a human explicitly submitted it; do not infer a link.
Comparison is **disjoint**: known workload/corpus mismatch with
`P-real@1`, despite the unknown environment. Reject the attachment via
`A-other: proposed → rejected` with that reason. No accepted-path impact on
`D-opt@1`, no opposition to `C-synth`, no changed assessment or decision.
Preserve the informational/rejection deltas and rejected link history.

For the distinct **unknown** subcase, `S-unknown@1/R-unknown@1` report the right
metric/workload but omit required corpus hash/environment. An explicit proposed
attachment `L-unknown@1` creates a preview candidate `I-unknown` naming those
missing dimensions; it is not an accepted-path result. Review records
`F-unknown=inconclusive`, reason “comparability unavailable”, and leaves the
link proposed pending clarification. No threshold conclusion or claim opposition
is allowed. Complete provenance later creates `R-unknown@2`/new proposed link,
fresh delta and candidate; it does not rewrite `F-unknown` or its old basis.

### C. Unrelated update

Create `S-ui@1 → S-ui@2` for a local document update about UI label spacing,
same logical ID, new exact text hash/version and a `content` delta `Δui`.
Neither version is an input of the above claims/checks/decisions and there is
no accepted dependency path. Store `Δui` only: no impact candidate/finding,
and `D-opt@1/A-D0-review` remain unchanged. A `similar_to` discovery link, if
someone proposes one, cannot change that outcome.

## Version freshness, duplicate supports and history checks

These additional paper checks are required conformance cases for #76–#78:

- Reimporting `S-report@1` through another local filename gives a duplicate
  receipt/source alias with the same measurement lineage. A second evidence
  interpretation does not make the two-question diagnostic independent.
- A truly separate documented run can create `E-independent@1` and a separately
  reviewed support link. Withdrawing `E-synth@1` appends `W-synth` and availability
  delta `ΔW`; traverse `L3/L4` to produce `I-withdrawn`, explaining remaining
  independent support. Do not reject `C-synth` automatically. Without that second
  run, state “no remaining available reviewed support”, still not “false”.
- An edit of `C-synth@1` to an unqualified production-benefit claim creates
  `C-synth@2`, `previous=@1`, new context and content delta. `A-synth` remains
  bound to `@1`; `@2` is unassessed and `L3` still targets `@1`. The old `L4`
  dependency yields a basis-change candidate for `D-opt@1`, not a redirected
  endorsement. Changing source bytes out of band likewise makes basis freshness
  unknown/inconclusive until import/review catches up.
- A review preview for `I-A` pins `R-real@1`, `A-L7` and `A-D0-review`. If another
  actor withdraws evidence or changes any expected head before acceptance,
  stale acceptance conflicts with no event/write. Refreshing may generate a
  successor candidate; it cannot alter the original.
- Guarded undo of `F-A-ack` before `T8-A/T9-A` appends a compensating event
  restoring open workflow. Undo after resolution/downstream use is refused;
  append a fresh reopen/correction with a reason. Both histories remain.
- Forgetting `S-real` hides its evidence, findings and derived quotes from live
  views; no cached brief or old assessment may disclose them. Revoking its ACL
  also blocks historical payloads today. An authorized snapshot at generation
  4 reconstructs only the original decision/basis; one after `T9-A` reconstructs
  the acknowledged/resolved finding and investigation conclusion, including the
  label that all later results were hypothetical. Neither snapshot reruns a check.

These cases exercise the contract's identity, lineage, scope, access and review
rules. They establish no measured usability or real-document performance claim;
the [prospective evaluation gates](decision-memory-v1.md#evaluation-gates-frozen-before-tuning)
require a separate frozen corpus and baseline.

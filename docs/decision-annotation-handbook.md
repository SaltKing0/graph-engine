# Decision Memory successor annotation handbook v1

Prepared for [#90](https://github.com/SaltKing0/graph-engine/issues/90).
Status: **protocol and development tools prepared; no human calibration,
successor corpus, independent labels or final freeze delivered**. Decision
Memory remains experimental. This document defines the rubric before new
system outputs or successor cases are inspected. It preserves the
[original contract and scoring gates](decision-memory-v1.md#evaluation-gates-frozen-before-tuning).
It is not a report of completed annotation.

Under the [21 October project closeout](decision-release-readiness.md#project-closeout-21-october-2026),
#90 is closed as `not_planned`. This handbook and its forms remain available
for future work; the original acceptance requirements below are unchanged.

## Units and labels

A case is one chronological source-update event with its available source
packet. The scoring unit is `(case_id, decision_version_ref)`, one exact
decision version available at that cutoff. Judge every eligible pair, not just
the decision that appears related to the update. Deduplicate alternate paths
for pair counts; retain all emitted paths for alert/provenance burden. A case
may have several pair outcomes. Count inconclusive **distinct cases**, alongside
their pair counts and overlaps, rather than inflating coverage with many
decisions attached to the same unknown update.

| Class | Source-derived rule |
| --- | --- |
| positive | The decision warrants review through a source-supported explicit accepted dependency path under comparable relevant conditions. This does not imply that the decision is wrong or reversed. Record exact triggering evidence and path. |
| negative | Complete enough known scope establishes a cosmetic, unrelated, disjoint or otherwise non-impacting update. Explain why no review is needed, including surviving support where relevant. Silence or missing data is not negative evidence. |
| inconclusive | Relevant scope, dependency, lineage or input is genuinely unknown, withdrawn/missing, or reviewer disagreement cannot be resolved. Record the missing fact and what would resolve it; never guess comparability. |
| pending | Administrative state for an unfinished annotation; never a scored negative, positive or inconclusive. |

Missing/withdrawn-input subtypes remain separately reported. If a downstream
format uses `unanswerable`, retain that reason and denominator while including
the distinct case in the contract's uncertainty audit; document overlap rather
than adding disjoint totals. Do not map unfinished reviewer work to a completed
inconclusive judgment.

## Source review procedure

Review sources independently, without engine predictions, baseline decisions,
rankings or draft labels. Annotators must be qualified to interpret the
technical domain and disclose limits of that qualification. Each initial
judgment is saved separately with its author and timestamp before discussion.

1. Identify the decision's exact source and version. Distinguish a documented
   action reconstructed from prose from an actual recorded human review.
   Preserve that limitation; an annotator cannot invent a historical approval.
2. Read only the packet available at the event cutoff. Record old and updated
   evidence as exact source/version/quote references. A patch records a code
   change, not measured performance. Commit time is an availability proxy
   unless publication evidence establishes a better timestamp.
3. Record typed conditions separately for basis and update: metric, units,
   workload, software/data versions, environment and relevant time interval.
   For each field give a quote or explicit `unknown` with reason. Convert units
   only with a documented transformation retaining original values. Classify
   comparability as `comparable`, `disjoint` or `unknown`, with evidence for each
   relevant dimension. Different times are not automatically contradictions.
4. Identify directed support, opposition, assumption/dependency and check
   relationships using exact version endpoints and source evidence for each
   edge. Similarity and topic overlap are not dependencies. Mark whether an
   accepted relationship was actually recorded; curated evaluation links and
   source-derived proposed links stay separate. No accepted historical link
   may be inferred merely because a gold path is needed.
5. Assess remaining support and withdrawal. Multiple citations, copies, patches
   and repeated timings from one experiment form one lineage. Record uncertain
   lineage as unknown; do not count it as an independent confirmation. Retain
   genuinely surviving independent support. Withdrawal may require review
   without proving the decision false.
6. Decide the pair class and `needs_review` (`true`, `false` or `null` for
   unresolved scope), citing the trigger or evidence excluding impact. Supply
   a rationale, explicit uncertainty and failure-mode tags. Use empty lists
   only for a verified absence; explain the search scope in the rationale.
7. Freeze both initial judgments. An adjudicator compares every disagreement
   in outcome, quote, condition, path, lineage and remaining support. Record
   both positions, resolution and rationale, or explicitly unresolved fields.
   Preserve the original judgments even when the final outcome changes.

An implementing agent or LLM may prepare forms and check references. Its labels,
self-ratings or simulated reviewers are not independent human acceptance.
Project-owner domain judgments are useful, but implementation involvement and
prior exposure must be disclosed rather than described as blind independence.

## Form and quote conventions

The development exporter below produces `blank-form.json` bound to the packet's
canonical SHA-256. Every eligible pair has two empty `initial_judgments` and a
separate empty `adjudication`. Nulls mean **not yet recorded**, not agreement or
negative evidence. `reviewers` starts empty; no reviewer is preassigned.
The legacy development form uses `decision_id`: the packet and original input
hash bind its single reconstructed version. A successor must instead record
explicit immutable `decision_version_ref` values; do not reuse this development
form as an accepted final-corpus schema.

Each reviewer record must include `id`, `identity` (or protected identity-map
reference), `role`, `qualifications`, `implementation_involvement`,
`prior_source_exposure`, `prior_output_exposure`, `conflicts`, `signed_at` and
`attestation`. Record specific exposures and dates, not just a boolean claim
of independence. The custodian verifies identities, qualifications and actual
separation; a string in JSON cannot authenticate a person.

Each judgment records reviewer/time, outcome, needs-review, triggering evidence,
conditions, comparability, dependency paths, remaining/withdrawn support,
uncertainty, rationale and failure-mode tags. Conditions use
`{dimension, basis, update, relation, evidence, reason}`. Paths use
`{profile, nodes, edges, evidence}` with version-specific nodes and directed,
typed edges. Support entries use `{lineage, status, evidence, reason}`.
Do not silently encode a gold path as a runtime proposal.

Every `evidence`/trigger reference is:

```json
{
  "source_id": "SOURCE_ID",
  "revision": "EXACT_REVISION",
  "sha256": "PACKET_SOURCE_SHA256",
  "byte_start": 0,
  "byte_end": 1,
  "quote": "EXACT_UTF8_TEXT"
}
```

Offsets are zero-based, end-exclusive **UTF-8 bytes in the packet source**,
not characters or the whole original blob. The source manifest separately
records original excerpt offsets or first-parent patch identity. Preserve its
repository/revision/path, original blob hashes, URL, availability, lineage,
license and license notice. `validate_quote(case, reference)` checks exact
packet version/hash/span. It does not judge whether the quote supports a claim.

Adjudication records reviewer/time, a complete disagreement list (an empty list
only when both judgments were actually compared), resolution/rationale and
final outcome. Retain unresolved questions and classify them inconclusive.
Identity/exposure/qualification and adjudication sign-off remain human checks.
The current tool checks source-packet structure and quote spans; **it does not
validate completed judgment semantics or certify reviewer independence**.

## Development calibration, not held-out evidence

The existing project-v1's 57 pairs and known controls have already been exposed
during development. They cannot become fresh held-out evidence by renaming a
split. The helper reads only previously exposed **development** source bytes
and never opens any label file or evaluation-source file:

```bash
.venv/bin/python -m tools.decision_benchmark.annotation_packets \
  --output /tmp/decision-annotation-development-v1
```

Use a new output directory. Existing directories are refused to preserve
annotations. `packet.json` contains eight chronological cases and 27 eligible
pairs, with only available sources and documented-action reconstructions;
source-derived condition drafts and curated/proposed dependency drafts are
omitted. `blank-form.json` has no outcomes or reviewer identities. MIT notices
are retained. `manifest.json` hashes exact generated bytes; the form separately
binds the canonical packet hash. This is a preparation manifest, **not a
successor corpus freeze**. Repeated exports are deterministic.

For a small calibration round, use all eligible pairs of the first two
chronological development cases, before looking at any engine output. Two
reviewers first submit separate forms to the custodian, who records all
disagreements and a calibration meeting. If these cases do not exercise all
classes, supplement with already exposed controls, explicitly synthetic and
separately counted. Revise wording using development only, version the rubric,
and sign it before final annotation. Do not fabricate disagreements or report
this proposed round as completed. **Calibration has not occurred.**

## Successor source acquisition and family allocation

The custodian, not this exporter, must acquire fresh real technical decisions
and actual later updates, with redistribution permission and exact chronological
source packets. No new real sources were assembled by this change. There is no
evidence that current repository history alone can meet independent coverage;
document shortages. Do not invent real results, copy synthetic controls into
real strata, or use previously exposed families as independent final evidence.

Before output inspection, build a family/lineage register. Group related
decision versions, near duplicates, source revisions, shared experiments and
derived copies in the same partition wherever they could leak answers. Review
cross-family sources and join connected groups before assignment. Keep all
previously exposed families in development. Reserve whole fresh groups for
final evaluation; if there are too few groups/strata, report the shortage.
Record split IDs, grouping rationale, duplicate/lineage audit and every exposure.

Final coverage must contain **at least 20 positive pairs, 20 negative pairs
and 10 distinct inconclusive cases**, independently judged and adjudicated.
Cover cosmetic/unrelated updates; changed conditions, versions, units and
workloads; non-overlapping times; duplicate lineage; surviving independent
support; withdrawal; missing inputs; and genuinely unknown comparability.
Report pair and distinct-case counts per failure mode, family, class and real/
synthetic stratum, with overlaps and all pending/disputed/removed cases visible.
Do not generate extra near-duplicate pairs just to reach a denominator.

## Access, runtime inputs and freeze protocol

The repository is public and is an implementation workspace. Files here,
ignored directories, local hashes and an exporter allowlist are **not access
controls**. Do not place reserved successor sources, final labels, final paths,
rationales or identity maps here, in PR artifacts, chat, CI logs or model prompts.

The project owner appoints a custodian and two qualified source reviewers;
names and permissions are currently unassigned. Use a separate evaluator-owned
store with actual account/ACL separation, auditable grants and an exposure log.
The custodian supplies each reviewer only source packets and the frozen rubric.
Reviewers cannot see each other's initial judgments or system outputs before
submission. The adjudicator gets both sealed judgments afterward. Implementers
receive development data only. Document who may release what and when, the
storage location, approvals, revocation and accidental-exposure handling.

Prepare **two separate artifacts** under evaluator control:

- Runtime inputs: only chronologically available source bytes and independently
  source-derived structured proposals/conditions, each with supporting quotes.
  Obtain a separate source-only proposal review, with identity/time/exposure
  evidence. Preserve proposed and curated accepted profiles independently.
- Gold: expected impacts, acceptable explanation paths, rationales, uncertainty
  and adjudicated labels. No expected path, target list or rationale may enter
  runtime input derivation. Record independent derivation order and cross-check
  the boundary before execution. Free-text gold pasted into source fields is
  still leakage; structural allowlists cannot detect all semantic leakage.

The custodian publishes a new versioned manifest only after review: schema and
rubric/scoring versions, split/case/decision-version IDs, source and license
hashes, chronological cutoffs, lineage/family grouping, proposal/input hashes,
separate gold hashes, exposure log, both initial judgments, adjudication and
sign-off. Sensitive material remains access-controlled; public manifests may
use opaque IDs and commitments without revealing final case content/counts
that would guide tuning. Retain a frozen copy of the original scoring gates.
Changing a signed artifact requires a new version and exposure disclosure.

Before #91 final execution, independently verify exact quote/path/version refs,
availability, family separation, duplicate lineage, all eligible pair records,
coverage and reviewer attestations. Freeze the candidate commit/configuration
and comparison protocol first. The evaluator then runs that candidate in the
controlled environment and scores sealed outputs separately. Release only the
approved aggregate report/evidence after evaluation. Exposure of final cases
or outputs makes later tuning development informed by that exposure; a tuned
candidate needs fresh independent final evidence. No automatic final-data
import or evaluation command is added by this PR.

## Unchanged scoring and handoff

Keep false alerts ≤5% over known negative pairs (including spurious unknown
warnings), missed impacts ≤5% over positive pairs, exact authorized provenance
100%, inconclusive handling 100%, and unsupported conclusions zero. Wrong paths,
errors and truncation count as misses when they prevent correct positive
explanation. Report raw alerts/paths, false discovery fraction, false abstention,
attempted/completed/error/abstained pairs, statement counts and empty denominators.
Missing data yields unavailable metrics, not a successful zero error rate.
Technical correctness is separate from the frozen 20% human review-time gate.

The preparation report always records acceptance incomplete and zero final
coverage; independently reviewed development counts are unknown, not inferred
from form fields. It is not an annotation verifier for a successor corpus.
Required external deliverables: actual calibration/disagreement records; fresh
licensed source packets; two separate initial human judgments per final pair;
adjudication and reviewed proposals/conditions; access/freeze/coverage sign-off.
If acceptance resumes, only these deliverables can unblock the final semantic
comparison in #91. Final integrity sign-off also belongs to #91, retaining the
original #92 criteria 3, 6, 8 and 10; #92 is closed for engineering delivery only.
Actual participant sessions belong to deferred #93. No benefit or release claim
follows from this preparation.

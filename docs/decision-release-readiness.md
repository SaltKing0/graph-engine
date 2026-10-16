# Decision Memory v1 release-readiness assessment

**Decision: keep experimental; do not promote v1 as a validated improvement.**
No version bump, release tag or package publication is authorized by this report.
This assessment follows [issue #81](https://github.com/SaltKing0/graph-engine/issues/81)
and retains the [original frozen gates](decision-memory-v1.md#evaluation-gates-frozen-before-tuning).

The complete offline workflow and deterministic production interfaces are
available, but independently adjudicated held-out evidence and a controlled user
exercise are absent. Execution correctness, a source-change diagnostic and
synthetic controls cannot establish real decision quality or review-time savings.
The [walkthrough](decision-workflow.md) explains intended users, explicit
activation, CLI/HTTP/MCP/UI flows, limitations and recovery.

## Evidence boundary and unresolved delivery

The frozen `project-v1` corpus has eight reconstructed actions and sixteen local
repository update events. All 57 eligible pairs, including 30 in the evaluation
split, remain pending. Independent real positive/negative/inconclusive coverage
is zero. Corpus/source bytes and labels are preserved unchanged; thresholds are
not adjusted after seeing results. The author has seen the evaluation design
and sources and is not a blind independent evaluator.

The source-only diagnostic uses the existing chronological allowlist, exact
800-character source slices, fixed task, k=5, 4000 estimated-token budget and
no provider/answer model. The original current-workflow baseline still produces
prepared prompts rather than decisions. A new unassessed basis-claim version
attaches an update to each declared changed dependency; production comparison
then follows the exact old accepted dependency. It does not interpret prose as
new support, opposition, withdrawal or typed conditions. Curated and proposed
inputs run independently, and proposed links stay unaccepted. This mapping is
pinned as `dm.source-change-diagnostic/1` in every raw report.

This executes available held-out inputs through production interfaces, but
**does not complete semantic held-out evaluation**. The frozen corpus lacks
independently reviewed structured proposals/conditions and accepted semantic
judgments. Inventing those after reading held-out labels would invalidate the
comparison. A new independently annotated and frozen successor is required;
retain the original sources, labels, reports and exposure disclosure.

Independent provenance correctness and unsupported-conclusion/comparability-error
judgments remain null. Exact reference/path correctness in a diagnostic is not a
substitute for these assessments. Missing provider measurements are absent, not
free successful answers; provider calls are zero and currency is unspecified.
Scripted review latency measures software work only. Human review-time savings
remain unmeasured.

## Required controlled user protocol before a savings claim

Freeze independently reviewed tasks and answers before recruitment. Use paired,
counterbalanced assignments of the same chronological source packets, task,
model/prompt (if any), budgets and settings to current-workflow, explicit-link
and Decision Memory conditions. Randomize order across participants and reserve
whole decision families to reduce learning transfer. Record active review time
with a documented timer/idle rule, completion, failures, abstentions and every
excluded trial with its reason. Freeze participant/trial counts, stopping rule,
exclusions and analysis before collecting results; do not select a sample size
or stop after seeing favorable times.

Independent reviewers blinded to condition score decision correctness, exact
provenance, unsupported conclusions, missed impacts and false alerts. Record
reviewer identity, disagreements, adjudication and all denominators. Compare
median active time only after checking no reduction in independent correctness
and no increase in unsupported claims. The original gate requires at least 20%
lower median active review time. No participants have performed this protocol;
there is no measured savings value or model self-rating standing in for it.

## Frozen gates and promotion

False alerts and misses must each be at most 5%; provenance and inconclusive
handling must be 100%; unsupported conclusions must be zero. Held-out coverage
requires at least 20 positive pairs, 20 negative pairs and 10 inconclusive cases,
plus all required failure modes. Every enumerated integrity scenario must pass.
The usability gate requires the controlled 20% median reduction with correctness
and unsupported-claim safeguards. The diagnostic's machine-readable gate
assessment marks missing observations unmeasured and inadequate independent
coverage failed. A partial integrity walkthrough cannot satisfy the complete
integrity gate.

Remaining delivery for #81: independently frozen semantic held-out cases,
independent provenance/statement/comparability assessment, full integrity-matrix
sign-off and the actual controlled user exercise. Until those are complete,
keep #81 open and the feature explicitly experimental. Paid calls and real
corpus execution remain opt-in. Release publishing is a separate action.

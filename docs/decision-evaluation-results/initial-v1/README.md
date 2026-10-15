> Historical reports: the palette formatting-only update was incorrectly labeled
> positive, and prepared prompts could omit the current update. Use the
> [corrected reports](../README.md) for the revised task and controls.

# Initial offline baselines

All three reports ran against clean code commit
`36286fd46186b070eab923532db62ff9cc22ae97`, with HashEmbedder, graph expansion
disabled, no reranker, no provider calls and no answer model. Full code and
corpus manifests, configuration, prompts, timestamps, errors and timings are
inside each report. They were copied into this later report commit after
execution, so their clean source status refers to the executed snapshot.

| Report | Events | Attempted pairs | Independent real labels | Errors |
| --- | --- | --- | --- | --- |
| project-development.json | 8 | 27 | 0 (all pending) | 0 |
| project-evaluation.json | 8 | 30 | 0 (all pending) | 0 |
| controls.json (synthetic) | 10 | 100 | not applicable | 0 |

Real impact and retrieval quality remain unscored. The manually supplied curated
dependency baseline surfaces eight decisions in each real split; these are
requests for source-basis review, not established correct impacts. Its proposed
profile has no supplied links and emits no alerts. Neither measures extraction.

On synthetic controls, the simple curated-dependency baseline has four correctly
explained positives out of four, four false alerts among 94 negative pairs,
and precision 4/8 on surfaced known pairs. It fails explicit uncertainty
handling (0/1 inconclusive and 0/1 unanswerable), so the false-alert rate being
below 5% does not establish readiness. Report raw alert burden (10) alongside
that rate: the many cross-topic negatives dilute it. The empty proposed profile
misses all four positives. Do not treat these fictional cases as evidence of
real project performance.

All reports explicitly fail release readiness. Answer quality, generated
rationale correctness, unsupported-conclusion judgment, integrity scenario
coverage and human annotation/review effort or savings remain unmeasured.
See the [protocol and missing delivery requirements](../../decision-evaluation.md).

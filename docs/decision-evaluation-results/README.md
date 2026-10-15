# Corrected offline baselines

All three reports use task version `decision-review-offline/2`, with HashEmbedder, graph expansion
disabled, no reranker, no provider calls and no answer model. Full code and
corpus manifests, configuration, prompts, timestamps, errors and timings are
inside each report. All three ran against clean source commit
`8adb83a20a6c288ae981357087919c595d1df84c` and were copied into this later report commit.
Each prompt includes the complete current update even when
retrieval omits it. Its estimated token count includes that task input; the
4000-token retrieved-context budget is recorded separately. The synthetic report
uses the corrected `controls-v2.0.0` freeze; real sources remain `project-v1.0.0`.

The original reports are preserved in [initial-v1/](initial-v1/README.md).
They used an incorrect positive label for the cosmetic palette update and a
task policy that could omit update content. They are historical artifacts,
not directly comparable baselines for the corrected task.

| Report | Events | Attempted pairs | Independent real labels | Errors |
| --- | --- | --- | --- | --- |
| project-development.json | 8 | 27 | 0 (all pending) | 0 |
| project-evaluation.json | 8 | 30 | 0 (all pending) | 0 |
| controls.json (synthetic) | 10 | 100 | not applicable | 0 |

Real impact and retrieval quality remain unscored. The manually supplied curated
dependency baseline surfaces eight decisions in each real split; these are
requests for source-basis review, not established correct impacts. Its proposed
profile has no supplied links and emits no alerts. Neither measures extraction.

On synthetic controls, the simple curated-dependency baseline has three correctly
explained positives out of three, five false alerts among 95 negative pairs,
and precision 3/8 on surfaced known pairs. Its false-alert rate is 5.26%, above
the frozen 5% maximum. It also fails explicit uncertainty handling
(0/1 inconclusive and 0/1 unanswerable). Report raw alert burden (10) alongside
that rate: the many cross-topic negatives dilute it. The empty proposed profile
misses all three positives. Do not treat these fictional cases as evidence of
real project performance.

All reports explicitly fail release readiness. Answer quality, generated
rationale correctness, unsupported-conclusion judgment, integrity scenario
coverage and human annotation/review effort or savings remain unmeasured.
See the [protocol and missing delivery requirements](../decision-evaluation.md).

# Fresh Y1 comparison and the unresolved withdrawal finding

The fresh comparison of the **same known synthetic development case** now pins
the Y1 successor's existing reviews and their exact inputs. An explicit scripted
diagnostic review records a **new version of the withdrawal finding, workflow
`open`**. Its old confirmed/acknowledged version survives unchanged. The old
decision still needs investigation; the successor decision and dependency stay
**proposed**. Activation, resolution and independent acceptance remain open.

This is a development replay with a diagnosed comparator fix, not independent
annotation, a new test corpus, measured semantic improvement or product benefit.
Only the previously exposed `controls-v2/event-surviving-support` sources are
used. No frozen source, label, threshold or old report/review is replaced.

## Why replay, and what changed

The original run's temporary brain was removed after exporting its journal.
Its [exact archive](../support-paths-v1/README.md) and
[source review](../y1-basis-review-v1/README.md) remain unchanged. The new run
therefore explicitly reproduces the same case through public proposal/review
APIs in an empty dedicated brain. A semantic-role mapping matches **14 content
payload/provenance/predecessor records** and **16 recorded review semantics**
against the archive. Per-run UUIDs, timestamps, anchors and Git revisions differ;
they are not presented as the original execution's exact identities. The
historical finding's path/support meaning is compared separately. All old
archive bytes and reviews remain preserved at their original references.

The first fresh comparison exposed a technical freshness defect. It correctly
pinned the new claim head, but selected review event IDs only from the old
reference set. Its successor claim's workflow/epistemic events were missing;
the public writer therefore rejected even a newly regenerated candidate with
`Review basis is stale; refresh the content and basis`. This was initially
attributed too generally to the old target. The precise missing-review pinning
was reproduced in four regression instances on original snapshot `22e398a`.

Fix **`5b53693114a0cf360dcb522c0ade3c09a664f1c9`** includes current endpoint heads,
their existing reviews and explicitly referenced content in the bounded basis
closure. Historical paths and endpoint versions remain exact. Existing
freshness/authorization checks are unchanged; no old approval transfers to the
new basis. The existing 200-reference expansion/output bounds and all impact
limits remain enforced, with truncation reported. Later changes to the current
claim assessment, its update source or its support still make the finding
stale. No source sufficiency rule or frozen evaluation threshold is changed.

Raw candidate support display tags (`shared`/`distinct_recorded_roots`) can vary
across independently assigned replay UUID order. The mapping preserves both raw
tags and compares exact roots, source refs, availability and `independence=not
inferred`; it never treats those tags as independent-run proof. The initial
mapping assertion, the pre-fix writer rejection and other authoring executions
of the same case remain in [authoring evidence](authoring/attempts.json).
These are not new independent cases or successful semantic measurements.

## Actual comparisons and finding review

The report retains frozen before/after Git revisions, all original deltas and
candidates, queues/detail, default limits and repeated-ID checks:

| Interval | Deltas | Review candidates | Interpretation |
| --- | --- | --- | --- |
| Initial X1/Y1 basis → Y1 successor | 10 | 3 | Withdrawal of X1; changed old claim; proposed successor dependency |
| Withdrawal snapshot → Y1 successor | 8 | 2 | Claim/dependency changes after the already recorded withdrawal |
| Y1 snapshot → itself | 0 | 0 | No new change in this interval; no finding is thereby resolved |

All three comparisons are **untruncated**. They retain the default limits
(depth 3, objects 200, links 500, paths 20, deltas 200). These are raw per-delta
review candidates from one remodeled known event, not three new incidents,
quality scores or an updated false-alert rate.

The refreshed withdrawal candidate targets the **old decision version**. Its
old X1 and Y1 support links are both no longer fresh at that old claim endpoint:
X1 evidence is withdrawn; Y1 evidence remains **available**, but its old link
is stale. Thus the old-target candidate correctly has zero remaining current
supports and two removed-or-stale links. This does not assert Y1 was withdrawn.
The successor-dependency candidate shows the accepted Y1 support on the **new
claim**, while the dependency/decision remain proposed. Its raw
`comparability_unknown` / `proposed_preview`, and the old claim-change
candidate's `comparability_unknown`, remain visible. A source-consistency audit
does not silently accept these logical paths or suppress their qualifications.

Reusing the **old candidate ID** against the fresh comparison is rejected.
After the pinning fix, public `record_finding` accepts the newly regenerated
withdrawal candidate as a material successor of the same finding identity,
with exact `previous` and `former_candidate_id`. This is **one explicit
synthetic developer finding-disposition event**, not human acceptance or a
decision conclusion/activation. The new version starts workflow **open** rather
than inheriting acknowledgement. It is fresh; the previous version retains its
confirmed/acknowledged history and is visibly stale.

The replay journal moves from **15 versions / 16 scripted events** to **16
versions / 17 events** by append only. The new pending finding is visible in the
default queue. With the fresh comparison, the queue shows the finding plus two
unreviewed candidates; history shows both finding versions. The old decision
remains `needs_investigation`; the successor decision and dependency have no
review events and remain `proposed`. There is no resolution or activation.

## Reproducibility and checks

The [raw report](report.json.gz) binds original input/source hashes, archive
SHA-256, runner and transitive code fingerprints, original-to-replay reference
mapping, complete journals, actual review results and exact Git revisions.
Dirty metadata is retained: code is frozen at `5b53693`, while new documentation
and audit files were being authored. Implementation fingerprints remain exact.
The [Git bundle](brain.bundle) now preserves this replay's actual commits and
objects for the next step; its SHA-256 is recorded. It contains only the dedicated
fictional brain. Restoring it reproduces exact references, deltas and candidate
IDs, unlike creating another replay with new IDs.

```bash
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-refresh-v1/refresh.py --output /tmp/y1-refresh-new
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-refresh-v1/verify.py
.venv/bin/python docs/decision-evaluation-results/false-alert-development-v1/y1-refresh-v1/check_references.py
```

Always use a new output directory. The runner supplies no arbitrary case,
reserved-data, outcome or activation option. An active source-read guard rejects
labels/evaluation-source paths. Full historical synthetic controls are rerun
only as already exposed regressions, never new final evaluation. The verifier
checks complete file inventory, source/code identities, append-only reviews,
actual open/proposed states and an offline bundle restore. The stale candidate
is rejected again without any write. Old evidence verifiers run in isolated
checkouts at their original heads; their guards/manifests are not weakened.

[Exact commands](commands.json), raw logs and JSON results distinguish execution
success, the confirmed basis-change diagnosis and still-missing independent
acceptance. Four new regressions fail on original `22e398a`; the expanded focused
run before the fix passes 178 existing tests, and after the fix **83 targeted
tests** pass, including the four regressions. Final validation on frozen fix `5b53693`:

| Check | Actual result |
| --- | --- |
| Full local suite | **2,186 passed / 10 optional model skips / 1 existing Starlette warning**, 815.16s |
| Expanded focused run | **182 passed**, 316.30s; same known development inputs only |
| Strict engineering integrity matrix | **55 passed; 41/41 applicable cells**, 13 technically N/A; independent final sign-off remains unmeasured |
| Fresh comparison and writer | Completed; fresh open finding; exact bundle restore and stale-candidate rejection verified |
| Reviewed development replay | 13/13 cases completed; original input hashes and normalized alerts identical |
| Smoke / controls / workflow / production / dependency consistency | All five commands exit 0; original scores/gates/thresholds unchanged |
| Historical evidence | Eight verifiers pass at their original snapshots |
| Fix CI | All **15 checks pass**, including actual model/trust stack and seven advisory profiles: [CI](https://github.com/SaltKing0/graph-engine/actions/runs/39152764601), [advisories](https://github.com/SaltKing0/graph-engine/actions/runs/39152764595) | No hypothetical event or failed write is counted as a
successful review.

## Open gates and next step

The historical standard diagnostic still **fails 5/95 false alerts (5.26%) >5%**;
the empty proposed profile misses **3/3 positives**. This focused replay and
freshness fix do not replace the frozen gate, relabel old outcomes or establish
semantic quality. Independent final coverage remains **0/0/0**. Real execution/
dataset-provenance review, independent annotation/adjudication, protected final
freeze/candidate sign-off, matched completed search-agent comparisons and
actual user sessions/product benefit remain missing.

No additional #90–#93 or #73 acceptance checkbox is completed. The PR remains
Draft, Decision Memory experimental, the withdrawal finding open and the
successor unactivated. Next: review the two outstanding change/dependency
candidates and establish an explicitly authorized current decision/basis path
before any activation or resolution. Independent-run credit still requires
actual artifacts and separate qualified human review. No merge or release.

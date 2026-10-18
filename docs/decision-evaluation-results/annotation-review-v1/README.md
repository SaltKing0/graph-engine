# Draft PR #94 review corrections — 18 October 2026

The review reproduced a provenance/inventory validation gap: a packet could
change a source revision, path, lineage, license or origin commitment, or omit
eligible cases/sources/pairs, while retaining `packet_valid=true`. These are
engineering regression cases, not semantic evaluation labels or human judgments.

The validator now binds every event, available source, decision and provenance
field to the original frozen development metadata and file commitments. It
still opens no labels or evaluation-source bytes and certifies no human review.
The original exported packet, blank form and manifest reproduce byte for byte;
original sources, labels, freezes, old reports and thresholds remain untouched.

Measured clean code: `2c479b8f7d7289d877a5822e212896531e6d450c`.
[Exact commands and identity](validation.json), [CI snapshot](ci-code.json) and
raw logs are saved here; [manifest.json](manifest.json) hashes these new files.
The old annotation-preparation-v1 evidence is preserved as a historical record.

| Check | Observation |
| --- | --- |
| Ten new regression cases, before correction | 10 failed / 23 deselected; expected defect reproduction |
| Complete annotation boundary suite after correction | 33 passed |
| Full local suite | 1982 passed / 11 optional skips / 1 existing warning; 312.78 s |
| Memory smoke and frozen Decision Memory controls | Both exit 0; no release/quality claim |
| Development export | Exit 0; packet/form/manifest exactly equal the saved originals |
| CI on measured code | All 14 checks successful, including Chromium, MCP, PDF, real-model/trust and seven advisory profiles |

Local skips are the absent optional Chromium module and ten optional real-model
cases. Matching CI supplies those required optional jobs. No paid provider,
new final/evaluation sources, independent annotations, calibration or user
sessions were run. Production workflow/diagnostic checks were not repeated for
this annotation-only correction; they are rerun on the combined #95 branch.
No product benefit, final coverage or new acceptance criterion is inferred.

Reproduce from this code checkout with CONTRIBUTING.md dependencies and the
commands in validation.json, using fresh output paths. To verify saved-file
hashes, run Python from the repository root and SHA-256 each path listed in
manifest.json; the manifest itself is excluded from its own hash inventory.
#90 stays open and both PRs remain drafts. No PR merge or release was performed.

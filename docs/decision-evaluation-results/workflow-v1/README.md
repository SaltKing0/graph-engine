# Offline production workflow audit and source-change diagnostics

Completed runs pin clean source commit `1d9581416cba60aa991a9d626f563d8203f34025`.
Reports were copied into version control afterward. `manifest.json` hashes the
saved files; each report also pins code/corpus/schema/settings and raw responses.
The [readiness assessment](../../decision-release-readiness.md) explains the
measurements and missing independent/user evidence. **Release readiness is false.**

- `issue81-workflow-frozen.json`: complete imported-document workflow, seven
  integrity checks, raw responses and separate per-operation timing.
- `issue81-production-{controls,development,evaluation}.json.gz`: conservative
  source-change diagnostic through production services, curated/proposed profiles
  separately, raw responses, exact revisions, pair scores and original gates.
- Corresponding `*-baseline.json`: existing current-workflow prepared prompts
  and direct-dependency baselines. All 26 events match their preserved #75 inputs,
  prepared prompts, configurations and explicit alerts.
- `issue81-controls-frozen.json` and `issue81-memory-smoke-frozen.json`: required
  bounded offline checks. Neither measures product release or answer quality.
- `summary.json`: stage p50/p95 with explicit event denominators, pair scores and
  typed context truncation counts. Synthetic and real strata stay separate.
- `validation/`: exact local gate logs, advisory dry-run resolutions, raw audit
  results and normalized findings. The advisory command script uses local
  temporary runtimes; the portable reproduction is in CONTRIBUTING.md.
- `interrupted/*.json.gz`: incomplete checkpoints from the initial per-record
  implementation at `1287ba4`, explicitly marked interrupted when batching was
  introduced. They are excluded from completed scores. A running event may have
  no saved profile yet; its absence is not success. Their original transient
  baseline files were overwritten during the restart and are unavailable; the
  retained checkpoint hashes expose that missing artifact. Do not treat them as
  fully reproducible/completed experiments.

Reproduce from a source checkout using the commands in
[the walkthrough](../../decision-workflow.md). The real bundle requires
`--real-corpus`, even though it is local and inert. No provider calls, model
weights, network source fetching or research execution are part of these runs.
Do not alter held-out labels, change gates or claim measured human review savings
from scripted timings. Independent real labels and a controlled user exercise
are still required for #81.

Large production reports and advisory resolution reports use deterministic gzip
compression. Decompress with `gzip -dc <file>.json.gz` to recover the exact
original JSON. `manifest.json` records both saved-file and decompressed SHA-256
hashes; compression does not change any measured report fields. Smaller baseline,
workflow and summary JSON files remain directly readable.

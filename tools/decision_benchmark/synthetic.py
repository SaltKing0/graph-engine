"""Explicit fictional controls, authored independently of baseline outputs."""
from __future__ import annotations

from pathlib import Path

from .freeze_sources import freeze

# These are contract conformance expectations, never real project measurements.
CONTROLS = (
    ("comparable", "positive", "The declared same workload, code, environment and metric now has a contrary result. Review the basis; do not reverse the decision automatically."),
    ("changed-conditions", "negative", "The workload is different and known disjoint. This result cannot oppose the original claim."),
    ("time-only", "negative", "A later observation repeats the same value. Time passing alone is not contradictory evidence."),
    ("duplicate-citation", "negative", "The new citation is a copy of the same measurement lineage, not independent support or opposition."),
    ("surviving-support", "positive", "One support is withdrawn, while a separately recorded independent support survives. Review the changed basis without rejecting the claim."),
    ("withdrawn", "positive", "The sole evidence source was withdrawn. Review the lost basis; withdrawal does not establish falsehood."),
    ("unknown-comparability", "inconclusive", "The update omits the environment and corpus hash. Explicitly report unknown comparability; no opposition is established."),
    ("unrelated", "negative", "The update changes label spacing in a different source with no dependency on this decision."),
    ("no-review", "negative", "A formatting-only source change leaves the exact proposition and conditions unchanged."),
    ("unanswerable", "unanswerable", "The artifact contains no result and no recoverable measurement. A review outcome cannot be determined."),
)

# Observed fictional source content is separate from the expected review
# rationales above. No gold impact instruction is included in model context.
OBSERVATIONS = {
    "comparable": "Observation X2: recall=0.2 fraction; workload W; environment E; code C; corpus H; replaces X1 recall=0.8. Both observations use the same protocol P.",
    "changed-conditions": "Observation X2: recall=0.2 fraction; workload W2; environment E; code C; corpus H2; protocol P. Original observation X1 used workload W and corpus H.",
    "time-only": "Observation X2 at 2026-01-04: recall=0.8 fraction; workload W; environment E; code C; corpus H; protocol P. Observation X1 at 2026-01-01 had the same value and conditions.",
    "duplicate-citation": "Artifact X-copy quotes measurement X1 verbatim; lineage_id=run-X1. No new measurement was performed.",
    "surviving-support": "Availability update: support X1 withdrawn by its author. Independent support Y1 remains available; Y1 was a separate run with known protocol and dataset provenance.",
    "withdrawn": "Availability update: measurement X1 withdrawn by its author. This record supplies no replacement measurement.",
    "unknown-comparability": "Observation X2: recall=0.2 fraction; workload W; code C; environment not supplied; corpus hash not supplied; protocol P.",
    "unrelated": "Palette artifact P2: the blue label now has two spaces instead of one. No mode-A measurements occur in this artifact.",
    "no-review": "The source contains the same observation X1 recall=0.8, workload W, environment E, code C, corpus H and protocol P. Only blank-line formatting changed.",
    "unanswerable": "The result artifact was not retained. There are no values, environment fields or measurement timestamps in this update.",
}


def build(output: Path, contract: bytes) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "sources").mkdir(exist_ok=True)
    inputs: dict = {"schema": "dm.eval.inputs/1", "kind": "synthetic", "version": "controls-v1.0.0",
                    "sources": [], "decisions": [], "dependencies": [], "events": []}
    labels: dict = {"schema": "dm.eval.labels/1", "author": "Codex contract fixture author",
                    "reviewer": None, "disagreements": None, "pairs": {}}
    for index, (name, outcome, text) in enumerate(CONTROLS):
        split = "development" if index < 5 else "evaluation"
        at = f"2026-01-{index + 2:02}T00:00:00Z"
        for suffix, content, available in (
            ("basis", "SYNTHETIC: Choose mode A when recall >=0.7 fraction. Observation X1: recall=0.8, workload W, environment E, code C, corpus H, protocol P, lineage run-X1. "
             + ("Separate support Y1: recall=0.8 under the same conditions, independent lineage run-Y1." if name == "surviving-support" else "No other support is recorded."), "2026-01-01T00:00:00Z"),
            ("other", "SYNTHETIC: Choose UI color blue based on the palette source. No dependency on mode A.", "2026-01-01T00:00:00Z"),
            ("update", "SYNTHETIC UPDATE: " + OBSERVATIONS[name], at)):
            sid = f"{name}-{suffix}"
            file = f"sources/{sid}.txt"
            (output / file).write_text(content + "\n", encoding="utf-8")
            inputs["sources"].append({"id": sid, "file": file, "available_at": available, "split": split,
                                      "lineage": f"fictional-{name}-{suffix}", "license": "MIT",
                                      "conditions": {"synthetic": True}})
        for suffix in ("basis", "other"):
            did = f"decision-{name}-{suffix}"
            inputs["decisions"].append({"id": did, "family": name, "split": split,
                                        "source_id": f"{name}-{suffix}",
                                        "action": "SYNTHETIC: choose mode A" if suffix == "basis" else "SYNTHETIC: choose blue"})
            inputs["dependencies"].append({"id": f"link-{name}-{suffix}", "source_id": f"{name}-{suffix}",
                                            "decision_id": did, "available_at": "2026-01-01T00:00:00Z",
                                            "status": "curated"})
        # A separately supplied proposed-link profile deliberately lacks links.
        # This is not an extractor and must not be scored as extraction quality.
        event = {"id": f"event-{name}", "at": at, "split": split,
                 "source_id": f"{name}-update", "changed_source_id": f"{name}-basis",
                 "changed_path": f"fictional/{name}.txt"}
        if name == "unrelated":
            event["changed_source_id"] = f"{name}-other"
        inputs["events"].append(event)
    for event in inputs["events"]:
        for decision in inputs["decisions"]:
            if decision["split"] != event["split"]:
                continue
            name = decision["family"]
            expected, explanation = next((o, t) for n, o, t in CONTROLS if n == name)
            primary = decision["id"] == f"decision-{name}-basis" and event["id"] == f"event-{name}"
            # The unrelated update changes the palette source; that separate
            # decision needs review, while mode A remains unaffected.
            palette = name == "unrelated" and event["id"] == "event-unrelated" and not primary
            outcome = expected if primary else "positive" if palette else "negative"
            path = [event["source_id"], event["changed_source_id"],
                    f"link-{name}-{'basis' if primary else 'other'}", decision["id"]]
            labels["pairs"][f"{event['id']}/{decision['id']}"] = {
                "outcome": outcome, "rationale": explanation if primary else "Separate source dependency.",
                "valid_paths": [path] if outcome in ("positive", "inconclusive", "unanswerable") else [],
                "control": name if primary else "unrelated-pair",
                "annotation": {"status": "synthetic-authored", "annotator": "Codex",
                               "reviewer": None, "disagreements": None}}
    freeze(output, inputs, labels, contract)

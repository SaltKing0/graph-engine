"""Frozen local bytes and source-only, chronological experiment inputs."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent / "data"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def local_file(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("corpus files must remain inside the bundle")
    return path


def load_bundle(root: Path) -> tuple[dict, dict, dict]:
    """Verify the freeze before reading inputs or isolated labels. No Git/network."""
    freeze = json.loads((root / "freeze.json").read_bytes())
    if freeze.get("schema") != "dm.eval.freeze/1" or digest(canonical(freeze["files"])) != freeze["sha256"]:
        raise ValueError("invalid freeze manifest")
    for name, expected in freeze["files"].items():
        if digest(local_file(root, name).read_bytes()) != expected:
            raise ValueError(f"frozen file changed: {name}")
    if not {"inputs.json", "labels.json"} <= freeze["files"].keys():
        raise ValueError("freeze must cover inputs and labels")
    inputs = json.loads((root / "inputs.json").read_bytes())
    labels = json.loads((root / "labels.json").read_bytes())
    validate(inputs, labels, freeze)
    return inputs, labels, freeze


def validate(inputs: dict, labels: dict, freeze: dict) -> None:
    if inputs["schema"] != "dm.eval.inputs/1" or labels["schema"] != "dm.eval.labels/1":
        raise ValueError("unsupported evaluation schema")
    sources = {s["id"]: s for s in inputs["sources"]}
    decisions = {d["id"]: d for d in inputs["decisions"]}
    events = {e["id"]: e for e in inputs["events"]}
    if (len(sources) != len(inputs["sources"]) or len(decisions) != len(inputs["decisions"])
            or len(events) != len(inputs["events"])):
        raise ValueError("duplicate source, decision or event ID")
    for source in sources.values():
        if source["file"] not in freeze["files"]:
            raise ValueError("source bytes not frozen")
        instant(source["available_at"])
    for decision in decisions.values():
        if (decision["source_id"] not in sources or decision["split"] not in ("development", "evaluation")
                or sources[decision["source_id"]]["split"] != decision["split"]):
            raise ValueError("invalid decision source/split")
    links = inputs["dependencies"]
    if len({link["id"] for link in links}) != len(links):
        raise ValueError("duplicate dependency ID")
    for link in links:
        if (link["decision_id"] not in decisions or link["source_id"] not in sources
                or link["status"] not in ("curated", "proposed")
                or sources[link["source_id"]]["split"] != decisions[link["decision_id"]]["split"]):
            raise ValueError("invalid dependency")
        if instant(link["available_at"]) < instant(sources[link["source_id"]]["available_at"]):
            raise ValueError("dependency precedes its source")
    last = None
    for event in inputs["events"]:
        time = instant(event["at"])
        if last is not None and time < last:
            raise ValueError("events must be chronological")
        last = time
        if event["source_id"] not in sources or event["changed_source_id"] not in sources:
            raise ValueError("unknown event source")
        if any(sources[event[key]]["split"] != event["split"] for key in ("source_id", "changed_source_id")):
            raise ValueError("event crosses frozen split")
        if time < instant(sources[event["source_id"]]["available_at"]):
            raise ValueError("event precedes update availability")
        if time < instant(sources[event["changed_source_id"]]["available_at"]):
            raise ValueError("event changes a future source")
        if event["split"] not in ("development", "evaluation"):
            raise ValueError("invalid event split")
        targets = [d for d in decisions.values() if d["split"] == event["split"]
                   and instant(sources[d["source_id"]]["available_at"]) <= time]
        for decision in targets:
            key = f"{event['id']}/{decision['id']}"
            label = labels["pairs"].get(key)
            if label is None or label["outcome"] not in (
                    "positive", "negative", "inconclusive", "unanswerable", "pending"):
                raise ValueError("every eligible case-decision pair needs an explicit label")
            if inputs["kind"] == "real" and label["outcome"] != "pending":
                provenance = label["annotation"]
                if (provenance["status"] != "adjudicated"
                        or provenance["annotator"] == provenance["reviewer"]
                        or not provenance["annotator"] or not provenance["reviewer"]
                        or provenance["disagreements"] is None or not provenance.get("reviewed_at")
                        or not label.get("rationale")):
                    raise ValueError("real scores require independent adjudication")
                instant(provenance["reviewed_at"])
    # Decision families cannot cross the development/evaluation boundary.
    families: dict[str, set[str]] = {}
    for decision in decisions.values():
        families.setdefault(decision["family"], set()).add(decision["split"])
    if any(len(splits) != 1 for splits in families.values()):
        raise ValueError("decision family crosses frozen split")


def visible_inputs(inputs: dict, event: dict, root: Path) -> dict:
    """Explicit allowlist: labels, draft rationales and future bytes never enter."""
    time = instant(event["at"])
    sources = [s for s in inputs["sources"] if instant(s["available_at"]) <= time
               and s["split"] == event["split"]]
    ids = {s["id"] for s in sources}
    decisions = [{k: d[k] for k in ("id", "source_id", "action")}
                 for d in inputs["decisions"] if d["source_id"] in ids]
    dids = {d["id"] for d in decisions}
    dependencies = [{k: link[k] for k in ("id", "source_id", "decision_id", "status")}
                    for link in inputs["dependencies"] if link["source_id"] in ids
                    and link["decision_id"] in dids and instant(link["available_at"]) <= time]
    documents = []
    for source in sources:
        text = local_file(root, source["file"]).read_text(encoding="utf-8")
        # Exact character slices; ID and source manifest preserve source provenance.
        for index, start in enumerate(range(0, len(text), 800)):
            documents.append({"id": f"{source['id']}-c{index:03}",
                              "source_id": source["id"], "text": text[start:start + 800]})
    return {"documents": documents, "decisions": decisions, "dependencies": dependencies}

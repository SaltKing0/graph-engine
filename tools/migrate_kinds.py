"""One-time migration: rewrite German edge-kind values to canonical English.

Audit #21 (fix wave 4): the engine historically emitted a German kind
dialect ("aehnlich"/"ähnlich", "erweitert", "kontradiktorisch") while
demo/UI/tests used ASCII. Since the wave-4 rename the engine emits and
expects canonical English kinds everywhere:

    aehnlich / ähnlich  ->  similar
    erweitert           ->  extends
    kontradiktorisch    ->  contradicts

Usage (dry-run first, then apply):

    python -m tools.migrate_kinds /path/to/brain            # dry-run report
    python -m tools.migrate_kinds /path/to/brain --apply    # rewrite edges.jsonl

The migration is idempotent (already-migrated kinds pass through), only
touches the `kind` field, preserves everything else (ids, timestamps,
provenance, ordering), and writes edges.jsonl atomically (tmp + os.replace).
A backup copy is left next to the file as edges.jsonl.bak-<timestamp>.
"""

from __future__ import annotations

from contextlib import nullcontext
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from graph_engine.brain import Brain

KIND_MAP = {
    "aehnlich": "similar",
    "ähnlich": "similar",
    "erweitert": "extends",
    "kontradiktorisch": "contradicts",
}


def migrate(edges_path: Path, apply: bool) -> tuple[int, int]:
    """Rewrite kind values in place. Returns (scanned, rewritten)."""
    with Brain(str(edges_path.resolve().parent)).write_guard() if apply else nullcontext():
        rewritten = 0
        scanned = 0
        out_lines: list[str] = []
        with edges_path.open(encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    out_lines.append(line)
                    continue
                try:
                    e = json.loads(stripped)
                except json.JSONDecodeError:
                    out_lines.append(line)  # skip-bad-line policy, unchanged
                    continue
                scanned += 1
                kind = e.get("kind")
                if kind in KIND_MAP:
                    e["kind"] = KIND_MAP[kind]
                    rewritten += 1
                out_lines.append(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")

        if apply and rewritten:
            data = "".join(out_lines)
            backup = edges_path.with_name(
                f"{edges_path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            backup.write_text(edges_path.read_text(encoding="utf-8"), encoding="utf-8")
            fd, tmp = tempfile.mkstemp(dir=str(edges_path.parent), prefix=".edges-")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, edges_path)
            print(f"backup written: {backup}")
        return scanned, rewritten


def main() -> int:
    args = [a for a in sys.argv[1:]]
    apply = "--apply" in args
    paths = [a for a in args if a != "--apply"]
    if len(paths) != 1:
        print(__doc__)
        return 2
    brain = Path(paths[0]).expanduser()
    edges = brain / "edges.jsonl" if brain.is_dir() else brain
    if not edges.is_file():
        print(f"error: {edges} not found")
        return 2
    scanned, rewritten = migrate(edges, apply)
    mode = "APPLIED" if apply else "DRY-RUN (add --apply to write)"
    print(f"{mode}: scanned {scanned} edges, would rewrite {rewritten}"
          if not apply else
          f"{mode}: scanned {scanned} edges, rewrote {rewritten}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

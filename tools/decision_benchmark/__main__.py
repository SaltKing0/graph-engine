"""Offline Decision Memory corpus baseline. No provider or download code path."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .corpus import DATA, load_bundle
from .freeze_sources import verify_git
from .runner import run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-corpus", action="store_true", help="opt in to the bounded project corpus")
    parser.add_argument("--split", choices=("development", "evaluation", "all"), default="development")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--check", action="store_true", help="structural offline CI gate, never a product release gate")
    parser.add_argument("--verify-git", type=Path, help="verify pinned sources against full local repository history")
    args = parser.parse_args()
    if args.check and args.real_corpus:
        parser.error("--check is only for bounded synthetic CI controls")
    root = DATA / ("project-v1" if args.real_corpus else "controls-v1")
    try:
        if args.verify_git:
            if not args.real_corpus:
                parser.error("--verify-git requires --real-corpus")
            inputs, _, _ = load_bundle(root)
            verify_git(args.verify_git, root, inputs)
        report = run(root, args.output, split=args.split)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Invalid corpus or configuration: {exc}\n")
    print(json.dumps({"status": report["status"], "events": len(report["results"]),
                      "release_ready": False, "output": str(args.output)}))
    return 1 if report["status"] != "complete" or (args.check and not report["smoke_passed"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())

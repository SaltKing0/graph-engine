"""Run from a source checkout: python -m tools.memory_benchmark."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from .adapters import ADAPTERS
from .answers import HTTPAnswers
from .dataset import DEFAULT_DATASET, import_longmemeval
from .runner import checkpoint, run


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adapter", action="append", choices=ADAPTERS)
    parser.add_argument("--k", type=positive, default=5)
    parser.add_argument("--context-budget", type=positive, default=256)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--embedding-model-path", type=Path,
                        help="opt in to an existing local SentenceTransformer model, no downloads")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--question", action="append", default=[])
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--allow-model-calls", action="store_true")
    parser.add_argument("--endpoint", help="exact Chat Completions compatible URL")
    parser.add_argument("--model", help="pinned answer model/revision; avoid moving aliases")
    parser.add_argument("--max-requests", type=positive, default=6)
    parser.add_argument("--max-output-tokens", type=positive, default=128)
    parser.add_argument("--max-total-estimated-tokens", type=positive, default=8192)
    parser.add_argument("--timeout-seconds", type=positive, default=30)
    parser.add_argument("--import-longmemeval", type=Path)
    parser.add_argument("--dataset-version", help="upstream release/revision for imported data")
    args = parser.parse_args()
    try:
        if args.import_longmemeval:
            if not args.dataset_version:
                parser.error("--import-longmemeval requires --dataset-version")
            checkpoint(args.output, import_longmemeval(args.import_longmemeval, args.dataset_version))
            print(f"Imported dataset: {args.output}")
            return
        if args.smoke and args.question:
            parser.error("select --smoke or --question")
        if (args.endpoint or args.model) and not args.allow_model_calls:
            parser.error("HTTP answers require explicit --allow-model-calls")
        if args.allow_model_calls and (not args.endpoint or not args.model or args.predictions):
            parser.error("model calls require --endpoint and --model, without --predictions")
        answerer = None
        if args.allow_model_calls:
            url = urlsplit(args.endpoint)
            if (url.scheme not in {"https", "http"} or not url.hostname
                    or url.username or url.password or url.query or url.fragment):
                parser.error("endpoint must be HTTP(S) without embedded credentials/query/fragment")
            answerer = HTTPAnswers(args.endpoint, args.model, args.seed, args.max_output_tokens,
                                  args.max_requests, args.max_total_estimated_tokens, args.timeout_seconds)
        report = run(dataset_path=args.dataset, output=args.output,
                     adapters=tuple(args.adapter or ADAPTERS), k=args.k, budget=args.context_budget,
                     seed=args.seed, smoke=args.smoke, question_ids=tuple(args.question),
                     predictions=args.predictions, answerer=answerer, check=args.check,
                     embedding_model_path=args.embedding_model_path)
        print(json.dumps({"status": report["status"], "summary": report["summary"]}, indent=2))
        if report["status"] != "complete" or report.get("smoke_passed") is False:
            raise SystemExit(1)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

"""Explicit, single-threaded local maintenance worker. Importing starts nothing."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import json
import math
import os
import signal
import subprocess
import threading
import time
from typing import Callable, Iterator

from . import namespaces, runtime
from .brain import Brain
from .consolidation import ConsolidationConfig, consolidate
from .consolidation_protocol import command_extractor, validate_consolidation
from .dream import lifecycle, refresh
from .write_guard import BrainWriteTimeout, git_deadline

ACTIONS = ("refresh", "lifecycle", "consolidate")
COUNTS = ("kind_changes", "recall_nodes", "recalls", "promoted", "revived", "staled",
          "created", "reused", "edges", "skipped", "pending_proposals")


@dataclass(frozen=True)
class MaintenanceConfig:
    graph: str = "default"
    actions: tuple[str, ...] = ("refresh", "lifecycle")
    interval: float = 900
    pass_timeout: float = 120
    lock_timeout: float = 30
    limit: int = 50
    max_records: int = 10000
    max_input_bytes: int = 64 * 1024 * 1024
    extract_model: bool = False
    model_timeout: float = 30
    consolidation: ConsolidationConfig = field(default_factory=ConsolidationConfig)

    def __post_init__(self) -> None:
        namespaces.validate_name(self.graph)
        if not self.actions or len(set(self.actions)) != len(self.actions) or set(self.actions) - set(ACTIONS):
            raise ValueError("choose distinct actions: refresh, lifecycle, consolidate")
        for name, lower, upper in (("interval", 0.01, 604800), ("pass_timeout", 0.01, 3600),
                                   ("lock_timeout", 0, 3600), ("model_timeout", 0.01, 3600)):
            value = getattr(self, name)
            if not math.isfinite(value) or not lower <= value <= upper:
                raise ValueError(f"{name} must be finite and between {lower} and {upper} seconds")
        for name, upper in (("limit", 1000), ("max_records", 1000000),
                            ("max_input_bytes", 1024 * 1024 * 1024)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError(f"{name} must be an integer between 1 and {upper}")
        if self.extract_model and ("consolidate" not in self.actions or self.model_timeout >= self.pass_timeout):
            raise ValueError("--extract-model needs consolidate and a model timeout shorter than the pass timeout")


class PassFailure(Exception):
    """Public error code, deliberately without exception text or private data."""

    def __init__(self, code: str, *, retryable: bool = True) -> None:
        super().__init__(code)
        self.code, self.retryable = code, retryable


class PassDeadline(BaseException):
    """Do not let best-effort helpers swallow an expired worker deadline."""


@contextmanager
def _deadline(seconds: float) -> Iterator[None]:
    if os.name != "posix" or threading.current_thread() is not threading.main_thread():
        raise ValueError("maintenance requires a POSIX main thread (Linux/macOS)")
    if signal.getitimer(signal.ITIMER_REAL)[0]:
        raise ValueError("maintenance cannot share an existing alarm timer")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(signum: int, frame: object) -> None:
        raise PassDeadline()

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        with git_deadline(time.monotonic() + seconds):
            yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _check_input(brain: Brain, config: MaintenanceConfig) -> None:
    """Reject oversized whole-corpus passes before any maintenance writes."""
    if not (brain.path / "nodes").is_dir():
        raise PassFailure("brain_uninitialized")
    total = 0
    for count, path in enumerate((brain.path / "nodes").glob("*.md"), 1):
        total += path.stat().st_size
        if count > config.max_records or total > config.max_input_bytes:
            raise PassFailure("input_limit")
    for name in ("edges.jsonl", "vectors.jsonl", "recalls.jsonl",
                 ".recall/pending.jsonl", ".recall/projection.json"):
        path = brain.path / name
        if not path.exists():
            continue
        total += path.stat().st_size
        if total > config.max_input_bytes:
            raise PassFailure("input_limit")
        with path.open("rb") as stream:
            for count, _ in enumerate(stream, 1):
                if count > config.max_records:
                    raise PassFailure("input_limit")


def _model(config: MaintenanceConfig) -> Callable[[list[dict]], dict]:
    # Reading configured commands does not enable them. Only --extract-model
    # reaches this factory, and only an eligible batch invokes the command.
    adapter = command_extractor(timeout=config.model_timeout)

    def extract(events: list[dict]) -> dict:
        try:
            data = adapter(events)
            validate_consolidation(data, events)
            return data
        except PassDeadline:
            # The adapter has cleaned up its process group, and consolidation
            # has not written any files while extracting/validating this batch.
            raise PassFailure("pass_timeout") from None
        except RuntimeError as exc:
            code = "model_timeout" if "timed out" in str(exc) else "model_failed"
            raise PassFailure(code) from None
        except (ValueError, OSError):
            raise PassFailure("model_output_invalid") from None

    return extract


def perform_pass(config: MaintenanceConfig, action: str) -> dict[str, int]:
    """Authorize fresh, bound input/time, and guard reads through final Git sync."""
    if action not in config.actions:
        raise ValueError("action was not selected")
    token = namespaces.request_graph.set(config.graph)
    mutating = False
    syncing = False
    try:
        with _deadline(config.pass_timeout):
            brain = runtime.make_brain()  # no embedder load/download; fresh policy
            brain.authorize("admin")
            with brain.write_guard(timeout=config.lock_timeout):
                if not (brain.path / "nodes").is_dir() or (brain.mode == "git" and not (brain.path / ".git").exists()):
                    raise PassFailure("brain_uninitialized")
                syncing = True
                brain.pull()
                syncing = False
                _check_input(brain, config)
                extractor = _model(config) if config.extract_model and action == "consolidate" else None
                mutating = True
                if action == "refresh":
                    result = refresh(brain, strict_report=True, sync=False)
                elif action == "lifecycle":
                    result = lifecycle(brain, limit=config.limit, sync=False)
                else:
                    result = consolidate(brain, config=replace(config.consolidation, limit=config.limit),
                                         structured_extractor=extractor, pending_evidence=True, sync=False)
                # Never export the rich maintenance result: it contains node
                # IDs, quotes, proposals and potentially private diagnostics.
                return {key: result[key] for key in COUNTS if type(result.get(key)) is int}
    except PassFailure:
        raise
    except BrainWriteTimeout:
        raise PassFailure("writer_busy") from None
    except PermissionError:
        raise PassFailure("access_denied", retryable=not (mutating or syncing)) from None
    except (PassDeadline, subprocess.TimeoutExpired):
        raise PassFailure("pass_timeout", retryable=not (mutating or syncing)) from None
    except Exception:
        raise PassFailure("storage_failure", retryable=not (mutating or syncing)) from None
    finally:
        namespaces.request_graph.reset(token)


def json_log(row: dict) -> None:
    print(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), **row}), flush=True)


class MaintenanceWorker:
    """Fixed delay after completion; no catch-up queue or concurrent passes.

    Clock, wait, runner and event sink are injectable for offline scheduling tests.
    SIGINT/SIGTERM request a stop; the current bounded pass finishes first.
    """

    def __init__(self, config: MaintenanceConfig, *, stop: threading.Event | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 wait: Callable[[float], bool] | None = None,
                 runner: Callable[[MaintenanceConfig, str], dict] = perform_pass,
                 emit: Callable[[dict], None] = json_log) -> None:
        self.config = config
        self.stop = stop if stop is not None else threading.Event()
        self.clock, self.wait = clock, wait if wait is not None else self.stop.wait
        self.runner, self.emit = runner, emit
        self._active = threading.Lock()

    def cycle(self) -> bool:
        if not self._active.acquire(blocking=False):
            self.emit({"event": "cycle_skipped", "reason": "already_running", "graph": self.config.graph})
            return False
        success = True
        try:
            for action in self.config.actions:
                if self.stop.is_set():
                    break
                started = self.clock()
                base = {"graph": self.config.graph, "action": action}
                self.emit({"event": "pass_started", **base})
                try:
                    result = self.runner(self.config, action)
                    counts = {key: result[key] for key in COUNTS if type(result.get(key)) is int}
                    self.emit({"event": "pass_completed", **base, "counts": counts,
                               "duration_seconds": round(self.clock() - started, 6)})
                except PassFailure as exc:
                    success = False
                    self.emit({"event": "pass_failed", **base, "error": exc.code,
                               "retryable": exc.retryable, "counts": {},
                               "duration_seconds": round(self.clock() - started, 6)})
                    if not exc.retryable:
                        self.stop.set()
                    break  # skip dependent actions; retry next interval
                except Exception:
                    success = False
                    self.stop.set()
                    self.emit({"event": "pass_failed", **base, "error": "unexpected_failure",
                               "retryable": False, "counts": {},
                               "duration_seconds": round(self.clock() - started, 6)})
                    break
        finally:
            self._active.release()
        return success

    def run(self, *, once: bool = False) -> int:
        self.emit({"event": "worker_started", "graph": self.config.graph,
                   "actions": list(self.config.actions), "interval_seconds": self.config.interval,
                   "extract_model": self.config.extract_model})
        status = 0
        while not self.stop.is_set():
            success = self.cycle()
            if not success and (once or self.stop.is_set()):
                status = 1
            if once or self.stop.is_set() or self.wait(self.config.interval):
                break
        self.emit({"event": "worker_stopped", "graph": self.config.graph, "exit_status": status})
        return status


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ig maintenance", description=__doc__)
    parser.add_argument("--once", action="store_true", help="run one cycle and exit nonzero on failure")
    parser.add_argument("--graph", help="fixed named graph under IG_GRAPH_HOME; defaults to startup selection")
    parser.add_argument("--actions", nargs="+", choices=ACTIONS, default=["refresh", "lifecycle"])
    parser.add_argument("--interval", type=float, default=900, help="seconds after each completed cycle")
    parser.add_argument("--pass-timeout", type=float, default=120)
    parser.add_argument("--lock-timeout", type=float, default=30)
    parser.add_argument("--limit", type=int, default=50, help="lifecycle transitions / consolidation source events")
    parser.add_argument("--max-records", type=int, default=10000, help="input ceiling per record family")
    parser.add_argument("--max-input-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--extract-model", action="store_true", help="explicitly enable structured model consolidation")
    parser.add_argument("--model-timeout", type=float, default=30)
    parser.add_argument("--threshold", type=int, default=1)
    parser.add_argument("--min-age-days", type=float, default=1)
    parser.add_argument("--min-count", type=int, default=1)
    opts = parser.parse_args(args)
    try:
        if os.name != "posix":
            raise ValueError("maintenance currently supports Linux/macOS local filesystems")
        if opts.graph and namespaces.home() is None:
            raise ValueError("--graph requires IG_GRAPH_HOME")
        config = MaintenanceConfig(
            graph=opts.graph or namespaces.selected(), actions=tuple(opts.actions),
            interval=opts.interval, pass_timeout=opts.pass_timeout, lock_timeout=opts.lock_timeout,
            limit=opts.limit, max_records=opts.max_records, max_input_bytes=opts.max_input_bytes,
            extract_model=opts.extract_model, model_timeout=opts.model_timeout,
            consolidation=ConsolidationConfig(threshold=opts.threshold, min_age_days=opts.min_age_days,
                                              min_count=opts.min_count, limit=opts.limit))
        if config.extract_model:
            _model(config)  # validate configured opt-in before the first pass
    except ValueError as exc:
        parser.error(str(exc))
    worker = MaintenanceWorker(config)

    def shutdown(signum: int, frame: object) -> None:
        worker.stop.set()

    previous = {sig: signal.signal(sig, shutdown) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        raise SystemExit(worker.run(once=opts.once))
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()

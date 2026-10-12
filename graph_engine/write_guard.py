"""Advisory local writer coordination; never a multi-file transaction.

Order: the existing process-wide thread RLock, then the per-brain OS lock.
Nested calls, including different Brain instances, reuse the held descriptor.
The file is permanent: unlinking it would let two writers lock different inodes.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import errno
import hashlib
import inspect
import math
import os
import signal
from pathlib import Path
import sys
import subprocess
import threading
import time
from typing import Callable, Iterator, ParamSpec, TypeVar

THREAD_LOCK = threading.RLock()
_HELD: dict[str, int] = {}
_GIT_DEADLINE: ContextVar[float | None] = ContextVar("ig_git_deadline", default=None)
P = ParamSpec("P")
T = TypeVar("T")


class BrainWriteTimeout(RuntimeError):
    """Another local writer did not finish within the configured wait."""


def canonical_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def lock_path(path: str | Path) -> Path:
    path = canonical_path(path)
    # macOS commonly has a case-insensitive, Unicode-normalizing filesystem.
    # Conservative folding also serializes distinct case-sensitive names there.
    import unicodedata
    identity = str(path)
    if sys.platform in ("darwin", "win32"):
        identity = unicodedata.normalize("NFD", identity).casefold()
    digest = hashlib.sha256(os.fsencode(identity)).hexdigest()
    return path.parent / (".graph-engine-write-" + digest + ".lock")


def _try_lock(fd: int) -> None:
    if os.name == "posix":
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    elif os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        raise RuntimeError("Brain write coordination requires POSIX flock or Windows byte locks")


def _unlock(fd: int) -> None:
    if os.name == "posix":
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
    else:
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextmanager
def write_guard(path: str | Path, timeout: float | None = None) -> Iterator[None]:
    from .brain_engine import write_lock_timeout_from_env
    timeout = write_lock_timeout_from_env() if timeout is None else float(timeout)
    if not math.isfinite(timeout) or not 0 <= timeout <= 3600:
        raise ValueError("Write lock timeout must be finite and between 0 and 3600 seconds")
    lock = lock_path(path)
    identity = lock.name
    deadline = time.monotonic() + timeout

    def busy() -> BrainWriteTimeout:
        return BrainWriteTimeout(
            f"Brain writer busy: {canonical_path(path)} (waited up to {timeout:g}s). "
            "Wait for the CLI/server/MCP writer to finish and retry, or increase "
            "IG_WRITE_LOCK_TIMEOUT. Do not delete the lock file.")

    if not THREAD_LOCK.acquire(timeout=timeout):
        raise busy()
    fd = None
    try:
        if identity in _HELD:
            yield
            return
        if _HELD:
            raise RuntimeError("Nested writes to different brains are unsupported; finish the first operation")
        lock.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock, flags, 0o600)
        os.set_inheritable(fd, False)
        if os.name == "nt" and os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        while True:
            try:
                _try_lock(fd)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise busy() from None
                time.sleep(min(0.05, remaining))
        _HELD[identity] = fd
        try:
            yield
        finally:
            del _HELD[identity]
            _unlock(fd)
    finally:
        if fd is not None:
            os.close(fd)
        THREAD_LOCK.release()


def write_operation(function: Callable[P, T]) -> Callable[P, T]:
    """Guard a complete Brain/BrainEngine operation, including its commit.

    Low-level writes are guarded too, but custom read-modify-write batches
    must hold brain.write_guard() from their first read through final sync.
    """
    first_parameter = next(iter(inspect.signature(function).parameters))

    @wraps(function)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> T:
        owner = args[0] if args else kwargs[first_parameter]
        brain = getattr(owner, "brain", owner)
        if kwargs.get("dry_run", False):
            return function(*args, **kwargs)
        with brain.write_guard():
            return function(*args, **kwargs)
    return guarded


@contextmanager
def git_deadline(deadline: float) -> Iterator[None]:
    """Bound worker Git subprocesses, including their descendants, to a pass."""
    token = _GIT_DEADLINE.set(deadline)
    try:
        yield
    finally:
        _GIT_DEADLINE.reset(token)


def run_git(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Keep POSIX Git children inside the guard even if their parent dies.

    Ordinary model/worker children do not inherit the lock. Git is the sole
    exception because it can continue changing the index after parent death.
    """
    if os.name == "posix" and _HELD:
        kwargs["pass_fds"] = tuple(_HELD.values())
    deadline = _GIT_DEADLINE.get()
    if deadline is not None:
        timeout = min(kwargs.pop("timeout", float("inf")), max(0, deadline - time.monotonic()))
        check = kwargs.pop("check", False)
        if kwargs.pop("capture_output", False):
            kwargs["stdout"], kwargs["stderr"] = subprocess.PIPE, subprocess.PIPE
        # Worker logs expose only redacted summaries. Commands such as add and
        # commit do not request capture; their diagnostics/hooks must not inherit
        # the worker's streams (and discarding avoids unbounded hook capture).
        for stream in ("stdout", "stderr"):
            if kwargs.get(stream) is None:
                kwargs[stream] = subprocess.DEVNULL
        kwargs["start_new_session"] = True
        with subprocess.Popen(args, **kwargs) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except BaseException:
                # Clean up Git/SSH/hooks before releasing their inherited lock.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.communicate()
                raise
        if check and proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, args, stdout, stderr)
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
    return subprocess.run(args, **kwargs)


def _after_fork() -> None:
    # A child must neither reuse nor retain its parent's flock descriptor.
    # Close without LOCK_UN: the parent still owns the open-file description.
    for fd in _HELD.values():
        os.close(fd)
    _HELD.clear()
    THREAD_LOCK._at_fork_reinit()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)

"""Cross-process mutation lock for catalogue / state / scores / history writes.

Stdlib only (no filelock dependency). Windows uses ``msvcrt.locking``; POSIX
uses ``fcntl.flock``. See ADR-24.
"""

from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

__all__ = ["MutationLockTimeout", "mutation_lock", "project_mutation_lock"]

_LOCK_NAME = ".mutation.lock"
_DEFAULT_TIMEOUT_S = 600.0
_POLL_S = 0.05

# Per-thread held paths: flock/msvcrt locks are not re-entrant, so a nested
# acquire in the same thread must not block on itself.
_held = threading.local()


class MutationLockTimeout(TimeoutError):
    """Raised when the mutation lock cannot be acquired within the timeout."""


def project_mutation_lock(
    cfg,
    *,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Iterator[None]:
    """Lock file under ``cfg.state_root() / .mutation.lock``."""
    root = cfg.state_root()
    root.mkdir(parents=True, exist_ok=True)
    return mutation_lock(root / _LOCK_NAME, timeout_s=timeout_s)


@contextmanager
def mutation_lock(
    lock_path: Path,
    *,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Iterator[None]:
    """Exclusive cross-process lock; blocks until acquired or *timeout_s*."""
    path = Path(lock_path)
    held = getattr(_held, "paths", None)
    if held is None:
        held = _held.paths = {}
    key = str(path.resolve())
    if held.get(key, 0) > 0:
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Open+create without truncating so a concurrent holder keeps the handle.
    fh = path.open("a+b")
    deadline = time.monotonic() + max(0.0, timeout_s)
    locked = False
    try:
        while True:
            if _try_lock(fh):
                locked = True
                held[key] = 1
                break
            if time.monotonic() >= deadline:
                raise MutationLockTimeout(
                    f"timed out after {timeout_s:.0f}s waiting for {path}"
                )
            time.sleep(_POLL_S)
        yield
    finally:
        if locked:
            held.pop(key, None)
            _unlock(fh)
        fh.close()


def _try_lock(fh) -> bool:
    if sys.platform == "win32":
        import msvcrt

        try:
            fh.seek(0, 2)
            if fh.tell() == 0:
                fh.write(b"\0")
                fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    import fcntl

    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fh) -> None:
    if sys.platform == "win32":
        import msvcrt

        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return

    import fcntl

    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass

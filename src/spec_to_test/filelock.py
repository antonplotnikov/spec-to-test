"""A lock around the read-check-write of one saved file, shared by processes and threads.

Saved data (documents, test runs, bug reports) is read, checked and rewritten as a whole. Without a
lock two writers can both check the same version, and the second write then replaces the first one
silently. Holding this lock across the check and the write closes that window.

- POSIX: fcntl.flock on a lock file next to the target. Each acquisition opens its own file
  description, so the lock also excludes threads of one process. The operating system releases it
  when the holder exits, so a crash never leaves a stale lock behind.
- Windows: msvcrt.locking on the first byte of the lock file, retried until the timeout.
- Anything else: no lock. The saved data is then only protected by the conflict check itself.

Locks are never deleted, which avoids the race of deleting a lock file another process is waiting on.
"""

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

LOCK_TIMEOUT_S = 10.0
_POLL_S = 0.01


class LockBusy(OSError):
    """The file stayed locked by another writer for the whole timeout."""


def lock_path_for(target: Path) -> Path:
    return target.with_name(f".{target.name}.lock")


def _try_lock(fd: int) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False
    if msvcrt is not None:  # pragma: no cover - Windows only
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    return True  # no locking available on this platform


def _unlock(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
    elif msvcrt is not None:  # pragma: no cover - Windows only
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextmanager
def locked(target: Path, timeout: float | None = None) -> Iterator[None]:
    """Hold the lock of `target` (the file that is read, checked and written). Raises LockBusy on timeout."""
    timeout = LOCK_TIMEOUT_S if timeout is None else timeout
    lock = lock_path_for(target)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise LockBusy(f"{target.name} is locked by another writer")
            time.sleep(_POLL_S)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)

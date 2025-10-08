from __future__ import annotations

import os
import time
from contextlib import AbstractContextManager
from pathlib import Path
from typing import IO

from .exceptions import FileLockTimeout


class FileLock(AbstractContextManager["FileLock"]):
    """Very small cross-platform file lock using advisory locking."""

    def __init__(self, target_path: Path, *, timeout: float = 10.0, poll_interval: float = 0.1) -> None:
        self.lock_path = Path(f"{target_path}.lock")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._handle: IO[str] | None = None

    def acquire(self) -> None:
        start = time.monotonic()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                handle = self.lock_path.open("a+")
                _acquire(handle)
                self._handle = handle
                return
            except BlockingIOError:
                handle.close()
            except OSError as exc:  # pragma: no cover - defensive
                handle.close()
                raise FileLockTimeout(f"Failed to acquire lock {self.lock_path}: {exc}") from exc

            if time.monotonic() - start > self.timeout:
                raise FileLockTimeout(f"Timed out waiting for lock {self.lock_path}")
            time.sleep(self.poll_interval)

    def release(self) -> None:
        if not self._handle:
            return
        try:
            _release(self._handle)
        finally:
            self._handle.close()
            self._handle = None
            try:
                self.lock_path.unlink(missing_ok=True)
            except AttributeError:  # pragma: no cover
                # Python 3.10 compat; not exercised but kept for clarity.
                try:
                    self.lock_path.unlink()
                except FileNotFoundError:
                    pass

    # Context manager protocol -------------------------------------------------

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def _acquire(handle: IO[str]) -> None:
    if os.name == "posix":
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:  # pragma: no cover - Windows path, not exercised on CI
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)


def _release(handle: IO[str]) -> None:
    if os.name == "posix":
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    else:  # pragma: no cover - Windows path, not exercised on CI
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

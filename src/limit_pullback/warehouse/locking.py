"""Advisory write lock serializing warehouse bootstrap/update runs."""

from __future__ import annotations

import fcntl
from pathlib import Path


class WarehouseLock:
    """Exclusive advisory lock on ``data/.warehouse.lock``.

    Concurrent bootstrap/update processes would otherwise race on the same
    raw-file paths and temporary files; the lock serializes all write
    pipelines per warehouse root. Read-only commands (status/validate) do
    not take the lock.
    """

    def __init__(self, lock_path: str | Path) -> None:
        self.lock_path = Path(lock_path)

    def __enter__(self) -> "WarehouseLock":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    def acquire(self, *, nonblocking: bool = False) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.lock_path.open("a+")
        flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
        fcntl.flock(self._file.fileno(), flags)

    def release(self) -> None:
        if not hasattr(self, "_file"):
            return
        fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        self._file.close()
        del self._file

"""Cross-process advisory lockfile.

Threat model
------------
Two RabbitSync instances launched against the same ``data/`` directory would
race on the SQLite WAL, journal files, and snapshot writes. Even though SQLite
itself is multi-process safe, the higher-level invariants RabbitSync maintains
(no two syncs touching the same pair, retention sweeps not concurrent with
backups, etc.) require a single instance.

This lock is *advisory* — it cannot prevent a process that ignores the file
from running. RabbitSync code paths take the lock at app startup; if they
can't, they refuse to launch with a clear message naming the holder PID.

Implementation
--------------
On Windows the lock uses ``msvcrt.locking`` for an OS-level byte-range lock on
the lockfile. The PID and start-time are written to the file content for
diagnostic display. Releasing is automatic on process exit (Windows clears the
lock when the file handle closes).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import TracebackType
from typing import IO

from rabbitsync.paths import lock_file


class LockHeldError(RuntimeError):
    """Raised when the lockfile is held by another process."""

    def __init__(self, path: Path, holder_pid: int | None, holder_started_at: str | None) -> None:
        if holder_pid is not None:
            msg = (
                f"RabbitSync is already running (pid {holder_pid}, started "
                f"{holder_started_at}). Lockfile: {path}. "
                "Close the other instance, or if it crashed, delete the lockfile."
            )
        else:
            msg = f"Could not acquire lockfile {path} (locked by another process)."
        super().__init__(msg)
        self.path = path
        self.holder_pid = holder_pid


class AppLock:
    """Context manager for the global app-instance lock.

    Usage::

        with AppLock():
            run_app()
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path = path if path is not None else lock_file()
        self._fh: IO[str] | None = None

    def __enter__(self) -> AppLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Open the file for read+write; create if missing.
        fh = open(self._path, "a+", encoding="utf-8")  # noqa: SIM115 -- handle held in self
        try:
            _platform_lock(fh)
        except OSError as exc:
            fh.seek(0)
            existing = fh.read().strip()
            fh.close()
            holder_pid, started_at = _parse_holder(existing)
            raise LockHeldError(self._path, holder_pid, started_at) from exc
        # Truncate and write our identity.
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid={os.getpid()}\nstarted_at={_now_iso()}\n")
        fh.flush()
        self._fh = fh

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            _platform_unlock(self._fh)
        finally:
            self._fh.close()
            self._fh = None


def _now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


def _parse_holder(content: str) -> tuple[int | None, str | None]:
    pid: int | None = None
    started_at: str | None = None
    for line in content.splitlines():
        if line.startswith("pid="):
            try:
                pid = int(line[4:])
            except ValueError:
                pass
        elif line.startswith("started_at="):
            started_at = line[len("started_at=") :]
    return pid, started_at


# Platform-specific locking implementations --------------------------------

if sys.platform == "win32":
    import msvcrt

    def _platform_lock(fh: IO[str]) -> None:
        # Lock the first byte non-blocking. msvcrt requires a positive length.
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)

    def _platform_unlock(fh: IO[str]) -> None:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:  # POSIX fallback (CI, tests on Linux/macOS)
    import fcntl

    def _platform_lock(fh: IO[str]) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _platform_unlock(fh: IO[str]) -> None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


# Convenience: identify whether we currently hold the lock (used by tests).
def is_locked_by(path: Path | None = None) -> int | None:
    """If the lockfile names a holder, return the PID; else ``None``.

    Does not attempt to acquire the lock.
    """
    p = path if path is not None else lock_file()
    if not p.exists():
        return None
    try:
        content = p.read_text(encoding="utf-8")
    except OSError:
        return None
    pid, _ = _parse_holder(content)
    return pid


__all__ = ["AppLock", "LockHeldError", "is_locked_by"]


# Suppress unused-import warning on POSIX builds where time isn't referenced.
_ = time

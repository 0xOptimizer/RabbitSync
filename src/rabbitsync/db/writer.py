"""Single dedicated writer thread for the SQLite database.

Why a dedicated writer
----------------------
SQLite WAL allows many concurrent readers but only one writer at a time. If
multiple QThread workers attempt writes concurrently they'll trip the busy
timeout and surface as ``database is locked``. Funneling every mutation
through one queue eliminates that class of error and makes write ordering
trivially observable.

Usage
-----

    writer = DbWriter()
    writer.start()
    fut = writer.submit(lambda conn: conn.execute("INSERT ..."))
    fut.result()  # blocks for the result
    writer.shutdown()

Mutations are arbitrary callables ``(conn) -> Any``. The writer runs them
sequentially on its own thread; exceptions are propagated through the future.
Each callable is responsible for its own transaction control if it needs more
than auto-commit semantics.
"""

from __future__ import annotations

import queue
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, TypeVar

from rabbitsync.db.connection import ConnectionFactory

_T = TypeVar("_T")

_Job = tuple[Callable[[sqlite3.Connection], Any], "Future[Any]"]
_SHUTDOWN: object = object()


class DbWriter:
    """Owns the writable SQLite connection on a dedicated thread."""

    def __init__(self, factory: ConnectionFactory | None = None) -> None:
        self._factory = factory if factory is not None else ConnectionFactory()
        self._queue: queue.Queue[_Job | object] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run,
            name="rabbitsync-db-writer",
            daemon=True,
        )
        self._started = False
        self._stopped = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._thread.start()

    def submit(self, fn: Callable[[sqlite3.Connection], _T]) -> Future[_T]:
        """Queue a mutation; return a future that resolves with its result."""
        if not self._started:
            raise RuntimeError("DbWriter.submit called before start()")
        if self._stopped:
            raise RuntimeError("DbWriter is shutting down; no new submissions accepted")
        fut: Future[_T] = Future()
        self._queue.put((fn, fut))
        return fut

    def execute(self, fn: Callable[[sqlite3.Connection], _T]) -> _T:
        """Submit a mutation and wait for the result. Convenience wrapper."""
        return self.submit(fn).result()

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            if not self._started or self._stopped:
                return
            self._stopped = True
        self._queue.put(_SHUTDOWN)
        if wait:
            self._thread.join()

    # Internal thread loop ------------------------------------------------

    def _run(self) -> None:
        conn = self._factory.writer()
        try:
            while True:
                item = self._queue.get()
                if item is _SHUTDOWN:
                    break
                assert isinstance(item, tuple)
                fn, fut = item
                if fut.cancelled():
                    continue
                try:
                    result = fn(conn)
                except BaseException as exc:  # noqa: BLE001 -- propagate everything
                    fut.set_exception(exc)
                else:
                    fut.set_result(result)
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass


__all__ = ["DbWriter"]

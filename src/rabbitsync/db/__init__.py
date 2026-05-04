"""SQLite-backed structured persistence for RabbitSync.

All structured state (pairs, syncs, journal entries, receipts, file cache,
pipelines, GitHub repo cache, credential references) lives in a single
``data/rabbitsync.db`` opened in WAL mode. Large blobs (snapshots, quarantined
files, pipeline captures, log files) live on the filesystem and are referenced
from rows in the ``blobs`` table.

Concurrency model
-----------------
A single dedicated writer thread owns the writable connection; UI and worker
threads enqueue mutations through :class:`db.writer.DbWriter`. Reader threads
open their own short-lived read-only connections (WAL allows them to run
unblocked by the writer). This eliminates ``database is locked`` errors at
the source.
"""

from __future__ import annotations

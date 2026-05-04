"""Syncs repository — lifecycle of a sync record."""

from __future__ import annotations

import datetime as _dt
import sqlite3
import uuid

from rabbitsync.db.connection import ConnectionFactory, closing
from rabbitsync.db.writer import DbWriter


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="milliseconds")


def begin(writer: DbWriter, *, pair_id: str) -> str:
    """Insert a new sync row in 'running' state, return its sync_id."""
    sync_id = str(uuid.uuid4())
    started = _now()

    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO syncs "
            "(sync_id, pair_id, started_at, status, files_added, files_modified, files_quarantined) "
            "VALUES (?, ?, ?, 'running', 0, 0, 0);",
            (sync_id, pair_id, started),
        )

    writer.execute(_do)
    return sync_id


def attach_snapshot(writer: DbWriter, *, sync_id: str, snapshot_blob_id: int) -> None:
    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE syncs SET snapshot_blob_id = ? WHERE sync_id = ?;",
            (snapshot_blob_id, sync_id),
        )

    writer.execute(_do)


def finalize(
    writer: DbWriter,
    *,
    sync_id: str,
    status: str,
    files_added: int = 0,
    files_modified: int = 0,
    files_quarantined: int = 0,
    source_sha: str | None = None,
    copy_commit_sha: str | None = None,
) -> None:
    """Mark a sync as finished (status: 'ok' | 'aborted' | 'failed')."""
    finished = _now()

    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE syncs SET status = ?, finished_at = ?, "
            "files_added = ?, files_modified = ?, files_quarantined = ?, "
            "source_sha = ?, copy_commit_sha = ? "
            "WHERE sync_id = ?;",
            (
                status, finished,
                int(files_added), int(files_modified), int(files_quarantined),
                source_sha, copy_commit_sha,
                sync_id,
            ),
        )

    writer.execute(_do)


def get_status(sync_id: str, *, factory: ConnectionFactory | None = None) -> str | None:
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        row = conn.execute(
            "SELECT status FROM syncs WHERE sync_id = ?;", (sync_id,),
        ).fetchone()
    return row["status"] if row else None


def list_for_pair(
    pair_id: str, *, limit: int = 100, factory: ConnectionFactory | None = None,
) -> list[sqlite3.Row]:
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        rows = conn.execute(
            "SELECT * FROM syncs WHERE pair_id = ? "
            "ORDER BY started_at DESC LIMIT ?;",
            (pair_id, limit),
        ).fetchall()
    return list(rows)


__all__ = ["attach_snapshot", "begin", "finalize", "get_status", "list_for_pair"]

"""``blobs`` table — every on-disk blob has a row, sha256, and size.

Used by :mod:`rabbitsync.core.backup` (snapshots) and
:mod:`rabbitsync.core.quarantine` (soft-deleted user files) so any drift
between the SQLite metadata and the actual file is detectable.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from rabbitsync.db.connection import ConnectionFactory, closing
from rabbitsync.db.writer import DbWriter


@dataclass(frozen=True)
class Blob:
    id: int
    kind: str
    path: Path
    sha256: str
    size: int
    created_at: str


def insert(
    writer: DbWriter,
    *,
    kind: str,
    path: Path,
    sha256: str,
    size: int,
) -> int:
    """Insert a blob row and return its id."""
    ts = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")

    def _do(conn: sqlite3.Connection) -> int:
        cur = conn.execute(
            "INSERT INTO blobs (kind, path, sha256, size, created_at) "
            "VALUES (?, ?, ?, ?, ?);",
            (kind, str(path), sha256, int(size), ts),
        )
        return int(cur.lastrowid or 0)

    return writer.execute(_do)


def get(blob_id: int, *, factory: ConnectionFactory | None = None) -> Blob | None:
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        row = conn.execute(
            "SELECT id, kind, path, sha256, size, created_at FROM blobs WHERE id = ?;",
            (blob_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_blob(row)


def list_by_kind(kind: str, *, factory: ConnectionFactory | None = None) -> list[Blob]:
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        rows = conn.execute(
            "SELECT id, kind, path, sha256, size, created_at FROM blobs "
            "WHERE kind = ? ORDER BY created_at DESC;",
            (kind,),
        ).fetchall()
    return [_row_to_blob(r) for r in rows]


def delete(blob_id: int, writer: DbWriter) -> None:
    """Delete the row only — caller is responsible for the on-disk file."""

    def _do(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM blobs WHERE id = ?;", (blob_id,))

    writer.execute(_do)


def _row_to_blob(row: sqlite3.Row) -> Blob:
    return Blob(
        id=int(row["id"]),
        kind=row["kind"],
        path=Path(row["path"]),
        sha256=row["sha256"],
        size=int(row["size"]),
        created_at=row["created_at"],
    )


__all__ = ["Blob", "delete", "get", "insert", "list_by_kind"]

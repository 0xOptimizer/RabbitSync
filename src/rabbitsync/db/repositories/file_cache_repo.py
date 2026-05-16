"""file_cache repository — memoize xxh64 content hashes by (size, mtime_ns).

The ``file_cache`` table stores one row per ``(pair_id, side, rel_path)``.
``diff()`` consults it before hashing a "suspect" file (same size, different
mtime): when ``(size, mtime_ns)`` matches the cached row, the stored
``content_hash`` is reused and the file is never re-read from disk.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3

from rabbitsync.db.connection import ConnectionFactory, closing
from rabbitsync.db.writer import DbWriter


CachedEntry = tuple[int, int, str | None]  # (size, mtime_ns, content_hash)


def load_for_side(
    pair_id: str,
    side: str,
    *,
    factory: ConnectionFactory | None = None,
) -> dict[str, CachedEntry]:
    """Return ``{rel_path: (size, mtime_ns, content_hash)}`` for one side.

    Includes rows whose ``content_hash`` is NULL (size/mtime-only entries).
    Callers that need a hash should check for ``None`` explicitly.
    """
    f = factory if factory is not None else ConnectionFactory()
    out: dict[str, CachedEntry] = {}
    with closing(f.reader()) as conn:
        rows = conn.execute(
            "SELECT rel_path, size, mtime_ns, content_hash "
            "FROM file_cache WHERE pair_id = ? AND side = ?;",
            (pair_id, side),
        ).fetchall()
    for row in rows:
        out[row["rel_path"]] = (
            int(row["size"]),
            int(row["mtime_ns"]),
            row["content_hash"],
        )
    return out


def upsert_hashes(
    writer: DbWriter,
    *,
    pair_id: str,
    side: str,
    entries: list[tuple[str, int, int, str]],
) -> None:
    """Bulk insert/replace ``(rel_path, size, mtime_ns, content_hash)`` rows.

    No-op on empty input. Wrapped in a single transaction.
    """
    if not entries:
        return
    now = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    payload = [
        (pair_id, side, rel_path, size, mtime_ns, content_hash, now)
        for (rel_path, size, mtime_ns, content_hash) in entries
    ]

    def _do(conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE;")
        try:
            conn.executemany(
                "INSERT INTO file_cache "
                "(pair_id, side, rel_path, size, mtime_ns, content_hash, last_seen_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(pair_id, side, rel_path) DO UPDATE SET "
                "  size = excluded.size, "
                "  mtime_ns = excluded.mtime_ns, "
                "  content_hash = excluded.content_hash, "
                "  last_seen_ts = excluded.last_seen_ts;",
                payload,
            )
            conn.execute("COMMIT;")
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except sqlite3.OperationalError:
                pass
            raise

    writer.execute(_do)


__all__ = ["CachedEntry", "load_for_side", "upsert_hashes"]

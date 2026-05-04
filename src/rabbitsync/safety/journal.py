"""Crash-recovery journal — durable record of every sync step.

The journal is the single source of truth for what a sync was doing when it
was interrupted. Each step is appended as a row in the ``journal_entries``
table with ``synchronous=FULL`` semantics (set on the writer connection in
:mod:`rabbitsync.db.connection`), so a row that returns from INSERT is
durable on disk before the file op it describes runs.

Recovery, on next app start
---------------------------
The :func:`open_unfinished_syncs` function returns sync IDs that have a row
in ``syncs`` with ``status='running'`` and journal entries but no ``close``
entry. The UI surfaces a Resume / Rollback prompt for each.

This module is the API surface; actual mutation routes through the DB
writer thread (every state-changing call is a small lambda submitted to
:class:`rabbitsync.db.writer.DbWriter`).
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from rabbitsync.db.writer import DbWriter


@dataclass(frozen=True)
class JournalEntry:
    """One row in ``journal_entries`` (read-only view)."""

    sync_id: str
    seq: int
    action: str
    rel_path: str | None
    prev_hash: str | None
    new_hash: str | None
    ts: str
    extra: dict[str, object]


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="milliseconds")


def append(
    writer: DbWriter,
    *,
    sync_id: str,
    action: str,
    rel_path: str | None = None,
    prev_hash: str | None = None,
    new_hash: str | None = None,
    extra: dict[str, object] | None = None,
) -> int:
    """Append one journal entry. Returns the assigned ``seq`` number.

    Synchronously waits on the writer to confirm durability before returning.
    """
    extra_json = json.dumps(extra or {}, sort_keys=True)
    ts = _now()

    def _insert(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM journal_entries WHERE sync_id = ?;",
            (sync_id,),
        ).fetchone()
        next_seq = (row[0] or 0) + 1
        conn.execute(
            "INSERT INTO journal_entries "
            "(sync_id, seq, action, rel_path, prev_hash, new_hash, ts, extra_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
            (sync_id, next_seq, action, rel_path, prev_hash, new_hash, ts, extra_json),
        )
        return int(next_seq)

    return writer.execute(_insert)


def entries_for(writer: DbWriter, sync_id: str) -> tuple[JournalEntry, ...]:
    """Return every entry for a sync, ordered by seq."""

    def _select(conn: sqlite3.Connection) -> list[sqlite3.Row]:
        return list(
            conn.execute(
                "SELECT sync_id, seq, action, rel_path, prev_hash, new_hash, ts, extra_json "
                "FROM journal_entries WHERE sync_id = ? ORDER BY seq;",
                (sync_id,),
            )
        )

    rows = writer.execute(_select)
    out: list[JournalEntry] = []
    for r in rows:
        out.append(
            JournalEntry(
                sync_id=r["sync_id"],
                seq=int(r["seq"]),
                action=r["action"],
                rel_path=r["rel_path"],
                prev_hash=r["prev_hash"],
                new_hash=r["new_hash"],
                ts=r["ts"],
                extra=_safe_json(r["extra_json"]),
            )
        )
    return tuple(out)


def open_unfinished_syncs(writer: DbWriter) -> tuple[str, ...]:
    """Return sync IDs whose journal has no ``close`` entry.

    Used by the startup recovery prompt: each ID listed here represents a
    sync that was interrupted and is awaiting Resume or Rollback.
    """

    def _select(conn: sqlite3.Connection) -> list[sqlite3.Row]:
        return list(
            conn.execute(
                "SELECT s.sync_id FROM syncs s "
                "WHERE s.status = 'running' "
                "  AND NOT EXISTS ( "
                "      SELECT 1 FROM journal_entries j "
                "      WHERE j.sync_id = s.sync_id AND j.action = 'close' "
                "  );"
            )
        )

    return tuple(row["sync_id"] for row in writer.execute(_select))


def _safe_json(text: str | None) -> dict[str, object]:
    if not text:
        return {}
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(result, dict):
        return {}
    return result


def actions_seen(entries: Iterable[JournalEntry]) -> set[str]:
    """Convenience: set of distinct ``action`` values across the entries."""
    return {e.action for e in entries}


__all__ = [
    "JournalEntry",
    "actions_seen",
    "append",
    "entries_for",
    "open_unfinished_syncs",
]

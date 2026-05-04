"""Receipts repository — append-only, hash-chained sync audit log.

Each receipt embeds the previous receipt's hash, so any tampering or disk
corruption surfaces when the chain is re-walked. The "Verify audit log"
button in the UI calls :func:`verify_chain` and reports the first break.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sqlite3
from dataclasses import dataclass

from rabbitsync.db.connection import ConnectionFactory, closing
from rabbitsync.db.writer import DbWriter


@dataclass(frozen=True)
class Receipt:
    sync_id: str
    prev_receipt_hash: str | None
    snapshot_hash: str | None
    journal_hash: str
    payload: dict[str, object]
    hash: str
    created_at: str


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="milliseconds")


def append(
    writer: DbWriter,
    *,
    sync_id: str,
    snapshot_hash: str | None,
    journal_hash: str,
    payload: dict[str, object],
) -> Receipt:
    """Insert a new receipt linked to the prior chain head."""
    payload_json = json.dumps(payload, sort_keys=True)
    created = _now()

    def _do(conn: sqlite3.Connection) -> Receipt:
        prev = conn.execute(
            "SELECT hash FROM receipts ORDER BY created_at DESC LIMIT 1;"
        ).fetchone()
        prev_hash = prev["hash"] if prev else None
        h = _compute_hash(
            prev_hash=prev_hash,
            snapshot_hash=snapshot_hash,
            journal_hash=journal_hash,
            payload_json=payload_json,
            sync_id=sync_id,
        )
        conn.execute(
            "INSERT INTO receipts "
            "(sync_id, prev_receipt_hash, snapshot_hash, journal_hash, payload_json, hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?);",
            (sync_id, prev_hash, snapshot_hash, journal_hash, payload_json, h, created),
        )
        return Receipt(
            sync_id=sync_id,
            prev_receipt_hash=prev_hash,
            snapshot_hash=snapshot_hash,
            journal_hash=journal_hash,
            payload=payload,
            hash=h,
            created_at=created,
        )

    return writer.execute(_do)


def list_all(*, factory: ConnectionFactory | None = None) -> list[Receipt]:
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        rows = conn.execute(
            "SELECT sync_id, prev_receipt_hash, snapshot_hash, journal_hash, "
            "payload_json, hash, created_at FROM receipts ORDER BY created_at;"
        ).fetchall()
    return [_row_to_receipt(r) for r in rows]


def verify_chain(*, factory: ConnectionFactory | None = None) -> tuple[bool, str | None]:
    """Re-walk the chain, return (ok, first_broken_sync_id)."""
    receipts = list_all(factory=factory)
    expected_prev: str | None = None
    for r in receipts:
        if r.prev_receipt_hash != expected_prev:
            return False, r.sync_id
        recomputed = _compute_hash(
            prev_hash=r.prev_receipt_hash,
            snapshot_hash=r.snapshot_hash,
            journal_hash=r.journal_hash,
            payload_json=json.dumps(r.payload, sort_keys=True),
            sync_id=r.sync_id,
        )
        if recomputed != r.hash:
            return False, r.sync_id
        expected_prev = r.hash
    return True, None


def _compute_hash(
    *,
    prev_hash: str | None,
    snapshot_hash: str | None,
    journal_hash: str,
    payload_json: str,
    sync_id: str,
) -> str:
    h = hashlib.sha256()
    h.update((prev_hash or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((snapshot_hash or "").encode("utf-8"))
    h.update(b"\x00")
    h.update(journal_hash.encode("utf-8"))
    h.update(b"\x00")
    h.update(payload_json.encode("utf-8"))
    h.update(b"\x00")
    h.update(sync_id.encode("utf-8"))
    return h.hexdigest()


def _row_to_receipt(row: sqlite3.Row) -> Receipt:
    return Receipt(
        sync_id=row["sync_id"],
        prev_receipt_hash=row["prev_receipt_hash"],
        snapshot_hash=row["snapshot_hash"],
        journal_hash=row["journal_hash"],
        payload=json.loads(row["payload_json"]),
        hash=row["hash"],
        created_at=row["created_at"],
    )


__all__ = ["Receipt", "append", "list_all", "verify_chain"]

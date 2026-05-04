"""Pairs repository — CRUD on the ``pairs`` table."""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import uuid

from rabbitsync.db.connection import ConnectionFactory, closing
from rabbitsync.db.writer import DbWriter
from rabbitsync.models.pair import Pair


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


def create(
    writer: DbWriter,
    *,
    label: str,
    source_path: str,
    copy_path: str,
    source_git_root: str | None = None,
    source_subpath: str | None = None,
    copy_git_root: str | None = None,
    copy_subpath: str | None = None,
    target_branch: str | None = None,
) -> str:
    """Create a new pair, returning its id."""
    pair_id = str(uuid.uuid4())
    now = _now_iso()

    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO pairs ("
            "id, label, source_path, source_git_root, source_subpath, "
            "copy_path, copy_git_root, copy_subpath, target_branch, "
            "ignore_files_json, commit_message_template, auto_push, "
            "sync_check_interval_s, secret_scan_enabled, snapshot_before_pipeline, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', "
            "'sync: {src_branch}@{src_sha} — {n} files', 0, 30, 1, 1, ?, ?);",
            (
                pair_id, label, source_path, source_git_root, source_subpath,
                copy_path, copy_git_root, copy_subpath, target_branch,
                now, now,
            ),
        )

    writer.execute(_do)
    return pair_id


def get(pair_id: str, *, factory: ConnectionFactory | None = None) -> Pair | None:
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        row = conn.execute("SELECT * FROM pairs WHERE id = ?;", (pair_id,)).fetchone()
    return _row_to_pair(row) if row else None


def list_all(*, factory: ConnectionFactory | None = None) -> list[Pair]:
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        rows = conn.execute("SELECT * FROM pairs ORDER BY label;").fetchall()
    return [_row_to_pair(r) for r in rows]


def delete(pair_id: str, writer: DbWriter) -> None:
    def _do(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM pairs WHERE id = ?;", (pair_id,))

    writer.execute(_do)


def _row_to_pair(row: sqlite3.Row) -> Pair:
    return Pair.model_validate(
        {
            "id": row["id"],
            "label": row["label"],
            "source_path": row["source_path"],
            "source_git_root": row["source_git_root"],
            "source_subpath": row["source_subpath"],
            "copy_path": row["copy_path"],
            "copy_git_root": row["copy_git_root"],
            "copy_subpath": row["copy_subpath"],
            "target_branch": row["target_branch"],
            "ignore_files": json.loads(row["ignore_files_json"] or "[]"),
            "commit_message_template": row["commit_message_template"],
            "auto_push": bool(row["auto_push"]),
            "sync_check_interval_s": int(row["sync_check_interval_s"]),
            "secret_scan_enabled": bool(row["secret_scan_enabled"]),
            "snapshot_before_pipeline": bool(row["snapshot_before_pipeline"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


__all__ = ["create", "delete", "get", "list_all"]

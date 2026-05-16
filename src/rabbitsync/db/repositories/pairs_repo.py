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


def update_ui_state(
    writer: DbWriter,
    *,
    pair_id: str,
    commit_on_sync: bool,
    auto_push: bool,
    target_branch: str | None,
) -> None:
    """Persist the Sync-tab toggles for a pair.

    Cheap, idempotent UPDATE — safe to call on every checkbox toggle.
    """
    now = _now_iso()

    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE pairs SET "
            "commit_on_sync = ?, auto_push = ?, target_branch = ?, updated_at = ? "
            "WHERE id = ?;",
            (int(commit_on_sync), int(auto_push), target_branch, now, pair_id),
        )

    writer.execute(_do)


def update_diff_summary(
    writer: DbWriter,
    *,
    pair_id: str,
    adds: int,
    modifies: int,
    quarantines: int,
) -> None:
    """Cache the most recent diff counts on the pair row.

    Used by the UI to show the cards instantly on pair selection while a
    fresh background diff is running. Does not touch updated_at — this is
    metadata, not a user-facing edit.
    """
    now = _now_iso()

    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE pairs SET "
            "last_diff_adds = ?, last_diff_modifies = ?, "
            "last_diff_quarantines = ?, last_diff_at = ? "
            "WHERE id = ?;",
            (int(adds), int(modifies), int(quarantines), now, pair_id),
        )

    writer.execute(_do)


def _row_to_pair(row: sqlite3.Row) -> Pair:
    # Tolerate older rows missing columns from later migrations.
    def _opt(key: str, default):  # noqa: ANN001, ANN202
        try:
            return row[key]
        except (IndexError, KeyError):
            return default

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
            "commit_on_sync": bool(_opt("commit_on_sync", 1)),
            "sync_check_interval_s": int(row["sync_check_interval_s"]),
            "secret_scan_enabled": bool(row["secret_scan_enabled"]),
            "snapshot_before_pipeline": bool(row["snapshot_before_pipeline"]),
            "last_diff_adds": int(_opt("last_diff_adds", 0)),
            "last_diff_modifies": int(_opt("last_diff_modifies", 0)),
            "last_diff_quarantines": int(_opt("last_diff_quarantines", 0)),
            "last_diff_at": _opt("last_diff_at", None),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


__all__ = ["create", "delete", "get", "list_all", "update_diff_summary", "update_ui_state"]

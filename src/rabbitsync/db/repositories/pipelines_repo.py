"""Pipeline definitions + run history queries."""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from rabbitsync.db.connection import ConnectionFactory, closing
from rabbitsync.db.writer import DbWriter


@dataclass(frozen=True)
class PipelineRow:
    id: int
    pair_id: str
    name: str
    pre_sync: bool
    post_sync: bool


@dataclass(frozen=True)
class StepRow:
    id: int
    pipeline_id: int
    ordinal: int
    name: str
    argv: list[str]
    cwd_kind: str
    cwd_subpath: str | None
    env_extra: dict[str, str]
    timeout_s: int
    on_fail: str
    inputs_globs: list[str]


def list_pipelines(
    pair_id: str, *, factory: ConnectionFactory | None = None,
) -> list[PipelineRow]:
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        rows = conn.execute(
            "SELECT id, pair_id, name, pre_sync, post_sync FROM pipelines "
            "WHERE pair_id = ? ORDER BY ordinal, name;",
            (pair_id,),
        ).fetchall()
    return [PipelineRow(
        id=int(r["id"]), pair_id=r["pair_id"], name=r["name"],
        pre_sync=bool(r["pre_sync"]), post_sync=bool(r["post_sync"]),
    ) for r in rows]


def steps_for(
    pipeline_id: int, *, factory: ConnectionFactory | None = None,
) -> list[StepRow]:
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        rows = conn.execute(
            "SELECT id, pipeline_id, ordinal, name, argv_json, cwd_kind, cwd_subpath, "
            "env_extra_json, timeout_s, on_fail, inputs_globs_json "
            "FROM pipeline_steps WHERE pipeline_id = ? ORDER BY ordinal;",
            (pipeline_id,),
        ).fetchall()
    out: list[StepRow] = []
    for r in rows:
        out.append(StepRow(
            id=int(r["id"]),
            pipeline_id=int(r["pipeline_id"]),
            ordinal=int(r["ordinal"]),
            name=r["name"],
            argv=_safe_list(r["argv_json"]),
            cwd_kind=r["cwd_kind"],
            cwd_subpath=r["cwd_subpath"],
            env_extra=_safe_dict(r["env_extra_json"]),
            timeout_s=int(r["timeout_s"]),
            on_fail=r["on_fail"],
            inputs_globs=_safe_list(r["inputs_globs_json"]),
        ))
    return out


def last_run_for(
    pipeline_id: int, *, factory: ConnectionFactory | None = None,
) -> tuple[str, str] | None:
    """Return ``(status, finished_at)`` of the most recent run, or None."""
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        row = conn.execute(
            "SELECT status, finished_at FROM pipeline_runs WHERE pipeline_id = ? "
            "ORDER BY started_at DESC LIMIT 1;",
            (pipeline_id,),
        ).fetchone()
    if row is None:
        return None
    return (row["status"], row["finished_at"] or "")


def delete_pipeline(writer: DbWriter, *, pipeline_id: int) -> None:
    def _do(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM pipelines WHERE id = ?;", (pipeline_id,))

    writer.execute(_do)


def set_hook(writer: DbWriter, *, pipeline_id: int, kind: str, on: bool) -> None:
    """Mark a pipeline as pre-sync or post-sync (or unset)."""
    if kind not in {"pre_sync", "post_sync"}:
        raise ValueError(f"unknown hook kind: {kind}")
    column = kind  # column name matches argument

    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            f"UPDATE pipelines SET {column} = ? WHERE id = ?;",
            (1 if on else 0, pipeline_id),
        )

    writer.execute(_do)


def begin_run(
    writer: DbWriter,
    *,
    pipeline_id: int,
    triggered_as: str,
    artifacts_dir: Path,
    sync_id: str | None = None,
) -> str:
    """Insert a pipeline_runs row in 'running' state, return run_id."""
    run_id = str(uuid.uuid4())
    started = _now()

    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO pipeline_runs "
            "(run_id, pipeline_id, sync_id, triggered_as, started_at, status, artifacts_dir) "
            "VALUES (?, ?, ?, ?, ?, 'running', ?);",
            (run_id, pipeline_id, sync_id, triggered_as, started, str(artifacts_dir)),
        )

    writer.execute(_do)
    return run_id


def finalize_run(
    writer: DbWriter,
    *,
    run_id: str,
    status: str,
) -> None:
    finished = _now()

    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE pipeline_runs SET status = ?, finished_at = ? WHERE run_id = ?;",
            (status, finished, run_id),
        )

    writer.execute(_do)


def _safe_list(text: str | None) -> list[str]:
    if not text:
        return []
    try:
        v = json.loads(text)
        return [str(x) for x in v] if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _safe_dict(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    try:
        v = json.loads(text)
        return {str(k): str(val) for k, val in v.items()} if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="milliseconds")


__all__ = [
    "PipelineRow", "StepRow",
    "begin_run", "delete_pipeline", "finalize_run",
    "last_run_for", "list_pipelines", "set_hook", "steps_for",
]

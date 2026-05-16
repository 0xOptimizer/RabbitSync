"""App settings — persisted as key/value rows in the ``settings`` table."""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from dataclasses import asdict, dataclass

from rabbitsync.db.connection import ConnectionFactory, closing
from rabbitsync.db.writer import DbWriter

_KEY = "app.settings.v1"


@dataclass
class Settings:
    theme: str = "dark"
    reduce_motion: bool = False
    snapshot_keep_count: int = 10
    snapshot_keep_days: int = 30
    snapshot_max_gb: int = 5
    log_keep_files: int = 7
    default_commit_on_sync: bool = True
    default_auto_push: bool = False
    sync_check_interval_s: int = 30
    diff_sample_rate: float = 0.01
    allow_elevated_pipelines: bool = False
    last_pair_id: str | None = None


def load_settings(*, factory: ConnectionFactory | None = None) -> Settings:
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?;", (_KEY,)).fetchone()
    if row is None:
        return Settings()
    try:
        data = json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    return Settings(**{k: v for k, v in data.items() if k in Settings.__annotations__})


def save_settings(writer: DbWriter, settings: Settings) -> None:
    payload = json.dumps(asdict(settings), sort_keys=True)
    ts = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")

    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at;",
            (_KEY, payload, ts),
        )

    writer.execute(_do)


__all__ = ["Settings", "load_settings", "save_settings"]

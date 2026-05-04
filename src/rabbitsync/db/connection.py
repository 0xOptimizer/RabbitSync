"""SQLite connection factory and migration runner.

Every connection is configured with WAL journal mode, ``foreign_keys = ON``,
and a sensible busy-timeout. The writer connection additionally sets
``synchronous = FULL`` so per-row fsync semantics hold during sync journal
writes.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from rabbitsync.paths import db_path

# Bump this when schemas change beyond what additive migrations cover.
APP_DB_VERSION = 1


class ConnectionFactory:
    """Builds SQLite connections with the right pragmas for each role."""

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path = path if path is not None else db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def writer(self) -> sqlite3.Connection:
        """Open the single writable connection.

        Caller is responsible for keeping at most one of these alive at a time;
        :class:`db.writer.DbWriter` enforces that contract.
        """
        conn = self._connect()
        conn.execute("PRAGMA synchronous = FULL;")
        return conn

    def reader(self) -> sqlite3.Connection:
        """Open a read-only connection.

        SQLite's WAL allows readers to run unblocked by the writer.
        """
        conn = self._connect()
        # Even on a 'reader', pragmas like cache_size are useful.
        conn.execute("PRAGMA query_only = ON;")
        return conn

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._path,
            isolation_level=None,  # we manage transactions explicitly
            check_same_thread=False,
            timeout=30.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        return conn


@contextmanager
def closing(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Context manager that closes a SQLite connection on exit."""
    try:
        yield conn
    finally:
        conn.close()


def initialize(factory: ConnectionFactory | None = None) -> None:
    """Create the database (if missing) and apply all pending migrations.

    Idempotent — safe to call on every app start. Each migration runs as a
    single explicit transaction; on failure it rolls back and re-raises.
    """
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.writer()) as conn:
        _ensure_migrations_table(conn)
        applied = _applied_versions(conn)
        for version, name, sql in _discover_migrations():
            if version in applied:
                continue
            statements = _split_sql(sql)
            conn.execute("BEGIN IMMEDIATE;")
            try:
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO migrations (version, name, applied_at) VALUES (?, ?, ?);",
                    (version, name, _now()),
                )
                conn.execute("COMMIT;")
            except Exception:
                try:
                    conn.execute("ROLLBACK;")
                except sqlite3.OperationalError:
                    pass
                raise


def _split_sql(sql: str) -> list[str]:
    """Strip line comments and split a migration into individual statements.

    Migration files are trusted internal SQL; we don't need a full parser.
    Comments inside string literals don't appear in our migrations.
    """
    cleaned_lines: list[str] = []
    for raw in sql.splitlines():
        # Drop everything from `--` onward on each line (no `--` inside strings
        # in our migrations, by convention).
        idx = raw.find("--")
        line = raw if idx < 0 else raw[:idx]
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)
    return [s.strip() for s in text.split(";") if s.strip()]


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migrations (
            version     INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            applied_at  TEXT NOT NULL
        );
        """
    )


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM migrations;").fetchall()
    return {int(row["version"]) for row in rows}


def _discover_migrations() -> list[tuple[int, str, str]]:
    """Return all migrations on disk, sorted by version.

    Migration file names follow ``NNNN_description.sql``.
    """
    out: list[tuple[int, str, str]] = []
    pkg = "rabbitsync.db.migrations"
    for entry in sorted(resources.files(pkg).iterdir(), key=lambda p: p.name):
        if not entry.name.endswith(".sql"):
            continue
        version_str, _, rest = entry.name.partition("_")
        try:
            version = int(version_str)
        except ValueError:
            continue
        name = rest.removesuffix(".sql")
        sql = entry.read_text(encoding="utf-8")
        out.append((version, name, sql))
    return out


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


__all__ = ["APP_DB_VERSION", "ConnectionFactory", "closing", "initialize"]

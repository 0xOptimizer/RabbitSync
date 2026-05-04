"""Well-known paths for RabbitSync's runtime data tree.

Everything RabbitSync persists lives under a single ``data/`` directory at the
project root. This module is the only place that resolves those locations, so
the layout can be moved (e.g. to ``%LOCALAPPDATA%`` in a future packaging) by
editing one function.
"""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Return the project root (the directory containing ``main.py``)."""
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """Root of the runtime data tree. Created on first access."""
    p = project_root() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    """Path to the SQLite database file."""
    return data_dir() / "rabbitsync.db"


def logs_dir() -> Path:
    """Directory for rotated structured JSONL log files."""
    p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def backups_dir() -> Path:
    """Root of pre-sync snapshots, organized per pair."""
    p = data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def quarantine_dir() -> Path:
    """Root of the soft-delete quarantine, organized per sync-id."""
    p = data_dir() / "quarantine"
    p.mkdir(parents=True, exist_ok=True)
    return p


def pipelines_dir() -> Path:
    """Root of pipeline run captures, organized per pair / run-id."""
    p = data_dir() / "pipelines"
    p.mkdir(parents=True, exist_ok=True)
    return p


def lock_file() -> Path:
    """Global app-instance lock file path."""
    return data_dir() / ".lock"


def assets_dir() -> Path:
    """Bundled (read-only) asset directory inside the package."""
    return Path(__file__).resolve().parent / "assets"


def lucide_dir() -> Path:
    """Bundled Lucide SVG icon directory."""
    return assets_dir() / "icons" / "lucide"

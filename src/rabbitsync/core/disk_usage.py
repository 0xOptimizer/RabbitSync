"""Per-category disk usage breakdown for the Data card."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rabbitsync.paths import (
    backups_dir,
    db_path,
    logs_dir,
    pipelines_dir,
    quarantine_dir,
)


@dataclass(frozen=True)
class DiskUsage:
    db_bytes: int
    snapshots_bytes: int
    quarantine_bytes: int
    pipelines_bytes: int
    logs_bytes: int

    @property
    def total_bytes(self) -> int:
        return (
            self.db_bytes + self.snapshots_bytes + self.quarantine_bytes
            + self.pipelines_bytes + self.logs_bytes
        )


def measure() -> DiskUsage:
    return DiskUsage(
        db_bytes=_size(db_path()),
        snapshots_bytes=_tree(backups_dir()),
        quarantine_bytes=_tree(quarantine_dir()),
        pipelines_bytes=_tree(pipelines_dir()),
        logs_bytes=_tree(logs_dir()),
    )


def fmt(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / 1024 / 1024:.2f} MB"
    return f"{n / 1024 / 1024 / 1024:.2f} GB"


def _size(p: Path) -> int:
    try:
        return p.stat().st_size if p.is_file() else 0
    except OSError:
        return 0


def _tree(p: Path) -> int:
    if not p.exists():
        return 0
    total = 0
    try:
        for entry in p.rglob("*"):
            try:
                if entry.is_file():
                    total += entry.stat().st_size
            except OSError:
                continue
    except OSError:
        return 0
    return total


__all__ = ["DiskUsage", "fmt", "measure"]

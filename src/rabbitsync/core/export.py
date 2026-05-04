"""Export the data tree (or a subset) as a portable archive.

Two formats supported: ``.tar.zst`` (default) and ``.zip`` (fallback).
"""

from __future__ import annotations

import shutil
import tarfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import zstandard as zstd

from rabbitsync.paths import data_dir


@dataclass(frozen=True)
class ExportResult:
    path: Path
    bytes_written: int


def export(
    target: Path,
    *,
    include: Iterable[str] = ("rabbitsync.db", "backups", "logs", "quarantine"),
    fmt: str | None = None,
) -> ExportResult:
    """Bundle the chosen subdirectories of ``data/`` into ``target``.

    ``fmt`` is inferred from the target extension when ``None``.
    """
    chosen = list(include)
    root = data_dir()
    target.parent.mkdir(parents=True, exist_ok=True)

    extension = (fmt or "").lower() or _infer_format(target)
    if extension == "zip":
        return _export_zip(target, root, chosen)
    return _export_tar_zst(target, root, chosen)


def _export_tar_zst(target: Path, root: Path, chosen: list[str]) -> ExportResult:
    cctx = zstd.ZstdCompressor(level=10, threads=-1)
    with target.open("wb") as fh:
        with cctx.stream_writer(fh, closefd=False) as zwriter:
            with tarfile.open(fileobj=zwriter, mode="w|", bufsize=256 * 1024) as tar:
                for name in chosen:
                    src = root / name
                    if src.exists():
                        tar.add(str(src), arcname=name, recursive=True)
    return ExportResult(path=target, bytes_written=target.stat().st_size)


def _export_zip(target: Path, root: Path, chosen: list[str]) -> ExportResult:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name in chosen:
            src = root / name
            if not src.exists():
                continue
            if src.is_file():
                zf.write(src, arcname=name)
                continue
            for entry in src.rglob("*"):
                if entry.is_file():
                    arc = entry.relative_to(root).as_posix()
                    try:
                        zf.write(entry, arcname=arc)
                    except OSError:
                        continue
    return ExportResult(path=target, bytes_written=target.stat().st_size)


def _infer_format(target: Path) -> str:
    name = target.name.lower()
    if name.endswith(".zip"):
        return "zip"
    return "zst"


__all__ = ["ExportResult", "export"]


# Reference shutil for forward use (it powers the export-to-folder variant).
_ = shutil

"""Background diff worker so pair selection / Recheck don't freeze the UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from rabbitsync.core.diff import DiffPlan, diff
from rabbitsync.core.ignore import load_for_pair
from rabbitsync.db.connection import ConnectionFactory
from rabbitsync.db.writer import DbWriter


class DiffWorker(QObject):
    """One-shot QObject worker that runs ``diff()`` off the GUI thread.

    The ``token`` field lets the caller ignore stale results when a newer
    request supersedes this one (e.g. user clicked a different pair).
    """

    finished = Signal(int, object)  # token, DiffPlan | None
    failed = Signal(int, str)       # token, error message

    def __init__(
        self,
        *,
        token: int,
        pair_id: str,
        source_folder: Path,
        copy_folder: Path,
        writer: DbWriter | None,
        factory: ConnectionFactory | None,
    ) -> None:
        super().__init__()
        self._token = token
        self._pair_id = pair_id
        self._source = source_folder
        self._copy = copy_folder
        self._writer = writer
        self._factory = factory

    @property
    def token(self) -> int:
        return self._token

    @Slot()
    def run(self) -> None:
        try:
            rules = load_for_pair(source_folder=self._source, copy_folder=self._copy)
            plan: DiffPlan = diff(
                source_folder=self._source,
                copy_folder=self._copy,
                rules=rules,
                sample_rate=0,
                pair_id=self._pair_id,
                writer=self._writer,
                factory=self._factory,
            )
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
            self.finished.emit(self._token, None)
            _ = exc
            return
        except Exception as exc:  # noqa: BLE001 -- surface via signal
            self.failed.emit(self._token, str(exc))
            return
        self.finished.emit(self._token, plan)


__all__ = ["DiffWorker"]

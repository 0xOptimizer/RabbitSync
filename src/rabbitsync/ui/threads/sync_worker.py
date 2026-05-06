"""QObject worker that runs the sync engine on a background thread."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from rabbitsync.core.sync import SyncOutcome, perform
from rabbitsync.db.writer import DbWriter


class SyncWorker(QObject):
    """Move-to-thread style worker.

    Connect :attr:`finished` to receive the outcome on the main thread.
    """

    started = Signal(str)        # sync_id
    finished = Signal(object)    # SyncOutcome
    failed = Signal(str)         # human-readable error

    def __init__(
        self,
        *,
        pair_id: str,
        source_folder: Path,
        copy_folder: Path,
        writer: DbWriter,
        sample_rate: float = 0.01,
        commit_on_sync: bool = False,
        auto_push: bool = False,
        target_branch: str | None = None,
    ) -> None:
        super().__init__()
        self._pair_id = pair_id
        self._source_folder = source_folder
        self._copy_folder = copy_folder
        self._writer = writer
        self._sample_rate = sample_rate
        self._commit_on_sync = commit_on_sync
        self._auto_push = auto_push
        self._target_branch = target_branch

    @Slot()
    def run(self) -> None:
        try:
            outcome: SyncOutcome = perform(
                pair_id=self._pair_id,
                source_folder=self._source_folder,
                copy_folder=self._copy_folder,
                writer=self._writer,
                sample_rate=self._sample_rate,
                commit_on_sync=self._commit_on_sync,
                auto_push=self._auto_push,
                target_branch=self._target_branch,
            )
            self.started.emit(outcome.sync_id)
            self.finished.emit(outcome)
        except Exception as exc:  # noqa: BLE001 -- always surface via signal
            self.failed.emit(str(exc))


__all__ = ["SyncWorker"]

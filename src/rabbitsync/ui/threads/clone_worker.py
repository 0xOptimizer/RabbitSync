"""Background clone worker — drives ``git clone --progress`` off the UI thread."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from rabbitsync.core.clone import CloneProgress, CloneResult, clone


class CloneWorker(QObject):
    progress = Signal(int, str)  # percent, phase
    finished = Signal(object)    # CloneResult
    failed = Signal(str)

    def __init__(
        self,
        *,
        url: str,
        target: Path,
        branch: str | None = None,
        depth: int | None = None,
    ) -> None:
        super().__init__()
        self._url = url
        self._target = target
        self._branch = branch
        self._depth = depth

    @Slot()
    def run(self) -> None:
        try:
            result: CloneResult = clone(
                url=self._url,
                target=self._target,
                branch=self._branch,
                depth=self._depth,
                on_progress=self._on_progress,
            )
        except FileExistsError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        if not result.ok:
            self.failed.emit(result.stderr_tail or f"git clone exit code {result.exit_code}")
            return
        self.finished.emit(result)

    def _on_progress(self, p: CloneProgress) -> None:
        self.progress.emit(p.percent, p.phase)


__all__ = ["CloneWorker"]

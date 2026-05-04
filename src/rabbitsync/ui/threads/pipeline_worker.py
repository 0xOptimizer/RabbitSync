"""Run a pipeline off the UI thread."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from rabbitsync.core.pipeline import RunResult, StepDef, run_pipeline
from rabbitsync.db.repositories import pipelines_repo
from rabbitsync.db.writer import DbWriter
from rabbitsync.paths import data_dir


class PipelineWorker(QObject):
    finished = Signal(object)  # RunResult
    failed = Signal(str)

    def __init__(
        self,
        *,
        pair_id: str,
        pipeline_id: int,
        steps: Iterable[StepDef],
        pair_source: Path,
        pair_copy: Path,
        writer: DbWriter,
        triggered_as: str = "standalone",
        sync_id: str | None = None,
    ) -> None:
        super().__init__()
        self._pair_id = pair_id
        self._pipeline_id = pipeline_id
        self._steps = list(steps)
        self._pair_source = pair_source
        self._pair_copy = pair_copy
        self._writer = writer
        self._triggered_as = triggered_as
        self._sync_id = sync_id

    @Slot()
    def run(self) -> None:
        artifacts = data_dir() / "pipelines" / self._pair_id  # actual run dir is under here
        run_id = pipelines_repo.begin_run(
            self._writer,
            pipeline_id=self._pipeline_id,
            triggered_as=self._triggered_as,
            artifacts_dir=artifacts,
            sync_id=self._sync_id,
        )
        try:
            result: RunResult = run_pipeline(
                pair_id=self._pair_id,
                steps=self._steps,
                pair_source=self._pair_source,
                pair_copy=self._pair_copy,
                data_root=data_dir(),
            )
            pipelines_repo.finalize_run(self._writer, run_id=run_id, status=result.status)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            pipelines_repo.finalize_run(self._writer, run_id=run_id, status="failed")
            self.failed.emit(str(exc))


__all__ = ["PipelineWorker"]

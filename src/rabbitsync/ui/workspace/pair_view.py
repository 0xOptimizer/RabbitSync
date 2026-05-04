"""The 3-tab workspace for one selected pair."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QTabWidget, QWidget

from rabbitsync.core.git_resolve import GitContext
from rabbitsync.core.git_resolve import resolve as resolve_git
from rabbitsync.ui.tabs.git_pipelines_tab import GitPipelinesTab
from rabbitsync.ui.tabs.history_data_tab import HistoryDataTab
from rabbitsync.ui.tabs.sync_tab import SyncTab


class PairView(QTabWidget):
    """Workspace shown when a pair is selected in the sidebar."""

    def __init__(
        self,
        *,
        on_preview_diff: Callable[[], None],
        on_sync_clicked: Callable[[], None],
        on_git_action: Callable[[str, str], None],
        on_pipeline_run: Callable[[int], None],
        on_pipeline_edit: Callable[[int], None],
        on_pipeline_new: Callable[[], None],
        on_pipeline_delete: Callable[[int], None],
        on_pipeline_set_pre: Callable[[int], None],
        on_pipeline_set_post: Callable[[int], None],
        on_sweep: Callable[[], None],
        on_verify_audit: Callable[[], None],
        on_export: Callable[[], None],
        on_reveal: Callable[[], None],
        on_history_restore: Callable[[str], None],
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setTabPosition(QTabWidget.TabPosition.North)
        self.setDocumentMode(True)
        self.setMovable(False)

        self._sync_tab = SyncTab(
            on_preview_diff=on_preview_diff,
            on_sync_clicked=on_sync_clicked,
            theme=theme,
        )
        self._git_tab = GitPipelinesTab(
            on_git_action=on_git_action,
            on_pipeline_run=on_pipeline_run,
            on_pipeline_edit=on_pipeline_edit,
            on_pipeline_new=on_pipeline_new,
            on_pipeline_delete=on_pipeline_delete,
            on_pipeline_set_pre=on_pipeline_set_pre,
            on_pipeline_set_post=on_pipeline_set_post,
            theme=theme,
        )
        self._history_tab = HistoryDataTab(
            on_sweep=on_sweep,
            on_verify_audit=on_verify_audit,
            on_export=on_export,
            on_reveal=on_reveal,
            theme=theme,
        )

        self.addTab(self._sync_tab, "Sync")
        self.addTab(self._git_tab, "Git & Pipelines")
        self.addTab(self._history_tab, "History & Data")

        self._on_history_restore = on_history_restore
        self._source_ctx: GitContext | None = None
        self._copy_ctx: GitContext | None = None

    def show_pair(self, *, source_folder: Path, copy_folder: Path) -> None:
        """Refresh all three tabs for the given pair."""
        source_ctx = resolve_git(source_folder)
        copy_ctx = resolve_git(copy_folder)
        self._source_ctx = source_ctx
        self._copy_ctx = copy_ctx
        self._git_tab.show_contexts(source=source_ctx, copy=copy_ctx)

    def set_pipelines(self, rows: list[dict]) -> None:
        self._git_tab.set_pipelines(rows)

    def set_sync_plan(self, plan) -> None:  # noqa: ANN001
        self._sync_tab.populate_from_plan(plan)

    def set_history_rows(self, rows: list[tuple[str, str, str]]) -> None:
        self._history_tab.populate_timeline(rows)

    def set_data_stats(self, **kwargs) -> None:  # noqa: ANN003
        self._history_tab.set_data_stats(**kwargs)

    @property
    def source_ctx(self) -> GitContext | None:
        return self._source_ctx

    @property
    def copy_ctx(self) -> GitContext | None:
        return self._copy_ctx


__all__ = ["PairView"]

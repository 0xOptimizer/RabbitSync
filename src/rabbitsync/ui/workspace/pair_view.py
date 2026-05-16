"""The 3-tab workspace for one selected pair."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QTabWidget, QWidget

from rabbitsync.core.git_resolve import GitContext
from rabbitsync.core.git_resolve import resolve as resolve_git
from rabbitsync.ui.tabs.git_pipelines_tab import GitPipelinesTab
from rabbitsync.ui.tabs.history_data_tab import HistoryDataTab
from rabbitsync.ui.tabs.overview_tab import OverviewTab
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

        self._overview_tab = OverviewTab(
            on_preview_diff=on_preview_diff,
            on_sync_clicked=on_sync_clicked,
            theme=theme,
        )
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

        self.addTab(self._overview_tab, "Overview")
        self.addTab(self._sync_tab, "Sync")
        self.addTab(self._git_tab, "Git & Pipelines")
        self.addTab(self._history_tab, "History & Data")
        self.setCurrentIndex(0)

        self._on_history_restore = on_history_restore
        self._source_ctx: GitContext | None = None
        self._copy_ctx: GitContext | None = None
        self._external_settings_handler: Callable[[], None] | None = None
        self._mirroring_settings = False

        # Mirror state between the two SyncSettingsPane instances so toggling
        # on one updates the other immediately. The mirror suspends events on
        # the receiver to avoid feedback loops.
        self._sync_tab._settings.set_on_changed(  # noqa: SLF001
            lambda: self._on_settings_changed(source="sync")
        )
        self._overview_tab.settings_pane.set_on_changed(
            lambda: self._on_settings_changed(source="overview")
        )

    def show_pair(self, *, source_folder: Path, copy_folder: Path) -> None:
        """Refresh all three tabs for the given pair."""
        source_ctx = resolve_git(source_folder)
        copy_ctx = resolve_git(copy_folder)
        self._source_ctx = source_ctx
        self._copy_ctx = copy_ctx
        self._git_tab.show_contexts(source=source_ctx, copy=copy_ctx)

        # Populate the target-branch dropdown from copy's local branches on
        # both settings panes (Sync tab + Overview tab).
        if copy_ctx.has_git:
            from rabbitsync.core.git_info import branches as list_branches, status as repo_status

            bs = [b.name for b in list_branches(copy_ctx)]
            cur = repo_status(copy_ctx)
            current = cur.branch if cur is not None else None
        else:
            bs, current = [], None
        for pane in self._settings_panes():
            pane.set_branches(bs, current)

    def set_pipelines(self, rows: list[dict]) -> None:
        self._git_tab.set_pipelines(rows)

    def set_sync_plan(self, plan) -> None:  # noqa: ANN001
        self._sync_tab.populate_from_plan(plan)
        self._overview_tab.populate_from_plan(plan)

    def set_cached_counts(self, *, adds: int, modifies: int, quarantines: int) -> None:
        """Show last-known counts on the cards/summaries while a fresh diff runs."""
        self._overview_tab.set_counts(
            adds=adds, modifies=modifies, quarantines=quarantines,
        )
        self._sync_tab._settings.show_summary(  # noqa: SLF001
            adds=adds, modifies=modifies, quarantines=quarantines,
        )

    def clear_sync_plan(self) -> None:
        """Wipe the Sync + Overview tabs (e.g. when a folder went missing)."""
        from rabbitsync.core.diff import DiffPlan
        empty = DiffPlan()
        self._sync_tab.populate_from_plan(empty)
        self._overview_tab.clear_summary()

    def set_history_rows(self, rows: list[tuple[str, str, str]]) -> None:
        self._history_tab.populate_timeline(rows)

    def set_data_stats(self, **kwargs) -> None:  # noqa: ANN003
        self._history_tab.set_data_stats(**kwargs)

    # -- Sync progress passthrough --------------------------------------

    def show_sync_progress(self) -> None:
        self._sync_tab.show_progress()

    def update_sync_progress(
        self, *, phase: str, step_no: int = 0, total: int = 0, rel_path: str | None = None,
    ) -> None:
        self._sync_tab.update_progress(
            phase=phase, step_no=step_no, total=total, rel_path=rel_path,
        )

    def hide_sync_progress(self) -> None:
        self._sync_tab.hide_progress()

    # -- Per-pair settings state ----------------------------------------

    def apply_pair_settings(
        self,
        *,
        commit_on_sync: bool,
        auto_push: bool,
        target_branch: str | None,
    ) -> None:
        """Seed both settings panes from a freshly-loaded pair."""
        for pane in self._settings_panes():
            pane.set_state(
                commit_on_sync=commit_on_sync,
                auto_push=auto_push,
                target_branch=target_branch,
            )

    def set_settings_changed_handler(self, handler: Callable[[], None] | None) -> None:
        """Register the MainWindow handler called whenever either pane changes."""
        self._external_settings_handler = handler

    def _settings_panes(self):  # noqa: ANN202
        return (self._sync_tab._settings, self._overview_tab.settings_pane)  # noqa: SLF001

    def _on_settings_changed(self, *, source: str) -> None:
        if self._mirroring_settings:
            return
        # Read the live state from the pane that fired, then mirror it onto
        # the other pane with events suspended.
        sync_pane = self._sync_tab._settings  # noqa: SLF001
        overview_pane = self._overview_tab.settings_pane
        src = sync_pane if source == "sync" else overview_pane
        dst = overview_pane if source == "sync" else sync_pane
        self._mirroring_settings = True
        try:
            dst.set_state(
                commit_on_sync=src.commit_on_sync,
                auto_push=src.auto_push,
                target_branch=src.target_branch,
            )
        finally:
            self._mirroring_settings = False
        if self._external_settings_handler is not None:
            self._external_settings_handler()

    @property
    def source_ctx(self) -> GitContext | None:
        return self._source_ctx

    @property
    def copy_ctx(self) -> GitContext | None:
        return self._copy_ctx

    @property
    def sync_tab(self) -> SyncTab:
        return self._sync_tab

    @property
    def commit_on_sync(self) -> bool:
        return self._sync_tab._settings.commit_on_sync  # noqa: SLF001

    @property
    def auto_push(self) -> bool:
        return self._sync_tab._settings.auto_push  # noqa: SLF001

    @property
    def target_branch(self) -> str | None:
        return self._sync_tab._settings.target_branch  # noqa: SLF001


__all__ = ["PairView"]

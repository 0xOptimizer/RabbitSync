"""Main application window — fully wired.

Every burger menu item, sidebar action, pair-view action, git-pane action,
and pipelines-pane action routes to a real implementation.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QTimer
from PySide6.QtGui import QAction, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from rabbitsync import __version__
from rabbitsync.config.store import Settings, load_settings, save_settings
from rabbitsync.core import disk_usage, retention
from rabbitsync.core.diff import DiffPlan, diff
from rabbitsync.core.git_resolve import resolve as resolve_git
from rabbitsync.core.ignore import load_for_pair
from rabbitsync.core.pipeline import StepDef
from rabbitsync.db.connection import ConnectionFactory
from rabbitsync.db.repositories import (
    blobs_repo,
    github_accounts_repo,
    pairs_repo,
    pipelines_repo,
    receipts_repo,
    syncs_repo,
)
from rabbitsync.db.writer import DbWriter
from rabbitsync.logging.setup import get_logger
from rabbitsync.safety import journal as journal_mod
from rabbitsync.ui import animations, icons
from rabbitsync.ui.dialogs import git_ops as git_ops_dlg
from rabbitsync.ui.dialogs.clone import CloneDialog
from rabbitsync.ui.dialogs.confirm_sync import ConfirmSyncDialog
from rabbitsync.ui.dialogs.connect_github import ConnectGitHubDialog
from rabbitsync.ui.dialogs.diff_preview import DiffPreviewDialog
from rabbitsync.ui.dialogs.edit_pipeline import EditPipelineDialog
from rabbitsync.ui.dialogs.export_backup import ExportBackupDialog
from rabbitsync.ui.dialogs.pipeline_run_view import PipelineRunView
from rabbitsync.ui.dialogs.recovery_prompt import RecoveryPromptDialog
from rabbitsync.ui.dialogs.register_pair import RegisterPairDialog
from rabbitsync.ui.dialogs.settings import SettingsDialog
from rabbitsync.ui.panels.log_dock import LogDock
from rabbitsync.ui.panels.pair_header import PairHeader
from rabbitsync.ui.panels.status_bar import AppStatusBar
from rabbitsync.ui.panels.toast import Toaster
from rabbitsync.ui.sidebar import Sidebar, SidebarView
from rabbitsync.ui.theme import DARK, LIGHT, Spacing, Window
from rabbitsync.ui.threads.clone_worker import CloneWorker
from rabbitsync.ui.threads.github_worker import RefreshReposWorker, TestCredentialWorker
from rabbitsync.ui.threads.pipeline_worker import PipelineWorker
from rabbitsync.ui.threads.sync_worker import SyncWorker
from rabbitsync.ui.widgets.status_pill import PillStatus
from rabbitsync.ui.workspace.accounts_view import AccountsView
from rabbitsync.ui.workspace.empty_view import EmptyView
from rabbitsync.ui.workspace.pair_view import PairView
from rabbitsync.ui.workspace.repos_view import ReposView

_log = get_logger("ui.main_window")


def _pill_for_plan(plan: DiffPlan | None) -> PillStatus:
    """Map a diff result to a status pill state.

    ``None`` means the diff couldn't run (folder missing, permission denied, …).
    """
    if plan is None:
        return PillStatus.BLOCKED
    if plan.is_noop:
        return PillStatus.IN_SYNC
    return PillStatus.PENDING


def _thread_running(t: QThread | None) -> bool:
    """Safe ``isRunning()``: tolerates None and already-deleted C++ wrappers.

    After ``deleteLater()`` runs on a finished thread, the C++ ``QThread``
    object is destroyed but the Python attribute still references the now-
    dangling wrapper; calling ``isRunning()`` on it raises ``RuntimeError:
    Internal C++ object already deleted``. This helper returns ``False`` in
    that case (the thread is, by definition, not running).
    """
    if t is None:
        return False
    try:
        return bool(t.isRunning())
    except RuntimeError:
        return False


class MainWindow(QMainWindow):
    """Application main window with every user-facing action wired."""

    def __init__(self, *, theme: str = "dark", db_writer: DbWriter | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"RabbitSync {__version__}")
        self.setMinimumSize(Window.MIN_W, Window.MIN_H)
        self.resize(Window.DEFAULT_W, Window.DEFAULT_H)

        self._settings: Settings = load_settings()
        animations.set_user_preference(self._settings.reduce_motion)
        if self._settings.theme in {"light", "dark"}:
            theme = self._settings.theme
        palette = DARK if theme == "dark" else LIGHT
        icons.set_tint(QColor(palette.fg))
        self._theme = theme
        self._writer = db_writer
        self._factory = ConnectionFactory()
        self._current_pair_id: str | None = None
        self._sync_thread: QThread | None = None
        self._sync_worker: SyncWorker | None = None
        self._clone_thread: QThread | None = None
        self._clone_worker: CloneWorker | None = None
        self._clone_dialog: CloneDialog | None = None
        self._pipeline_thread: QThread | None = None
        self._pipeline_worker: PipelineWorker | None = None
        self._gh_thread: QThread | None = None
        self._gh_worker: RefreshReposWorker | TestCredentialWorker | None = None
        self._toaster = Toaster(app_icon=icons.Icons.menu(), parent=self)
        self._suppress_tab_refresh = False

        # --- Header strip with burger ---------------------------------
        header_strip = self._build_header_strip()

        # --- Pair header (above tabs) ---------------------------------
        self._pair_header = PairHeader(
            on_sync=self._on_sync_clicked,
            on_recheck=self._on_recheck_clicked,
            on_edit_pair=self._on_edit_pair,
            on_remove_pair=self._on_remove_pair,
            theme=theme,
        )
        self._pair_header.show_empty()

        # --- Sidebar --------------------------------------------------
        self._sidebar = Sidebar(theme=theme)
        self._sidebar.view_changed.connect(self._on_sidebar_view_changed)
        self._sidebar.item_selected.connect(self._on_sidebar_item_selected)
        self._sidebar.add_requested.connect(self._on_sidebar_add)

        # --- Workspace stack -----------------------------------------
        self._workspace_stack = QStackedWidget()
        self._empty_view = EmptyView(theme=theme)
        self._pair_view = PairView(
            on_preview_diff=self._on_preview_diff,
            on_sync_clicked=self._on_sync_clicked,
            on_git_action=self._on_git_action,
            on_pipeline_run=self._on_pipeline_run,
            on_pipeline_edit=self._on_pipeline_edit,
            on_pipeline_new=self._on_pipeline_new,
            on_pipeline_delete=self._on_pipeline_delete,
            on_pipeline_set_pre=lambda pid: self._on_pipeline_set_hook(pid, "pre_sync"),
            on_pipeline_set_post=lambda pid: self._on_pipeline_set_hook(pid, "post_sync"),
            on_sweep=self._on_sweep,
            on_verify_audit=self._on_verify_audit,
            on_export=self._on_export,
            on_reveal=self._on_reveal,
            on_history_restore=self._on_history_restore,
            theme=theme,
        )
        self._repos_view = ReposView(
            on_clone=self._on_clone_url,
            on_refresh=self._on_repos_refresh,
            theme=theme,
        )
        self._accounts_view = AccountsView(
            on_connect=self._on_connect_github,
            on_test=self._on_test_account,
            on_forget=self._on_forget_account,
            theme=theme,
        )
        self._workspace_stack.addWidget(self._empty_view)     # 0
        self._workspace_stack.addWidget(self._pair_view)      # 1
        self._workspace_stack.addWidget(self._repos_view)     # 2
        self._workspace_stack.addWidget(self._accounts_view)  # 3
        self._workspace_stack.setCurrentWidget(self._empty_view)
        # Persist per-pair Sync settings whenever the user toggles them.
        self._pair_view.set_settings_changed_handler(self._on_pair_settings_changed)
        # Refresh diff/pill on every tab switch within a pair workspace.
        self._pair_view.currentChanged.connect(self._on_pair_view_tab_changed)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._pair_header)
        right_layout.addWidget(self._workspace_stack, 1)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(self._sidebar)
        self._splitter.addWidget(right)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setCollapsible(0, True)
        self._splitter.setCollapsible(1, False)

        central = QWidget()
        central.setObjectName("central")
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(header_strip)
        cl.addWidget(self._splitter, 1)
        self.setCentralWidget(central)

        self._log_dock = LogDock(theme=theme)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)
        self._log_dock.hide()

        self._status_bar = AppStatusBar(
            on_toggle_logs=self._toggle_log_dock,
            theme=theme,
        )
        self.setStatusBar(self._status_bar)

        self._refresh_sidebar_pairs()
        self._refresh_accounts_view()
        self._maybe_restore_last_pair()

        # --- Auto sync-check timer -----------------------------------
        self._auto_check_timer = QTimer(self)
        self._auto_check_timer.setInterval(self._settings.sync_check_interval_s * 1000)
        self._auto_check_timer.timeout.connect(self._on_auto_check_tick)
        self._auto_check_timer.start()

        # --- Recovery prompt at startup ------------------------------
        QTimer.singleShot(0, self._maybe_show_recovery_prompt)

        _log.info(
            "ui.main_window.shown",
            theme=theme,
            min_size=(Window.MIN_W, Window.MIN_H),
        )

    # -- Header / burger menu ---------------------------------------------

    def _build_header_strip(self) -> QWidget:
        strip = QWidget()
        strip.setObjectName("HeaderStrip")
        strip.setFixedHeight(32)

        burger = QToolButton(strip)
        burger.setIcon(icons.Icons.menu())
        burger.setIconSize(QSize(16, 16))
        burger.setToolTip("Menu")
        burger.setAutoRaise(True)
        burger.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(burger)
        self._populate_burger_menu(menu)
        burger.setMenu(menu)

        title = QLabel("RabbitSync", strip)
        title.setProperty("role", "header")

        layout = QHBoxLayout(strip)
        layout.setContentsMargins(Spacing.SM, 0, Spacing.MD, 0)
        layout.setSpacing(Spacing.SM)
        layout.addWidget(burger)
        layout.addWidget(title)
        layout.addStretch(1)
        return strip

    def _populate_burger_menu(self, menu: QMenu) -> None:
        items: list[tuple[str, Callable[[], object] | None, Callable[[], None]] | None] = [
            ("New Pair…", icons.Icons.pairs, self._on_new_pair),
            ("Clone…", icons.Icons.clone, lambda: self._on_clone_url("")),
            ("Connect GitHub…", icons.Icons.key, self._on_connect_github),
            None,
            ("Re-check All", icons.Icons.recheck_all, self._on_recheck_all),
            ("Export Backup…", icons.Icons.export_, self._on_export),
            None,
            ("Settings…", icons.Icons.settings, self._on_settings),
            ("Toggle Log Dock", icons.Icons.logs, self._toggle_log_dock),
            None,
            ("About", None, self._on_about),
            ("Quit", None, self.close),
        ]
        for entry in items:
            if entry is None:
                menu.addSeparator()
                continue
            label, icon_fn, handler = entry
            action = QAction(label, menu)
            if icon_fn is not None:
                action.setIcon(icon_fn())
            action.triggered.connect(handler)
            menu.addAction(action)

    # -- Sidebar wiring ---------------------------------------------------

    def _on_sidebar_view_changed(self, view: SidebarView) -> None:
        if view == SidebarView.PAIRS:
            self._workspace_stack.setCurrentWidget(self._empty_view)
            self._pair_header.show_empty()
            self._refresh_sidebar_pairs()
        elif view == SidebarView.REPOSITORIES:
            self._workspace_stack.setCurrentWidget(self._repos_view)
            self._pair_header.show_empty()
            self._refresh_repos_view()
        elif view == SidebarView.ACCOUNTS:
            self._workspace_stack.setCurrentWidget(self._accounts_view)
            self._pair_header.show_empty()
            self._refresh_accounts_view()
        _log.info("ui.sidebar.view_changed", view=view.value)

    def _on_sidebar_item_selected(self, view: SidebarView, item_id: str) -> None:
        _log.info("ui.sidebar.item_selected", view=view.value, item_id=item_id)
        if view != SidebarView.PAIRS:
            return
        pair = pairs_repo.get(item_id, factory=self._factory)
        if pair is None:
            return
        self._current_pair_id = pair.id
        self._pair_header.show_pair(
            label=pair.label,
            source=Path(pair.source_path),
            copy=Path(pair.copy_path),
            status=PillStatus.PENDING,  # real state computed in _refresh_current_pair_view
        )
        # Seed the per-pair Sync settings before the refresh so the first
        # populate_from_plan + diff use the right toggles.
        self._pair_view.apply_pair_settings(
            commit_on_sync=pair.commit_on_sync,
            auto_push=pair.auto_push,
            target_branch=pair.target_branch,
        )
        self._workspace_stack.setCurrentWidget(self._pair_view)
        # Land on Overview every time a pair is selected. Suppress the tab-
        # changed handler so we don't double-refresh; we call refresh explicitly.
        self._suppress_tab_refresh = True
        try:
            self._pair_view.setCurrentIndex(0)
        finally:
            self._suppress_tab_refresh = False
        self._refresh_current_pair_view()
        self._persist_last_pair_id(pair.id)

    def _on_sidebar_add(self, view: SidebarView) -> None:
        if view == SidebarView.PAIRS:
            self._on_new_pair()
        elif view == SidebarView.REPOSITORIES:
            self._on_repos_refresh()
        elif view == SidebarView.ACCOUNTS:
            self._on_connect_github()

    def _refresh_sidebar_pairs(self) -> None:
        pairs = pairs_repo.list_all(factory=self._factory)
        self._sidebar.set_items(SidebarView.PAIRS,
                                [(p.id, p.label) for p in pairs])

    def _refresh_current_pair_view(self) -> None:
        if self._current_pair_id is None:
            return
        pair = pairs_repo.get(self._current_pair_id, factory=self._factory)
        if pair is None:
            return
        source = Path(pair.source_path)
        copy = Path(pair.copy_path)
        self._pair_view.show_pair(source_folder=source, copy_folder=copy)

        # Compute the actual diff and drive both the Sync/Overview tabs and the
        # status pill. Skip during an active sync so we don't fight the worker.
        if not _thread_running(self._sync_thread):
            plan: DiffPlan | None = None
            try:
                rules = load_for_pair(source_folder=source, copy_folder=copy)
                plan = diff(
                    source_folder=source, copy_folder=copy,
                    rules=rules, sample_rate=0,
                    pair_id=pair.id,
                    writer=self._writer,
                    factory=self._factory,
                )
            except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
                _log.warning("ui.refresh.diff_failed",
                             pair_id=pair.id, error=str(exc),
                             error_type=type(exc).__name__)
            if plan is None:
                self._pair_view.clear_sync_plan()
            else:
                self._pair_view.set_sync_plan(plan)
            self._pair_header.set_status(_pill_for_plan(plan))

        # Pipelines list
        rows: list[dict] = []
        for p in pipelines_repo.list_pipelines(pair.id, factory=self._factory):
            last = pipelines_repo.last_run_for(p.id, factory=self._factory)
            rows.append({
                "id": p.id, "name": p.name,
                "last_status": last[0] if last else None,
                "last_when": last[1] if last else None,
            })
        self._pair_view.set_pipelines(rows)
        # History timeline
        sync_rows = syncs_repo.list_for_pair(pair.id, factory=self._factory)
        history: list[tuple[str, str, str]] = []
        for s in sync_rows:
            when = s["finished_at"] or s["started_at"] or ""
            delta = (
                f"+{s['files_added']} ~{s['files_modified']} -{s['files_quarantined']}"
            )
            history.append((when, delta, s["status"]))
        self._pair_view.set_history_rows(history)
        # Data stats
        usage = disk_usage.measure()
        self._pair_view.set_data_stats(
            db=disk_usage.fmt(usage.db_bytes),
            snapshots=disk_usage.fmt(usage.snapshots_bytes),
            quarantine=disk_usage.fmt(usage.quarantine_bytes),
            pipelines=disk_usage.fmt(usage.pipelines_bytes),
            logs=disk_usage.fmt(usage.logs_bytes),
        )

    # -- Burger / per-pair actions ----------------------------------------

    def _on_new_pair(self) -> None:
        if self._writer is None:
            QMessageBox.information(self, "DB writer not ready",
                                    "The database writer is not running yet.")
            return
        dialog = RegisterPairDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        reg = dialog.registration()
        if reg is None:
            return
        src_ctx = resolve_git(reg.source)
        cpy_ctx = resolve_git(reg.copy)
        pair_id = pairs_repo.create(
            self._writer,
            label=reg.label,
            source_path=str(reg.source),
            copy_path=str(reg.copy),
            source_git_root=str(src_ctx.git_root) if src_ctx.git_root else None,
            source_subpath=src_ctx.subpath,
            copy_git_root=str(cpy_ctx.git_root) if cpy_ctx.git_root else None,
            copy_subpath=cpy_ctx.subpath,
        )
        _log.info("ui.pair.created", pair_id=pair_id, label=reg.label)
        self._refresh_sidebar_pairs()
        self._toaster.info("Pair registered", reg.label)

    def _on_sync_clicked(self) -> None:
        if self._current_pair_id is None or self._writer is None:
            return
        pair = pairs_repo.get(self._current_pair_id, factory=self._factory)
        if pair is None:
            return
        source = Path(pair.source_path)
        copy = Path(pair.copy_path)
        rules = load_for_pair(source_folder=source, copy_folder=copy)
        plan = diff(
            source_folder=source, copy_folder=copy, rules=rules, sample_rate=0,
            pair_id=pair.id, writer=self._writer, factory=self._factory,
        )
        from rabbitsync.paths import backups_dir
        snapshot_target = backups_dir() / pair.id
        # Initial-sync test: any prior receipt for this pair?
        prior = syncs_repo.list_for_pair(pair.id, limit=1, factory=self._factory)
        is_initial = not prior
        confirm = ConfirmSyncDialog(
            plan=plan,
            copy_folder=copy,
            snapshot_target=snapshot_target,
            is_initial_sync=is_initial,
            theme=self._theme,
            parent=self,
        )
        if confirm.exec() != confirm.DialogCode.Accepted:
            return
        self._launch_sync(pair_id=pair.id, source=source, copy=copy)

    def _launch_sync(self, *, pair_id: str, source: Path, copy: Path) -> None:
        if self._writer is None:
            return
        if _thread_running(self._sync_thread):
            QMessageBox.information(self, "Sync running",
                                    "A sync is already in progress.")
            return
        self._sync_thread = QThread(self)
        self._sync_worker = SyncWorker(
            pair_id=pair_id,
            source_folder=source,
            copy_folder=copy,
            writer=self._writer,
            sample_rate=self._settings.diff_sample_rate,
            commit_on_sync=self._pair_view.commit_on_sync,
            auto_push=self._pair_view.auto_push,
            target_branch=self._pair_view.target_branch,
        )
        self._sync_worker.moveToThread(self._sync_thread)
        self._sync_thread.started.connect(self._sync_worker.run)
        self._sync_worker.progress.connect(self._on_sync_progress)
        self._sync_worker.finished.connect(self._on_sync_finished)
        self._sync_worker.failed.connect(self._on_sync_failed)
        self._sync_worker.finished.connect(self._sync_thread.quit)
        self._sync_worker.failed.connect(self._sync_thread.quit)
        self._sync_thread.finished.connect(self._sync_thread.deleteLater)
        self._sync_thread.start()
        self._status_bar.set_status("Syncing…")
        self._status_bar.show_progress()
        self._pair_view.show_sync_progress()
        self._pair_header.set_status(PillStatus.SYNCING)
        # Auto-show the log dock so the user sees what's happening.
        self._log_dock.reveal()

    def _on_sync_progress(self, ev) -> None:  # noqa: ANN001 -- ProgressEvent
        # Forward the worker's progress event to both visible surfaces.
        self._status_bar.update_progress(
            phase=ev.phase, step_no=ev.step_no, total=ev.total, rel_path=ev.rel_path,
        )
        self._pair_view.update_sync_progress(
            phase=ev.phase, step_no=ev.step_no, total=ev.total, rel_path=ev.rel_path,
        )

    def _on_sync_finished(self, outcome) -> None:  # noqa: ANN001
        self._status_bar.hide_progress()
        self._pair_view.hide_sync_progress()
        commit_short = (
            outcome.copy_commit_sha[:7] if getattr(outcome, "copy_commit_sha", None) else None
        )
        bits = [
            f"+{outcome.files_added} ~{outcome.files_modified} -{outcome.files_quarantined}",
        ]
        if commit_short:
            bits.append(f"committed {commit_short}")
        if getattr(outcome, "pushed", False):
            bits.append("pushed")
        self._status_bar.set_status(f"Sync {outcome.status} · " + " · ".join(bits))

        lines = [
            f"Status: {outcome.status}",
            f"Added: {outcome.files_added}  Modified: {outcome.files_modified}  "
            f"Quarantined: {outcome.files_quarantined}",
        ]
        if outcome.commit_message:
            lines.append("")
            lines.append(f"Commit: {commit_short}")
            lines.append(f"Message: {outcome.commit_message}")
        if outcome.pushed:
            lines.append("Pushed to remote.")
        QMessageBox.information(self, "Sync complete", "\n".join(lines))
        self._toaster.info("Sync complete", " · ".join(bits))
        self._refresh_current_pair_view()
        self._maybe_run_post_sync_pipelines(outcome)

    def _on_sync_failed(self, message: str) -> None:
        self._status_bar.hide_progress()
        self._pair_view.hide_sync_progress()
        self._status_bar.set_status("Sync failed")
        self._pair_header.set_status(PillStatus.BLOCKED)
        QMessageBox.critical(self, "Sync failed", message)
        self._toaster.error("Sync failed", message)

    def _maybe_run_post_sync_pipelines(self, outcome) -> None:  # noqa: ANN001
        if outcome.status != "ok" or self._current_pair_id is None or self._writer is None:
            return
        pair = pairs_repo.get(self._current_pair_id, factory=self._factory)
        if pair is None:
            return
        for p in pipelines_repo.list_pipelines(pair.id, factory=self._factory):
            if p.post_sync:
                self._launch_pipeline(p.id, triggered_as="post-sync", sync_id=outcome.sync_id)
                break  # one post-sync hook at a time

    def _on_recheck_clicked(self) -> None:
        self._refresh_current_pair_view()

    def _on_recheck_all(self) -> None:
        self._refresh_sidebar_pairs()
        if self._workspace_stack.currentWidget() is self._pair_view:
            self._refresh_current_pair_view()
        self._toaster.info("Re-check", "All pairs refreshed.")

    def _on_edit_pair(self) -> None:
        if self._current_pair_id is None:
            return
        pair = pairs_repo.get(self._current_pair_id, factory=self._factory)
        if pair is None:
            return
        dialog = RegisterPairDialog(self)
        # Pre-fill — uses internal field access; acceptable since this is the same package.
        dialog._label_input.setText(pair.label)               # noqa: SLF001
        dialog._source_input.setText(pair.source_path)        # noqa: SLF001
        dialog._copy_input.setText(pair.copy_path)            # noqa: SLF001
        dialog._refresh_source_status()                       # noqa: SLF001
        dialog._refresh_copy_status()                         # noqa: SLF001
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        reg = dialog.registration()
        if reg is None or self._writer is None:
            return
        # Replace by delete + create — keeps the schema migration cost down.
        pairs_repo.delete(pair.id, self._writer)
        src_ctx = resolve_git(reg.source)
        cpy_ctx = resolve_git(reg.copy)
        new_id = pairs_repo.create(
            self._writer,
            label=reg.label,
            source_path=str(reg.source),
            copy_path=str(reg.copy),
            source_git_root=str(src_ctx.git_root) if src_ctx.git_root else None,
            source_subpath=src_ctx.subpath,
            copy_git_root=str(cpy_ctx.git_root) if cpy_ctx.git_root else None,
            copy_subpath=cpy_ctx.subpath,
        )
        self._current_pair_id = new_id
        self._refresh_sidebar_pairs()
        self._refresh_current_pair_view()

    def _on_remove_pair(self) -> None:
        if self._current_pair_id is None or self._writer is None:
            return
        confirm = QMessageBox.question(
            self, "Remove pair",
            "Remove this pair from RabbitSync? Snapshots and quarantine entries on disk are kept.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        removed_id = self._current_pair_id
        pairs_repo.delete(removed_id, self._writer)
        if self._settings.last_pair_id == removed_id:
            self._persist_last_pair_id(None)
        self._current_pair_id = None
        self._pair_header.show_empty()
        self._workspace_stack.setCurrentWidget(self._empty_view)
        self._refresh_sidebar_pairs()

    def _on_preview_diff(self) -> None:
        if self._current_pair_id is None:
            return
        pair = pairs_repo.get(self._current_pair_id, factory=self._factory)
        if pair is None:
            return
        source = Path(pair.source_path)
        copy = Path(pair.copy_path)
        rules = load_for_pair(source_folder=source, copy_folder=copy)
        plan = diff(
            source_folder=source, copy_folder=copy, rules=rules, sample_rate=0,
            pair_id=pair.id, writer=self._writer, factory=self._factory,
        )
        DiffPreviewDialog(
            plan=plan, source_folder=source, copy_folder=copy,
            on_sync=self._on_sync_clicked,
            theme=self._theme, parent=self,
        ).exec()

    def _on_git_action(self, side: str, action: str) -> None:
        if self._current_pair_id is None:
            return
        ctx = self._pair_view.source_ctx if side == "source" else self._pair_view.copy_ctx
        if ctx is None or not ctx.has_git:
            QMessageBox.information(self, "Git", "This side has no git repo.")
            return
        try:
            if action == "fetch":
                git_ops_dlg.fetch(self, ctx)
            elif action == "pull":
                git_ops_dlg.pull(self, ctx)
            elif action == "push":
                git_ops_dlg.push(self, ctx)
            elif action == "stage":
                git_ops_dlg.stage_changes(self, ctx)
            elif action == "commit":
                git_ops_dlg.commit_dialog(self, ctx)
            elif action == "branch":
                git_ops_dlg.branch_dialog(self, ctx)
            elif action == "stash":
                git_ops_dlg.stash_save(self, ctx)
            elif action == "quick_push":
                git_ops_dlg.quick_push(self, ctx)
        finally:
            self._refresh_current_pair_view()

    # -- Pipelines --------------------------------------------------------

    def _on_pipeline_run(self, pipeline_id: int) -> None:
        self._launch_pipeline(pipeline_id, triggered_as="standalone")

    def _on_pipeline_edit(self, pipeline_id: int) -> None:
        if self._writer is None or self._current_pair_id is None:
            return
        EditPipelineDialog(
            pair_id=self._current_pair_id,
            writer=self._writer,
            pipeline_id=pipeline_id,
            factory=self._factory,
            parent=self,
        ).exec()
        self._refresh_current_pair_view()

    def _on_pipeline_new(self) -> None:
        if self._writer is None or self._current_pair_id is None:
            QMessageBox.information(self, "New pipeline",
                                    "Pick a pair first, then add a pipeline.")
            return
        EditPipelineDialog(
            pair_id=self._current_pair_id,
            writer=self._writer,
            pipeline_id=None,
            factory=self._factory,
            parent=self,
        ).exec()
        self._refresh_current_pair_view()

    def _on_pipeline_delete(self, pipeline_id: int) -> None:
        if self._writer is None:
            return
        confirm = QMessageBox.question(
            self, "Delete pipeline",
            "Remove this pipeline definition? Past run records are kept.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        pipelines_repo.delete_pipeline(self._writer, pipeline_id=pipeline_id)
        self._refresh_current_pair_view()

    def _on_pipeline_set_hook(self, pipeline_id: int, kind: str) -> None:
        if self._writer is None:
            return
        pipelines_repo.set_hook(self._writer, pipeline_id=pipeline_id, kind=kind, on=True)
        self._refresh_current_pair_view()
        self._toaster.info("Hook set",
                           f"Pipeline configured as {kind.replace('_', '-')}.")

    def _launch_pipeline(
        self, pipeline_id: int, *, triggered_as: str, sync_id: str | None = None,
    ) -> None:
        if self._writer is None or self._current_pair_id is None:
            return
        pair = pairs_repo.get(self._current_pair_id, factory=self._factory)
        if pair is None:
            return
        steps_db = pipelines_repo.steps_for(pipeline_id, factory=self._factory)
        if not steps_db:
            QMessageBox.information(self, "Pipeline", "This pipeline has no steps yet.")
            return
        pair_source = Path(pair.source_path)
        pair_copy = Path(pair.copy_path)
        step_defs: list[StepDef] = []
        for s in steps_db:
            cwd = pair_source if s.cwd_kind == "source" else pair_copy
            if s.cwd_subpath:
                cwd = cwd / s.cwd_subpath
            step_defs.append(StepDef(
                name=s.name,
                argv=tuple(s.argv),
                cwd=cwd,
                env_extra=dict(s.env_extra),
                timeout_s=int(s.timeout_s),
                on_fail=s.on_fail,
                inputs_globs=tuple(s.inputs_globs),
            ))
        if _thread_running(self._pipeline_thread):
            QMessageBox.information(self, "Pipeline running",
                                    "Another pipeline run is already in progress.")
            return
        self._pipeline_thread = QThread(self)
        self._pipeline_worker = PipelineWorker(
            pair_id=pair.id,
            pipeline_id=pipeline_id,
            steps=step_defs,
            pair_source=pair_source,
            pair_copy=pair_copy,
            writer=self._writer,
            triggered_as=triggered_as,
            sync_id=sync_id,
        )
        self._pipeline_worker.moveToThread(self._pipeline_thread)
        self._pipeline_thread.started.connect(self._pipeline_worker.run)
        self._pipeline_worker.finished.connect(self._on_pipeline_finished)
        self._pipeline_worker.failed.connect(self._on_pipeline_failed)
        self._pipeline_worker.finished.connect(self._pipeline_thread.quit)
        self._pipeline_worker.failed.connect(self._pipeline_thread.quit)
        self._pipeline_thread.finished.connect(self._pipeline_thread.deleteLater)
        self._pipeline_thread.start()
        self._status_bar.set_status(f"Pipeline running ({triggered_as})…")

    def _on_pipeline_finished(self, result) -> None:  # noqa: ANN001
        self._status_bar.set_status(f"Pipeline {result.status}")
        PipelineRunView(result=result, theme=self._theme, parent=self).exec()
        self._toaster.info("Pipeline finished", f"Status: {result.status}")
        self._refresh_current_pair_view()
        # Auto-rollback offer on post-sync failure.
        if result.status == "failed":
            self._maybe_offer_rollback()

    def _on_pipeline_failed(self, message: str) -> None:
        self._status_bar.set_status("Pipeline failed")
        QMessageBox.critical(self, "Pipeline failed", message)
        self._toaster.error("Pipeline failed", message)

    def _maybe_offer_rollback(self) -> None:
        if self._current_pair_id is None:
            return
        rows = syncs_repo.list_for_pair(self._current_pair_id, limit=1, factory=self._factory)
        if not rows:
            return
        last = rows[0]
        snap_id = last["snapshot_blob_id"]
        if snap_id is None:
            return
        snap = blobs_repo.get(int(snap_id), factory=self._factory)
        if snap is None:
            return
        confirm = QMessageBox.question(
            self, "Restore from pre-sync snapshot?",
            "The post-sync pipeline failed. Restore copy from the pre-sync snapshot "
            f"into a sibling directory?\n\nSnapshot: {snap.path}",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._on_history_restore(str(snap.path))

    # -- Repos / accounts -------------------------------------------------

    def _refresh_repos_view(self) -> None:
        accounts = github_accounts_repo.list_accounts(factory=self._factory)
        if not accounts:
            self._repos_view.populate([])
            return
        # Show the first account's repos. (Multi-account picker is a future polish.)
        repos = github_accounts_repo.list_repos_for(accounts[0].id, factory=self._factory)
        self._repos_view.populate([{
            "full_name": r.full_name,
            "default_branch": r.default_branch,
            "pushed_at": r.pushed_at,
            "private": r.private,
            "https_url": r.https_url,
            "ssh_url": r.ssh_url,
        } for r in repos])

    def _refresh_accounts_view(self) -> None:
        accounts = github_accounts_repo.list_accounts(factory=self._factory)
        self._accounts_view.populate([{
            "login": a.login,
            "scopes": a.scopes,
            "expires_at": a.expires_at,
        } for a in accounts])

    def _on_repos_refresh(self) -> None:
        if self._writer is None:
            return
        accounts = github_accounts_repo.list_accounts(factory=self._factory)
        if not accounts:
            QMessageBox.information(
                self, "Refresh repos",
                "Connect a GitHub account first (burger menu → Connect GitHub…).",
            )
            return
        first = accounts[0]
        if _thread_running(self._gh_thread):
            return
        self._gh_thread = QThread(self)
        worker = RefreshReposWorker(
            account_id=first.id, login=first.login, writer=self._writer,
        )
        self._gh_worker = worker
        worker.moveToThread(self._gh_thread)
        self._gh_thread.started.connect(worker.run)
        worker.finished.connect(lambda n: self._on_repos_refreshed(n, first.login))
        worker.failed.connect(lambda msg: self._on_repos_refresh_failed(msg))
        worker.finished.connect(self._gh_thread.quit)
        worker.failed.connect(self._gh_thread.quit)
        self._gh_thread.finished.connect(self._gh_thread.deleteLater)
        self._gh_thread.start()
        self._status_bar.set_status(f"Refreshing repos for {first.login}…")

    def _on_repos_refreshed(self, count: int, login: str) -> None:
        self._status_bar.set_status(f"Refreshed {count} repos for {login}")
        self._toaster.info("Repos refreshed", f"{count} repos for {login}")
        self._refresh_repos_view()

    def _on_repos_refresh_failed(self, msg: str) -> None:
        self._status_bar.set_status("Repo refresh failed")
        QMessageBox.critical(self, "Repo refresh failed", msg)

    def _on_clone_url(self, url: str) -> None:
        dialog = CloneDialog(prefill_url=url, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        request = dialog.request_value()
        if request is None:
            return
        self._launch_clone(request)

    def _launch_clone(self, request) -> None:  # noqa: ANN001
        if _thread_running(self._clone_thread):
            QMessageBox.information(self, "Clone running",
                                    "A clone is already in progress.")
            return
        progress_dialog = CloneDialog(prefill_url=request.url, parent=self)
        progress_dialog._url.setText(request.url)               # noqa: SLF001
        progress_dialog._url.setReadOnly(True)                  # noqa: SLF001
        progress_dialog._dest.setText(str(request.destination)) # noqa: SLF001
        progress_dialog._dest.setReadOnly(True)                 # noqa: SLF001
        progress_dialog._clone_btn.setEnabled(False)            # noqa: SLF001
        progress_dialog.set_progress(0, phase="starting…")
        self._clone_dialog = progress_dialog

        self._clone_thread = QThread(self)
        worker = CloneWorker(url=request.url, target=request.destination)
        self._clone_worker = worker
        worker.moveToThread(self._clone_thread)
        self._clone_thread.started.connect(worker.run)
        worker.progress.connect(lambda pct, phase: progress_dialog.set_progress(pct, phase=phase))
        worker.finished.connect(lambda result: self._on_clone_finished(result, request))
        worker.failed.connect(self._on_clone_failed)
        worker.finished.connect(self._clone_thread.quit)
        worker.failed.connect(self._clone_thread.quit)
        self._clone_thread.finished.connect(self._clone_thread.deleteLater)
        self._clone_thread.start()
        progress_dialog.show()

    def _on_clone_finished(self, result, request) -> None:  # noqa: ANN001
        if self._clone_dialog is not None:
            self._clone_dialog.set_complete(ok=result.ok,
                                            message=f"Cloned to {result.target_dir}")
            self._clone_dialog.accept()
        self._toaster.info("Clone complete", str(result.target_dir))
        # Post-clone chaining.
        if request.post_action == "register-source-new":
            self._open_register_with(source=result.target_dir, copy=None)
        elif request.post_action == "register-copy-new":
            self._open_register_with(source=None, copy=result.target_dir)

    def _on_clone_failed(self, message: str) -> None:
        if self._clone_dialog is not None:
            self._clone_dialog.set_complete(ok=False, message=message)
        QMessageBox.critical(self, "Clone failed", message)

    def _open_register_with(self, *, source: Path | None, copy: Path | None) -> None:
        dialog = RegisterPairDialog(self)
        if source is not None:
            dialog._source_input.setText(str(source))   # noqa: SLF001
            dialog._refresh_source_status()             # noqa: SLF001
        if copy is not None:
            dialog._copy_input.setText(str(copy))       # noqa: SLF001
            dialog._refresh_copy_status()               # noqa: SLF001
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        reg = dialog.registration()
        if reg is None or self._writer is None:
            return
        src_ctx = resolve_git(reg.source)
        cpy_ctx = resolve_git(reg.copy)
        pairs_repo.create(
            self._writer,
            label=reg.label,
            source_path=str(reg.source),
            copy_path=str(reg.copy),
            source_git_root=str(src_ctx.git_root) if src_ctx.git_root else None,
            source_subpath=src_ctx.subpath,
            copy_git_root=str(cpy_ctx.git_root) if cpy_ctx.git_root else None,
            copy_subpath=cpy_ctx.subpath,
        )
        self._refresh_sidebar_pairs()

    def _on_connect_github(self) -> None:
        dialog = ConnectGitHubDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.result_value()
        if result is None or self._writer is None:
            return
        scopes = ",".join(result.info.scopes)
        expires = result.info.expires_at.isoformat() if result.info.expires_at else None
        github_accounts_repo.upsert_account(
            self._writer,
            login=result.info.login,
            scopes=scopes,
            keyring_service=result.keyring_service,
            keyring_account=result.keyring_account,
            expires_at=expires,
        )
        self._refresh_accounts_view()
        QMessageBox.information(
            self, "GitHub connected",
            f"Connected as {result.info.login} ({result.info.token_kind}).\n"
            f"Token stored in Windows Credential Manager.",
        )
        self._toaster.info("GitHub connected", f"as {result.info.login}")

    def _on_test_account(self, login: str) -> None:
        if _thread_running(self._gh_thread):
            return
        self._gh_thread = QThread(self)
        worker = TestCredentialWorker(login=login)
        self._gh_worker = worker
        worker.moveToThread(self._gh_thread)
        self._gh_thread.started.connect(worker.run)
        worker.finished.connect(lambda text: QMessageBox.information(self, "Test connection", text))
        worker.failed.connect(lambda msg: QMessageBox.critical(self, "Test connection", msg))
        worker.finished.connect(self._gh_thread.quit)
        worker.failed.connect(self._gh_thread.quit)
        self._gh_thread.finished.connect(self._gh_thread.deleteLater)
        self._gh_thread.start()

    def _on_forget_account(self, login: str) -> None:
        if self._writer is None:
            return
        confirm = QMessageBox.question(
            self, "Forget account",
            f"Remove the keyring entry and account record for {login}?\n\n"
            "After this, open https://github.com/settings/tokens to revoke the PAT.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        from rabbitsync.credentials import vault
        try:
            vault.forget(service=vault.github_service(login), account=login)
        except vault.VaultError as exc:
            QMessageBox.warning(self, "Forget account", f"Keyring removal failed: {exc}")
        github_accounts_repo.delete_account(self._writer, login=login)
        self._refresh_accounts_view()

    # -- Data card --------------------------------------------------------

    def _on_sweep(self) -> None:
        if self._writer is None:
            return
        result = retention.sweep(self._writer, settings=self._settings, factory=self._factory)
        QMessageBox.information(
            self, "Sweep complete",
            f"Snapshots removed: {result.snapshots_removed} "
            f"({disk_usage.fmt(result.snapshots_freed_bytes)})\n"
            f"Quarantine entries removed: {result.quarantine_removed} "
            f"({disk_usage.fmt(result.quarantine_freed_bytes)})\n"
            f"Log files removed: {result.logs_removed}\n"
            f"Pipeline runs removed: {result.pipeline_runs_removed}\n"
            f"Journal entries removed: {result.journals_removed}",
        )
        self._refresh_current_pair_view()

    def _on_verify_audit(self) -> None:
        ok, broken = receipts_repo.verify_chain(factory=self._factory)
        if ok:
            QMessageBox.information(self, "Audit log", "Receipt chain is intact.")
        else:
            QMessageBox.warning(
                self, "Audit log broken",
                f"First broken sync_id: {broken}",
            )

    def _on_export(self) -> None:
        ExportBackupDialog(self).exec()

    def _on_reveal(self) -> None:
        from rabbitsync.paths import data_dir
        from rabbitsync.ui.widgets.path_chip import PathChip

        chip = PathChip(label="", path=data_dir(), parent=self)
        chip._reveal()  # noqa: SLF001
        chip.deleteLater()

    def _on_history_restore(self, snapshot_path: str) -> None:
        if self._current_pair_id is None:
            return
        pair = pairs_repo.get(self._current_pair_id, factory=self._factory)
        if pair is None:
            return
        from rabbitsync.core.backup import restore_to_sibling
        try:
            target = restore_to_sibling(Path(snapshot_path), copy_folder=Path(pair.copy_path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Restore failed", str(exc))
            return
        QMessageBox.information(
            self, "Restored",
            f"Snapshot extracted to:\n{target}\n\n"
            "The live copy folder was not modified.",
        )

    # -- Settings ---------------------------------------------------------

    def _on_settings(self) -> None:
        if self._writer is None:
            return
        if SettingsDialog(writer=self._writer, parent=self).exec() == 1:
            self._settings = load_settings(factory=self._factory)
            self._auto_check_timer.setInterval(self._settings.sync_check_interval_s * 1000)
            QMessageBox.information(
                self, "Settings",
                "Some changes (theme, palette) take effect on next launch.",
            )

    def _on_about(self) -> None:
        QMessageBox.about(
            self, "About RabbitSync",
            f"<b>RabbitSync</b> {__version__}<br>"
            "Safe source-to-copy folder synchronization with git management "
            "and CI/CD pipelines, for Windows.<br><br>"
            "Built with PySide 6 on Python 3.13.",
        )

    # -- Auto sync-check tick --------------------------------------------

    def _on_auto_check_tick(self) -> None:
        # Don't churn while sync/pipeline/clone are running.
        if any(_thread_running(t) for t in (
            self._sync_thread, self._pipeline_thread, self._clone_thread, self._gh_thread,
        )):
            return
        # Skip when window isn't focused (per design — saves CPU).
        app = QGuiApplication.instance()
        if app is not None and not self.isActiveWindow():
            return
        if self._workspace_stack.currentWidget() is self._pair_view:
            self._refresh_current_pair_view()

    # -- Recovery prompt --------------------------------------------------

    def _maybe_show_recovery_prompt(self) -> None:
        if self._writer is None:
            return
        ids = list(journal_mod.open_unfinished_syncs(self._writer))
        if not ids:
            return
        RecoveryPromptDialog(
            unfinished_sync_ids=ids, writer=self._writer, parent=self,
        ).exec()

    # -- Per-pair settings persistence ------------------------------------

    def _on_pair_settings_changed(self) -> None:
        """User toggled commit-on-sync, auto-push, or target-branch on the Sync tab."""
        if self._writer is None or self._current_pair_id is None:
            return
        try:
            pairs_repo.update_ui_state(
                self._writer,
                pair_id=self._current_pair_id,
                commit_on_sync=self._pair_view.commit_on_sync,
                auto_push=self._pair_view.auto_push,
                target_branch=self._pair_view.target_branch,
            )
        except Exception as exc:  # noqa: BLE001
            _log.error("ui.pair.settings.persist_failed",
                       pair_id=self._current_pair_id, error=str(exc))

    def _on_pair_view_tab_changed(self, _index: int) -> None:
        """Refresh the diff when the user clicks between Overview/Sync/etc."""
        if self._suppress_tab_refresh:
            return
        if self._current_pair_id is None:
            return
        if _thread_running(self._sync_thread):
            return
        self._refresh_current_pair_view()

    def _persist_last_pair_id(self, pair_id: str | None) -> None:
        if self._writer is None:
            return
        if self._settings.last_pair_id == pair_id:
            return
        self._settings.last_pair_id = pair_id
        try:
            save_settings(self._writer, self._settings)
        except Exception as exc:  # noqa: BLE001
            _log.error("ui.settings.persist_failed", error=str(exc))

    def _maybe_restore_last_pair(self) -> None:
        last = self._settings.last_pair_id
        if not last:
            return
        pair = pairs_repo.get(last, factory=self._factory)
        if pair is None:
            # Stale id — forget it so we don't keep retrying.
            self._persist_last_pair_id(None)
            return
        self._on_sidebar_item_selected(SidebarView.PAIRS, last)

    # -- Log dock toggle --------------------------------------------------

    def _toggle_log_dock(self) -> None:
        self._log_dock.setVisible(not self._log_dock.isVisible())


__all__ = ["MainWindow"]

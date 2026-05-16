"""Sync tab — left: change list, right: settings/conflicts/secrets, bottom: actions."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.core.diff import DiffPlan
from rabbitsync.ui import icons
from rabbitsync.ui.panels.sync_changes_list import SyncChangesList
from rabbitsync.ui.panels.sync_settings_pane import SyncSettingsPane
from rabbitsync.ui.theme import DARK, LIGHT, Radius, Spacing


_PHASE_LABEL = {
    "preflight": "Preflight checks…",
    "diff": "Scanning folders…",
    "snapshot": "Taking pre-sync snapshot…",
    "apply": "Applying changes",
    "verify": "Verifying written files…",
    "commit": "Committing on copy…",
    "push": "Pushing to remote…",
    "done": "Done",
}


class _ProgressBanner(QFrame):
    """Slim top-of-tab progress strip; hidden when no sync is running."""

    def __init__(self, *, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self.setObjectName("SyncProgressBanner")
        self.setStyleSheet(
            f"#SyncProgressBanner {{ "
            f"background-color: {palette.accent_subtle}; "
            f"border: 1px solid {palette.border_subtle}; "
            f"border-radius: {Radius.MD}px; }} "
            f"#SyncProgressBanner QLabel {{ color: {palette.fg}; "
            f"background: transparent; }}"
        )

        self._phase_label = QLabel("Starting…", self)
        self._phase_label.setProperty("role", "header")
        self._bar = QProgressBar(self)
        self._bar.setRange(0, 0)
        self._bar.setMaximumHeight(8)
        self._bar.setTextVisible(False)
        self._file_label = QLabel("", self)
        self._file_label.setProperty("role", "muted")
        self._file_label.setStyleSheet("font-family: Cascadia Code, Consolas, monospace;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.XS)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(Spacing.SM)
        top.addWidget(self._phase_label, 1)
        layout.addLayout(top)
        layout.addWidget(self._bar)
        layout.addWidget(self._file_label)

    def update(
        self, *, phase: str, step_no: int = 0, total: int = 0, rel_path: str | None = None,
    ) -> None:
        base = _PHASE_LABEL.get(phase, phase.capitalize())
        if phase == "apply" and total > 0:
            self._bar.setRange(0, total)
            self._bar.setValue(step_no)
            self._phase_label.setText(f"{base} — {step_no}/{total}")
        else:
            self._bar.setRange(0, 0)
            self._phase_label.setText(base)
        self._file_label.setText(rel_path or "")


class SyncTab(QFrame):
    """The Sync tab body."""

    def __init__(
        self,
        *,
        on_preview_diff: Callable[[], None],
        on_sync_clicked: Callable[[], None],
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self.setStyleSheet(
            f"QFrame {{ background-color: {palette.bg}; }}"
        )

        self._changes = SyncChangesList(theme=theme, parent=self)
        self._settings = SyncSettingsPane(theme=theme, parent=self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._changes)
        splitter.addWidget(self._settings)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        # Bottom action bar
        bottom = QFrame(self)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(Spacing.LG, Spacing.SM, Spacing.LG, Spacing.SM)
        bottom_layout.setSpacing(Spacing.MD)

        preview_btn = QPushButton("Preview Diff…", bottom)
        preview_btn.setIcon(icons.Icons.preview_diff())
        preview_btn.setIconSize(QSize(14, 14))
        preview_btn.setMinimumHeight(24)
        preview_btn.clicked.connect(on_preview_diff)

        sync_btn = QPushButton("Sync…", bottom)
        sync_btn.setIcon(icons.Icons.sync())
        sync_btn.setIconSize(QSize(14, 14))
        sync_btn.setMinimumHeight(24)
        sync_btn.clicked.connect(on_sync_clicked)

        bottom_layout.addWidget(preview_btn)
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(sync_btn)

        self._progress_banner = _ProgressBanner(theme=theme, parent=self)
        self._progress_banner.hide()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, 0)
        outer.setSpacing(Spacing.SM)
        outer.addWidget(self._progress_banner)
        outer.addWidget(splitter, 1)
        outer.addWidget(bottom)

    def populate_from_plan(self, plan: DiffPlan) -> None:
        self._changes.populate(plan)
        self._settings.show_summary(
            adds=len(plan.adds),
            modifies=len(plan.modifies),
            quarantines=len(plan.quarantines),
        )

    # -- Progress banner -------------------------------------------------

    def show_progress(self) -> None:
        self._progress_banner.update(phase="preflight")
        self._progress_banner.show()

    def update_progress(
        self, *, phase: str, step_no: int = 0, total: int = 0, rel_path: str | None = None,
    ) -> None:
        self._progress_banner.update(
            phase=phase, step_no=step_no, total=total, rel_path=rel_path,
        )

    def hide_progress(self) -> None:
        self._progress_banner.hide()


__all__ = ["SyncTab"]

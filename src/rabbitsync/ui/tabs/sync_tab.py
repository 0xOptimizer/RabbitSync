"""Sync tab — left: change list, right: settings/conflicts/secrets, bottom: actions."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.core.diff import DiffPlan
from rabbitsync.ui import icons
from rabbitsync.ui.panels.sync_changes_list import SyncChangesList
from rabbitsync.ui.panels.sync_settings_pane import SyncSettingsPane
from rabbitsync.ui.theme import DARK, LIGHT, Spacing


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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(splitter, 1)
        outer.addWidget(bottom)

    def populate_from_plan(self, plan: DiffPlan) -> None:
        self._changes.populate(plan)
        self._settings.show_summary(
            adds=len(plan.adds),
            modifies=len(plan.modifies),
            quarantines=len(plan.quarantines),
        )


__all__ = ["SyncTab"]

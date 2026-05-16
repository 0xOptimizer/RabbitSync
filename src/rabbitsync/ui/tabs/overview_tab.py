"""Overview tab — high-level summary of what would change.

Three count cards (New / Modified / Quarantined) on top, a filename-only list
with a state badge below, action buttons at the bottom. No diff content —
that's what the Sync tab is for.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.core.diff import DiffPlan
from rabbitsync.ui import icons
from rabbitsync.ui.panels.sync_settings_pane import SyncSettingsPane
from rabbitsync.ui.theme import DARK, LIGHT, Palette, Radius, Spacing, Typography


class _CountCard(QFrame):
    """A single big-number card. Colored by accent."""

    def __init__(
        self,
        *,
        title: str,
        accent: str,
        palette: Palette,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("OverviewCard")
        self.setStyleSheet(
            f"#OverviewCard {{ "
            f"background-color: {palette.bg_subtle}; "
            f"border: 1px solid {palette.border_subtle}; "
            f"border-radius: {Radius.LG}px; }} "
            f"#OverviewCard QLabel {{ background: transparent; }}"
        )

        self._title = QLabel(title, self)
        self._title.setStyleSheet(
            f"color: {palette.fg_muted}; "
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"font-weight: 600; "
            f"letter-spacing: 0.5px;"
        )

        self._count = QLabel("0", self)
        self._count.setStyleSheet(
            f"color: {accent}; "
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: 28pt; "
            f"font-weight: 700;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        layout.setSpacing(Spacing.XS)
        layout.addWidget(self._title)
        layout.addWidget(self._count)
        layout.addStretch(1)

    def set_count(self, n: int) -> None:
        self._count.setText(str(n))


class _ChangesList(QTreeWidget):
    """Two columns: Path (basename, full path as tooltip) + State badge."""

    HEADERS = ("Path", "State")

    def __init__(self, *, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(self.HEADERS)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.setStyleSheet(
            f"QTreeWidget {{ background-color: {palette.bg}; "
            f"color: {palette.fg}; "
            f"alternate-background-color: {palette.bg_subtle}; "
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"border: none; }}"
        )
        self._palette = palette

    def populate(self, plan: DiffPlan) -> None:
        self.clear()
        for entry in plan.adds:
            self._row(entry.rel_path, "Added", self._palette.success)
        for entry in plan.modifies:
            self._row(entry.rel_path, "Modified", self._palette.warning)
        for entry in plan.quarantines:
            self._row(entry.rel_path, "Quarantined", self._palette.danger)

    def _row(self, rel_path: str, state: str, color: str) -> None:
        basename = PurePosixPath(rel_path).name or rel_path
        item = QTreeWidgetItem([basename, state])
        item.setToolTip(0, rel_path)
        item.setForeground(1, QColor(color))
        self.addTopLevelItem(item)


class OverviewTab(QFrame):
    """First-tab landing view for a selected pair."""

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
        self.setStyleSheet(f"QFrame {{ background-color: {palette.bg}; }}")

        self._new_card = _CountCard(
            title="NEW", accent=palette.success, palette=palette, parent=self,
        )
        self._mod_card = _CountCard(
            title="MODIFIED", accent=palette.warning, palette=palette, parent=self,
        )
        self._quar_card = _CountCard(
            title="QUARANTINED", accent=palette.danger, palette=palette, parent=self,
        )

        cards_row = QHBoxLayout()
        cards_row.setContentsMargins(0, 0, 0, 0)
        cards_row.setSpacing(Spacing.MD)
        cards_row.addWidget(self._new_card, 1)
        cards_row.addWidget(self._mod_card, 1)
        cards_row.addWidget(self._quar_card, 1)

        section_title = QLabel("Changes", self)
        section_title.setProperty("role", "header")
        section_title.setStyleSheet(
            f"color: {palette.fg}; "
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.HEADER_PT}pt; "
            f"font-weight: 600;"
        )

        self._list = _ChangesList(palette=palette, parent=self)
        self._settings = SyncSettingsPane(theme=theme, parent=self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._list)
        splitter.addWidget(self._settings)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        # Bottom action bar.
        bottom = QFrame(self)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, Spacing.SM, 0, Spacing.SM)
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
        outer.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.MD)
        outer.setSpacing(Spacing.MD)
        outer.addLayout(cards_row)
        outer.addWidget(section_title)
        outer.addWidget(splitter, 1)
        outer.addWidget(bottom)

    def populate_from_plan(self, plan: DiffPlan) -> None:
        self.set_counts(
            adds=len(plan.adds),
            modifies=len(plan.modifies),
            quarantines=len(plan.quarantines),
        )
        self._list.populate(plan)

    def set_counts(self, *, adds: int, modifies: int, quarantines: int) -> None:
        """Update only the cards + settings summary, without touching the list.

        Used to show cached counts immediately on pair selection.
        """
        self._new_card.set_count(adds)
        self._mod_card.set_count(modifies)
        self._quar_card.set_count(quarantines)
        self._settings.show_summary(adds=adds, modifies=modifies, quarantines=quarantines)

    def clear_summary(self) -> None:
        self.set_counts(adds=0, modifies=0, quarantines=0)
        self._list.clear()

    @property
    def settings_pane(self) -> SyncSettingsPane:
        return self._settings


__all__ = ["OverviewTab"]

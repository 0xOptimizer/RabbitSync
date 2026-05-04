"""History & Data tab — sync timeline left, data management right."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
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

from rabbitsync.ui import icons
from rabbitsync.ui.theme import DARK, LIGHT, Spacing, Typography


class SyncTimeline(QTreeWidget):
    HEADERS = ("When", "Δ files", "Audit", "Restore")

    def __init__(self, *, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self.setHeaderLabels(self.HEADERS)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setStyleSheet(
            f"QTreeWidget {{ background-color: {palette.bg}; "
            f"color: {palette.fg}; "
            f"alternate-background-color: {palette.bg_subtle}; "
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"border: none; }}"
        )
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)


class DataPane(QFrame):
    def __init__(
        self,
        *,
        on_sweep: Callable[[], None],
        on_verify_audit: Callable[[], None],
        on_export: Callable[[], None],
        on_reveal: Callable[[], None],
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self.setStyleSheet(
            f"QFrame {{ background-color: {palette.bg_subtle}; "
            f"border-left: 1px solid {palette.border}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        title = QLabel("Data", self)
        title.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.HEADER_PT}pt; "
            f"font-weight: 600; "
            f"color: {palette.fg};"
        )
        layout.addWidget(title)

        self._stats_label = QLabel("DB: — | snapshots: — | quarantine: — | logs: —", self)
        self._stats_label.setStyleSheet(
            f"font-family: {Typography.MONO_FAMILY}; "
            f"font-size: {Typography.MONO_PT}pt; "
            f"color: {palette.fg};"
        )
        layout.addWidget(self._stats_label)

        layout.addSpacing(Spacing.SM)

        for label, icon_fn, handler in [
            ("Sweep now", icons.Icons.sweep, on_sweep),
            ("Verify audit log", icons.Icons.verify, on_verify_audit),
            ("Export…", icons.Icons.export_, on_export),
            ("Reveal in Explorer", icons.Icons.reveal, on_reveal),
        ]:
            btn = QPushButton(label, self)
            btn.setIcon(icon_fn())
            btn.setMinimumHeight(22)
            btn.clicked.connect(handler)
            layout.addWidget(btn)

        layout.addStretch(1)

    def set_stats(self, *, db: str, snapshots: str, quarantine: str, pipelines: str, logs: str) -> None:
        self._stats_label.setText(
            f"DB: {db}\nsnapshots: {snapshots}\nquarantine: {quarantine}\n"
            f"pipelines: {pipelines}\nlogs: {logs}"
        )


class HistoryDataTab(QFrame):
    def __init__(
        self,
        *,
        on_sweep: Callable[[], None],
        on_verify_audit: Callable[[], None],
        on_export: Callable[[], None],
        on_reveal: Callable[[], None],
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self.setStyleSheet(f"QFrame {{ background-color: {palette.bg}; }}")

        self._timeline = SyncTimeline(theme=theme, parent=self)
        self._data_pane = DataPane(
            on_sweep=on_sweep,
            on_verify_audit=on_verify_audit,
            on_export=on_export,
            on_reveal=on_reveal,
            theme=theme,
            parent=self,
        )

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._timeline)
        splitter.addWidget(self._data_pane)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter)

    def populate_timeline(self, rows: list[tuple[str, str, str]]) -> None:
        self._timeline.clear()
        for when, delta, audit in rows:
            it = QTreeWidgetItem([when, delta, audit, ""])
            self._timeline.addTopLevelItem(it)

    def set_data_stats(self, **kwargs) -> None:  # noqa: ANN003
        self._data_pane.set_stats(**kwargs)


__all__ = ["DataPane", "HistoryDataTab", "SyncTimeline"]

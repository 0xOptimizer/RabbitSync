"""Sync tab — left column: file change list with per-row checkboxes."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem, QWidget

from rabbitsync.core.diff import DiffPlan
from rabbitsync.ui.theme import DARK, LIGHT, Typography


class SyncChangesList(QTreeWidget):
    """Three columns: action, path, size delta. Sortable; checkbox per row."""

    HEADERS = ("", "Action", "Path", "Size")

    def __init__(self, *, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self.setHeaderLabels(self.HEADERS)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.setStyleSheet(
            f"QTreeWidget {{ background-color: {palette.bg}; "
            f"color: {palette.fg}; "
            f"alternate-background-color: {palette.bg_subtle}; "
            f"font-family: {Typography.MONO_FAMILY}; "
            f"font-size: {Typography.MONO_PT}pt; "
            f"border: none; }}"
        )

    def populate(self, plan: DiffPlan) -> None:
        self.clear()
        for entry in plan.adds:
            self._row("add", "+", entry.rel_path, entry.source_size, entry.copy_size)
        for entry in plan.modifies:
            self._row("modify", "~", entry.rel_path, entry.source_size, entry.copy_size)
        for entry in plan.quarantines:
            self._row("quarantine", "-", entry.rel_path, entry.source_size, entry.copy_size)

    def _row(self, kind: str, sign: str, rel_path: str, src_size, cpy_size) -> None:  # noqa: ANN001
        item = QTreeWidgetItem(["", sign, rel_path, _fmt_size(src_size, cpy_size)])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked)
        item.setData(2, Qt.ItemDataRole.UserRole, kind)
        self.addTopLevelItem(item)

    def selected_paths(self) -> list[str]:
        out: list[str] = []
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item is None:
                continue
            if item.checkState(0) == Qt.CheckState.Checked:
                out.append(item.text(2))
        return out


def _fmt_size(src: int | None, cpy: int | None) -> str:
    if src is None:
        return f"-{_b(cpy or 0)}"
    if cpy is None:
        return f"+{_b(src)}"
    return _b(src)


def _b(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


__all__ = ["SyncChangesList"]

"""Full-screen per-file diff viewer.

Shows the change list on the left; selecting a file renders a unified diff
against the source's current content (or a placeholder when the file is
either being added or quarantined).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.core.diff import DiffPlan
from rabbitsync.ui.theme import DARK, LIGHT, Spacing, Typography


_BINARY_LIMIT = 256 * 1024  # don't try to diff anything larger or non-text


class DiffPreviewDialog(QDialog):
    def __init__(
        self,
        *,
        plan: DiffPlan,
        source_folder: Path,
        copy_folder: Path,
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self.setWindowTitle("Preview diff")
        self.setModal(True)
        self.resize(1200, 800)
        self._source = source_folder
        self._copy = copy_folder

        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(("Action", "Path"))
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tree.itemSelectionChanged.connect(self._on_selection)
        self._tree.setStyleSheet(
            f"QTreeWidget {{ background-color: {palette.bg}; "
            f"alternate-background-color: {palette.bg_subtle}; "
            f"color: {palette.fg}; "
            f"font-family: {Typography.MONO_FAMILY}; "
            f"font-size: {Typography.MONO_PT}pt; }}"
        )
        for entry in plan.adds:
            self._row("add", entry.rel_path)
        for entry in plan.modifies:
            self._row("modify", entry.rel_path)
        for entry in plan.quarantines:
            self._row("quarantine", entry.rel_path)

        self._view = QPlainTextEdit(self)
        self._view.setReadOnly(True)
        self._view.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {palette.bg}; "
            f"color: {palette.fg}; "
            f"font-family: {Typography.MONO_FAMILY}; "
            f"font-size: {Typography.MONO_PT}pt; }}"
        )

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._tree)
        splitter.addWidget(self._view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)
        layout.addWidget(splitter, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        for b in buttons.buttons():
            b.clicked.connect(self.accept)
        layout.addWidget(buttons)

        if self._tree.topLevelItemCount() > 0:
            self._tree.setCurrentItem(self._tree.topLevelItem(0))

        layout_h = QHBoxLayout()  # reserved for future toolbar
        layout_h.setContentsMargins(0, 0, 0, 0)

    def _row(self, action: str, rel_path: str) -> None:
        item = QTreeWidgetItem([action, rel_path])
        item.setData(0, Qt.ItemDataRole.UserRole, action)
        item.setData(1, Qt.ItemDataRole.UserRole, rel_path)
        self._tree.addTopLevelItem(item)

    def _on_selection(self) -> None:
        items = self._tree.selectedItems()
        if not items:
            self._view.clear()
            return
        item = items[0]
        action = item.data(0, Qt.ItemDataRole.UserRole)
        rel_path = item.data(1, Qt.ItemDataRole.UserRole)
        self._view.setPlainText(self._build_diff(action, rel_path))

    def _build_diff(self, action: str, rel_path: str) -> str:
        src_path = self._source / rel_path
        cpy_path = self._copy / rel_path
        if action == "add":
            return self._render_one_side("source", src_path, prefix="+ ")
        if action == "quarantine":
            return self._render_one_side("copy", cpy_path, prefix="- ")
        # modify -> two-side
        src = self._read_text_or_marker(src_path)
        cpy = self._read_text_or_marker(cpy_path)
        if isinstance(src, str) and isinstance(cpy, str):
            import difflib

            return "".join(
                difflib.unified_diff(
                    cpy.splitlines(keepends=True),
                    src.splitlines(keepends=True),
                    fromfile=f"copy/{rel_path}",
                    tofile=f"source/{rel_path}",
                )
            ) or "(no textual difference)"
        # one or both binary/too-big
        return f"(diff not shown: {src if not isinstance(src, str) else cpy})"

    def _render_one_side(self, label: str, path: Path, *, prefix: str) -> str:
        text = self._read_text_or_marker(path)
        if not isinstance(text, str):
            return f"({label} {path}: {text})"
        out: list[str] = [f"--- {label}/{path.name}"]
        out.extend(prefix + line for line in text.splitlines())
        return "\n".join(out)

    def _read_text_or_marker(self, path: Path) -> str | str:
        try:
            if not path.is_file():
                return "missing or not a regular file"
            if path.stat().st_size > _BINARY_LIMIT:
                return f"file is {path.stat().st_size} bytes; too large to preview"
            data = path.read_bytes()
            if b"\x00" in data:
                return "binary file"
            return data.decode("utf-8", errors="replace")
        except OSError as exc:
            return f"could not read: {exc}"


__all__ = ["DiffPreviewDialog"]

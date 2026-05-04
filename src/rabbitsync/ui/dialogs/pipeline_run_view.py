"""Pipeline run output viewer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.core.pipeline import RunResult
from rabbitsync.ui.theme import DARK, LIGHT, Spacing, Typography


class PipelineRunView(QDialog):
    def __init__(
        self,
        *,
        result: RunResult,
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self.setWindowTitle(f"Pipeline run · {result.status}")
        self.setModal(True)
        self.resize(1080, 720)

        tree = QTreeWidget(self)
        tree.setHeaderLabels(("Step", "Status", "Exit", "Duration"))
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        for sr in result.steps:
            it = QTreeWidgetItem([
                sr.name, sr.status,
                str(sr.exit_code) if sr.exit_code is not None else "—",
                f"{sr.duration_s:.2f}s",
            ])
            it.setData(0, Qt.ItemDataRole.UserRole, sr)
            tree.addTopLevelItem(it)
        tree.itemSelectionChanged.connect(lambda: self._show_selected(tree))

        self._stdout = QPlainTextEdit(self)
        self._stdout.setReadOnly(True)
        self._stdout.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {palette.bg}; "
            f"color: {palette.fg}; "
            f"font-family: {Typography.MONO_FAMILY}; "
            f"font-size: {Typography.MONO_PT}pt; }}"
        )

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.addWidget(tree)
        splitter.addWidget(self._stdout)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)
        layout.addWidget(splitter, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        for b in buttons.buttons():
            b.clicked.connect(self.accept)
        layout.addWidget(buttons)

        if tree.topLevelItemCount() > 0:
            tree.setCurrentItem(tree.topLevelItem(0))

    def _show_selected(self, tree: QTreeWidget) -> None:
        items = tree.selectedItems()
        if not items:
            self._stdout.clear()
            return
        sr = items[0].data(0, Qt.ItemDataRole.UserRole)
        text_parts: list[str] = []
        if sr.stdout_path is not None and isinstance(sr.stdout_path, Path) and sr.stdout_path.is_file():
            text_parts.append("--- stdout ---")
            text_parts.append(_safe_read(sr.stdout_path))
        if sr.stderr_path is not None and isinstance(sr.stderr_path, Path) and sr.stderr_path.is_file():
            text_parts.append("\n--- stderr ---")
            text_parts.append(_safe_read(sr.stderr_path))
        self._stdout.setPlainText("\n".join(text_parts) or "(no output captured)")


def _safe_read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"(could not read {p}: {exc})"


__all__ = ["PipelineRunView"]

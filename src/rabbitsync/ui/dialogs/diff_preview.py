"""Full-screen per-file diff viewer with hard caps so huge diffs don't crash.

The change list is rendered through a custom :class:`QAbstractTableModel`
(via ``QTableView``) so a 50 000-row diff plan opens instantly — no
per-row widget allocation, no per-insert layout pass.

Selecting a file generates its diff lazily, capped at a fixed line+byte
budget. Anything beyond the cap is replaced with a clear truncation marker.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.core.diff import DiffPlan
from rabbitsync.ui import icons
from rabbitsync.ui.theme import DARK, LIGHT, Spacing


# Per-file caps — keeping these tight is what makes huge diffs survivable.
_BINARY_LIMIT = 256 * 1024     # don't preview files larger than this
_DIFF_LINE_LIMIT = 5_000       # cap rendered diff to N lines
_DIFF_BYTE_LIMIT = 1_000_000   # cap rendered diff to ~1 MB of text


@dataclass(frozen=True)
class _Row:
    action: str   # 'add' | 'modify' | 'quarantine'
    rel_path: str


class _DiffPlanModel(QAbstractTableModel):
    """Tiny tabular model wrapping a list of (action, rel_path) rows.

    O(1) row access; populating from a 50k-row plan is microseconds vs
    seconds for the equivalent QTreeWidget.
    """

    HEADERS = ("Action", "Path")

    def __init__(
        self,
        rows: list[_Row],
        *,
        palette,  # noqa: ANN001
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._rows = rows
        self._palette = palette

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(self._rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 2

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: ANN201
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        if 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: ANN201
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return _ACTION_GLYPH.get(row.action, row.action)
            return row.rel_path
        if role == Qt.ItemDataRole.ForegroundRole and col == 0:
            return QColor(_color_for_action(row.action, self._palette))
        if role == Qt.ItemDataRole.UserRole:
            return (row.action, row.rel_path)
        if role == Qt.ItemDataRole.TextAlignmentRole and col == 0:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def row_at(self, index: int) -> _Row | None:
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None


_ACTION_GLYPH: dict[str, str] = {
    "add": "+",
    "modify": "~",
    "quarantine": "−",
}


def _color_for_action(action: str, palette) -> str:  # noqa: ANN001
    if action == "add":
        return palette.success
    if action == "quarantine":
        return palette.danger
    return palette.warning


class DiffPreviewDialog(QDialog):
    """Full-screen diff viewer with optional Sync button.

    Pass ``on_sync`` to add a Sync button to the footer that closes the
    dialog and invokes the callback.
    """

    def __init__(
        self,
        *,
        plan: DiffPlan,
        source_folder: Path,
        copy_folder: Path,
        on_sync: Callable[[], None] | None = None,
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview diff")
        self.setModal(True)
        self.resize(1100, 640)
        self._source = source_folder
        self._copy = copy_folder
        self._on_sync = on_sync
        self._pending_token = 0
        palette = DARK if theme == "dark" else LIGHT

        # Build the row list in one pass — O(N), no widget allocation.
        rows: list[_Row] = []
        rows.extend(_Row("add", e.rel_path) for e in plan.adds)
        rows.extend(_Row("modify", e.rel_path) for e in plan.modifies)
        rows.extend(_Row("quarantine", e.rel_path) for e in plan.quarantines)

        self._model = _DiffPlanModel(rows, palette=palette, parent=self)
        self._table = QTableView(self)
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.verticalHeader().setVisible(False)
        # Uniform row height + a fixed action column = constant-time layout.
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self._table.verticalHeader().setDefaultSectionSize(20)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 56)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.selectionModel().selectionChanged.connect(self._on_selection)

        self._view = QPlainTextEdit(self)
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._view.setMaximumBlockCount(_DIFF_LINE_LIMIT + 32)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._table)
        splitter.addWidget(self._view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)
        layout.addWidget(splitter, 1)

        # Footer.
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        if on_sync is not None:
            sync_btn = QPushButton("Sync…", self)
            sync_btn.setIcon(icons.Icons.sync())
            sync_btn.setIconSize(QSize(14, 14))
            sync_btn.setProperty("role", "primary")
            sync_btn.setDefault(True)
            sync_btn.clicked.connect(self._on_sync_clicked)
            buttons.addButton(sync_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        for b in buttons.buttons():
            if b.text() == "Close":
                b.clicked.connect(self.reject)
        layout.addWidget(buttons)

        # Auto-select the first row so the diff pane isn't empty.
        if self._model.rowCount() > 0:
            first = self._model.index(0, 0)
            self._table.setCurrentIndex(first)

    # -- Internals --------------------------------------------------------

    def _on_selection(self, *_args: object) -> None:
        idx = self._table.currentIndex()
        if not idx.isValid():
            self._view.clear()
            return
        row = self._model.row_at(idx.row())
        if row is None:
            return

        # Show a placeholder immediately, then render on the next event tick.
        self._view.setPlainText("(generating diff…)")
        self._pending_token += 1
        token = self._pending_token
        QTimer.singleShot(0, lambda: self._render(token, row.action, row.rel_path))

    def _render(self, token: int, action: str, rel_path: str) -> None:
        if token != self._pending_token:
            return
        text = self._build_diff_capped(action, rel_path)
        if token != self._pending_token:
            return
        self._view.setPlainText(text)

    def _build_diff_capped(self, action: str, rel_path: str) -> str:
        src_path = self._source / rel_path
        cpy_path = self._copy / rel_path
        if action == "add":
            return self._render_one_side("source", src_path, prefix="+ ", header_path=rel_path)
        if action == "quarantine":
            return self._render_one_side("copy", cpy_path, prefix="- ", header_path=rel_path)

        src = self._read_text_or_marker(src_path)
        cpy = self._read_text_or_marker(cpy_path)
        if not isinstance(src, str) or not isinstance(cpy, str):
            other = src if not isinstance(src, str) else cpy
            return f"(diff not shown: {other})"
        if src == cpy:
            return "(no textual difference)"

        return self._unified_diff_capped(
            cpy, src,
            from_label=f"copy/{rel_path}",
            to_label=f"source/{rel_path}",
        )

    def _render_one_side(
        self, label: str, path: Path, *, prefix: str, header_path: str,
    ) -> str:
        text = self._read_text_or_marker(path)
        if not isinstance(text, str):
            return f"({label} {header_path}: {text})"
        out: list[str] = [f"--- {label}/{header_path}"]
        line_budget = _DIFF_LINE_LIMIT
        byte_budget = _DIFF_BYTE_LIMIT
        rendered = 0
        total = 0
        for line in text.splitlines():
            total += 1
            if line_budget <= 0 or byte_budget <= 0:
                continue
            chunk = prefix + line
            if len(chunk) > byte_budget:
                break
            out.append(chunk)
            line_budget -= 1
            byte_budget -= len(chunk)
            rendered += 1
        if rendered < total:
            out.append(f"\n[diff truncated: showing {rendered} of {total} lines]")
        return "\n".join(out)

    @staticmethod
    def _unified_diff_capped(
        from_text: str, to_text: str, *, from_label: str, to_label: str,
    ) -> str:
        from_lines = from_text.splitlines(keepends=True)
        to_lines = to_text.splitlines(keepends=True)
        if len(from_lines) + len(to_lines) > 200_000:
            return (
                f"(diff suppressed: combined input is {len(from_lines):,} + "
                f"{len(to_lines):,} lines — too large to render in-app. "
                "Use an external diff tool.)"
            )
        out: list[str] = []
        line_budget = _DIFF_LINE_LIMIT
        byte_budget = _DIFF_BYTE_LIMIT
        truncated = False
        for chunk in difflib.unified_diff(
            from_lines, to_lines,
            fromfile=from_label, tofile=to_label, n=3,
        ):
            if line_budget <= 0 or byte_budget <= 0:
                truncated = True
                break
            piece = chunk if chunk.endswith("\n") else chunk + "\n"
            if len(piece) > byte_budget:
                truncated = True
                break
            out.append(piece)
            line_budget -= 1
            byte_budget -= len(piece)
        if not out:
            return "(no textual difference)"
        if truncated:
            out.append(
                f"\n[diff truncated: kept {_DIFF_LINE_LIMIT - line_budget} hunk lines, "
                f"~{_DIFF_BYTE_LIMIT - byte_budget} bytes; "
                "open an external tool for the full diff]\n"
            )
        return "".join(out)

    @staticmethod
    def _read_text_or_marker(path: Path) -> str:
        try:
            if not path.is_file():
                return "missing or not a regular file"
            size = path.stat().st_size
            if size > _BINARY_LIMIT:
                return f"file is {size:,} bytes; too large to preview"
            data = path.read_bytes()
            if b"\x00" in data:
                return "binary file"
            return data.decode("utf-8", errors="replace")
        except OSError as exc:
            return f"could not read: {exc}"

    def _on_sync_clicked(self) -> None:
        self.accept()
        if self._on_sync is not None:
            self._on_sync()


__all__ = ["DiffPreviewDialog"]

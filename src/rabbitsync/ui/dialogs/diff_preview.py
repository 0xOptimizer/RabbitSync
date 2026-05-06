"""Full-screen per-file diff viewer with hard caps so huge diffs don't crash.

Selecting a file generates its diff lazily, capped at a fixed line+byte budget.
Anything beyond the cap is replaced with a clear truncation marker — better
than freezing the UI on a 50 MB file.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.core.diff import DiffPlan
from rabbitsync.ui import icons
from rabbitsync.ui.theme import Spacing


# Per-file caps — keeping these tight is what makes huge diffs survivable.
_BINARY_LIMIT = 256 * 1024     # don't preview files larger than this
_DIFF_LINE_LIMIT = 5_000       # cap rendered diff to N lines
_DIFF_BYTE_LIMIT = 1_000_000   # cap rendered diff to ~1 MB of text


class DiffPreviewDialog(QDialog):
    """Full-screen diff viewer with optional Sync button.

    Pass ``on_sync`` to add a Sync button to the footer that closes the
    dialog and invokes the callback (typically wired to the main window's
    sync-clicked handler).
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
        _ = theme
        self.setWindowTitle("Preview diff")
        self.setModal(True)
        self.resize(1100, 640)
        self._source = source_folder
        self._copy = copy_folder
        self._on_sync = on_sync
        # Pending render guard: if the user clicks rows quickly, only the
        # latest selection's diff actually gets rendered to the view.
        self._pending_token = 0

        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(("Action", "Path"))
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tree.itemSelectionChanged.connect(self._on_selection)
        for entry in plan.adds:
            self._row("add", entry.rel_path)
        for entry in plan.modifies:
            self._row("modify", entry.rel_path)
        for entry in plan.quarantines:
            self._row("quarantine", entry.rel_path)

        self._view = QPlainTextEdit(self)
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # Hard ceiling on rendered blocks so even an under-cap diff that gets
        # appended to repeatedly cannot exhaust memory.
        self._view.setMaximumBlockCount(_DIFF_LINE_LIMIT + 32)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._tree)
        splitter.addWidget(self._view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)
        layout.addWidget(splitter, 1)

        # Footer: Close on the left, Sync (primary) on the right when supplied.
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

        if self._tree.topLevelItemCount() > 0:
            self._tree.setCurrentItem(self._tree.topLevelItem(0))

    # -- Internals --------------------------------------------------------

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
        action = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        rel_path = str(item.data(1, Qt.ItemDataRole.UserRole) or "")

        # Show a placeholder immediately so the UI feels responsive, then
        # generate the real diff on the next event loop tick. This way even
        # a slow-to-read file doesn't block the row click.
        self._view.setPlainText("(generating diff…)")
        self._pending_token += 1
        token = self._pending_token
        QTimer.singleShot(0, lambda: self._render(token, action, rel_path))

    def _render(self, token: int, action: str, rel_path: str) -> None:
        if token != self._pending_token:
            return  # superseded by a later selection
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

        # modify -> two-sided diff with a strict line+byte cap.
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
        # Bail before doing any work if the inputs are absurd.
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
        # Close first so the confirm dialog stacks on top of the main window
        # rather than this preview, which would feel jarring at fullscreen.
        self.accept()
        if self._on_sync is not None:
            self._on_sync()


__all__ = ["DiffPreviewDialog"]

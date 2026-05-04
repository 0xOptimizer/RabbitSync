"""Register a new sync pair: source folder + copy folder + label."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.core.git_resolve import resolve as resolve_git
from rabbitsync.ui.theme import Spacing


@dataclass(frozen=True)
class PairRegistration:
    label: str
    source: Path
    copy: Path


class RegisterPairDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Register sync pair")
        self.setMinimumWidth(560)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        layout.addWidget(QLabel("Pair label", self))
        self._label_input = QLineEdit(self)
        self._label_input.setPlaceholderText("e.g. proj-a · src ↔ copy")
        layout.addWidget(self._label_input)

        layout.addWidget(QLabel("Source folder", self))
        self._source_input, source_row = _path_row(self, on_browse=self._browse_source)
        layout.addLayout(source_row)
        self._source_status = QLabel("", self)
        layout.addWidget(self._source_status)

        layout.addWidget(QLabel("Copy folder", self))
        self._copy_input, copy_row = _path_row(self, on_browse=self._browse_copy)
        layout.addLayout(copy_row)
        self._copy_status = QLabel("", self)
        layout.addWidget(self._copy_status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._buttons = buttons

        self._registration: PairRegistration | None = None

    def registration(self) -> PairRegistration | None:
        return self._registration

    def _browse_source(self) -> None:
        start = self._source_input.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(
            self,
            "Pick source folder",
            start,
            QFileDialog.Option.ShowDirsOnly
            | QFileDialog.Option.DontResolveSymlinks
            | QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self._source_input.setText(path)
            self._refresh_source_status()

    def _browse_copy(self) -> None:
        start = self._copy_input.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(
            self,
            "Pick copy folder",
            start,
            QFileDialog.Option.ShowDirsOnly
            | QFileDialog.Option.DontResolveSymlinks
            | QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self._copy_input.setText(path)
            self._refresh_copy_status()

    def _refresh_source_status(self) -> None:
        self._source_status.setText(_describe_git_context(self._source_input.text()))

    def _refresh_copy_status(self) -> None:
        self._copy_status.setText(_describe_git_context(self._copy_input.text()))

    def _on_accept(self) -> None:
        label = self._label_input.text().strip()
        source = Path(self._source_input.text().strip())
        copy = Path(self._copy_input.text().strip())
        if not label:
            QMessageBox.warning(self, "Missing label", "Please enter a label for the pair.")
            return
        if not source.exists() or not source.is_dir():
            QMessageBox.warning(self, "Source folder invalid",
                                f"The source folder does not exist or is not a directory: {source}")
            return
        if not copy.exists() or not copy.is_dir():
            QMessageBox.warning(self, "Copy folder invalid",
                                f"The copy folder does not exist or is not a directory: {copy}")
            return
        if source.resolve() == copy.resolve():
            QMessageBox.warning(self, "Same folder",
                                "Source and copy must be different folders.")
            return
        self._registration = PairRegistration(label=label, source=source, copy=copy)
        self.accept()


def _path_row(parent: QWidget, *, on_browse) -> tuple[QLineEdit, QHBoxLayout]:  # noqa: ANN001
    line = QLineEdit(parent)
    line.setReadOnly(False)
    btn = QPushButton("Browse…", parent)
    btn.clicked.connect(on_browse)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(Spacing.SM)
    row.addWidget(line, 1)
    row.addWidget(btn)
    return line, row


def _describe_git_context(path_str: str) -> str:
    if not path_str:
        return ""
    try:
        ctx = resolve_git(Path(path_str))
    except (FileNotFoundError, NotADirectoryError):
        return "Folder does not exist or is not a directory."
    if not ctx.has_git:
        return "No git repo detected — sync will run; git features hidden for this side."
    if ctx.is_root:
        return "Folder is the root of a git repository."
    return f"Folder is at '{ctx.subpath}' inside git repo at {ctx.git_root}."


__all__ = ["PairRegistration", "RegisterPairDialog"]


# `Qt` is referenced for forward compatibility with rich-text dialogs.
_ = Qt

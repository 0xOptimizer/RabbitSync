"""Clone dialog — URL + destination + post-clone action."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.ui.theme import Spacing


@dataclass(frozen=True)
class CloneRequest:
    url: str
    destination: Path
    post_action: str  # 'just-clone' | 'register-source-new' | 'register-copy-new' | ...


class CloneDialog(QDialog):
    POST_ACTIONS = [
        ("just-clone", "Just clone"),
        ("register-source-new", "Register as source of new pair"),
        ("register-copy-new", "Register as copy of new pair"),
    ]

    def __init__(self, *, prefill_url: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Clone repository")
        self.setMinimumWidth(640)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        layout.addWidget(QLabel("Repository URL"))
        self._url = QLineEdit(self)
        self._url.setPlaceholderText("https://github.com/owner/repo.git")
        self._url.setText(prefill_url)
        layout.addWidget(self._url)

        layout.addWidget(QLabel("Destination folder"))
        dest_row = QHBoxLayout()
        dest_row.setContentsMargins(0, 0, 0, 0)
        dest_row.setSpacing(Spacing.SM)
        self._dest = QLineEdit(self)
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._browse)
        dest_row.addWidget(self._dest, 1)
        dest_row.addWidget(browse)
        layout.addLayout(dest_row)

        layout.addWidget(QLabel("After clone"))
        self._post = QComboBox(self)
        for key, label in self.POST_ACTIONS:
            self._post.addItem(label, key)
        layout.addWidget(self._post)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status = QLabel("", self)
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(self)
        self._clone_btn = buttons.addButton("Clone", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._clone_btn.clicked.connect(self._on_clone)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._request: CloneRequest | None = None

    def request_value(self) -> CloneRequest | None:
        return self._request

    def set_progress(self, percent: int, *, phase: str = "") -> None:
        self._progress.setVisible(True)
        self._progress.setValue(max(0, min(100, percent)))
        if phase:
            self._status.setText(phase)

    def set_complete(self, *, ok: bool, message: str = "") -> None:
        self._progress.setValue(100 if ok else self._progress.value())
        self._status.setText(message)
        self._clone_btn.setEnabled(True)

    def _browse(self) -> None:
        start = self._dest.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(
            self,
            "Pick destination folder",
            start,
            QFileDialog.Option.ShowDirsOnly
            | QFileDialog.Option.DontResolveSymlinks
            | QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self._dest.setText(path)

    def _on_clone(self) -> None:
        url = self._url.text().strip()
        dest = self._dest.text().strip()
        if not url or not dest:
            QMessageBox.warning(self, "Missing fields",
                                "Provide both a repository URL and a destination folder.")
            return
        self._request = CloneRequest(
            url=url,
            destination=Path(dest),
            post_action=self._post.currentData(),
        )
        self.accept()


__all__ = ["CloneRequest", "CloneDialog"]

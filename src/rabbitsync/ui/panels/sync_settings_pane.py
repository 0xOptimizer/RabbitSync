"""Sync tab — right column: change summary + sync settings + warnings."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.ui.theme import Spacing


class SyncSettingsPane(QFrame):
    """The right-side info column on the Sync tab."""

    def __init__(self, *, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _ = theme
        self.setObjectName("SyncSettings")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        layout.addWidget(_section_label("Changes"))
        self._summary = QLabel("—")
        layout.addWidget(self._summary)

        layout.addSpacing(Spacing.SM)
        layout.addWidget(_section_label("Sync settings"))

        self._branch_combo = QComboBox(self)
        layout.addWidget(_field_label("Target branch"))
        layout.addWidget(self._branch_combo)

        self._commit_chk = QCheckBox("commit on sync", self)
        self._commit_chk.setChecked(True)
        layout.addWidget(self._commit_chk)

        self._push_chk = QCheckBox("auto-push after commit", self)
        self._push_chk.setChecked(False)
        layout.addWidget(self._push_chk)

        layout.addWidget(_field_label("Commit message template"))
        self._template = QLineEdit(self)
        self._template.setPlaceholderText("sync: {src_branch}@{src_sha} — {n} files")
        self._template.setText("sync: {src_branch}@{src_sha} — {n} files")
        layout.addWidget(self._template)

        layout.addSpacing(Spacing.SM)
        layout.addWidget(_section_label("Conflicts"))
        self._conflicts = QLabel("none")
        layout.addWidget(self._conflicts)

        layout.addSpacing(Spacing.SM)
        layout.addWidget(_section_label("Secrets"))
        self._secrets = QLabel("no findings")
        layout.addWidget(self._secrets)

        layout.addStretch(1)

    def show_summary(self, *, adds: int, modifies: int, quarantines: int) -> None:
        self._summary.setText(f"+{adds}  ~{modifies}  -{quarantines}")

    def set_branches(self, branches: list[str], current: str | None = None) -> None:
        self._branch_combo.clear()
        self._branch_combo.addItems(branches)
        if current is not None and current in branches:
            self._branch_combo.setCurrentIndex(branches.index(current))

    def set_conflicts(self, count: int) -> None:
        self._conflicts.setText("none" if count == 0 else f"{count} files")

    def set_secret_findings(self, count: int) -> None:
        self._secrets.setText("no findings" if count == 0 else f"{count} findings")

    @property
    def commit_on_sync(self) -> bool:
        return self._commit_chk.isChecked()

    @property
    def auto_push(self) -> bool:
        return self._push_chk.isChecked()

    @property
    def commit_message_template(self) -> str:
        return self._template.text()

    @property
    def target_branch(self) -> str | None:
        return self._branch_combo.currentText() or None


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "header")
    return lbl


def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "muted")
    return lbl


__all__ = ["SyncSettingsPane"]

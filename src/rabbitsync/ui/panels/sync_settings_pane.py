"""Sync tab — right column: change summary + sync settings + warnings."""

from __future__ import annotations

from collections.abc import Callable

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
        self._on_changed: Callable[[], None] | None = None
        self._suspend_change_events = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        layout.addWidget(_section_label("Changes"))
        self._summary = QLabel("—")
        layout.addWidget(self._summary)

        layout.addSpacing(Spacing.SM)
        layout.addWidget(_section_label("Sync settings"))

        self._branch_combo = QComboBox(self)
        self._branch_combo.currentIndexChanged.connect(self._emit_changed)
        layout.addWidget(_field_label("Target branch"))
        layout.addWidget(self._branch_combo)

        self._commit_chk = QCheckBox("commit on sync", self)
        self._commit_chk.setChecked(True)
        self._commit_chk.toggled.connect(self._emit_changed)
        layout.addWidget(self._commit_chk)

        self._push_chk = QCheckBox("auto-push after commit", self)
        self._push_chk.setChecked(False)
        self._push_chk.toggled.connect(self._emit_changed)
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
        self._suspend_change_events = True
        try:
            self._branch_combo.clear()
            self._branch_combo.addItems(branches)
            if current is not None and current in branches:
                self._branch_combo.setCurrentIndex(branches.index(current))
        finally:
            self._suspend_change_events = False

    def set_state(
        self,
        *,
        commit_on_sync: bool,
        auto_push: bool,
        target_branch: str | None,
    ) -> None:
        """Seed all toggles from a freshly-loaded pair, without firing on_changed."""
        self._suspend_change_events = True
        try:
            self._commit_chk.setChecked(commit_on_sync)
            self._push_chk.setChecked(auto_push)
            if target_branch is not None:
                idx = self._branch_combo.findText(target_branch)
                if idx >= 0:
                    self._branch_combo.setCurrentIndex(idx)
        finally:
            self._suspend_change_events = False

    def set_on_changed(self, handler: Callable[[], None] | None) -> None:
        self._on_changed = handler

    def _emit_changed(self, *_args) -> None:  # noqa: ANN002
        if self._suspend_change_events or self._on_changed is None:
            return
        self._on_changed()

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

"""Sync confirm dialog — snapshot path, change counts, optional typed-confirm.

Initial sync (no prior receipt for this pair) requires the user to type the
copy folder name to confirm. Subsequent syncs use a lighter confirm.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.core.diff import DiffPlan
from rabbitsync.ui.theme import DARK, LIGHT, Spacing, Typography


@dataclass(frozen=True)
class ConfirmDecision:
    proceed: bool
    add_findings_to_ignore: bool


class ConfirmSyncDialog(QDialog):
    def __init__(
        self,
        *,
        plan: DiffPlan,
        copy_folder: Path,
        snapshot_target: Path,
        is_initial_sync: bool,
        secret_finding_count: int = 0,
        conflict_count: int = 0,
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self.setWindowTitle("Confirm sync")
        self.setMinimumWidth(560)
        self.setModal(True)
        self._copy_name = copy_folder.name
        self._is_initial = is_initial_sync

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.SM)

        title = QLabel(
            "Initial sync of this pair" if is_initial_sync else "Sync source → copy",
            self,
        )
        title.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.HEADER_PT}pt; "
            f"font-weight: 600; "
            f"color: {palette.fg};"
        )
        layout.addWidget(title)

        plan_summary = QLabel(
            f"This sync will write {len(plan.adds)} new and {len(plan.modifies)} modified files,\n"
            f"and quarantine {len(plan.quarantines)} file(s) currently in copy but not in source.",
            self,
        )
        plan_summary.setWordWrap(True)
        plan_summary.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"color: {palette.fg};"
        )
        layout.addWidget(plan_summary)

        if plan.quarantines:
            warn = QLabel(
                f"{len(plan.quarantines)} file(s) will be moved to data/quarantine/<sync-id>/ "
                "and remain recoverable until retention sweeps them. If those files should "
                "always exist in copy, add them to .rabbitsyncignore and re-run.",
                self,
            )
            warn.setWordWrap(True)
            warn.setStyleSheet(
                f"font-family: {Typography.UI_FAMILY}; "
                f"font-size: {Typography.BASE_PT}pt; "
                f"color: {palette.danger};"
            )
            layout.addWidget(warn)

        snap_label = QLabel(
            f"Snapshot of copy will be written to:\n  {snapshot_target}",
            self,
        )
        snap_label.setWordWrap(True)
        snap_label.setStyleSheet(
            f"font-family: {Typography.MONO_FAMILY}; "
            f"font-size: {Typography.MONO_PT}pt; "
            f"color: {palette.fg_muted};"
        )
        layout.addWidget(snap_label)

        if conflict_count > 0:
            layout.addWidget(self._warn_label(
                f"{conflict_count} file(s) in copy have uncommitted changes that this sync would overwrite.",
                palette,
            ))

        self._scan_chk: QCheckBox | None = None
        if secret_finding_count > 0:
            layout.addWidget(self._warn_label(
                f"Secret scan flagged {secret_finding_count} possible findings in the file set.",
                palette,
            ))
            self._scan_chk = QCheckBox("Add flagged paths to .rabbitsyncignore", self)
            layout.addWidget(self._scan_chk)

        self._typed_input: QLineEdit | None = None
        if is_initial_sync:
            layout.addWidget(QLabel(
                f"Type '{self._copy_name}' to confirm this initial sync:", self,
            ))
            self._typed_input = QLineEdit(self)
            self._typed_input.textChanged.connect(self._refresh_button_state)
            layout.addWidget(self._typed_input)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Sync")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._refresh_button_state()

        self._decision: ConfirmDecision | None = None

    def decision(self) -> ConfirmDecision | None:
        if self.result() != QDialog.DialogCode.Accepted:
            return None
        return ConfirmDecision(
            proceed=True,
            add_findings_to_ignore=bool(self._scan_chk and self._scan_chk.isChecked()),
        )

    def _refresh_button_state(self) -> None:
        if not self._is_initial or self._typed_input is None:
            self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
            return
        ok = self._typed_input.text().strip() == self._copy_name
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def _warn_label(self, text: str, palette) -> QLabel:  # noqa: ANN001
        lbl = QLabel(text, self)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"color: {palette.warning};"
        )
        return lbl


__all__ = ["ConfirmDecision", "ConfirmSyncDialog"]


# `Qt` is referenced for forward compatibility with rich-text settings.
_ = Qt

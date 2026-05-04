"""Crash-recovery prompt — shown at startup if any sync left an open journal.

The user picks Resume (re-run from where it stopped) or Rollback (mark the
sync aborted and restore copy from the snapshot via the standard
restore-to-sibling flow).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.db.writer import DbWriter
from rabbitsync.safety import journal as journal_mod
from rabbitsync.ui.theme import Spacing, Typography


class RecoveryPromptDialog(QDialog):
    def __init__(
        self,
        *,
        unfinished_sync_ids: list[str],
        writer: DbWriter,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Recover unfinished syncs")
        self.setModal(True)
        self.resize(560, 360)
        self._writer = writer
        self._sync_ids = unfinished_sync_ids

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        title = QLabel(
            f"Found {len(unfinished_sync_ids)} unfinished sync(s) from a previous run.",
            self,
        )
        title.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.HEADER_PT}pt; font-weight: 600;"
        )
        layout.addWidget(title)

        explanation = QLabel(
            "Each entry below was interrupted before completion. The pre-sync "
            "snapshot is intact, so you can either:\n"
            " • Mark them aborted and inspect the snapshot manually, or\n"
            " • Leave them recorded as failed for later review.\n\n"
            "Closing this dialog without action keeps the entries as-is.",
            self,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self._list = QListWidget(self)
        for sid in unfinished_sync_ids:
            self._list.addItem(QListWidgetItem(sid))
        layout.addWidget(self._list, 1)

        buttons = QDialogButtonBox(self)
        abort_btn = buttons.addButton("Mark all aborted", QDialogButtonBox.ButtonRole.AcceptRole)
        keep_btn = buttons.addButton("Keep as-is", QDialogButtonBox.ButtonRole.RejectRole)
        abort_btn.clicked.connect(self._mark_aborted)
        keep_btn.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def _mark_aborted(self) -> None:
        from rabbitsync.db.repositories import syncs_repo
        for sid in self._sync_ids:
            syncs_repo.finalize(self._writer, sync_id=sid, status="aborted")
            journal_mod.append(
                self._writer, sync_id=sid, action="close",
                extra={"reason": "recovery_marked_aborted"},
            )
        self.accept()


__all__ = ["RecoveryPromptDialog"]

"""Export backup dialog — pick categories + format + destination."""

from __future__ import annotations

import datetime as _dt

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.core.disk_usage import fmt as fmt_bytes, measure
from rabbitsync.core.export import export
from rabbitsync.ui.theme import Spacing, Typography


class ExportBackupDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export backup")
        self.setModal(True)
        self.resize(500, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        usage = measure()
        layout.addWidget(QLabel(
            f"Current data tree: <b>{fmt_bytes(usage.total_bytes)}</b>",
            self,
        ))

        form = QFormLayout()
        self._db_chk = _check(f"Database ({fmt_bytes(usage.db_bytes)})", checked=True)
        self._snap_chk = _check(f"Snapshots ({fmt_bytes(usage.snapshots_bytes)})", checked=True)
        self._quar_chk = _check(f"Quarantine ({fmt_bytes(usage.quarantine_bytes)})", checked=True)
        self._pipe_chk = _check(f"Pipeline runs ({fmt_bytes(usage.pipelines_bytes)})", checked=False)
        self._logs_chk = _check(f"Log files ({fmt_bytes(usage.logs_bytes)})", checked=False)
        for chk in (self._db_chk, self._snap_chk, self._quar_chk, self._pipe_chk, self._logs_chk):
            form.addRow(chk)
        layout.addLayout(form)

        self._fmt_combo = QComboBox(self)
        self._fmt_combo.addItem("tar.zst (compressed, recommended)", "zst")
        self._fmt_combo.addItem("zip (cross-tool compatibility)", "zip")
        layout.addWidget(QLabel("Format", self))
        layout.addWidget(self._fmt_combo)

        layout.addStretch(1)

        self._note = QLabel("", self)
        self._note.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt;"
        )
        layout.addWidget(self._note)

        buttons = QDialogButtonBox(self)
        export_btn = buttons.addButton("Export…", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        export_btn.clicked.connect(self._on_export)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_export(self) -> None:
        chosen: list[str] = []
        if self._db_chk.isChecked():
            chosen.append("rabbitsync.db")
        if self._snap_chk.isChecked():
            chosen.append("backups")
        if self._quar_chk.isChecked():
            chosen.append("quarantine")
        if self._pipe_chk.isChecked():
            chosen.append("pipelines")
        if self._logs_chk.isChecked():
            chosen.append("logs")
        if not chosen:
            QMessageBox.warning(self, "Export", "Pick at least one category to export.")
            return
        ext = self._fmt_combo.currentData()
        suggested = f"rabbitsync-export-{_dt.datetime.now().strftime('%Y%m%dT%H%M%S')}." + (
            "zip" if ext == "zip" else "tar.zst"
        )
        from pathlib import Path as _Path
        start = str(_Path.home() / suggested)
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save backup", start,
            "Compressed archive (*.tar.zst *.zip)",
            options=QFileDialog.Option.DontResolveSymlinks
            | QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        try:
            result = export(__import__("pathlib").Path(path), include=chosen, fmt=ext)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export failed",
                                 f"Could not write archive: {exc}")
            return
        QMessageBox.information(
            self, "Export complete",
            f"Wrote {fmt_bytes(result.bytes_written)} to {result.path}",
        )
        self.accept()


def _check(label: str, *, checked: bool) -> QCheckBox:
    chk = QCheckBox(label)
    chk.setChecked(checked)
    return chk


__all__ = ["ExportBackupDialog"]

"""Settings dialog — appearance, retention, sync behavior."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.config.store import Settings, load_settings, save_settings
from rabbitsync.db.writer import DbWriter
from rabbitsync.ui import animations
from rabbitsync.ui.theme import Spacing


class SettingsDialog(QDialog):
    def __init__(self, *, writer: DbWriter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(560, 480)
        self._writer = writer
        self._loaded = load_settings()

        tabs = QTabWidget(self)

        # Appearance
        appearance = QWidget(tabs)
        af = QFormLayout(appearance)
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["dark", "light", "system"])
        self._theme_combo.setCurrentText(self._loaded.theme)
        self._reduce_motion = QCheckBox("Reduce motion (snap animations to end)")
        self._reduce_motion.setChecked(self._loaded.reduce_motion)
        af.addRow("Theme", self._theme_combo)
        af.addRow(self._reduce_motion)
        tabs.addTab(appearance, "Appearance")

        # Retention
        retention = QWidget(tabs)
        rf = QFormLayout(retention)
        self._snap_keep_count = QSpinBox()
        self._snap_keep_count.setRange(1, 1000)
        self._snap_keep_count.setValue(self._loaded.snapshot_keep_count)
        self._snap_keep_days = QSpinBox()
        self._snap_keep_days.setRange(1, 3650)
        self._snap_keep_days.setValue(self._loaded.snapshot_keep_days)
        self._snap_max_gb = QSpinBox()
        self._snap_max_gb.setRange(1, 1024)
        self._snap_max_gb.setValue(self._loaded.snapshot_max_gb)
        self._log_keep_files = QSpinBox()
        self._log_keep_files.setRange(1, 365)
        self._log_keep_files.setValue(self._loaded.log_keep_files)
        rf.addRow("Snapshots: keep last N", self._snap_keep_count)
        rf.addRow("Snapshots: keep at least N days", self._snap_keep_days)
        rf.addRow("Snapshots: max GB per pair", self._snap_max_gb)
        rf.addRow("Log files to keep", self._log_keep_files)
        tabs.addTab(retention, "Retention")

        # Sync behavior
        sync_tab = QWidget(tabs)
        sf = QFormLayout(sync_tab)
        self._commit_default = QCheckBox("Default 'commit on sync' to ON")
        self._commit_default.setChecked(self._loaded.default_commit_on_sync)
        self._auto_push_default = QCheckBox("Default 'auto-push after commit' to ON")
        self._auto_push_default.setChecked(self._loaded.default_auto_push)
        self._sync_check_s = QSpinBox()
        self._sync_check_s.setRange(5, 3600)
        self._sync_check_s.setValue(self._loaded.sync_check_interval_s)
        self._sample_rate_pct = QSpinBox()
        self._sample_rate_pct.setRange(0, 100)
        self._sample_rate_pct.setValue(int(self._loaded.diff_sample_rate * 100))
        sf.addRow(self._commit_default)
        sf.addRow(self._auto_push_default)
        sf.addRow("Sync-check interval (seconds)", self._sync_check_s)
        sf.addRow("Diff integrity sample rate (%)", self._sample_rate_pct)
        tabs.addTab(sync_tab, "Sync")

        # Advanced
        advanced = QWidget(tabs)
        adf = QFormLayout(advanced)
        self._allow_elevated = QCheckBox("Allow pipelines while RabbitSync is elevated")
        self._allow_elevated.setChecked(self._loaded.allow_elevated_pipelines)
        adf.addRow(self._allow_elevated)
        tabs.addTab(advanced, "Advanced")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        new = Settings(
            theme=self._theme_combo.currentText(),
            reduce_motion=self._reduce_motion.isChecked(),
            snapshot_keep_count=self._snap_keep_count.value(),
            snapshot_keep_days=self._snap_keep_days.value(),
            snapshot_max_gb=self._snap_max_gb.value(),
            log_keep_files=self._log_keep_files.value(),
            default_commit_on_sync=self._commit_default.isChecked(),
            default_auto_push=self._auto_push_default.isChecked(),
            sync_check_interval_s=self._sync_check_s.value(),
            diff_sample_rate=self._sample_rate_pct.value() / 100.0,
            allow_elevated_pipelines=self._allow_elevated.isChecked(),
        )
        save_settings(self._writer, new)
        animations.set_user_preference(new.reduce_motion)
        self.accept()


__all__ = ["SettingsDialog"]

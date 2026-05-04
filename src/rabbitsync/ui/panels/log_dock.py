"""Bottom log dock — live structured log stream with level + text filters.

Receives events from :data:`rabbitsync.logging.setup.ui_sink` and renders
each as one line. Level filter dropdown lets the user dial verbosity.
The dock is hidden by default; the burger menu / status bar / sync flow
all toggle or auto-show it.
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.logging.setup import ui_sink
from rabbitsync.ui.theme import Spacing, Typography


_LEVEL_RANK = {
    "TRACE": 5, "DEBUG": 10, "INFO": 20,
    "WARN": 30, "WARNING": 30, "ERROR": 40, "CRITICAL": 50,
}


class LogBridge(QObject):
    """Forwards log events from the producer thread onto the UI thread."""

    event_arrived = Signal(dict)

    def __init__(self) -> None:
        super().__init__()


class LogDock(QDockWidget):
    """Dockable log panel."""

    MAX_LINES = 5_000

    def __init__(self, *, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__("Logs", parent)
        self.setObjectName("LogDock")
        _ = theme
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        container = QWidget(self)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        outer.setSpacing(Spacing.XS)

        # Toolbar: level dropdown + text filter + clear + pause
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(Spacing.SM)

        toolbar.addWidget(QLabel("Level:", container))
        self._level_combo = QComboBox(container)
        for label in ("TRACE", "DEBUG", "INFO", "WARN", "ERROR"):
            self._level_combo.addItem(label, _LEVEL_RANK[label])
        self._level_combo.setCurrentText("INFO")
        toolbar.addWidget(self._level_combo)

        self._filter = QLineEdit(container)
        self._filter.setPlaceholderText("Filter (substring match across event + values)…")
        toolbar.addWidget(self._filter, 1)

        self._pause_btn = QPushButton("Pause", container)
        self._pause_btn.setCheckable(True)
        toolbar.addWidget(self._pause_btn)

        clear_btn = QPushButton("Clear", container)
        clear_btn.clicked.connect(lambda: self._view.clear())
        toolbar.addWidget(clear_btn)

        outer.addLayout(toolbar)

        self._view = QPlainTextEdit(container)
        self._view.setObjectName("LogView")
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(self.MAX_LINES)
        font = QFont(Typography.MONO_FAMILY.split(",")[0].strip())
        font.setPointSize(Typography.MONO_PT)
        self._view.setFont(font)
        outer.addWidget(self._view, 1)

        self.setWidget(container)

        self._bridge = LogBridge()
        self._bridge.event_arrived.connect(self._on_event, Qt.ConnectionType.QueuedConnection)
        ui_sink.set_emit(self._bridge.event_arrived.emit)

    @Slot(dict)
    def _on_event(self, event: dict[str, Any]) -> None:
        if self._pause_btn.isChecked():
            return
        threshold = int(self._level_combo.currentData() or 20)
        level = str(event.get("level", "info")).upper()
        if _LEVEL_RANK.get(level, 20) < threshold:
            return
        line = self._format(event)
        needle = self._filter.text().strip().lower()
        if needle and needle not in line.lower():
            return
        self._view.appendPlainText(line)
        self._view.moveCursor(QTextCursor.MoveOperation.End)

    def _format(self, event: dict[str, Any]) -> str:
        ts = str(event.get("ts", ""))
        level = str(event.get("level", "info")).upper().ljust(5)
        name = str(event.get("event", ""))
        rest = {k: v for k, v in event.items() if k not in {"ts", "level", "event"}}
        kv = " ".join(f"{k}={_compact(v)}" for k, v in rest.items())
        return f"{ts}  {level}  {name}  {kv}".rstrip()

    def reveal(self) -> None:
        """Make sure the dock is visible — used at sync/clone start."""
        if not self.isVisible():
            self.show()
        self.raise_()


def _compact(value: Any) -> str:
    if isinstance(value, str):
        return value if " " not in value else json.dumps(value)
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


__all__ = ["LogDock"]

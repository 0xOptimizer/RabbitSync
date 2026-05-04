"""Bottom status bar — ambient state + log dock toggle."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLabel, QPushButton, QStatusBar, QWidget

from rabbitsync.ui import icons


class AppStatusBar(QStatusBar):
    """Status bar with a toggle for the log dock."""

    def __init__(
        self,
        *,
        on_toggle_logs: Callable[[], None],
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        _ = theme

        self._status_label = QLabel("Ready · DB: WAL · lock: held")
        self._status_label.setProperty("role", "muted")
        self.addWidget(self._status_label, 1)

        self._toggle_btn = QPushButton("Logs")
        self._toggle_btn.setIcon(icons.Icons.logs())
        self._toggle_btn.setIconSize(QSize(12, 12))
        self._toggle_btn.setFlat(True)
        self._toggle_btn.clicked.connect(on_toggle_logs)
        self.addPermanentWidget(self._toggle_btn)

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)


__all__ = ["AppStatusBar"]

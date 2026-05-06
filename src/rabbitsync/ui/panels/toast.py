"""Native Windows toast notifications via the system tray icon."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon, QWidget

_DURATION_MS = 4000
_HIDE_GRACE_MS = 1000


class Toaster(QObject):
    """Wraps a QSystemTrayIcon for toast-style notifications.

    Falls back to no-op when the tray isn't available (Windows server SKUs,
    headless test environments, etc.). The tray icon is only visible while
    a toast is active so it doesn't permanently squat in the system tray.
    """

    def __init__(self, *, app_icon: QIcon, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tray: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(app_icon, parent)
            self._tray.setToolTip("RabbitSync")
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide)

    def info(self, title: str, message: str) -> None:
        self._show(title, message, QSystemTrayIcon.MessageIcon.Information)

    def warning(self, title: str, message: str) -> None:
        self._show(title, message, QSystemTrayIcon.MessageIcon.Warning)

    def error(self, title: str, message: str) -> None:
        self._show(title, message, QSystemTrayIcon.MessageIcon.Critical)

    def _show(
        self, title: str, message: str, icon: QSystemTrayIcon.MessageIcon,
    ) -> None:
        if self._tray is None:
            return
        self._tray.setVisible(True)
        self._tray.showMessage(title, message, icon, _DURATION_MS)
        self._hide_timer.start(_DURATION_MS + _HIDE_GRACE_MS)

    def _hide(self) -> None:
        if self._tray is not None:
            self._tray.setVisible(False)


__all__ = ["Toaster"]

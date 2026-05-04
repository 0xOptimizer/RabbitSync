"""Native Windows toast notifications via the system tray icon."""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon, QWidget


class Toaster(QObject):
    """Wraps a QSystemTrayIcon for toast-style notifications.

    Falls back to no-op when the tray isn't available (Windows server SKUs,
    headless test environments, etc.).
    """

    def __init__(self, *, app_icon: QIcon, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tray: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(app_icon, parent)
            self._tray.setToolTip("RabbitSync")
            self._tray.setVisible(True)

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
        self._tray.showMessage(title, message, icon, 4000)


__all__ = ["Toaster"]

"""Status pill — SVG icon + label, color-coded by semantic status.

Used in the sidebar (per pair) and in the pair header. Never uses emoji.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from rabbitsync.ui import icons
from rabbitsync.ui.theme import DARK, LIGHT, Spacing


class PillStatus(StrEnum):
    IN_SYNC = "in_sync"
    PENDING = "pending"
    SYNCING = "syncing"
    BLOCKED = "blocked"


_LABELS: dict[PillStatus, str] = {
    PillStatus.IN_SYNC: "In sync",
    PillStatus.PENDING: "Pending",
    PillStatus.SYNCING: "Syncing",
    PillStatus.BLOCKED: "Blocked",
}


def _color_for(status: PillStatus, palette) -> str:  # noqa: ANN001
    if status == PillStatus.IN_SYNC:
        return palette.success
    if status == PillStatus.BLOCKED:
        return palette.danger
    if status == PillStatus.SYNCING:
        return palette.accent
    return palette.warning


def _bg_for(status: PillStatus, palette) -> str:  # noqa: ANN001
    """Tint background — accent_subtle for syncing, otherwise a slightly
    elevated panel so the pill reads as a chip."""
    if status == PillStatus.SYNCING:
        return palette.accent_subtle
    return palette.bg_elevated


class StatusPill(QWidget):
    """A compact icon+label pill. Set status with :meth:`set_status`."""

    ICON_PX = 12

    def __init__(self, *, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = DARK if theme == "dark" else LIGHT
        self.setObjectName("StatusPill")

        self._icon_label = QLabel(self)
        self._icon_label.setFixedSize(self.ICON_PX, self.ICON_PX)
        self._text_label = QLabel(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Spacing.SM, 2, Spacing.SM, 2)
        layout.setSpacing(Spacing.XS)
        layout.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._text_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.set_status(PillStatus.IN_SYNC)

    def set_status(self, status: PillStatus, *, label: str | None = None) -> None:
        text = label if label is not None else _LABELS[status]
        color = _color_for(status, self._palette)
        bg = _bg_for(status, self._palette)
        icon = _icon_for(status)
        pix = icon.pixmap(self.ICON_PX, self.ICON_PX)
        self._icon_label.setPixmap(pix)
        self._text_label.setText(text)
        # Apply via the StatusPill object name so the cascade beats the global QSS.
        self.setStyleSheet(
            f"#StatusPill {{ background-color: {bg}; "
            f"border: 1px solid {self._palette.border_subtle}; "
            f"border-radius: 9px; }} "
            f"#StatusPill QLabel {{ color: {color}; background: transparent; }}"
        )


def _icon_for(status: PillStatus):  # noqa: ANN201
    if status == PillStatus.IN_SYNC:
        return icons.Icons.in_sync()
    if status == PillStatus.PENDING:
        return icons.Icons.pending()
    if status == PillStatus.SYNCING:
        return icons.Icons.syncing()
    return icons.Icons.blocked()


__all__ = ["PillStatus", "StatusPill"]

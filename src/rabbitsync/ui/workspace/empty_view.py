"""Placeholder workspace shown when no pair is selected (or none exist)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from rabbitsync.ui.theme import DARK, LIGHT, Spacing, Typography


class EmptyView(QWidget):
    """Centered hint copy: register a pair or pick one from the sidebar."""

    def __init__(self, *, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.XL)
        layout.setSpacing(Spacing.MD)

        title = QLabel("No pair selected", self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.HEADER_LG_PT}pt; "
            f"font-weight: 600; "
            f"color: {palette.fg};"
        )
        body = QLabel(
            "Pick a pair from the sidebar to view its sync state, "
            "or use the burger menu to add a new pair or clone a repository.",
            self,
        )
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"color: {palette.fg_muted};"
        )

        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch(2)


__all__ = ["EmptyView"]

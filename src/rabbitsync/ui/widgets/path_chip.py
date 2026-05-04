"""Path chip — folder path label + reveal-in-Explorer button."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from rabbitsync.ui import icons
from rabbitsync.ui.theme import LIGHT, DARK, Spacing, Typography


class PathChip(QWidget):
    """One row: ``label: <path>  [reveal]``."""

    def __init__(
        self,
        *,
        label: str,
        path: Path,
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self._path = path

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.XS)

        prefix = QLabel(label, self)
        prefix.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"color: {palette.fg_muted};"
        )

        path_label = QLabel(str(path), self)
        path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        path_label.setStyleSheet(
            f"font-family: {Typography.MONO_FAMILY}; "
            f"font-size: {Typography.MONO_PT}pt; "
            f"color: {palette.fg};"
        )

        reveal = QPushButton(self)
        reveal.setIcon(icons.Icons.reveal())
        reveal.setIconSize(QSize(14, 14))
        reveal.setFlat(True)
        reveal.setToolTip("Reveal in Explorer")
        reveal.setFixedSize(QSize(22, 22))
        reveal.clicked.connect(self._reveal)

        layout.addWidget(prefix)
        layout.addWidget(path_label, 1)
        layout.addWidget(reveal)

    def _reveal(self) -> None:
        target = self._path
        if sys.platform == "win32":
            arg = "/select," + str(target) if target.is_file() else str(target)
            try:
                subprocess.Popen(["explorer", arg])  # noqa: S603, S607
            except OSError:
                pass
        elif sys.platform == "darwin":
            try:
                subprocess.Popen(["open", str(target.parent if target.is_file() else target)])  # noqa: S603, S607
            except OSError:
                pass
        else:
            try:
                subprocess.Popen(["xdg-open", str(target.parent if target.is_file() else target)])  # noqa: S603, S607
            except OSError:
                pass


__all__ = ["PathChip"]


# Suppress unused import warning on POSIX platforms.
_ = os

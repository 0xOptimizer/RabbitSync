"""Always-visible pair header above the workspace tabs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.ui import icons
from rabbitsync.ui.theme import Spacing
from rabbitsync.ui.widgets.path_chip import PathChip
from rabbitsync.ui.widgets.status_pill import PillStatus, StatusPill


class PairHeader(QFrame):
    """Header strip: label, paths, status pill, primary Sync, Actions menu."""

    def __init__(
        self,
        *,
        on_sync: Callable[[], None],
        on_recheck: Callable[[], None],
        on_edit_pair: Callable[[], None],
        on_remove_pair: Callable[[], None],
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PairHeader")
        self.setFixedHeight(52)

        # Top row: label + status pill + Sync + Actions
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(Spacing.MD)

        self._label = QLabel("(no pair selected)", self)
        self._label.setProperty("role", "header")
        self._status_pill = StatusPill(theme=theme, parent=self)

        self._sync_btn = QPushButton("Sync…", self)
        self._sync_btn.setIcon(icons.Icons.sync())
        self._sync_btn.setIconSize(QSize(14, 14))
        self._sync_btn.setMinimumHeight(24)
        self._sync_btn.clicked.connect(on_sync)

        self._actions_btn = QToolButton(self)
        self._actions_btn.setText("Actions")
        self._actions_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._actions_btn.setMinimumHeight(24)
        self._actions_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        actions_menu = QMenu(self._actions_btn)
        recheck_act = QAction(icons.Icons.recheck(), "Recheck now", actions_menu)
        recheck_act.triggered.connect(on_recheck)
        actions_menu.addAction(recheck_act)
        actions_menu.addSeparator()
        edit_act = QAction(icons.Icons.edit(), "Edit pair…", actions_menu)
        edit_act.triggered.connect(on_edit_pair)
        actions_menu.addAction(edit_act)
        remove_act = QAction("Remove pair…", actions_menu)
        remove_act.triggered.connect(on_remove_pair)
        actions_menu.addAction(remove_act)
        self._actions_btn.setMenu(actions_menu)

        top.addWidget(self._label)
        top.addWidget(self._status_pill)
        top.addStretch(1)
        top.addWidget(self._sync_btn)
        top.addWidget(self._actions_btn)

        # Bottom row: source + copy paths
        self._source_chip = PathChip(label="source:", path=Path("."), theme=theme, parent=self)
        self._copy_chip = PathChip(label="copy:", path=Path("."), theme=theme, parent=self)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(Spacing.LG)
        bottom.addWidget(self._source_chip, 1)
        bottom.addWidget(self._copy_chip, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.LG, Spacing.SM, Spacing.LG, Spacing.SM)
        outer.setSpacing(Spacing.XS)
        outer.addLayout(top)
        outer.addLayout(bottom)

    def show_pair(self, *, label: str, source: Path, copy: Path, status: PillStatus) -> None:
        self._label.setText(label)
        self._source_chip.setParent(None)
        self._copy_chip.setParent(None)
        # Replace path chips so the displayed paths stay current.
        layout = self.layout()
        assert layout is not None
        # Bottom row is the second item; rebuild by destroying old chips.
        self._source_chip.deleteLater()
        self._copy_chip.deleteLater()
        self._source_chip = PathChip(label="source:", path=source, parent=self)
        self._copy_chip = PathChip(label="copy:", path=copy, parent=self)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(Spacing.LG)
        bottom.addWidget(self._source_chip, 1)
        bottom.addWidget(self._copy_chip, 1)
        layout.addLayout(bottom)  # type: ignore[union-attr]
        self._status_pill.set_status(status)
        self._sync_btn.setEnabled(True)
        self._actions_btn.setEnabled(True)

    def set_status(self, status: PillStatus) -> None:
        self._status_pill.set_status(status)

    def show_empty(self) -> None:
        self._label.setText("(no pair selected)")
        self._sync_btn.setEnabled(False)
        self._actions_btn.setEnabled(False)


__all__ = ["PairHeader"]

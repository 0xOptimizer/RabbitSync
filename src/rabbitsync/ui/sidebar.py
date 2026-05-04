"""Three-section sidebar with a single ``View ▾`` dropdown switcher.

The user picks Pairs / Repositories / Accounts from the dropdown; the list
below shows the active section's entries. Selecting an entry emits a signal
the main window maps to a workspace view swap.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.ui import icons
from rabbitsync.ui.theme import Spacing


class SidebarView(StrEnum):
    PAIRS = "pairs"
    REPOSITORIES = "repositories"
    ACCOUNTS = "accounts"


class Sidebar(QFrame):
    """Sidebar with a view-switcher dropdown + list + add-button."""

    view_changed = Signal(SidebarView)
    item_selected = Signal(SidebarView, str)  # view, item-id
    add_requested = Signal(SidebarView)

    def __init__(self, *, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _ = theme
        self.setObjectName("Sidebar")
        self.setMinimumWidth(180)
        self.setMaximumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        layout.setSpacing(Spacing.XS)

        # View ▾ dropdown
        self._view_combo = QComboBox(self)
        self._view_combo.addItem(icons.Icons.pairs(), "Pairs", SidebarView.PAIRS)
        self._view_combo.addItem(icons.Icons.github(), "Repositories", SidebarView.REPOSITORIES)
        self._view_combo.addItem(icons.Icons.accounts(), "Accounts", SidebarView.ACCOUNTS)
        self._view_combo.currentIndexChanged.connect(self._on_view_changed)

        self._list = QListWidget(self)
        self._list.setObjectName("SidebarList")
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.itemClicked.connect(self._on_item_clicked)

        self._add_btn = QPushButton("+ Add Pair…", self)
        self._add_btn.setFlat(True)
        self._add_btn.clicked.connect(lambda: self.add_requested.emit(self.current_view()))

        layout.addWidget(self._view_combo)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._add_btn)

    # -- Public API --------------------------------------------------------

    def current_view(self) -> SidebarView:
        data = self._view_combo.currentData()
        return SidebarView(data) if data else SidebarView.PAIRS

    def set_items(self, view: SidebarView, entries: list[tuple[str, str]]) -> None:
        """Set ``[(item_id, display_label)]`` for the named view.

        Only updates the list if the named view is currently active. The
        caller is expected to refresh after the user switches views.
        """
        if self.current_view() != view:
            return
        self._list.clear()
        for item_id, label in entries:
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, item_id)
            self._list.addItem(it)

    # -- Internals ---------------------------------------------------------

    def _on_view_changed(self, _index: int) -> None:
        view = self.current_view()
        self._add_btn.setText(_add_label_for(view))
        self.view_changed.emit(view)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        item_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(item_id, str):
            self.item_selected.emit(self.current_view(), item_id)


def _add_label_for(view: SidebarView) -> str:
    if view == SidebarView.REPOSITORIES:
        return "+ Refresh repositories"
    if view == SidebarView.ACCOUNTS:
        return "+ Connect account…"
    return "+ Add Pair…"


__all__ = ["Sidebar", "SidebarView"]

"""GitHub repositories view — sortable, filterable list with clone action."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.ui import icons
from rabbitsync.ui.theme import DARK, LIGHT, Spacing, Typography


class ReposView(QFrame):
    HEADERS = ("Repository", "Default branch", "Updated", "Visibility")

    def __init__(
        self,
        *,
        on_clone: Callable[[str], None],
        on_refresh: Callable[[], None],
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self.setStyleSheet(f"QFrame {{ background-color: {palette.bg}; }}")
        self._on_clone = on_clone

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.SM)

        title = QLabel("GitHub Repositories", self)
        title.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.HEADER_LG_PT}pt; "
            f"font-weight: 600; "
            f"color: {palette.fg};"
        )
        layout.addWidget(title)

        # Filter + actions row
        bar = QFrame(self)
        from PySide6.QtWidgets import QHBoxLayout
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(Spacing.SM)
        self._filter = QLineEdit(bar)
        self._filter.setPlaceholderText("Filter by name…")
        self._filter.textChanged.connect(self._on_filter_changed)
        refresh_btn = QPushButton("Refresh", bar)
        refresh_btn.setIcon(icons.Icons.recheck_all())
        refresh_btn.clicked.connect(on_refresh)
        bar_layout.addWidget(self._filter, 1)
        bar_layout.addWidget(refresh_btn)
        layout.addWidget(bar)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(self.HEADERS)
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSortingEnabled(True)
        self._tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tree.itemDoubleClicked.connect(self._on_double_clicked)
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setStyleSheet(
            f"QTreeWidget {{ background-color: {palette.bg}; "
            f"color: {palette.fg}; "
            f"alternate-background-color: {palette.bg_subtle}; "
            f"border: 1px solid {palette.border}; }}"
        )
        layout.addWidget(self._tree, 1)

        self._empty_state = QLabel(
            "Connect a GitHub account from the burger menu to see your repositories here.",
            self,
        )
        self._empty_state.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"color: {palette.fg_muted};"
        )
        self._empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_state)
        self._empty_state.show()
        self._tree.hide()

    def populate(self, repos: list[dict]) -> None:
        self._tree.clear()
        if not repos:
            self._empty_state.show()
            self._tree.hide()
            return
        self._empty_state.hide()
        self._tree.show()
        for repo in repos:
            it = QTreeWidgetItem([
                str(repo.get("full_name", "")),
                str(repo.get("default_branch", "") or ""),
                str(repo.get("pushed_at", "") or ""),
                "private" if repo.get("private") else "public",
            ])
            it.setData(0, Qt.ItemDataRole.UserRole, repo.get("https_url") or repo.get("ssh_url"))
            self._tree.addTopLevelItem(it)

    def _on_filter_changed(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item is None:
                continue
            visible = needle in item.text(0).lower() if needle else True
            item.setHidden(not visible)

    def _on_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        url = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(url, str) and url:
            self._on_clone(url)


__all__ = ["ReposView"]

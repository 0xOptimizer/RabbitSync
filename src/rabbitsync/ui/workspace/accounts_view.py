"""Accounts view — connected GitHub accounts and their PAT metadata."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.credentials import gcm
from rabbitsync.ui import icons
from rabbitsync.ui.theme import DARK, LIGHT, Spacing, Typography


class AccountsView(QFrame):
    """Connected accounts + credentials manager."""

    def __init__(
        self,
        *,
        on_connect: Callable[[], None],
        on_test: Callable[[str], None],
        on_forget: Callable[[str], None],
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        palette = DARK if theme == "dark" else LIGHT
        self.setStyleSheet(f"QFrame {{ background-color: {palette.bg}; }}")
        self._on_test = on_test
        self._on_forget = on_forget

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        title = QLabel("Accounts", self)
        title.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.HEADER_LG_PT}pt; "
            f"font-weight: 600; "
            f"color: {palette.fg};"
        )
        layout.addWidget(title)

        gcm_text = "Git Credential Manager: " + (
            f"available ({gcm.version() or 'detected'})"
            if gcm.is_available()
            else "not detected (RabbitSync will manage HTTPS credentials via PAT)"
        )
        gcm_label = QLabel(gcm_text, self)
        gcm_label.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"color: {palette.fg_muted};"
        )
        layout.addWidget(gcm_label)

        connect_btn = QPushButton("Connect GitHub…", self)
        connect_btn.setIcon(icons.Icons.key())
        connect_btn.setMinimumHeight(24)
        connect_btn.clicked.connect(on_connect)
        layout.addWidget(connect_btn)

        self._list = QListWidget(self)
        self._list.setStyleSheet(
            f"QListWidget {{ background-color: {palette.bg_subtle}; "
            f"border: 1px solid {palette.border}; "
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt; "
            f"color: {palette.fg}; }}"
        )
        layout.addWidget(self._list, 1)

        actions = QFrame(self)
        ah = QHBoxLayout(actions)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.setSpacing(Spacing.SM)
        test_btn = QPushButton("Test connection", actions)
        test_btn.clicked.connect(self._on_test_clicked)
        forget_btn = QPushButton("Forget account", actions)
        forget_btn.clicked.connect(self._on_forget_clicked)
        ah.addWidget(test_btn)
        ah.addWidget(forget_btn)
        ah.addStretch(1)
        layout.addWidget(actions)

    def populate(self, accounts: list[dict]) -> None:
        from PySide6.QtCore import Qt as _Qt

        self._list.clear()
        if not accounts:
            empty = QListWidgetItem("(no accounts connected — click Connect GitHub)")
            empty.setFlags(_Qt.ItemFlag.NoItemFlags)
            self._list.addItem(empty)
            return
        for acc in accounts:
            scopes = acc.get("scopes") or "(scopes inferred from token kind)"
            text = (
                f"{acc.get('login')}  ·  scopes: {scopes}  ·  "
                f"expires {acc.get('expires_at') or 'no expiration'}"
            )
            it = QListWidgetItem(text)
            it.setData(0x0100, acc.get("login"))  # UserRole
            self._list.addItem(it)

    def _selected_login(self) -> str | None:
        item = self._list.currentItem()
        if item is None:
            return None
        data = item.data(0x0100)
        return str(data) if data else None

    def _on_test_clicked(self) -> None:
        login = self._selected_login()
        if login:
            self._on_test(login)

    def _on_forget_clicked(self) -> None:
        login = self._selected_login()
        if login:
            self._on_forget(login)


__all__ = ["AccountsView"]

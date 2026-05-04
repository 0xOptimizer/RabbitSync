"""Connect GitHub — paste a PAT, verify, store in keyring.

Embeds the full PAT setup walkthrough so the user has the steps right next
to the input field (no context-switching to the README).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from rabbitsync.credentials import vault
from rabbitsync.credentials.redactor import redact
from rabbitsync.github.api import GitHubApiError
from rabbitsync.github.pat import TokenInfo, verify
from rabbitsync.ui.theme import Spacing, Typography


_INSTRUCTIONS_HTML = """
<h3>Option A — Fine-grained token (recommended)</h3>
<ol>
  <li>Open <a href="https://github.com/settings/personal-access-tokens/new">github.com/settings/personal-access-tokens/new</a>.</li>
  <li>Token name: <b>RabbitSync</b> (or include your machine name).</li>
  <li>Expiration: 90 days is a sensible default.</li>
  <li>Resource owner: your account (or an org you administer).</li>
  <li>Repository access: choose what you want RabbitSync to see.</li>
  <li>Permissions → Repository permissions:
    <ul>
      <li><b>Contents</b>: Read (required).</li>
      <li><b>Metadata</b>: Read (auto-selected).</li>
      <li>Bump <b>Contents</b> to Read &amp; write only if you want RabbitSync to push over HTTPS using this token.</li>
    </ul>
  </li>
  <li>Generate token, copy the value (starts with <code>github_pat_</code>).</li>
  <li>Paste below and click <b>Verify &amp; Save</b>.</li>
</ol>
<h3>Option B — Classic token</h3>
<ol>
  <li>Open <a href="https://github.com/settings/tokens/new">github.com/settings/tokens/new</a>.</li>
  <li>Note: <b>RabbitSync</b>. Expiration: 90 days.</li>
  <li>Scopes: tick <code>repo</code> (or <code>public_repo</code> for read-only public access).</li>
  <li>Generate, copy (starts with <code>ghp_</code>), paste below.</li>
</ol>
<p>RabbitSync stores the token in <b>Windows Credential Manager</b> via the
OS keyring — never in SQLite or on disk in plaintext.</p>
"""


@dataclass(frozen=True)
class ConnectionResult:
    info: TokenInfo
    keyring_service: str
    keyring_account: str


class ConnectGitHubDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect GitHub")
        self.setModal(True)
        self.resize(720, 720)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        outer.setSpacing(Spacing.MD)

        # Scrollable instructions
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        instructions = QLabel(_INSTRUCTIONS_HTML, self)
        instructions.setWordWrap(True)
        instructions.setOpenExternalLinks(False)
        instructions.linkActivated.connect(self._open_url)
        instructions.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        instructions.setStyleSheet(
            f"font-family: {Typography.UI_FAMILY}; "
            f"font-size: {Typography.BASE_PT}pt;"
        )
        scroll.setWidget(instructions)
        outer.addWidget(scroll, 1)

        outer.addWidget(QLabel("Personal access token", self))
        token_row = QHBoxLayout()
        token_row.setContentsMargins(0, 0, 0, 0)
        token_row.setSpacing(Spacing.SM)
        self._token_input = QLineEdit(self)
        self._token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._token_input.setPlaceholderText("github_pat_…  or  ghp_…")
        self._reveal_btn = QPushButton("Show", self)
        self._reveal_btn.setCheckable(True)
        self._reveal_btn.toggled.connect(self._toggle_reveal)
        token_row.addWidget(self._token_input, 1)
        token_row.addWidget(self._reveal_btn)
        outer.addLayout(token_row)

        self._status_label = QLabel("", self)
        outer.addWidget(self._status_label)

        buttons = QDialogButtonBox(self)
        verify_btn = buttons.addButton("Verify && Save", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        verify_btn.clicked.connect(self._verify_and_save)
        outer.addWidget(buttons)

        self._result: ConnectionResult | None = None

    def result_value(self) -> ConnectionResult | None:
        return self._result

    def _toggle_reveal(self, checked: bool) -> None:
        self._token_input.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self._reveal_btn.setText("Hide" if checked else "Show")

    def _open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _verify_and_save(self) -> None:
        token = self._token_input.text().strip()
        if not token:
            QMessageBox.warning(self, "No token", "Paste your PAT into the field above.")
            return
        try:
            info = verify(token)
        except GitHubApiError as exc:
            self._status_label.setText(
                f"Verification failed: {redact(exc.message)} (HTTP {exc.status_code})"
            )
            return
        except Exception as exc:  # noqa: BLE001 -- show any failure to the user
            self._status_label.setText(f"Verification failed: {redact(str(exc))}")
            return

        service = vault.github_service(info.login)
        try:
            vault.store(service=service, account=info.login, secret=token)
        except vault.VaultError as exc:
            self._status_label.setText(f"Could not save credential: {redact(str(exc))}")
            return

        # Clear the token field immediately after a successful save.
        self._token_input.clear()
        self._reveal_btn.setChecked(False)
        self._result = ConnectionResult(
            info=info, keyring_service=service, keyring_account=info.login
        )
        self.accept()


__all__ = ["ConnectionResult", "ConnectGitHubDialog"]

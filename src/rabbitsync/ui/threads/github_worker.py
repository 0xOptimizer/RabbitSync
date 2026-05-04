"""Background workers for GitHub API calls (refresh repos, test creds)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from rabbitsync.credentials import vault
from rabbitsync.db.writer import DbWriter
from rabbitsync.github.api import GitHubApiError, GitHubClient
from rabbitsync.github.sync_repos import fetch_repos, replace_cached_repos


class RefreshReposWorker(QObject):
    finished = Signal(int)   # rows inserted
    failed = Signal(str)

    def __init__(self, *, account_id: int, login: str, writer: DbWriter) -> None:
        super().__init__()
        self._account_id = account_id
        self._login = login
        self._writer = writer

    @Slot()
    def run(self) -> None:
        try:
            token = vault.fetch(service=vault.github_service(self._login), account=self._login)
            if not token:
                self.failed.emit("No PAT found in keyring for this account.")
                return
            repos = fetch_repos(token)
            n = replace_cached_repos(self._writer, account_id=self._account_id, repos=repos)
            self.finished.emit(n)
        except GitHubApiError as exc:
            self.failed.emit(f"GitHub API error: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class TestCredentialWorker(QObject):
    finished = Signal(str)   # status text
    failed = Signal(str)

    def __init__(self, *, login: str) -> None:
        super().__init__()
        self._login = login

    @Slot()
    def run(self) -> None:
        try:
            token = vault.fetch(service=vault.github_service(self._login), account=self._login)
            if not token:
                self.failed.emit("No PAT in keyring for this login.")
                return
            with GitHubClient(token=token) as client:
                resp = client.get("/user")
                data = resp.json()
            self.finished.emit(f"OK · authenticated as {data.get('login')}")
        except GitHubApiError as exc:
            self.failed.emit(f"GitHub API error: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


__all__ = ["RefreshReposWorker", "TestCredentialWorker"]

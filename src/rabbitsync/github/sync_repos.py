"""Refresh GitHub repository listings into the local cache table.

Reads the user's repos via the API, replaces the rows in ``github_repos`` for
the given account, and updates ``github_accounts.last_synced_at``. The
operation is one transaction on the writer thread.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from rabbitsync.db.writer import DbWriter
from rabbitsync.github.api import GitHubClient


@dataclass(frozen=True)
class RepoRow:
    full_name: str
    default_branch: str | None
    ssh_url: str | None
    https_url: str | None
    private: bool
    description: str | None
    pushed_at: str | None


def fetch_repos(token: str, *, per_page: int = 100) -> list[RepoRow]:
    """Pull ``/user/repos`` from GitHub and return parsed rows."""
    out: list[RepoRow] = []
    with GitHubClient(token=token) as client:
        for item in client.paginated(
            "/user/repos",
            params={"per_page": per_page, "sort": "pushed", "affiliation": "owner,collaborator,organization_member"},
        ):
            if not isinstance(item, dict):
                continue
            out.append(RepoRow(
                full_name=str(item.get("full_name") or ""),
                default_branch=item.get("default_branch") or None,
                ssh_url=item.get("ssh_url") or None,
                https_url=item.get("clone_url") or None,
                private=bool(item.get("private")),
                description=item.get("description") or None,
                pushed_at=item.get("pushed_at") or None,
            ))
    return out


def replace_cached_repos(
    writer: DbWriter, *, account_id: int, repos: Iterable[RepoRow],
) -> int:
    """Replace the cached repo set for ``account_id``.

    Returns the number of rows inserted.
    """
    cached_at = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    payload = [
        (account_id, r.full_name, r.default_branch, r.ssh_url, r.https_url,
         int(r.private), r.description, r.pushed_at, cached_at)
        for r in repos if r.full_name
    ]

    def _do(conn: sqlite3.Connection) -> int:
        conn.execute("BEGIN IMMEDIATE;")
        try:
            conn.execute("DELETE FROM github_repos WHERE account_id = ?;", (account_id,))
            conn.executemany(
                "INSERT INTO github_repos "
                "(account_id, full_name, default_branch, ssh_url, https_url, "
                " private, description, pushed_at, cached_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                payload,
            )
            conn.execute(
                "UPDATE github_accounts SET last_synced_at = ?, updated_at = ? WHERE id = ?;",
                (cached_at, cached_at, account_id),
            )
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise
        return len(payload)

    return writer.execute(_do)


__all__ = ["RepoRow", "fetch_repos", "replace_cached_repos"]

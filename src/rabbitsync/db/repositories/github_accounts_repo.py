"""GitHub accounts + cached repos."""

from __future__ import annotations

import datetime as _dt
import sqlite3
from dataclasses import dataclass

from rabbitsync.db.connection import ConnectionFactory, closing
from rabbitsync.db.writer import DbWriter


@dataclass(frozen=True)
class GitHubAccount:
    id: int
    login: str
    scopes: str
    credential_ref_id: int
    last_synced_at: str | None
    expires_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class GitHubRepo:
    id: int
    account_id: int
    full_name: str
    default_branch: str | None
    ssh_url: str | None
    https_url: str | None
    private: bool
    description: str | None
    pushed_at: str | None


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


def upsert_account(
    writer: DbWriter,
    *,
    login: str,
    scopes: str,
    keyring_service: str,
    keyring_account: str,
    expires_at: str | None,
) -> int:
    """Create or update an account row + matching credential_refs row.

    Returns the github_accounts.id.
    """
    now = _now()

    def _do(conn: sqlite3.Connection) -> int:
        # Upsert credential ref.
        ref_row = conn.execute(
            "SELECT id FROM credential_refs WHERE keyring_service=? AND keyring_account=?;",
            (keyring_service, keyring_account),
        ).fetchone()
        if ref_row is None:
            cur = conn.execute(
                "INSERT INTO credential_refs "
                "(kind, label, keyring_service, keyring_account, extra_json, created_at, updated_at) "
                "VALUES ('github-pat', ?, ?, ?, '{}', ?, ?);",
                (login, keyring_service, keyring_account, now, now),
            )
            ref_id = int(cur.lastrowid or 0)
        else:
            ref_id = int(ref_row["id"])
            conn.execute(
                "UPDATE credential_refs SET label=?, updated_at=? WHERE id=?;",
                (login, now, ref_id),
            )

        # Upsert account.
        acc_row = conn.execute(
            "SELECT id FROM github_accounts WHERE login=?;",
            (login,),
        ).fetchone()
        if acc_row is None:
            cur = conn.execute(
                "INSERT INTO github_accounts "
                "(login, scopes, credential_ref_id, expires_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?);",
                (login, scopes, ref_id, expires_at, now, now),
            )
            return int(cur.lastrowid or 0)
        acc_id = int(acc_row["id"])
        conn.execute(
            "UPDATE github_accounts SET scopes=?, credential_ref_id=?, expires_at=?, updated_at=? "
            "WHERE id=?;",
            (scopes, ref_id, expires_at, now, acc_id),
        )
        return acc_id

    return writer.execute(_do)


def list_accounts(*, factory: ConnectionFactory | None = None) -> list[GitHubAccount]:
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        rows = conn.execute(
            "SELECT id, login, scopes, credential_ref_id, last_synced_at, expires_at, "
            "created_at, updated_at FROM github_accounts ORDER BY login;"
        ).fetchall()
    return [GitHubAccount(
        id=int(r["id"]),
        login=r["login"],
        scopes=r["scopes"],
        credential_ref_id=int(r["credential_ref_id"]),
        last_synced_at=r["last_synced_at"],
        expires_at=r["expires_at"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    ) for r in rows]


def delete_account(writer: DbWriter, *, login: str) -> None:
    def _do(conn: sqlite3.Connection) -> None:
        # Find ref id first so we can remove the orphan ref too.
        row = conn.execute(
            "SELECT credential_ref_id FROM github_accounts WHERE login=?;",
            (login,),
        ).fetchone()
        if row is None:
            return
        ref_id = int(row["credential_ref_id"])
        conn.execute("DELETE FROM github_accounts WHERE login=?;", (login,))
        conn.execute("DELETE FROM credential_refs WHERE id=?;", (ref_id,))

    writer.execute(_do)


def list_repos_for(account_id: int, *, factory: ConnectionFactory | None = None) -> list[GitHubRepo]:
    f = factory if factory is not None else ConnectionFactory()
    with closing(f.reader()) as conn:
        rows = conn.execute(
            "SELECT id, account_id, full_name, default_branch, ssh_url, https_url, "
            "private, description, pushed_at FROM github_repos "
            "WHERE account_id = ? ORDER BY pushed_at DESC, full_name;",
            (account_id,),
        ).fetchall()
    return [GitHubRepo(
        id=int(r["id"]),
        account_id=int(r["account_id"]),
        full_name=r["full_name"],
        default_branch=r["default_branch"],
        ssh_url=r["ssh_url"],
        https_url=r["https_url"],
        private=bool(r["private"]),
        description=r["description"],
        pushed_at=r["pushed_at"],
    ) for r in rows]


__all__ = [
    "GitHubAccount",
    "GitHubRepo",
    "delete_account",
    "list_accounts",
    "list_repos_for",
    "upsert_account",
]

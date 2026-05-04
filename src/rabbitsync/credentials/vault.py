"""OS-keyring wrapper. The ONLY module allowed to import ``keyring``.

Threat model
------------
GitHub PATs (and any future credential) must never sit in SQLite or on disk
in plaintext. They live in Windows Credential Manager via the cross-platform
``keyring`` library; SQLite's ``credential_refs`` table records only the
keyring service + account names so we can find the entry again.

Operations
----------
- :func:`store` — set the secret (overwrites any existing entry).
- :func:`fetch` — retrieve the secret (returns ``None`` if absent).
- :func:`forget` — delete the keyring entry.

All accessors take the (service, account) tuple verbatim; building the
service name (e.g. ``"rabbitsync:github:<login>"``) is the caller's job so
this module stays generic.
"""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError, PasswordDeleteError


class VaultError(RuntimeError):
    """Raised when the OS keyring operation fails."""


def store(*, service: str, account: str, secret: str) -> None:
    """Store ``secret`` in the OS keyring under (service, account).

    Overwrites any existing entry for that pair.
    """
    try:
        keyring.set_password(service, account, secret)
    except KeyringError as exc:
        raise VaultError(
            f"Failed to write credential to OS keyring "
            f"(service={service!r}, account={account!r}): {exc}"
        ) from exc


def fetch(*, service: str, account: str) -> str | None:
    """Return the stored secret, or ``None`` if no entry exists."""
    try:
        return keyring.get_password(service, account)
    except KeyringError as exc:
        raise VaultError(
            f"Failed to read credential from OS keyring "
            f"(service={service!r}, account={account!r}): {exc}"
        ) from exc


def forget(*, service: str, account: str) -> bool:
    """Delete the keyring entry. Returns True if something was deleted.

    Idempotent — deleting an absent entry is a no-op (returns False).
    """
    try:
        keyring.delete_password(service, account)
        return True
    except PasswordDeleteError:
        return False
    except KeyringError as exc:
        raise VaultError(
            f"Failed to delete credential from OS keyring "
            f"(service={service!r}, account={account!r}): {exc}"
        ) from exc


def github_service(login: str) -> str:
    """Canonical keyring service name for a GitHub PAT belonging to ``login``."""
    return f"rabbitsync:github:{login}"


__all__ = ["VaultError", "fetch", "forget", "github_service", "store"]

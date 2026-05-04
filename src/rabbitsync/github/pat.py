"""PAT verification — ``GET /user`` round-trip + scope/expiration parsing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from rabbitsync.github.api import GitHubApiError, GitHubClient


@dataclass(frozen=True)
class TokenInfo:
    """The verified facts about a GitHub PAT."""

    login: str
    scopes: tuple[str, ...]      # for fine-grained tokens this may be empty
    token_kind: str              # "fine-grained" | "classic" | "unknown"
    expires_at: datetime | None  # None when no expiration header is sent


def verify(token: str) -> TokenInfo:
    """Verify a PAT against the GitHub API and return what we learned.

    Raises :class:`rabbitsync.github.api.GitHubApiError` for invalid tokens
    (the message embeds the GitHub error body).
    """
    with GitHubClient(token=token) as client:
        response = client.get("/user")
        data = response.json()
        login = str(data.get("login") or "")
        if not login:
            raise GitHubApiError(response.status_code, "/user response missing 'login'")

        scopes_header = response.headers.get("x-oauth-scopes", "")
        scopes = tuple(s.strip() for s in scopes_header.split(",") if s.strip())

        expires_header = response.headers.get("github-authentication-token-expiration")
        expires_at = _parse_expiration(expires_header)

        token_kind = _classify_token(token)

        return TokenInfo(
            login=login,
            scopes=scopes,
            token_kind=token_kind,
            expires_at=expires_at,
        )


def _classify_token(token: str) -> str:
    if token.startswith("github_pat_"):
        return "fine-grained"
    if token.startswith("ghp_"):
        return "classic"
    return "unknown"


def _parse_expiration(header: str | None) -> datetime | None:
    """Parse the ``GitHub-Authentication-Token-Expiration`` header.

    Format observed in the wild: ``2026-04-01 00:00:00 UTC``.
    """
    if not header:
        return None
    text = header.strip()
    # Strip a trailing ' UTC' if present and let fromisoformat handle the rest.
    if text.endswith(" UTC"):
        text = text[:-4]
    text = text.replace(" ", "T")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


__all__ = ["TokenInfo", "verify"]

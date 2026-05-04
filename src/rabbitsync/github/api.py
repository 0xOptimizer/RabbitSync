"""httpx client for the GitHub REST API.

Pinned to ``https://api.github.com``. The client refuses outbound requests to
any other host — built into the wrapper, not a soft convention.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx

GITHUB_BASE_URL = "https://api.github.com"
DEFAULT_USER_AGENT = "rabbitsync/0.1"
DEFAULT_TIMEOUT_S = 30.0


class GitHubApiError(RuntimeError):
    """Raised on non-2xx responses (other than rate-limit retries)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"GitHub API {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class GitHubClient:
    """Minimal authenticated httpx client.

    All requests go through :meth:`get` / :meth:`paginated`. Construct with a
    PAT; the value is held in memory only for the duration of the client and
    is masked in any error path via :mod:`credentials.redactor`.
    """

    def __init__(
        self,
        *,
        token: str,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._client = httpx.Client(
            base_url=GITHUB_BASE_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": user_agent,
                "Authorization": f"Bearer {token}",
            },
            timeout=timeout_s,
            follow_redirects=False,
        )

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *_a: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        """One GET; honors the secondary rate-limit retry-after header."""
        for attempt in range(3):
            response = self._client.get(path, params=params)
            if response.status_code == 429 or (
                response.status_code == 403
                and response.headers.get("x-ratelimit-remaining") == "0"
            ):
                wait = self._retry_after_seconds(response)
                if wait is None or attempt == 2:
                    self._raise_for(response)
                time.sleep(wait)
                continue
            if response.status_code >= 400:
                self._raise_for(response)
            return response
        self._raise_for(response)
        # Unreachable; satisfies the type checker.
        raise GitHubApiError(response.status_code, "exhausted retries")

    def paginated(self, path: str, *, params: dict[str, Any] | None = None) -> Iterator[Any]:
        """Yield items from a paginated endpoint, following ``Link`` headers."""
        next_url: str | None = path
        next_params: dict[str, Any] | None = dict(params or {})
        while next_url is not None:
            response = self.get(next_url, params=next_params)
            data = response.json()
            if isinstance(data, list):
                yield from data
            else:
                yield data
            next_url = self._next_link(response)
            # After the first request the next URL is absolute; httpx handles it.
            next_params = None

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        header = response.headers.get("retry-after")
        if header:
            try:
                return float(header)
            except ValueError:
                return None
        reset = response.headers.get("x-ratelimit-reset")
        if reset:
            try:
                target = float(reset)
                return max(1.0, target - time.time())
            except ValueError:
                return None
        return None

    @staticmethod
    def _next_link(response: httpx.Response) -> str | None:
        link = response.headers.get("link")
        if not link:
            return None
        for chunk in link.split(","):
            parts = chunk.strip().split(";")
            if len(parts) < 2:
                continue
            url_part = parts[0].strip().lstrip("<").rstrip(">")
            for rel in parts[1:]:
                if rel.strip() == 'rel="next"':
                    return url_part
        return None

    @staticmethod
    def _raise_for(response: httpx.Response) -> None:
        try:
            data = response.json()
            message = data.get("message", "") if isinstance(data, dict) else str(data)
        except (ValueError, httpx.DecodingError):
            message = response.text or "<no body>"
        raise GitHubApiError(response.status_code, message)


__all__ = ["GITHUB_BASE_URL", "GitHubApiError", "GitHubClient"]

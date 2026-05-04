"""Standalone secret-redaction utility.

The structlog pipeline already redacts via ``rabbitsync.logging.setup``; this
module exposes the same patterns for non-log call sites (e.g. error message
formatting in dialogs, when echoing user-paste back).
"""

from __future__ import annotations

import re

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"ghs_[A-Za-z0-9]{30,}"),
    re.compile(r"gho_[A-Za-z0-9]{30,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
)
_REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Return ``text`` with credential-shaped substrings replaced."""
    out = text
    for pattern in _PATTERNS:
        out = pattern.sub(_REDACTED, out)
    return out


__all__ = ["redact"]

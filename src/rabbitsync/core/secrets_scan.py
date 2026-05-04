"""Advisory secret scan run before sync.

Pure regex sweep across the about-to-be-synced file set. Findings are
shown to the user with options to continue, exclude via .rabbitsyncignore,
or cancel. The scan is opt-out per pair (default on).

This is *advisory* — it cannot detect every secret, only common shapes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Patterns and their human-readable labels.
_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("GitHub fine-grained PAT", re.compile(rb"github_pat_[A-Za-z0-9_]{20,}")),
    ("GitHub classic PAT", re.compile(rb"ghp_[A-Za-z0-9]{30,}")),
    ("GitHub OAuth token", re.compile(rb"gho_[A-Za-z0-9]{30,}")),
    ("GitHub server token", re.compile(rb"ghs_[A-Za-z0-9]{30,}")),
    ("AWS access key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("Private key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Slack token", re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}")),
)

# Don't bother scanning files larger than this (likely binary or generated).
_MAX_SCAN_BYTES = 1 * 1024 * 1024


@dataclass(frozen=True)
class SecretFinding:
    rel_path: str
    line: int
    label: str
    snippet: str  # surrounding text, secret value redacted


def scan_files(folder: Path, rel_paths: list[str]) -> list[SecretFinding]:
    """Scan the given relative paths under ``folder`` for secret-shaped strings.

    Returns one finding per match. Caller is expected to deduplicate by path
    if a friendlier UI summary is desired.
    """
    findings: list[SecretFinding] = []
    for rel in rel_paths:
        path = folder / rel
        try:
            if not path.is_file():
                continue
            if path.stat().st_size > _MAX_SCAN_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        findings.extend(_scan_bytes(rel, data))
    return findings


def _scan_bytes(rel_path: str, data: bytes) -> list[SecretFinding]:
    out: list[SecretFinding] = []
    # Compute line numbers cheaply by counting newlines up to the match.
    for label, pattern in _PATTERNS:
        for m in pattern.finditer(data):
            start = m.start()
            line = data.count(b"\n", 0, start) + 1
            snippet = _build_snippet(data, start, m.end())
            out.append(SecretFinding(
                rel_path=rel_path,
                line=line,
                label=label,
                snippet=snippet,
            ))
    return out


def _build_snippet(data: bytes, start: int, end: int) -> str:
    """Return ~80 chars of context around the match with the value redacted."""
    line_start = data.rfind(b"\n", 0, start) + 1
    line_end = data.find(b"\n", end)
    if line_end == -1:
        line_end = len(data)
    line = data[line_start:line_end]
    redacted = line[: start - line_start] + b"[REDACTED]" + line[end - line_start :]
    text = redacted.decode("utf-8", errors="replace").rstrip()
    return text[:160] + ("…" if len(text) > 160 else "")


__all__ = ["SecretFinding", "scan_files"]

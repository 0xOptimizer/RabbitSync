"""Path-safety guards for Windows file-system operations.

Threat model
------------
Sync writes file paths derived from the source folder's working tree. A
malicious or malformed source could include:

- Absolute paths (``C:\\Windows\\System32``) — would write outside copy.
- Parent-traversal segments (``..\\..\\..\\Users\\Admin``) — same risk.
- Symlinks pointing outside the registered folder.
- Reserved Windows names (``CON``, ``PRN``, ``AUX``, ``NUL``, ``COM1``-``COM9``,
  ``LPT1``-``LPT9``) which Windows treats specially even when in a subfolder.
- Trailing dots/spaces — silently stripped by Win32, can collide with sibling
  files.
- Paths exceeding ``MAX_PATH`` (260 chars) without the ``\\\\?\\`` prefix.

This module rejects unsafe paths at preflight time and provides helpers to
normalize and verify them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePath, PureWindowsPath


class UnsafePathError(ValueError):
    """Raised when a path fails a safety check."""


_RESERVED_NAMES: frozenset[str] = frozenset(
    {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def is_within(path: Path, root: Path) -> bool:
    """True iff ``path`` is contained within ``root`` after symlink resolution.

    Uses ``Path.resolve(strict=False)`` so missing leaves are tolerated, but
    any existing intermediate symlinks are followed. The comparison is done on
    the resolved real paths to defeat ``..`` traversal and symlink escapes.
    """
    try:
        rp = path.resolve(strict=False)
        rr = root.resolve(strict=False)
    except OSError as exc:
        raise UnsafePathError(f"could not resolve {path!s}: {exc}") from exc
    try:
        rp.relative_to(rr)
    except ValueError:
        return False
    return True


def assert_within(path: Path, root: Path, *, what: str = "path") -> None:
    """Raise :class:`UnsafePathError` if ``path`` is not within ``root``."""
    if not is_within(path, root):
        raise UnsafePathError(
            f"{what} {path!s} resolves outside its expected root {root!s}"
        )


def is_reserved_windows_name(name: str) -> bool:
    """True if ``name`` (a single path component, no extension considered) is
    one of Windows' reserved device names.

    Windows treats ``CON.txt`` the same as ``CON`` for reservation purposes —
    so we check the stem.
    """
    stem = name.split(".", 1)[0].upper()
    return stem in _RESERVED_NAMES


def has_unsafe_components(rel_path: str) -> bool:
    """True if a *relative* path string contains components that are unsafe to
    write on Windows.

    Checks for: empty path, absolute drive specs, parent-traversal, trailing
    dots/spaces in components, NUL bytes, and reserved device names.
    """
    if not rel_path:
        return True
    if "\x00" in rel_path:
        return True
    pure: PurePath = PureWindowsPath(rel_path)
    if pure.is_absolute() or pure.drive:
        return True
    for part in pure.parts:
        if part in (".", ".."):
            return True
        if part != part.rstrip(". "):
            return True
        if is_reserved_windows_name(part):
            return True
    return False


def long_path(path: Path) -> Path:
    """Return ``path`` with the ``\\\\?\\`` extended-length prefix on Windows.

    Required for paths longer than ``MAX_PATH`` (260) on systems where the
    long-path opt-in is not enabled. No-op on POSIX.
    """
    if sys.platform != "win32":
        return path
    s = str(path.resolve(strict=False))
    if s.startswith("\\\\?\\"):
        return path
    if s.startswith("\\\\"):  # UNC: \\server\share -> \\?\UNC\server\share
        return Path("\\\\?\\UNC\\" + s.lstrip("\\"))
    return Path("\\\\?\\" + s)


def is_symlink_escaping(path: Path, root: Path) -> bool:
    """True if ``path`` is a symlink whose target resolves outside ``root``."""
    try:
        if not path.is_symlink():
            return False
    except OSError:
        return False
    return not is_within(path, root)


__all__ = [
    "UnsafePathError",
    "assert_within",
    "has_unsafe_components",
    "is_reserved_windows_name",
    "is_symlink_escaping",
    "is_within",
    "long_path",
]


# os is imported for future expansion (perms checks); reference it to satisfy
# strict unused-import linting without a special-case ignore.
_ = os

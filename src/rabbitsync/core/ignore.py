"""Ignore-rule resolver for sync.

Three sources, evaluated additively in this order:

1. ``<source>/.gitignore`` plus any ancestor ``.gitignore`` that applies
   (only when source is in a git repo and the registered folder is the root
   of consideration; for subpath registration we still walk source's git
   ancestors to honor the same rules git itself would apply).
2. ``<source>/.rabbitsyncignore`` — additional excludes specific to RabbitSync.
3. ``<copy>/.rabbitsync-keep`` — copy-side allowlist of files that sync must
   never touch (overrides the include set; never overrides excludes).

All paths are evaluated relative to the registered folder, never the git
working-tree root, so a subpath registration sees only its own subtree.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pathspec


@dataclass(frozen=True)
class IgnoreRules:
    """Compiled ignore + keep rules for a single side of a sync pair."""

    excludes: pathspec.PathSpec
    keep: pathspec.PathSpec  # paths matched here are NEVER touched by sync

    def is_excluded(self, rel_path: str) -> bool:
        """True if the given relative path should be excluded from sync."""
        return self.excludes.match_file(rel_path)

    def is_kept(self, rel_path: str) -> bool:
        """True if the path is in the copy-side keep allowlist."""
        return self.keep.match_file(rel_path)


def load_for_pair(
    *,
    source_folder: Path,
    copy_folder: Path,
    extra_ignore_files: tuple[Path, ...] = (),
) -> IgnoreRules:
    """Build :class:`IgnoreRules` for a registered source/copy pair.

    Reads ignore files relative to the *registered folders*, not the git roots.
    Missing files are treated as empty.
    """
    patterns: list[str] = []

    # 1. .gitignore at source root (and walk a small set of common subdirs?
    #    For correctness we rely on `git check-ignore` semantics later; for
    #    now we approximate by reading the top-level .gitignore which covers
    #    the vast majority of cases. Per-directory .gitignore files are
    #    handled by walking them during scan.)
    patterns.extend(_read_patterns(source_folder / ".gitignore"))

    # 2. .rabbitsyncignore at source root
    patterns.extend(_read_patterns(source_folder / ".rabbitsyncignore"))

    # 3. Any user-configured extra ignore files
    for p in extra_ignore_files:
        patterns.extend(_read_patterns(p))

    # Always exclude the .git directory itself from sync.
    patterns.append(".git/")
    patterns.append(".git")
    # Always exclude RabbitSync's own keep file from being copied
    # (it's metadata local to copy).
    patterns.append(".rabbitsync-keep")

    excludes = pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    keep_patterns = _read_patterns(copy_folder / ".rabbitsync-keep")
    keep = pathspec.PathSpec.from_lines("gitwildmatch", keep_patterns)

    return IgnoreRules(excludes=excludes, keep=keep)


def per_directory_patterns(folder: Path) -> list[str]:
    """Read patterns from a folder's ``.gitignore`` if present.

    Used by the diff scanner to honor per-directory ``.gitignore`` files
    encountered while walking. Returns ``[]`` when no file exists.
    """
    return _read_patterns(folder / ".gitignore")


def _read_patterns(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


__all__ = ["IgnoreRules", "load_for_pair", "per_directory_patterns"]

"""Typed subprocess wrapper around the ``git`` binary.

Threat model
------------
``git`` is the source of truth for repository state; using a Python git library
would mean RabbitSync interprets the on-disk format, which lags upstream. This
wrapper instead shells out to the git binary the user already has installed,
captures stdout/stderr cleanly, and surfaces structured results.

All invocations are **argv-only** (``shell=False``); arguments are passed as a
list and never interpolated into a shell command line. The repo's working tree
is set via ``cwd``; we never compose paths into the command string.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class GitNotInstalledError(RuntimeError):
    """Raised when ``git`` is not on PATH."""

    def __init__(self) -> None:
        super().__init__(
            "git is not installed or not on PATH. Install Git for Windows from "
            "https://git-scm.com/download/win and restart RabbitSync."
        )


class GitCommandError(RuntimeError):
    """Raised when a git invocation exits non-zero."""

    def __init__(self, argv: Sequence[str], cwd: Path | None, code: int, stderr: str) -> None:
        location = f" (cwd={cwd})" if cwd is not None else ""
        msg = (
            f"git {' '.join(argv[1:])}{location} failed with exit code {code}: "
            f"{stderr.strip() or '<no stderr>'}"
        )
        super().__init__(msg)
        self.argv = list(argv)
        self.cwd = cwd
        self.exit_code = code
        self.stderr = stderr


@dataclass(frozen=True)
class GitResult:
    """The outcome of a single git invocation."""

    argv: tuple[str, ...]
    cwd: Path | None
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class GitRunner:
    """Run git commands against an optional working directory.

    A single :class:`GitRunner` is bound to a specific repository (via the
    ``cwd`` constructor arg). For ad-hoc invocations not tied to a repo
    (e.g. ``git --version``), use :meth:`run_at` with ``cwd=None``.
    """

    DEFAULT_TIMEOUT_S = 60.0

    def __init__(self, cwd: Path | None = None, *, git_binary: str | None = None) -> None:
        self._cwd = cwd
        self._git_binary = git_binary

    @property
    def cwd(self) -> Path | None:
        return self._cwd

    @classmethod
    def find_binary(cls) -> str:
        """Return the absolute path to the ``git`` executable, or raise.

        Tries multiple lookup strategies because ``shutil.which("git")`` can
        return ``None`` on Windows even when git is on PATH — particularly
        inside virtualenvs where PATHEXT may not propagate cleanly:

        1. ``shutil.which("git")``
        2. ``shutil.which("git.exe")``
        3. ``where git`` (the Windows shell builtin)
        4. Standard Git for Windows install locations.

        The first hit wins and is cached for the process lifetime.
        """
        global _CACHED_GIT_BINARY
        if _CACHED_GIT_BINARY is not None:
            return _CACHED_GIT_BINARY
        for candidate in _resolve_git_candidates():
            if candidate and Path(candidate).is_file():
                _CACHED_GIT_BINARY = candidate
                return candidate
        raise GitNotInstalledError

    def version(self) -> str:
        """Return the ``git --version`` string (e.g. ``"git version 2.46.0"``)."""
        result = self.run_at(None, ["--version"], check=True)
        return result.stdout.strip()

    def run(self, args: Sequence[str], *, check: bool = True, timeout: float | None = None) -> GitResult:
        """Run a git subcommand against this runner's cwd."""
        return self.run_at(self._cwd, args, check=check, timeout=timeout)

    def run_at(
        self,
        cwd: Path | None,
        args: Sequence[str],
        *,
        check: bool = True,
        timeout: float | None = None,
    ) -> GitResult:
        """Run a git subcommand at the given working directory.

        Always invokes git with ``shell=False`` and a fully-resolved binary
        path. Captures stdout and stderr as text (UTF-8, errors=``replace``).
        """
        binary = self._git_binary or self.find_binary()
        argv: list[str] = [binary, *args]
        try:
            completed = subprocess.run(  # noqa: S603 -- argv list, shell=False
                argv,
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                timeout=timeout if timeout is not None else self.DEFAULT_TIMEOUT_S,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GitNotInstalledError from exc
        result = GitResult(
            argv=tuple(argv),
            cwd=cwd,
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        if check and not result.ok:
            raise GitCommandError(argv, cwd, result.exit_code, result.stderr)
        return result


_CACHED_GIT_BINARY: str | None = None


def _resolve_git_candidates() -> list[str]:
    """Yield candidate absolute paths to the ``git`` binary."""
    out: list[str] = []
    for name in ("git", "git.exe"):
        hit = shutil.which(name)
        if hit:
            out.append(hit)

    # `where` is more permissive than shutil.which on Windows in some venv
    # configurations because it queries the OS resolver directly.
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["where", "git"],
            capture_output=True, text=True, check=False, timeout=5, shell=False,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line:
                    out.append(line)
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass

    # Standard Git for Windows install locations.
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    for base in (program_files, program_files_x86):
        out.append(str(Path(base) / "Git" / "cmd" / "git.exe"))
        out.append(str(Path(base) / "Git" / "bin" / "git.exe"))
    if local_app_data:
        out.append(str(Path(local_app_data) / "Programs" / "Git" / "cmd" / "git.exe"))

    # De-dup while preserving order.
    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        norm = str(Path(p)).lower()
        if norm in seen:
            continue
        seen.add(norm)
        uniq.append(p)
    return uniq


__all__ = [
    "GitCommandError",
    "GitNotInstalledError",
    "GitResult",
    "GitRunner",
]

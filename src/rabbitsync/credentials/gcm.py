"""Detect Git Credential Manager (GCM) presence.

When GCM is installed, ``git push`` / ``pull`` / ``clone`` over HTTPS will
prompt the OS-native credential dialog and store its result in the OS vault
without RabbitSync ever seeing the credential. This is the recommended
default for git operations; RabbitSync's PAT is then used only for the
GitHub REST API (listing/cloning).

The detection is best-effort: presence on PATH or as a configured
``credential.helper`` is reported. Caller decides what to do with the info.
"""

from __future__ import annotations

import shutil
import subprocess


def is_available() -> bool:
    """True if Git Credential Manager appears to be installed."""
    if shutil.which("git-credential-manager") is not None:
        return True
    # Older installs use git-credential-manager-core
    if shutil.which("git-credential-manager-core") is not None:
        return True
    # Bundled GCM ships inside Git for Windows; the helper is then
    # configured in git's global config rather than as a separate exe.
    return _git_helper_mentions_manager()


def _git_helper_mentions_manager() -> bool:
    git = shutil.which("git")
    if git is None:
        return False
    try:
        result = subprocess.run(  # noqa: S603 -- argv list, shell=False
            [git, "config", "--global", "--get-all", "credential.helper"],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    haystack = (result.stdout or "").lower()
    return "manager" in haystack


def version() -> str | None:
    """Return GCM's version string, or ``None`` if not installed."""
    for name in ("git-credential-manager", "git-credential-manager-core"):
        binary = shutil.which(name)
        if binary is None:
            continue
        try:
            result = subprocess.run(  # noqa: S603 -- argv list, shell=False
                [binary, "--version"],
                capture_output=True, text=True, check=False, timeout=10,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            return result.stdout.strip() or None
    return None


__all__ = ["is_available", "version"]

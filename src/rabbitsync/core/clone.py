"""``git clone`` orchestration with progress streaming.

Spawns ``git clone --progress`` and parses the percent updates from stderr
so the UI can show a determinate progress bar. The implementation streams
output line-by-line; the entire clone never holds more than one progress
update in memory.

Cancellation
------------
The orchestrator returns a :class:`CloneHandle` you can call ``cancel()`` on.
Cancellation kills the git process tree (Windows: ``taskkill /T /F``).
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Lines like "Receiving objects: 42% (210/500), 1.20 MiB | 4.50 MiB/s"
_PROGRESS_RE = re.compile(r"^([A-Za-z][A-Za-z ]+):\s+(\d{1,3})%")


@dataclass(frozen=True)
class CloneProgress:
    phase: str       # 'Counting objects' / 'Receiving objects' / etc.
    percent: int     # 0..100
    raw: str         # full stderr line, for log dock display


@dataclass(frozen=True)
class CloneResult:
    ok: bool
    exit_code: int
    target_dir: Path
    stderr_tail: str


class CloneHandle:
    """Tracks a running clone so it can be observed and cancelled."""

    def __init__(self, proc: subprocess.Popen[str], target: Path) -> None:
        self._proc = proc
        self._target = target
        self._cancelled = False

    @property
    def pid(self) -> int:
        return self._proc.pid

    @property
    def target(self) -> Path:
        return self._target

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        if sys.platform == "win32":
            subprocess.run(  # noqa: S603, S607
                ["taskkill", "/T", "/F", "/PID", str(self._proc.pid)],
                capture_output=True, check=False,
            )
        else:
            try:
                self._proc.terminate()
            except OSError:
                pass


def clone(
    *,
    url: str,
    target: Path,
    branch: str | None = None,
    depth: int | None = None,
    on_progress: Callable[[CloneProgress], None] | None = None,
    git_binary: str | None = None,
) -> CloneResult:
    """Run ``git clone`` and stream progress updates.

    Returns a :class:`CloneResult` once git exits. Errors during clone
    surface as ``ok=False`` with the captured stderr tail; the function
    does not raise unless git itself is missing.
    """
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(
            f"Clone target {target} exists and is not empty. "
            "Pick a different folder or remove the existing one."
        )
    target.parent.mkdir(parents=True, exist_ok=True)

    git = git_binary or _resolve_git()
    argv: list[str] = [git, "clone", "--progress"]
    if branch is not None:
        argv += ["--branch", branch]
    if depth is not None:
        argv += ["--depth", str(int(depth))]
    argv += [url, str(target)]

    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(  # noqa: S603 -- argv list, shell=False
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
    )
    handle = CloneHandle(proc, target)
    stderr_tail: list[str] = []

    def _read_stderr() -> None:
        assert proc.stderr is not None
        for raw_line in proc.stderr:
            line = raw_line.rstrip("\r\n")
            stderr_tail.append(line)
            if len(stderr_tail) > 200:
                stderr_tail.pop(0)
            if on_progress is None:
                continue
            m = _PROGRESS_RE.match(line)
            if m:
                try:
                    pct = int(m.group(2))
                except ValueError:
                    continue
                on_progress(CloneProgress(phase=m.group(1), percent=pct, raw=line))

    reader = threading.Thread(target=_read_stderr, name="rabbitsync-clone-stderr", daemon=True)
    reader.start()
    proc.wait()
    reader.join(timeout=5)

    return CloneResult(
        ok=proc.returncode == 0 and not handle._cancelled,  # noqa: SLF001
        exit_code=proc.returncode,
        target_dir=target,
        stderr_tail="\n".join(stderr_tail[-50:]),
    )


def _resolve_git() -> str:
    import shutil

    binary = shutil.which("git")
    if binary is None:
        raise RuntimeError(
            "git is not installed or not on PATH. Install Git for Windows from "
            "https://git-scm.com/download/win and try again."
        )
    return binary


__all__ = ["CloneHandle", "CloneProgress", "CloneResult", "clone"]

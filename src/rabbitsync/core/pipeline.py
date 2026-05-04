"""Pipeline runner — argv-only subprocess execution with hard safety rails.

Threat model
------------
The user explicitly stated they cannot risk damage to the host. Pipelines are
the most dangerous subsystem after sync deletion because they execute user-
supplied commands. The runner is built around constraint, not convenience:

- **Argv-only.** ``subprocess.Popen(argv, shell=False, …)``. ``shell=True``
  is forbidden codebase-wide by lint. There is no string-to-shell parsing,
  no ``os.system``, no ``os.popen``.
- **Tokenized argv editor in the UI** (Phase 16) — the user cannot type a
  shell command anywhere; each argument is a separate input field.
- **cwd is constrained.** Resolved from the per-step ``cwd_kind`` enum
  (``source`` / ``copy`` / ``subpath``); refused if it escapes the registered
  pair's source or copy folder, or if it lands inside RabbitSync's ``data/``.
- **Environment is allowlist-curated.** Sensitive ambient vars
  (``AWS_*``, ``GITHUB_TOKEN``, ``RABBITSYNC_*``) are stripped unless the
  user explicitly adds them per-step.
- **Hard timeout per step** with process-group kill on Windows
  (``CREATE_NEW_PROCESS_GROUP`` + ``taskkill /T /F``).
- **Output capped** at 50 MB per stream per run.
- **Refuses to run when RabbitSync is elevated** (overridable in Settings).

Step caching
------------
A step is skipped if all its declared input globs hash identically to the
last successful run. The cache key is the SHA-256 of: argv + env_extra +
cwd + sorted(input_file_hashes). Cache lookup happens before subprocess
launch — no side effects.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from rabbitsync.core.hashing import xxh64_file
from rabbitsync.logging.setup import get_logger
from rabbitsync.paths import pipelines_dir

_log = get_logger("core.pipeline")

# Per-stream output cap (50 MB) — beyond this, we keep the head and a
# truncation marker. Prevents a runaway process from filling disk via logs.
_MAX_STREAM_BYTES = 50 * 1024 * 1024

# Allowlist of ambient env vars passed through to pipeline subprocesses.
# Sensitive vars (AWS_*, GITHUB_TOKEN, RABBITSYNC_*) are NOT on this list and
# must be added per-step via env_extra.
_ENV_ALLOWLIST: frozenset[str] = frozenset({
    "PATH", "PATHEXT",
    "SystemRoot", "SYSTEMROOT", "WINDIR", "ComSpec", "COMSPEC",
    "TEMP", "TMP", "USERPROFILE", "USERNAME", "USERDOMAIN", "COMPUTERNAME",
    "HOMEDRIVE", "HOMEPATH",
    "LANG", "LC_ALL", "LC_CTYPE", "LC_COLLATE",
    "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
    "PYTHONIOENCODING",
})


@dataclass(frozen=True)
class StepDef:
    """Definition of one pipeline step."""

    name: str
    argv: tuple[str, ...]
    cwd: Path
    env_extra: dict[str, str] = field(default_factory=dict)
    timeout_s: int = 300
    on_fail: str = "abort"           # 'abort' | 'continue'
    inputs_globs: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StepResult:
    """The outcome of one step's execution."""

    name: str
    status: str        # 'ok' | 'failed' | 'timeout' | 'cached' | 'skipped'
    exit_code: int | None
    started_at: str
    finished_at: str
    duration_s: float
    stdout_path: Path | None
    stderr_path: Path | None
    cache_input_hash: str | None


@dataclass(frozen=True)
class RunResult:
    """The outcome of a whole pipeline run."""

    run_id: str
    artifacts_dir: Path
    started_at: str
    finished_at: str
    status: str        # 'ok' | 'failed' | 'aborted' | 'cancelled'
    steps: tuple[StepResult, ...]


class ElevationRefusedError(RuntimeError):
    """Raised when RabbitSync is running elevated and the user hasn't allowed it."""


class CwdRefusedError(ValueError):
    """Raised when a step's cwd escapes the pair or lands inside data/."""


def run_pipeline(
    *,
    pair_id: str,
    steps: Iterable[StepDef],
    pair_source: Path,
    pair_copy: Path,
    data_root: Path | None = None,
    allow_elevated: bool = False,
    cache_lookup: callable | None = None,  # type: ignore[type-arg]
    cache_store: callable | None = None,   # type: ignore[type-arg]
) -> RunResult:
    """Execute every step in order. Returns the run result.

    ``cache_lookup`` and ``cache_store`` are optional callables wired by
    the UI to the ``step_cache`` table; in tests they default to no-op.
    """
    if not allow_elevated and _is_elevated():
        raise ElevationRefusedError(
            "RabbitSync is running elevated; pipeline runs are blocked by default. "
            "Restart RabbitSync without administrator privileges, or enable "
            "Settings → Advanced → Allow pipelines while elevated."
        )

    run_id = str(uuid.uuid4())
    artifacts = pipelines_dir() / pair_id / run_id
    artifacts.mkdir(parents=True, exist_ok=True)

    started = _now()
    started_perf = time.perf_counter()
    results: list[StepResult] = []
    overall_status = "ok"

    for step in steps:
        _validate_cwd(step.cwd, pair_source, pair_copy, data_root)
        step_result = _run_step(
            step,
            artifacts_dir=artifacts,
            cache_lookup=cache_lookup,
            cache_store=cache_store,
        )
        results.append(step_result)
        if step_result.status in {"failed", "timeout"} and step.on_fail == "abort":
            overall_status = "failed"
            break

    finished = _now()
    duration = time.perf_counter() - started_perf
    _log.info(
        "pipeline.run.done",
        run_id=run_id, pair_id=pair_id, status=overall_status,
        duration_s=duration, step_count=len(results),
    )

    # Persist a result.json for the UI to render later.
    _write_result_json(artifacts, run_id=run_id, status=overall_status, steps=results)

    return RunResult(
        run_id=run_id,
        artifacts_dir=artifacts,
        started_at=started,
        finished_at=finished,
        status=overall_status,
        steps=tuple(results),
    )


def _run_step(
    step: StepDef,
    *,
    artifacts_dir: Path,
    cache_lookup: callable | None,  # type: ignore[type-arg]
    cache_store: callable | None,  # type: ignore[type-arg]
) -> StepResult:
    started = _now()
    started_perf = time.perf_counter()

    # Step caching by input hash.
    input_hash = _compute_input_hash(step) if step.inputs_globs else None
    if input_hash is not None and cache_lookup is not None:
        cached = cache_lookup(step.name, input_hash)
        if cached is not None:
            _log.info("pipeline.step.cached", step=step.name, input_hash=input_hash)
            return StepResult(
                name=step.name, status="cached", exit_code=0,
                started_at=started, finished_at=_now(),
                duration_s=time.perf_counter() - started_perf,
                stdout_path=None, stderr_path=None,
                cache_input_hash=input_hash,
            )

    stdout_path = artifacts_dir / f"{step.name}.stdout.log"
    stderr_path = artifacts_dir / f"{step.name}.stderr.log"
    env = _build_env(step.env_extra)

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

    _log.info("pipeline.step.start", step=step.name, argv=list(step.argv),
              cwd=str(step.cwd), timeout_s=step.timeout_s)

    try:
        proc = subprocess.Popen(  # noqa: S603 -- argv list, shell=False
            list(step.argv),
            cwd=str(step.cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=creation_flags,
        )
    except FileNotFoundError as exc:
        finished = _now()
        _write_text(stderr_path, f"binary not found: {step.argv[0]}\n{exc}\n")
        return StepResult(
            name=step.name, status="failed", exit_code=None,
            started_at=started, finished_at=finished,
            duration_s=time.perf_counter() - started_perf,
            stdout_path=None, stderr_path=stderr_path, cache_input_hash=input_hash,
        )

    stdout_bytes = bytearray()
    stderr_bytes = bytearray()
    timed_out = False
    try:
        stdout_b, stderr_b = proc.communicate(timeout=step.timeout_s)
        stdout_bytes.extend(stdout_b or b"")
        stderr_bytes.extend(stderr_b or b"")
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc.pid)
        try:
            stdout_b, stderr_b = proc.communicate(timeout=5)
            stdout_bytes.extend(stdout_b or b"")
            stderr_bytes.extend(stderr_b or b"")
        except subprocess.TimeoutExpired:
            pass

    _write_capped(stdout_path, bytes(stdout_bytes))
    _write_capped(stderr_path, bytes(stderr_bytes))

    finished = _now()
    duration = time.perf_counter() - started_perf

    if timed_out:
        status = "timeout"
        exit_code = None
    elif proc.returncode == 0:
        status = "ok"
        exit_code = 0
        if input_hash is not None and cache_store is not None:
            cache_store(step.name, input_hash)
    else:
        status = "failed"
        exit_code = proc.returncode

    _log.info("pipeline.step.done", step=step.name, status=status,
              exit_code=exit_code, duration_s=duration)

    return StepResult(
        name=step.name, status=status, exit_code=exit_code,
        started_at=started, finished_at=finished, duration_s=duration,
        stdout_path=stdout_path, stderr_path=stderr_path,
        cache_input_hash=input_hash,
    )


def _validate_cwd(cwd: Path, pair_source: Path, pair_copy: Path, data_root: Path | None) -> None:
    cwd_resolved = cwd.resolve(strict=False)
    src_resolved = pair_source.resolve(strict=False)
    cpy_resolved = pair_copy.resolve(strict=False)

    in_source = _is_within(cwd_resolved, src_resolved)
    in_copy = _is_within(cwd_resolved, cpy_resolved)
    if not (in_source or in_copy):
        raise CwdRefusedError(
            f"Pipeline cwd {cwd_resolved} is outside the registered pair "
            f"(source={src_resolved}, copy={cpy_resolved}). "
            "Pick a folder under one of those."
        )

    if data_root is not None:
        data_resolved = data_root.resolve(strict=False)
        if _is_within(cwd_resolved, data_resolved):
            raise CwdRefusedError(
                f"Pipeline cwd {cwd_resolved} is inside RabbitSync's data directory "
                f"({data_resolved}). RabbitSync's own state must not be modified by pipelines."
            )


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _build_env(env_extra: dict[str, str]) -> dict[str, str]:
    base: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in _ENV_ALLOWLIST:
            base[key] = value
    base["PYTHONIOENCODING"] = "utf-8"
    base.update(env_extra)
    return base


def _compute_input_hash(step: StepDef) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(list(step.argv), sort_keys=True).encode("utf-8"))
    h.update(b"\x00")
    h.update(json.dumps(step.env_extra, sort_keys=True).encode("utf-8"))
    h.update(b"\x00")
    h.update(str(step.cwd).encode("utf-8"))
    h.update(b"\x00")

    matched: list[Path] = []
    for pattern in step.inputs_globs:
        matched.extend(sorted(step.cwd.glob(pattern)))
    seen: set[Path] = set()
    for p in matched:
        if p in seen or not p.is_file():
            continue
        seen.add(p)
        try:
            file_hash = xxh64_file(p)
        except OSError:
            continue
        h.update(p.relative_to(step.cwd).as_posix().encode("utf-8"))
        h.update(b":")
        h.update(file_hash.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _kill_tree(pid: int) -> None:
    """Kill a process and all its children. Windows-specific."""
    if sys.platform == "win32":
        # /T = tree, /F = force; this is the standard way to kill a process
        # group on Windows when you don't have POSIX process groups.
        subprocess.run(  # noqa: S603, S607
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True, check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(pid), 15)
            time.sleep(0.5)
            os.killpg(os.getpgid(pid), 9)
        except (OSError, ProcessLookupError):
            pass


def _write_capped(path: Path, data: bytes) -> None:
    if len(data) <= _MAX_STREAM_BYTES:
        path.write_bytes(data)
        return
    head = data[:_MAX_STREAM_BYTES]
    marker = (
        f"\n\n[RabbitSync] truncated: original was {len(data)} bytes, "
        f"kept first {_MAX_STREAM_BYTES} bytes\n"
    ).encode("utf-8")
    path.write_bytes(head + marker)


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _write_result_json(
    artifacts: Path, *, run_id: str, status: str, steps: list[StepResult],
) -> None:
    payload = {
        "run_id": run_id,
        "status": status,
        "steps": [
            {
                "name": s.name, "status": s.status, "exit_code": s.exit_code,
                "started_at": s.started_at, "finished_at": s.finished_at,
                "duration_s": s.duration_s,
                "stdout": str(s.stdout_path) if s.stdout_path else None,
                "stderr": str(s.stderr_path) if s.stderr_path else None,
                "cache_input_hash": s.cache_input_hash,
            }
            for s in steps
        ],
    }
    (artifacts / "result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def _is_elevated() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 -- defensive; default to "not elevated"
        return False


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="milliseconds")


__all__ = [
    "CwdRefusedError",
    "ElevationRefusedError",
    "RunResult",
    "StepDef",
    "StepResult",
    "run_pipeline",
]

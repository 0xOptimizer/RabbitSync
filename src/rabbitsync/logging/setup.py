"""Configure structlog with RabbitSync's two-sink pipeline + secret redaction.

This module is the only place in the codebase that wires up structlog. The
secret redactor is applied as the FIRST processor so credential values never
reach any downstream sink, regardless of how they entered the event dict.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import structlog

from rabbitsync.logging.sinks import JsonlFileSink, QtSignalSink
from rabbitsync.paths import logs_dir

# Patterns that match common credential shapes. These are masked at log-write
# time across every level — credentials must never appear in any sink, even at
# TRACE/DEBUG, even by mistake.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"ghs_[A-Za-z0-9]{30,}"),
    re.compile(r"gho_[A-Za-z0-9]{30,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_REDACTED = "[REDACTED]"


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        out = value
        for pattern in _SECRET_PATTERNS:
            out = pattern.sub(_REDACTED, out)
        return out
    if isinstance(value, Mapping):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        coerced = [_redact(v) for v in value]
        return type(value)(coerced) if isinstance(value, tuple) else coerced
    return value


def _redactor(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor that masks credential-shaped values everywhere."""
    return {k: _redact(v) for k, v in event_dict.items()}


def _add_iso_timestamp(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict["ts"] = _dt.datetime.now(_dt.UTC).isoformat(timespec="milliseconds")
    return event_dict


# A single shared QtSignalSink instance — the UI replaces its emit callback
# once the signal-bearing object exists. Producers can log before the UI is up;
# the events are simply dropped from the UI sink (the file sink still records
# them).
ui_sink = QtSignalSink()


def configure(*, log_dir: Path | None = None, level: str = "INFO") -> None:
    """Install the global structlog configuration.

    Idempotent: calling twice will replace the previous configuration but
    keeps the same shared :data:`ui_sink` instance (so any UI binding made
    earlier is preserved).
    """
    target_dir = log_dir if log_dir is not None else logs_dir()
    today = _dt.date.today().isoformat()
    file_sink = JsonlFileSink(target_dir / f"rabbitsync-{today}.jsonl")

    structlog.configure(
        processors=[
            _redactor,
            _add_iso_timestamp,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            ui_sink,
            file_sink,
            structlog.processors.JSONRenderer(serializer=__import__("json").dumps),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_level_to_int(level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=_NullStream()),
        cache_logger_on_first_use=True,
    )


class _NullStream:
    """structlog requires a stream; we don't want stdout chatter on Windows GUI runs."""

    def write(self, _data: str) -> int:
        return 0

    def flush(self) -> None:
        pass


_LEVELS = {
    "TRACE": 5,
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


def _level_to_int(name: str) -> int:
    return _LEVELS.get(name.upper(), 20)


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger. Convenience re-export."""
    return structlog.get_logger(name) if name else structlog.get_logger()

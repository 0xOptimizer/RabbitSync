"""Log sinks used by structlog.

Two sinks share one structured event stream:

- :class:`JsonlFileSink` — appends one JSON object per line to a daily-rotated
  file under ``data/logs/``. Rotation by size (10 MB) and a configurable count.
- :class:`QtSignalSink` — pushes events through a Qt signal so the UI's log
  dock can render them live without coupling the producer to Qt.

The stdlib ``logging.handlers.RotatingFileHandler`` does the actual rotation;
we adapt structlog's processor pipeline onto its ``write`` interface.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Default rotation: 10 MB per file, keep 7 backups (one week of busy days).
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 7


class JsonlFileSink:
    """File sink that writes one JSON object per line, with size-based rotation.

    The sink is tolerant of non-serializable values: anything that ``json.dumps``
    cannot encode is coerced to ``repr()`` so a logging mistake never crashes
    the producer.
    """

    def __init__(
        self,
        path: Path,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        backup_count: int = _DEFAULT_BACKUP_COUNT,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handler = logging.handlers.RotatingFileHandler(
            filename=str(path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=True,
        )

    def __call__(self, _logger: Any, _name: str, event_dict: dict[str, Any]) -> str:
        line = json.dumps(event_dict, default=repr, ensure_ascii=False)
        record = logging.LogRecord(
            name="rabbitsync",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=line,
            args=None,
            exc_info=None,
        )
        self._handler.emit(record)
        return line

    def close(self) -> None:
        self._handler.close()


class QtSignalSink:
    """Sink that forwards events to a callable (typically a Qt signal emit).

    The callable is invoked synchronously on the producer thread; downstream
    Qt connections should be queued so the UI thread receives the event.

    The sink is registered without an actual signal during early bootstrap
    (when Qt is not yet imported); the caller installs the signal later by
    swapping in a different callable via :meth:`set_emit`.
    """

    def __init__(self, emit: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._emit: Callable[[dict[str, Any]], None] | None = emit

    def set_emit(self, emit: Callable[[dict[str, Any]], None] | None) -> None:
        self._emit = emit

    def __call__(self, _logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        if self._emit is not None:
            try:
                self._emit(dict(event_dict))
            except Exception:  # noqa: BLE001 -- never let UI sink crash the producer
                pass
        return event_dict

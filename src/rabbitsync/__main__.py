"""Entry point for ``python -m rabbitsync``.

Delegates to the same :func:`rabbitsync.app.run` that ``python main.py`` calls.
"""

from __future__ import annotations

from rabbitsync.app import run

if __name__ == "__main__":
    raise SystemExit(run())

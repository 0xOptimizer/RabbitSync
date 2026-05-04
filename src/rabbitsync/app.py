"""QApplication bootstrap and process lifecycle.

Boot order
----------
1. Configure structlog (file + UI sinks; secret redactor first).
2. Acquire the global app lockfile — refuse to launch if another instance holds it.
3. Initialize SQLite (WAL, migrations).
4. Start the DB writer thread.
5. Create QApplication, apply HiDPI policy, load fonts.
6. Show the main window.
7. Run the Qt event loop.
8. On exit, drain DB writer, release lockfile.
"""

from __future__ import annotations

import sys

from rabbitsync import __version__
from rabbitsync.db.connection import ConnectionFactory, initialize as db_initialize
from rabbitsync.db.writer import DbWriter
from rabbitsync.logging.setup import configure as configure_logging, get_logger
from rabbitsync.safety.lockfile import AppLock, LockHeldError


def run() -> int:
    """Boot RabbitSync and run the Qt event loop. Returns the exit code."""
    configure_logging()
    log = get_logger("app")
    log.info("app.start", version=__version__, python=sys.version.split()[0])

    try:
        with AppLock() as lock:
            log.info("app.lock_acquired", path=str(lock._path), pid=_pid())  # noqa: SLF001
            return _run_locked(log)
    except LockHeldError as exc:
        # The error message already names the holder PID and lockfile path.
        # Try to surface it via Qt if we can; fall back to stderr otherwise.
        _surface_lock_error(str(exc))
        log.error("app.lock_held", error=str(exc))
        return 2


def _run_locked(log: object) -> int:
    factory = ConnectionFactory()
    db_initialize(factory)
    log.info("app.db_initialized", path=str(factory.path))  # type: ignore[attr-defined]

    writer = DbWriter(factory)
    writer.start()
    log.info("app.db_writer_started")  # type: ignore[attr-defined]

    try:
        return _run_qt(log, writer)
    finally:
        writer.shutdown()
        log.info("app.db_writer_stopped")  # type: ignore[attr-defined]


def _run_qt(log: object, writer: DbWriter) -> int:
    # Defer Qt imports until after lock + DB are confirmed healthy. Importing
    # PySide6 is non-trivial; keeping it out of the early failure path makes
    # cold-start errors faster and more legible.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QPalette, QColor
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    qapp = QApplication.instance() or QApplication(sys.argv)
    qapp.setApplicationName("RabbitSync")
    qapp.setApplicationVersion(__version__)
    qapp.setOrganizationName("RabbitSync")

    # Force the Fusion style — it accepts our QSS cleanly across Windows
    # versions and ignores the legacy native theming that doesn't.
    qapp.setStyle("Fusion")

    # Apply our typography globally so QSS can rely on it.
    from rabbitsync.config.store import load_settings
    from rabbitsync.ui import qss as qss_mod
    from rabbitsync.ui.theme import Typography, palette_for

    settings = load_settings()
    theme_name = settings.theme if settings.theme in {"light", "dark"} else "dark"
    palette = palette_for(theme_name)

    qfont = QFont(Typography.UI_FAMILY.split(",")[0].strip())
    qfont.setPointSize(Typography.BASE_PT)
    qapp.setFont(qfont)

    # Set the QPalette so native widgets (message boxes etc.) match.
    qpal = QPalette()
    qpal.setColor(QPalette.ColorRole.Window, QColor(palette.bg))
    qpal.setColor(QPalette.ColorRole.WindowText, QColor(palette.fg))
    qpal.setColor(QPalette.ColorRole.Base, QColor(palette.bg))
    qpal.setColor(QPalette.ColorRole.AlternateBase, QColor(palette.bg_subtle))
    qpal.setColor(QPalette.ColorRole.ToolTipBase, QColor(palette.bg_elevated))
    qpal.setColor(QPalette.ColorRole.ToolTipText, QColor(palette.fg))
    qpal.setColor(QPalette.ColorRole.Text, QColor(palette.fg))
    qpal.setColor(QPalette.ColorRole.Button, QColor(palette.bg_elevated))
    qpal.setColor(QPalette.ColorRole.ButtonText, QColor(palette.fg))
    qpal.setColor(QPalette.ColorRole.Highlight, QColor(palette.accent))
    qpal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    qpal.setColor(QPalette.ColorRole.PlaceholderText, QColor(palette.fg_subtle))
    qpal.setColor(QPalette.ColorRole.Link, QColor(palette.accent))
    qpal.setColor(QPalette.ColorRole.LinkVisited, QColor(palette.accent_hover))
    qpal.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(palette.fg_subtle)
    )
    qpal.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(palette.fg_subtle)
    )
    qapp.setPalette(qpal)

    # Apply the global QSS.
    qapp.setStyleSheet(qss_mod.build(palette))

    from rabbitsync.ui.main_window import MainWindow

    window = MainWindow(db_writer=writer, theme=theme_name)
    window.showMaximized()
    log.info("app.window_shown")  # type: ignore[attr-defined]
    return int(qapp.exec())


def _surface_lock_error(message: str) -> None:
    """Try to show a Qt message box; fall back to stderr if Qt unavailable."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print(message, file=sys.stderr)
        return
    qapp = QApplication.instance() or QApplication(sys.argv)
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("RabbitSync — already running")
    box.setText(message)
    box.exec()
    _ = qapp


def _pid() -> int:
    import os

    return os.getpid()


__all__ = ["run"]

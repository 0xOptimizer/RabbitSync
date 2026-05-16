"""Bottom status bar — ambient state + log dock toggle + sync progress."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QStatusBar, QWidget

from rabbitsync.ui import icons


_PHASE_LABEL = {
    "preflight": "Preflight",
    "diff": "Scanning",
    "snapshot": "Snapshot",
    "apply": "Applying",
    "verify": "Verifying",
    "commit": "Committing",
    "push": "Pushing",
    "done": "Done",
}


class AppStatusBar(QStatusBar):
    """Status bar with a toggle for the log dock and an inline sync progress bar."""

    def __init__(
        self,
        *,
        on_toggle_logs: Callable[[], None],
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        _ = theme

        self._status_label = QLabel("Ready · DB: WAL · lock: held")
        self._status_label.setProperty("role", "muted")
        self.addWidget(self._status_label, 1)

        # Inline progress (hidden until a sync starts).
        self._progress_label = QLabel("")
        self._progress_label.setProperty("role", "muted")
        self._progress_label.hide()
        self.addPermanentWidget(self._progress_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(180)
        self._progress_bar.setMaximumHeight(14)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.hide()
        self.addPermanentWidget(self._progress_bar)

        self._toggle_btn = QPushButton("Logs")
        self._toggle_btn.setIcon(icons.Icons.logs())
        self._toggle_btn.setIconSize(QSize(12, 12))
        self._toggle_btn.setFlat(True)
        self._toggle_btn.clicked.connect(on_toggle_logs)
        self.addPermanentWidget(self._toggle_btn)

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def show_progress(self) -> None:
        """Reveal the progress widgets in an indeterminate state."""
        self._progress_bar.setRange(0, 0)  # busy spinner until first apply tick
        self._progress_bar.setFormat("")
        self._progress_label.setText("Starting…")
        self._progress_bar.show()
        self._progress_label.show()

    def update_progress(
        self, *, phase: str, step_no: int = 0, total: int = 0, rel_path: str | None = None,
    ) -> None:
        label = _PHASE_LABEL.get(phase, phase.capitalize())
        if phase == "apply" and total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(step_no)
            self._progress_bar.setFormat(f"{step_no}/{total}")
            short = _shorten(rel_path) if rel_path else ""
            self._progress_label.setText(f"{label} · {short}" if short else label)
        else:
            # Non-per-file phases — keep the bar busy.
            self._progress_bar.setRange(0, 0)
            self._progress_bar.setFormat("")
            self._progress_label.setText(label)

    def hide_progress(self) -> None:
        self._progress_bar.hide()
        self._progress_label.hide()
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("")
        self._progress_label.clear()


def _shorten(rel_path: str, max_len: int = 48) -> str:
    if len(rel_path) <= max_len:
        return rel_path
    return "…" + rel_path[-(max_len - 1):]


__all__ = ["AppStatusBar"]

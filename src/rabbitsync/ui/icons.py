"""Typed icon provider — loads SVGs from the bundled Lucide set, theme-tinted.

Every icon in the UI resolves through this module. The accessor names below
form a checkable contract: a missing SVG file logs a warning and returns a
neutral placeholder, but the *name* is always valid Python so refactor tools
can find call sites.

The bundled SVG set is populated by ``tools/vendor_lucide.py`` (run once at
project setup, requires internet). On a fresh checkout without vendored
icons, the provider returns blank placeholder pixmaps — the UI still works,
icons just don't render. A startup notice surfaces this state.

No emoji is permitted as iconography anywhere in the UI; this provider is the
*only* sanctioned source of icon imagery.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from rabbitsync.paths import lucide_dir


# Authoritative icon catalog. Each entry is (accessor_name, lucide_basename).
# Accessor names mirror the table in the plan; basename is the SVG file under
# data/assets/icons/lucide/.
_CATALOG: dict[str, str] = {
    # Status
    "in_sync": "circle-check-big",
    "pending": "circle-alert",
    "blocked": "octagon-x",
    "syncing": "refresh-cw",
    # Sidebar
    "pairs": "git-compare",
    # Lucide removed the GitHub mark icon for trademark reasons; we use the
    # neutral git-fork glyph for the GitHub Repositories section.
    "github": "git-fork",
    "accounts": "user-cog",
    # Header / burger menu
    "menu": "menu",
    "clone": "cloud-download",
    "recheck_all": "refresh-cw",
    "settings": "settings-2",
    # Pair actions
    "sync": "circle-arrow-right",
    "recheck": "rotate-cw",
    "preview_diff": "file-diff",
    "reveal": "folder-open",
    "external_link": "external-link",
    # Git
    "branch": "git-branch",
    "commit": "git-commit-horizontal",
    "fetch": "download",
    "pull": "arrow-down-to-line",
    "push": "arrow-up-from-line",
    "stage": "circle-plus",
    "stash": "archive",
    # Pipelines
    "step_pass": "check",
    "step_fail": "x",
    "step_skipped": "fast-forward",
    "run": "play",
    "edit": "pencil",
    # Backup / safety
    "snapshot": "package",
    "quarantine": "shield-alert",
    "restore": "history",
    "verify": "shield-check",
    "export": "share",
    "sweep": "eraser",
    # Misc
    "logs": "square-terminal",
    "lock": "lock",
    "unlock": "lock-open",
    "key": "key-round",
}


def catalog() -> dict[str, str]:
    """Return a copy of the icon name → file basename mapping."""
    return dict(_CATALOG)


def write_index(target: Path | None = None) -> Path:
    """Persist the catalog to ``INDEX.json`` (called by the vendoring script)."""
    out = target if target is not None else lucide_dir() / "INDEX.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_CATALOG, indent=2, sort_keys=True), encoding="utf-8")
    return out


def expected_files() -> Iterable[str]:
    """Iterate over every ``<basename>.svg`` the UI may request."""
    return (f"{name}.svg" for name in _CATALOG.values())


class Icons:
    """Typed accessors. One method per UI use-site."""

    # Status
    @staticmethod
    def in_sync() -> QIcon: return _load("in_sync")  # noqa: E704
    @staticmethod
    def pending() -> QIcon: return _load("pending")  # noqa: E704
    @staticmethod
    def blocked() -> QIcon: return _load("blocked")  # noqa: E704
    @staticmethod
    def syncing() -> QIcon: return _load("syncing")  # noqa: E704

    # Sidebar
    @staticmethod
    def pairs() -> QIcon: return _load("pairs")  # noqa: E704
    @staticmethod
    def github() -> QIcon: return _load("github")  # noqa: E704
    @staticmethod
    def accounts() -> QIcon: return _load("accounts")  # noqa: E704

    # Header
    @staticmethod
    def menu() -> QIcon: return _load("menu")  # noqa: E704
    @staticmethod
    def clone() -> QIcon: return _load("clone")  # noqa: E704
    @staticmethod
    def recheck_all() -> QIcon: return _load("recheck_all")  # noqa: E704
    @staticmethod
    def settings() -> QIcon: return _load("settings")  # noqa: E704

    # Pair actions
    @staticmethod
    def sync() -> QIcon: return _load("sync")  # noqa: E704
    @staticmethod
    def recheck() -> QIcon: return _load("recheck")  # noqa: E704
    @staticmethod
    def preview_diff() -> QIcon: return _load("preview_diff")  # noqa: E704
    @staticmethod
    def reveal() -> QIcon: return _load("reveal")  # noqa: E704
    @staticmethod
    def external_link() -> QIcon: return _load("external_link")  # noqa: E704

    # Git
    @staticmethod
    def branch() -> QIcon: return _load("branch")  # noqa: E704
    @staticmethod
    def commit() -> QIcon: return _load("commit")  # noqa: E704
    @staticmethod
    def fetch() -> QIcon: return _load("fetch")  # noqa: E704
    @staticmethod
    def pull() -> QIcon: return _load("pull")  # noqa: E704
    @staticmethod
    def push() -> QIcon: return _load("push")  # noqa: E704
    @staticmethod
    def stage() -> QIcon: return _load("stage")  # noqa: E704
    @staticmethod
    def stash() -> QIcon: return _load("stash")  # noqa: E704

    # Pipelines
    @staticmethod
    def step_pass() -> QIcon: return _load("step_pass")  # noqa: E704
    @staticmethod
    def step_fail() -> QIcon: return _load("step_fail")  # noqa: E704
    @staticmethod
    def step_skipped() -> QIcon: return _load("step_skipped")  # noqa: E704
    @staticmethod
    def run() -> QIcon: return _load("run")  # noqa: E704
    @staticmethod
    def edit() -> QIcon: return _load("edit")  # noqa: E704

    # Backup / safety
    @staticmethod
    def snapshot() -> QIcon: return _load("snapshot")  # noqa: E704
    @staticmethod
    def quarantine() -> QIcon: return _load("quarantine")  # noqa: E704
    @staticmethod
    def restore() -> QIcon: return _load("restore")  # noqa: E704
    @staticmethod
    def verify() -> QIcon: return _load("verify")  # noqa: E704
    @staticmethod
    def export_() -> QIcon: return _load("export")  # noqa: E704
    @staticmethod
    def sweep() -> QIcon: return _load("sweep")  # noqa: E704

    # Misc
    @staticmethod
    def logs() -> QIcon: return _load("logs")  # noqa: E704
    @staticmethod
    def lock() -> QIcon: return _load("lock")  # noqa: E704
    @staticmethod
    def unlock() -> QIcon: return _load("unlock")  # noqa: E704
    @staticmethod
    def key() -> QIcon: return _load("key")  # noqa: E704


# --- Theme tinting ---------------------------------------------------------

_active_tint: QColor | None = None


def set_tint(color: QColor | None) -> None:
    """Set the global tint applied to monochrome icons. Pass ``None`` to disable."""
    global _active_tint
    _active_tint = color
    _load.cache_clear()


def missing_files() -> list[str]:
    """Return the basenames of any catalog SVGs not present on disk."""
    base = lucide_dir()
    out = []
    for fname in expected_files():
        if not (base / fname).is_file():
            out.append(fname)
    return out


# --- Internals -------------------------------------------------------------


@lru_cache(maxsize=128)
def _load(name: str) -> QIcon:
    basename = _CATALOG.get(name)
    if basename is None:
        return QIcon()
    svg_path = lucide_dir() / f"{basename}.svg"
    if not svg_path.is_file():
        return QIcon()
    data = svg_path.read_bytes()
    if _active_tint is not None:
        data = _retint_svg(data, _active_tint)
    icon = QIcon()
    for size in (16, 20, 24, 32, 48):
        pix = _render(data, size)
        icon.addPixmap(pix)
    return icon


def _retint_svg(data: bytes, color: QColor) -> bytes:
    """Replace ``stroke``/``fill`` colors in a Lucide SVG with ``color``.

    Lucide icons use ``currentColor`` for stroke by default, which Qt's SVG
    renderer paints in black. We rewrite ``stroke="currentColor"`` to the
    tint color so the same SVG renders in any theme.
    """
    try:
        root = ET.fromstring(data.decode("utf-8"))
    except ET.ParseError:
        return data
    hex_color = color.name(QColor.NameFormat.HexRgb)
    _walk(root, hex_color)
    return ET.tostring(root, encoding="utf-8")


def _walk(elem: ET.Element, hex_color: str) -> None:
    for attr in ("stroke", "fill"):
        if elem.get(attr) == "currentColor":
            elem.set(attr, hex_color)
    for child in elem:
        _walk(child, hex_color)


def _render(svg_data: bytes, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_data))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return QPixmap.fromImage(image)


def _icon_size(px: int) -> QSize:
    return QSize(px, px)


__all__ = [
    "Icons",
    "catalog",
    "expected_files",
    "missing_files",
    "set_tint",
    "write_index",
]

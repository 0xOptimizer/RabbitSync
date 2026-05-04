"""Centralized animation primitives, durations, and the reduced-motion gate.

Every UI animation in RabbitSync goes through this module so durations,
easings, and the reduced-motion preference are tunable from one place.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


class Durations:
    """Animation lengths in milliseconds."""

    MICRO = 90
    SHORT = 150
    MEDIUM = 220
    LONG = 320


@dataclass(frozen=True)
class _EasingNames:
    """Names of Qt easing curves used by the app.

    Stored as strings here so this module doesn't import PySide at import time
    (callers that build animations resolve them via ``QEasingCurve.Type``).
    """

    out_cubic: str = "OutCubic"
    in_cubic: str = "InCubic"
    in_out_quart: str = "InOutQuart"
    out_back: str = "OutBack"
    linear: str = "Linear"


Easings = _EasingNames()


# --- Reduced-motion gate ---------------------------------------------------

_user_disabled = False
_system_disabled_cache: bool | None = None


def set_user_preference(disabled: bool) -> None:
    """Settings → Appearance → Reduce motion is wired here."""
    global _user_disabled
    _user_disabled = disabled


def is_enabled() -> bool:
    """True when animations should play; False to snap to end state."""
    if _user_disabled:
        return False
    if _system_reduce_motion():
        return False
    return True


def _system_reduce_motion() -> bool:
    """Read the OS-level reduced-motion preference. Cached for the process."""
    global _system_disabled_cache
    if _system_disabled_cache is not None:
        return _system_disabled_cache
    _system_disabled_cache = _query_system_reduce_motion()
    return _system_disabled_cache


def _query_system_reduce_motion() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        SPI_GETCLIENTAREAANIMATION = 0x1042
        result = wintypes.BOOL()
        ok = ctypes.windll.user32.SystemParametersInfoW(  # type: ignore[attr-defined]
            SPI_GETCLIENTAREAANIMATION,
            0,
            ctypes.byref(result),
            0,
        )
        if not ok:
            return False
        # When SPI_GETCLIENTAREAANIMATION is FALSE, the user wants reduced motion.
        return not bool(result.value)
    except Exception:  # noqa: BLE001 -- never let a UI helper crash the app
        return False


__all__ = ["Durations", "Easings", "is_enabled", "set_user_preference"]

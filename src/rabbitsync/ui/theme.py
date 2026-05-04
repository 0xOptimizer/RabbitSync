"""Centralized theme: palette, spacing scale, typography.

All UI sizing constants live here. Magic numbers in widgets are a lint error
(see Quality Bar in the plan) — pull values from this module.
"""

from __future__ import annotations

from dataclasses import dataclass


# Spacing scale (logical px). Tight, native-Windows-desktop-app proportions.
class Spacing:
    XS = 4
    SM = 6
    MD = 8
    LG = 12
    XL = 16


# Typography. Sized to match native Windows apps.
class Typography:
    UI_FAMILY = "Segoe UI Variable, Segoe UI, sans-serif"
    MONO_FAMILY = "Cascadia Code, Consolas, monospace"
    BASE_PT = 9
    HEADER_PT = 10
    HEADER_LG_PT = 12
    MONO_PT = 9


# Window sizing.
class Window:
    MIN_W = 1024
    MIN_H = 640
    DEFAULT_W = 1440
    DEFAULT_H = 900


# Border radii.
class Radius:
    SM = 3
    MD = 4
    LG = 6


@dataclass(frozen=True)
class Palette:
    bg: str
    bg_subtle: str
    bg_elevated: str
    bg_hover: str
    bg_active: str
    fg: str
    fg_muted: str
    fg_subtle: str
    accent: str
    accent_hover: str
    accent_subtle: str
    success: str
    warning: str
    danger: str
    border: str
    border_subtle: str
    border_strong: str
    selection: str


# GitHub-inspired dark palette — calm, high-contrast, never saturated.
DARK = Palette(
    bg="#0D1117",
    bg_subtle="#161B22",
    bg_elevated="#1C2128",
    bg_hover="#1F242C",
    bg_active="#262C36",
    fg="#E6EDF3",
    fg_muted="#9198A1",
    fg_subtle="#6E7681",
    accent="#2F81F7",
    accent_hover="#4493F8",
    accent_subtle="#1F3A6B",
    success="#3FB950",
    warning="#D29922",
    danger="#F85149",
    border="#30363D",
    border_subtle="#21262D",
    border_strong="#484F58",
    selection="#1F3A6B",
)

# GitHub-inspired light palette.
LIGHT = Palette(
    bg="#FFFFFF",
    bg_subtle="#F6F8FA",
    bg_elevated="#FFFFFF",
    bg_hover="#F3F4F6",
    bg_active="#EAEEF2",
    fg="#1F2328",
    fg_muted="#656D76",
    fg_subtle="#8C959F",
    accent="#0969DA",
    accent_hover="#218BFF",
    accent_subtle="#DDEEFF",
    success="#1A7F37",
    warning="#9A6700",
    danger="#D1242F",
    border="#D0D7DE",
    border_subtle="#D8DEE4",
    border_strong="#AFB8C1",
    selection="#DDEEFF",
)


def palette_for(theme: str) -> Palette:
    """Return the palette for ``"light"`` or ``"dark"``."""
    if theme == "dark":
        return DARK
    return LIGHT


__all__ = [
    "DARK",
    "LIGHT",
    "Palette",
    "Radius",
    "Spacing",
    "Typography",
    "Window",
    "palette_for",
]

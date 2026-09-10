"""Fonts media: loads the Star4000 font set into ``ctx.fonts``.

Looked up from ``<asset_dir>/fonts``; when the directory or files are absent it
falls back to named system monospace fonts, then to pygame's default font.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pygame

from weatherstar.logging_setup import get_logger
from weatherstar.media.base import FontSet
from weatherstar.registry import plugin

log = get_logger("weatherstar.fonts")

#: name -> (relative font file, size)
_FONT_SPECS = {
    "title": ("star4000.ttf", 32),
    "large": ("star4000_large.ttf", 32),
    "extended": ("star4000_extended.ttf", 32),
    "small": ("star4000_small.ttf", 28),
    "normal": ("star4000.ttf", 20),
    "forecast": ("star4000_small.ttf", 24),
    "tiny": ("star4000.ttf", 16),
    "scroller": ("star4000_extended.ttf", 24),
}

_FALLBACK_FONTS = ["consolas", "courier new", "courier", "monospace", "dejavu sans mono"]


def _fallback_font_path(bold: bool = False) -> str | None:
    for name in _FALLBACK_FONTS:
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return path
    return None


@plugin
class Fonts(FontSet):
    name = "fonts"
    #: Subdirectory of ``asset_dir`` scanned for the font files (drives whether
    #: a theme supplies its own typeface).
    asset_subdirs = ("fonts",)

    def _resolved_specs(self, ctx: Any, fonts_dir: Path) -> dict[str, tuple[str, int]]:
        """Font slots, with the active theme's ``[fonts]`` mapping applied.

        A theme can point the named slots at its own typeface files (e.g. a
        ``ws3000.ttf`` set). A mapping is only adopted when that file actually
        exists in ``fonts_dir``; otherwise the slot keeps the classic filename,
        so a theme whose font files are absent degrades to the classic set
        instead of losing fonts entirely.
        """
        specs = dict(_FONT_SPECS)
        theme = getattr(ctx, "theme", None)
        overrides = getattr(theme, "fonts", None) or {}
        for key, value in overrides.items():
            if not (isinstance(value, (list, tuple)) and len(value) == 2):
                continue
            file_name, size = str(value[0]), int(value[1])
            if (fonts_dir / file_name).exists():
                specs[key] = (file_name, size)
        return specs

    def load(self, ctx: Any) -> Any:
        fonts_dir = Path(self.asset_dir) / "fonts"
        specs = self._resolved_specs(ctx, fonts_dir)
        loaded: dict[str, pygame.font.Font] = {}
        for key, (file_name, size) in specs.items():
            font = self._load_one(fonts_dir, file_name, size)
            if font is not None:
                loaded[key] = font
        if not loaded:
            log.warning("no_star4000_fonts; falling back to system/default")
            for key, (_file_name, size) in specs.items():
                loaded[key] = self._make_system_font(key, size)
        self.provide_fonts(ctx, loaded)
        return loaded

    @staticmethod
    def _load_one(fonts_dir: Path, file_name: str, size: int) -> pygame.font.Font | None:
        path = fonts_dir / file_name
        if path.exists():
            try:
                return pygame.font.Font(str(path), size)
            except pygame.error:  # pragma: no cover - corrupt font file
                log.warning("font_load_failed", path=str(path))
        return None

    @staticmethod
    def _make_system_font(key: str, size: int) -> pygame.font.Font:
        bold = key in {"title", "large", "extended", "scroller"}
        path = _fallback_font_path(bold=bold)
        if path:
            return pygame.font.Font(path, size)
        return pygame.font.Font(None, size)  # pragma: no cover - last resort

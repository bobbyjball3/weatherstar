"""Shared drawing helpers used by Screens/Components.

These reproduce the classic Weather Star header/background look so ported screens
stay visually faithful while reading everything from the AppContext instead of a
god object.
"""

from __future__ import annotations

from datetime import datetime

import pygame

from weatherstar.context import AppContext
from weatherstar.renderer import Renderer, blit_text_shadowed

#: Stateless renderer for the module-level helpers below (they predate the
#: Renderer mixin and are used by non-Screen callers such as the engine).
_RENDERER = Renderer()


def draw_background(surface: pygame.Surface, ctx: AppContext, name: str = "1") -> None:
    """Blit a named background, falling back to the first available."""
    backgrounds = ctx.assets.get("backgrounds")
    if not backgrounds:
        surface.fill(ctx.colors["blue"])
        return
    image = backgrounds.get(name)
    if image is None:
        first = next(iter(backgrounds.values()), None)
        image = first
    if image is not None:
        surface.blit(image, (0, 0))


def draw_header(
    surface: pygame.Surface,
    ctx: AppContext,
    title_top: str,
    title_bottom: str | None = None,
    has_noaa: bool = False,
    include_clock: bool = True,
) -> None:
    """Draw the screen header: logo, title, NOAA mark, clock/date.

    The layout is theme-driven through per-screen tokens (see ``Theme.layout``):

    - ``title_style``: ``"dual"`` (two lines), ``"tall"`` (one centered line in
      the title face, the classic 3000 look), ``"single"`` (one line), or
      ``"hidden"`` (draw nothing - screens with no 3000 header).
    - ``title_align``: ``"left"`` or ``"center"``.
    - ``title_font`` / ``title_color``: the font slot and color key for the
      title text.
    - ``show_logo`` / ``show_noaa``: whether the corner logo and NOAA mark draw.

    When no ``title_style`` token is present the classic Weather Star 4000 header
    (corner logo, yellow two-line title, optional NOAA mark) is reproduced.
    ``include_clock`` lets compositors draw the top-right clock/date separately
    (e.g. via the ``clock`` component) instead of inside the header band.
    """
    tokens = ctx.layout_for(ctx.active_screen)
    style = tokens.get("title_style")
    logos = ctx.assets.get("logos") or {}
    colors = ctx.colors
    fonts = ctx.fonts

    if style == "hidden":
        return

    align = tokens.get("title_align", "left")
    font_name = tokens.get("title_font", "title")
    color_key = tokens.get("title_color", "yellow")
    show_logo = tokens.get("show_logo", True)
    show_noaa = tokens.get("show_noaa", has_noaa)
    # A screen's layout may override the header text itself (e.g. the 3000 uses
    # "The Weatherstar Almanac" where the classic screen says "Weather Almanac").
    title_top = str(tokens.get("title_text") or title_top)
    if tokens.get("title_sub") is not None:
        title_bottom = str(tokens["title_sub"])

    title_font = fonts.get(font_name) or fonts.get("title") or fonts.get("large")

    def blit_line(text: str, dest) -> None:
        blit_text_shadowed(surface, ctx, title_font, text, colors[color_key], dest)

    if style is None:
        # Legacy Weather Star 4000 header, unchanged when the theme specifies
        # no per-screen title_style token.
        if show_logo and "logo-corner" in logos:
            surface.blit(logos["logo-corner"], (50, 25))
        if title_bottom:
            blit_line(title_top.upper(), (170, 27))
            blit_line(title_bottom.upper(), (170, 53))
        else:
            blit_line(title_top.upper(), (170, 40))
        if show_noaa and "noaa" in logos:
            surface.blit(logos["noaa"], (356, 39))
    else:
        if show_logo and "logo-corner" in logos:
            surface.blit(logos["logo-corner"], (50, 25))
        top = title_top.upper()
        if style == "tall":
            text = f"{top} {title_bottom.upper()}".strip() if title_bottom else top
            if align == "center":
                blit_line(text, text_center_rect(surface, title_font, text, 60))
            else:
                blit_line(text, (35, 40))
        elif style == "single":
            text = f"{top} {title_bottom.upper()}".strip() if title_bottom else top
            if align == "center":
                blit_line(text, text_center_rect(surface, title_font, text, 60))
            else:
                blit_line(text, (35, 40))
        else:  # dual
            line1 = top
            line2 = (title_bottom or getattr(ctx.theme, "title_bottom", "") or "").upper()
            if align == "center":
                blit_line(line1, text_center_rect(surface, title_font, line1, 32))
                if line2:
                    blit_line(line2, text_center_rect(surface, title_font, line2, 60))
            else:
                blit_line(line1, (170, 27))
                if line2:
                    blit_line(line2, (170, 53))
        if show_noaa and "noaa" in logos:
            surface.blit(logos["noaa"], (356, 39))

    if not include_clock:
        return

    small = fonts.get("small", title_font)
    time_str = datetime.now().strftime("%I:%M %p").lstrip("0")
    time_rect = text_center_rect(surface, small, time_str, 34, right=True)
    blit_text_shadowed(surface, ctx, small, time_str, colors["white"], time_rect)

    date_str = datetime.now().strftime("%a %b %d").upper()
    date_rect = text_center_rect(surface, small, date_str, 54, right=True)
    blit_text_shadowed(surface, ctx, small, date_str, colors["white"], date_rect)


def text_center_rect(
    surface: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    y: int,
    *,
    right: bool = False,
) -> pygame.Rect:
    """Rect for text drawn centered (or right-aligned) at height ``y``."""
    glyph = font.render(text, True, (255, 255, 255))
    if right:
        return glyph.get_rect(right=surface.get_width() - 50, y=y)
    return glyph.get_rect(center=(surface.get_width() // 2, y))


def draw_centered_text(
    surface: pygame.Surface,
    ctx: AppContext,
    text: str,
    y: int,
    font_name: str = "small",
    color_key: str = "white",
    center_x: int | None = None,
) -> pygame.Rect:
    return _RENDERER.centered(
        surface, ctx, text, y, font_name=font_name, color_key=color_key, center_x=center_x
    )


def draw_text(
    surface: pygame.Surface,
    ctx: AppContext,
    text: str,
    pos: tuple[int, int],
    font_name: str = "small",
    color_key: str = "white",
) -> pygame.Rect:
    return _RENDERER.draw_text(surface, ctx, text, pos, font_name=font_name, color_key=color_key)

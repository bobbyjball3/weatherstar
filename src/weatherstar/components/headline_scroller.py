"""HeadlineScroller component: vertical scrolling headline ticker.

Owns the classic Weather Star vertical-ticker mechanics shared by the news
screens: a clip region, word-wrap, time-based upward scroll with wrap-around
reset, and the "Updated" footer.  Content is either fetched from a configured
datasource (``datasource_name``) each render or pushed by the owning screen via
:meth:`set_headlines`.  Headlines are color-coded by category: each headline is
split on ``:`` and the prefix is colored by its keywords (red/yellow terms,
else cyan).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

import pygame
from pydantic import Field, PrivateAttr

from weatherstar.components.base import Component
from weatherstar.datasources.news import Headline
from weatherstar.registry import plugin

if TYPE_CHECKING:
    from weatherstar.context import AppContext

#: Geometry of the scrolling headline area (mirrors the legacy news screens).
_CLIP_RECT = pygame.Rect(55, 100, 530, 298)
_LINE_HEIGHT = 28
_HEADLINE_SPACING = 15
_WRAP_WIDTH = 470
_SCROLL_SPEED = 20.0
#: The list is anchored to the top of its clip band: the first headline starts
#: at the top edge and rolls upward, looping back to the top when it is done.
_START_SCROLL = 100.0
_NUMBER_X = 65
_TEXT_X = 95
_RESET_TOP = 100.0
_RESET_SCROLL = 100.0
_FOOTER_Y = 440
#: Vertical band in which a headline is worth drawing.
_HEADLINE_VISIBLE = (-200, 500)
_LINE_VISIBLE = (95, 398)


@plugin
class HeadlineScroller(Component):
    """Vertically scrolling headline list (news ticker)."""

    name = "headlines"

    numbered: bool = Field(
        default=True, description="Prefix each headline with a yellow number (1., 2., ...)."
    )
    accent: Literal["category"] = Field(
        default="category",
        description="Headline accent style: split categories on ':' and color the prefix.",
    )
    red_terms: tuple[str, ...] = Field(
        default=("BREAKING", "EMERGENCY", "ALERT"),
        description="Category keywords drawn in red (category accent only).",
    )
    yellow_terms: tuple[str, ...] = Field(
        default=("UPDATE",), description="Category keywords drawn in yellow (category accent only)."
    )
    datasource_name: str | None = Field(
        default=None,
        description="Optional datasource whose headlines() supplies content each render.",
    )
    empty_text: str = Field(
        default="No headlines are available right now",
        description="Centered message shown when there is no content.",
    )

    _content: list[Any] | None = PrivateAttr(default=None)
    _scroll: float = PrivateAttr(default=_START_SCROLL)

    def set_headlines(self, headlines: list[Any]) -> None:
        """Push static content (used by screens without a datasource)."""
        self._content = list(headlines or [])

    @staticmethod
    def _headline_text(headline: Any) -> str:
        """Extract the display text from a Headline model, tuple or string."""
        if isinstance(headline, Headline):
            return headline.title
        if isinstance(headline, (tuple, list)):
            return headline[0] if headline else ""
        return str(headline)

    def step(self, ctx: AppContext, dt: float) -> None:
        if self._content is None and not self.datasource_name:
            return
        content = self._items(ctx)
        if content:
            self._scroll -= (dt or 0.0) * _SCROLL_SPEED

    def render(self, surface: pygame.Surface, ctx: AppContext) -> None:
        content = self._items(ctx)
        if not content:
            self.centered(surface, ctx, self.empty_text, 240, font_name="normal")
            return

        news_font = self.font(ctx, "small")
        num_font = self.font(ctx, "normal")
        yellow = self.color(ctx, "yellow")

        surface.set_clip(_CLIP_RECT)
        y_pos = self._scroll
        for i, headline in enumerate(content, 1):
            text = self._headline_text(headline)
            lines = self.wrap(news_font, text, _WRAP_WIDTH)

            if _HEADLINE_VISIBLE[0] < y_pos < _HEADLINE_VISIBLE[1]:
                if self.numbered:
                    number = num_font.render(f"{i}.", True, yellow)
                    # Align the number's baseline with the first text line's
                    # baseline so small numbers sit level with taller headlines.
                    baseline = y_pos + news_font.get_ascent()
                    surface.blit(number, (_NUMBER_X, baseline - num_font.get_ascent()))

                line_y = y_pos
                for line in lines:
                    if _LINE_VISIBLE[0] < line_y < _LINE_VISIBLE[1]:
                        self._draw_line(surface, ctx, news_font, line, _TEXT_X, line_y)
                    line_y += _LINE_HEIGHT
                y_pos = line_y + _HEADLINE_SPACING
            else:
                y_pos += _LINE_HEIGHT * 2 + _HEADLINE_SPACING
        surface.set_clip(None)

        if y_pos < _RESET_TOP:
            self._scroll = _RESET_SCROLL

        if self.layout_token(ctx, "show_headline_footer", True):
            footer = news_font.render(
                f"Updated: {datetime.now().strftime('%I:%M %p')}", True, yellow
            )
            surface.blit(footer, footer.get_rect(center=(320, _FOOTER_Y)))

    # -- internals --------------------------------------------------------

    def _items(self, ctx: AppContext) -> list[Any]:
        if self._content is not None:
            return self._content
        if not self.datasource_name:
            return []
        ds = self.datasource(ctx, self.datasource_name)
        if ds is None or not callable(getattr(ds, "headlines", None)):
            return []
        lat, lon = self.latlon(ctx)
        try:
            return list(ds.headlines(lat, lon) or [])
        except Exception:  # noqa: BLE001 - datasource content is optional
            return []

    def _draw_line(
        self,
        surface: pygame.Surface,
        ctx: AppContext,
        font: pygame.font.Font,
        line: str,
        x: int,
        y: int,
    ) -> None:
        white = self.color(ctx, "white")
        if ":" not in line:
            surface.blit(font.render(line, True, white), (x, y))
            return

        category, rest = line.split(":", 1)
        upper = category.upper()
        if any(term in upper for term in self.red_terms):
            color = self.color(ctx, "red", (255, 0, 0))
        elif any(term in upper for term in self.yellow_terms):
            color = self.color(ctx, "yellow")
        else:
            color = self.color(ctx, "cyan", (0, 255, 255))
        category_text = font.render(f"{category}:", True, color)
        rest_text = font.render(rest, True, white)
        surface.blit(category_text, (x, y))
        surface.blit(rest_text, (x + category_text.get_width(), y))

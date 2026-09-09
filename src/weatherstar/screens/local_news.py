"""Local News screen: city header plus live local headlines.

Headlines come from the ``local_news`` datasource (webz.io when configured; the
screen shows its empty-state message when the feed is unconfigured or empty).
The ``headlines`` component scrolls them and shows a friendly placeholder when
the feed is empty.
"""

from __future__ import annotations

from typing import Any

import pygame

from weatherstar.components.base import ComponentSpec
from weatherstar.registry import plugin
from weatherstar.screens.base import Screen
from weatherstar.themes import LayoutVariant


@plugin
class LocalNewsScreen(Screen):
    name = "local_news"
    media = ("backgrounds", "logos")
    datasources = ("local_news", "weather")
    variants = {
        LayoutVariant.WS4000: "compose_4000",
    }

    layout = (
        ComponentSpec(component="background", config={"background_name": "1"}),
        ComponentSpec(component="header", config={"title_top": "Local News", "title_bottom": ""}),
        ComponentSpec(component="clock"),
        ComponentSpec(
            component="headlines",
            config={
                "numbered": True,
                "accent": "category",
                "red_terms": ("BREAKING", "EMERGENCY", "ALERT"),
                "yellow_terms": (),
                "datasource_name": "local_news",
                "empty_text": "No local headlines are available right now",
            },
        ),
    )

    def compose_4000(self, surface: pygame.Surface, ctx: Any, dt: float) -> None:
        y = self._city_y(ctx)
        city_text = self.text_surface(ctx, self._resolve_city(ctx).upper(), color_key="yellow")
        surface.blit(city_text, city_text.get_rect(centerx=320, y=y))

    @staticmethod
    def _city_y(ctx: Any) -> int:
        """Sit the city line below a centered header title (3000 style).

        The classic header is left-aligned (lines end around x=270), so the
        centered city at y=65 is clear of it; a centered ``tall`` 3000 title
        spans the full width down to ~y=80, so the city drops below it.
        """
        tokens = ctx.layout_for(ctx.active_screen)
        style = tokens.get("title_style", "dual")
        align = tokens.get("title_align", "left")
        if style in ("tall", "single") and align == "center":
            # Centered title spans the width down to ~y=75; the headline
            # scroller clip starts at y=100, so the city lives in the gap.
            return 80
        return 65

    def _resolve_city(self, ctx: Any) -> str:
        lat, lon = self.latlon(ctx)
        news = self.datasource(ctx, "local_news")
        try:
            name = news.city_name(lat, lon)
            if name:
                return str(name)
        except Exception:  # noqa: BLE001 - fall through to weather/location
            pass
        weather = self.datasource(ctx, "weather")
        try:
            city = weather.get_city(lat, lon)
            if city.city:
                return str(city.city)
        except Exception:  # noqa: BLE001 - fall through to location
            pass
        location = getattr(ctx, "location", None)
        if location is not None and getattr(location, "description", ""):
            return str(location.description)
        return "Local Area"

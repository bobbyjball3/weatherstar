"""Sun & Moon screen (port of legacy ``draw_sun_moon``).

Two-column table of (simplified, locally computed) sun and moon data in the
classic small/tiny Weather Star fonts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pygame

from weatherstar.components.base import ComponentSpec
from weatherstar.registry import plugin
from weatherstar.screens.base import Screen
from weatherstar.themes import LayoutVariant

_WHITE = (255, 255, 255)
_YELLOW = (255, 255, 0)


@plugin
class SunMoonScreen(Screen):
    name = "sun_moon"
    media = ("backgrounds",)
    datasources = ()

    variants = {
        LayoutVariant.WS4000: "compose_4000",
    }

    layout = (
        ComponentSpec(component="background", config={"background_name": "1"}),
        ComponentSpec(
            component="header",
            config={"title_top": "Sun & Moon", "title_bottom": "Data", "has_noaa": False},
        ),
        ComponentSpec(component="clock"),
    )

    def compose_4000(self, surface: pygame.Surface, ctx: Any, dt: float) -> None:
        colors = ctx.colors
        yellow = colors.get("yellow", _YELLOW)
        white = colors.get("white", _WHITE)

        left_col_x = 60
        right_col_x = 335
        y_pos = 120

        self.draw_text(surface, ctx, "SUN", (left_col_x, y_pos), font_name="normal", color=yellow)
        sun_y = y_pos + 30

        now = datetime.now()
        sunrise = now.replace(hour=6, minute=45, second=0)
        sunset = now.replace(hour=19, minute=30, second=0)
        day_length = sunset - sunrise
        hours = int(day_length.total_seconds() // 3600)
        minutes = int((day_length.total_seconds() % 3600) // 60)

        sun_data = [
            ("Sunrise", sunrise.strftime("%I:%M %p")),
            ("Sunset", sunset.strftime("%I:%M %p")),
            ("Day Length", f"{hours}h {minutes}m"),
            ("Solar Noon", "1:07 PM"),
            ("Civil Dawn", "6:20 AM"),
            ("Civil Dusk", "8:00 PM"),
            ("UV Index", "6 (High)"),
        ]

        for label, value in sun_data:
            self._draw_row(surface, ctx, label, value, left_col_x, sun_y, white, yellow, 110)
            sun_y += 24

        self.draw_text(surface, ctx, "MOON", (right_col_x, y_pos), font_name="normal", color=yellow)
        moon_y = y_pos + 30

        moon_age = now.day % 30
        if moon_age < 7:
            phase = "Waxing Crescent"
            illumination = moon_age * 14
        elif moon_age < 14:
            phase = "Waxing Gibbous"
            illumination = 50 + (moon_age - 7) * 7
        elif moon_age == 14:
            phase = "Full Moon"
            illumination = 100
        elif moon_age < 21:
            phase = "Waning Gibbous"
            illumination = 100 - (moon_age - 14) * 7
        else:
            phase = "Waning Crescent"
            illumination = 50 - (moon_age - 21) * 7

        moon_data = [
            ("Phase", phase),
            ("Illumination", f"{illumination}%"),
            ("Moonrise", "3:45 PM"),
            ("Moonset", "2:30 AM"),
            ("Next Full", "In 3 days"),
            ("Next New", "In 18 days"),
            ("Age", f"{moon_age} days"),
        ]

        for label, value in moon_data:
            self._draw_row(surface, ctx, label, value, right_col_x, moon_y, white, yellow, 100)
            moon_y += 24

    def _draw_row(
        self,
        surface: pygame.Surface,
        ctx: Any,
        label: str,
        value: str,
        col_x: int,
        y: int,
        white,
        yellow,
        min_value_x: int,
    ) -> None:
        font = self.font(ctx, "tiny")
        if font is None:
            return
        label_surf = font.render(f"{label}:", True, white)
        surface.blit(label_surf, (col_x + 10, y))
        label_width = font.size(f"{label}:")[0]
        value_x = col_x + 15 + max(min_value_x, label_width + 10)
        value_surf = font.render(value, True, yellow)
        surface.blit(value_surf, (value_x, y))

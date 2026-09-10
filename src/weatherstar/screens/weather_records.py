"""Weather Records screen (port of legacy ``draw_weather_records``).

Hardcoded record table for "this day" plus a "This Day in Weather History"
note, reproduced verbatim from the legacy simulator.
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
class WeatherRecordsScreen(Screen):
    name = "weather_records"
    media = ("backgrounds",)
    datasources = ()

    variants = {
        LayoutVariant.WS4000: "compose_4000",
    }

    layout = (
        ComponentSpec(component="background", config={"background_name": "5"}),
        ComponentSpec(
            component="header",
            config={"title_top": "Weather", "title_bottom": "Records", "has_noaa": False},
        ),
        ComponentSpec(component="clock"),
    )

    def compose_4000(self, surface: pygame.Surface, ctx: Any, dt: float) -> None:
        colors = ctx.colors
        yellow = colors.get("yellow", _YELLOW)
        white = colors.get("white", _WHITE)

        now = datetime.now()
        date_str = now.strftime("%B %d")
        y_pos = int(self.layout_token(ctx, "content_top", 120))

        font_normal = self.font(ctx, "normal")
        if font_normal is not None:
            title = font_normal.render(f"Records for {date_str}", True, yellow)
            surface.blit(title, title.get_rect(center=(320, y_pos)))
        row_step = int(self.layout_token(ctx, "row_step", 28))
        y_pos += 40

        records = [
            ("Record High", "92\u00b0F (1998)"),
            ("Record Low", "41\u00b0F (1965)"),
            ("Average High", "75\u00b0F"),
            ("Average Low", "58\u00b0F"),
            ("Record Rainfall", '3.21" (1977)'),
            ("Record Snowfall", '0.0" (Never)'),
        ]

        for label, value in records:
            self.draw_text(surface, ctx, f"{label}:", (120, y_pos), font_name="normal", color=white)
            self.draw_text(surface, ctx, value, (350, y_pos), font_name="normal", color=yellow)
            y_pos += row_step

        section_gap = int(self.layout_token(ctx, "section_gap", 12))
        heading_gap = int(self.layout_token(ctx, "heading_gap", 30))
        y_pos += section_gap
        self.draw_text(
            surface,
            ctx,
            "THIS DAY IN WEATHER HISTORY",
            (60, y_pos),
            font_name="extended",
            color=yellow,
        )
        y_pos += heading_gap

        history_text = "1992: Hurricane Andrew made landfall in Florida"
        self.draw_text(surface, ctx, history_text, (80, y_pos), font_name="small", color=white)

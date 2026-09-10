"""30-Day Monthly Outlook screen (port of legacy ``draw_monthly_outlook``).

Hardcoded temperature/precipitation outlook narrative reproduced verbatim from
the legacy simulator.
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
class MonthlyOutlookScreen(Screen):
    name = "monthly_outlook"
    media = ("backgrounds",)
    datasources = ()

    variants = {
        LayoutVariant.WS4000: "compose_4000",
    }

    layout = (
        ComponentSpec(component="background", config={"background_name": "4"}),
        ComponentSpec(
            component="header",
            config={"title_top": "30-Day", "title_bottom": "Outlook", "has_noaa": False},
        ),
        ComponentSpec(component="clock"),
    )

    def compose_4000(self, surface: pygame.Surface, ctx: Any, dt: float) -> None:
        colors = ctx.colors
        yellow = colors.get("yellow", _YELLOW)
        white = colors.get("white", _WHITE)

        now = datetime.now()
        month = now.strftime("%B %Y")
        y_pos = 120

        font_normal = self.font(ctx, "normal")
        if font_normal is not None:
            title = font_normal.render(f"Outlook for {month}", True, yellow)
            surface.blit(title, title.get_rect(center=(320, y_pos)))
        y_pos += 35

        self.draw_text(
            surface, ctx, "TEMPERATURE OUTLOOK", (60, y_pos), font_name="extended", color=yellow
        )
        y_pos += 35

        self.draw_text(
            surface,
            ctx,
            "Above Normal Temperatures Expected",
            (80, y_pos),
            font_name="normal",
            color=white,
        )
        y_pos += 30

        self.draw_text(
            surface,
            ctx,
            "Probability: 60% above normal",
            (100, y_pos),
            font_name="small",
            color=white,
        )
        y_pos += 40

        self.draw_text(
            surface, ctx, "PRECIPITATION OUTLOOK", (60, y_pos), font_name="extended", color=yellow
        )
        y_pos += 35

        self.draw_text(
            surface,
            ctx,
            "Near Normal Precipitation Expected",
            (80, y_pos),
            font_name="normal",
            color=white,
        )
        y_pos += 30

        self.draw_text(
            surface, ctx, "Probability: Equal chances", (100, y_pos), font_name="small", color=white
        )
        y_pos += 40

        font_small = self.font(ctx, "small")
        if font_small is not None:
            source = font_small.render("Source: NOAA Climate Prediction Center", True, white)
            surface.blit(source, source.get_rect(center=(320, 380)))

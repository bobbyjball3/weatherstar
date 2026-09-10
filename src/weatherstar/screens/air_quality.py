"""Air Quality & Health screen (port of legacy ``draw_air_quality``).

Content is static in the legacy simulator: a fixed AQI value (45 / GOOD), a
small AQI scale reference, color-coded pollen bars, and health recommendations
with a small vertical scroll animation.
"""

from __future__ import annotations

from typing import Any

import pygame
from pydantic import PrivateAttr

from weatherstar.components.base import ComponentSpec
from weatherstar.registry import plugin
from weatherstar.screens.base import Screen
from weatherstar.themes import LayoutVariant

_GREEN = (0, 255, 0)
_SOFT_GREEN = (100, 255, 100)
_ORANGE = (255, 165, 0)
_SOFT_RED = (255, 100, 100)
_YELLOW = (255, 255, 0)
_WHITE = (255, 255, 255)

_MAX_TIP_WIDTH = 500


@plugin
class AirQualityScreen(Screen):
    name = "air_quality"
    media = ("backgrounds",)
    datasources = ()
    _scroll_offset: float = PrivateAttr(default=0.0)
    _scroll_dir: float = PrivateAttr(default=1.0)

    variants = {
        LayoutVariant.WS4000: "compose_4000",
    }

    layout = (
        ComponentSpec(component="background", config={"background_name": "5"}),
        ComponentSpec(
            component="header",
            config={"title_top": "Air Quality", "title_bottom": "& Health", "has_noaa": False},
        ),
        ComponentSpec(component="clock"),
    )

    def compose_4000(self, surface: pygame.Surface, ctx: Any, dt: float) -> None:
        colors = ctx.colors
        yellow = colors.get("yellow", _YELLOW)
        white = colors.get("white", _WHITE)

        left_x = 80
        right_x = 350
        y_pos = 120

        self.draw_text(
            surface, ctx, "AIR QUALITY INDEX", (left_x, y_pos), font_name="normal", color=yellow
        )
        y_pos += 30

        aqi_value = 45
        aqi_text = "GOOD"

        pygame.draw.rect(surface, _GREEN, (left_x, y_pos, 60, 40), 2)
        font_normal = self.font(ctx, "normal")
        if font_normal is not None:
            num = font_normal.render(str(aqi_value), True, _GREEN)
            surface.blit(num, num.get_rect(center=(left_x + 30, y_pos + 20)))
        font_small = self.font(ctx, "small")
        if font_small is not None:
            desc = font_small.render(aqi_text, True, _GREEN)
            surface.blit(desc, (left_x + 70, y_pos + 12))
        y_pos += 50

        scale = [
            ("0-50", "Good", _GREEN),
            ("51-100", "Moderate", yellow),
            ("101-150", "Sensitive Groups", _ORANGE),
        ]
        for range_txt, desc, color in scale:
            self.draw_text(
                surface,
                ctx,
                f"{range_txt}: {desc}",
                (left_x, y_pos),
                font_name="tiny",
                color=color,
            )
            y_pos += 26

        pollen_y = 120
        self.draw_text(
            surface, ctx, "POLLEN COUNT", (right_x, pollen_y), font_name="normal", color=yellow
        )
        pollen_y += 30

        pollen_data = [
            ("Tree", "LOW"),
            ("Grass", "MODERATE"),
            ("Weed", "LOW"),
            ("Mold", "HIGH"),
        ]
        for pollen_type, level in pollen_data:
            self.draw_text(
                surface, ctx, f"{pollen_type}:", (right_x, pollen_y), font_name="tiny", color=white
            )

            if level == "HIGH":
                color = _SOFT_RED
            elif level == "MODERATE":
                color = yellow
            else:
                color = _SOFT_GREEN

            bar_x = right_x + 70
            bar_width = 80 if level == "HIGH" else 60 if level == "MODERATE" else 40
            pygame.draw.rect(surface, color, (bar_x, pollen_y + 2, bar_width, 12))

            text_x = bar_x + bar_width + 10
            self.draw_text(surface, ctx, level, (text_x, pollen_y), font_name="tiny", color=color)
            pollen_y += 25

        y_pos = max(y_pos, pollen_y) + 20
        font_normal = self.font(ctx, "normal")
        if font_normal is not None:
            tips_title = font_normal.render("HEALTH RECOMMENDATIONS", True, yellow)
            surface.blit(tips_title, tips_title.get_rect(center=(320, y_pos)))
        y_pos += 25

        tips = [
            "Air quality is good for outdoor activities",
            "High mold count - allergy sufferers take precaution",
            "UV index moderate - use sunscreen if outside",
        ]

        clip_rect = pygame.Rect(60, y_pos, 520, 440 - y_pos)
        surface.set_clip(clip_rect)

        total_height = len(tips) * 22
        visible_height = 440 - y_pos

        offset = getattr(self, "_scroll_offset", 0.0)
        direction = getattr(self, "_scroll_dir", 1.0)
        if total_height > visible_height:
            offset += direction * dt * 30.0
            if offset > 0:
                offset = 0.0
                direction = -1.0
            elif offset < -(total_height - visible_height):
                offset = -(total_height - visible_height)
                direction = 1.0
            self._scroll_offset = offset
            self._scroll_dir = direction

        font_tiny = self.font(ctx, "tiny")
        tip_y = y_pos + offset
        for tip in tips:
            if font_tiny is None:
                break
            if font_tiny.size(tip)[0] > _MAX_TIP_WIDTH:
                for line in self.wrap(font_tiny, tip, _MAX_TIP_WIDTH):
                    if 0 < tip_y < 440:
                        self.draw_text(
                            surface,
                            ctx,
                            f"\u2022 {line}",
                            (70, tip_y),
                            font_name="tiny",
                            color=white,
                        )
                    tip_y += 20
            else:
                if 0 < tip_y < 440:
                    self.draw_text(
                        surface, ctx, f"\u2022 {tip}", (70, tip_y), font_name="tiny", color=white
                    )
                tip_y += 22

        surface.set_clip(None)

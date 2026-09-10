"""Local Forecast screen: three-day column layout with wrapped text.

The three tinted "blocks" come from the ``2`` background art.  Column geometry
is detected from that art at runtime so text is centered inside each block and
kept clear of its edges (the classic look has the wrapped forecast text running
flush to the block borders otherwise).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pygame

from weatherstar import render
from weatherstar.components.base import ComponentSpec
from weatherstar.datasources.noaa import ForecastPeriod
from weatherstar.plugin import memoize
from weatherstar.registry import plugin
from weatherstar.screens.base import Screen
from weatherstar.themes import LayoutVariant

#: Vertical rhythm inside each block (px).  Content is inset from the detected
#: block edges by these amounts.
_PAD_TOP = 8
_PAD_BOTTOM = 10
_PAD_X = 12
_GROUP_GAP = 8
#: Line-to-line step for the wrapped forecast text (the star fonts carry large
#: leading, so ~18px keeps glyph ink clear without crowding or truncation).
_LINE_SPACING = 18
#: Weather Star 3000 rolling text column geometry (ws3kp local-forecast.scss:
#: a 280px text column at the 35px margins, 40px line height).
_3000_LEFT = 35
_3000_WIDTH = 570
_3000_TOP = 118
_3000_HEIGHT = 280
_3000_LINE_SPACING = 40


@plugin
class LocalForecastScreen(Screen):
    name = "local_forecast"
    media = ("fonts", "backgrounds", "logos", "icons")
    datasources = ("weather",)

    variants = {
        LayoutVariant.WS4000: "compose_4000",
        LayoutVariant.WS3000: "compose_3000",
    }

    layout = (
        ComponentSpec(component="background", config={"background_name": "2"}),
        ComponentSpec(
            component="header",
            config={"title_top": "Local", "title_bottom": "Forecast", "has_noaa": True},
        ),
        ComponentSpec(component="clock"),
    )

    def compose_4000(self, surface: pygame.Surface, ctx: Any, dt: float) -> None:
        periods: list[ForecastPeriod] = self.weather_data(ctx, "get_forecast") or []
        if len(periods) < 3:
            render.draw_centered_text(
                surface, ctx, "NO DATA AVAILABLE", 240, font_name="large", color_key="yellow"
            )
            return

        yellow = self.color(ctx, "yellow")
        white = self.color(ctx, "white")
        panels = self._panels(ctx)

        # A 3-day outlook shows the three *daytime* windows (today / tomorrow /
        # the day after).  Fall back to the raw first periods when the feed does
        # not carry day/night flags.
        columns = self._outlook_columns(periods)
        labels = self._column_labels(columns)

        for col_idx, period in enumerate(columns):
            x0, x1, top, bottom = panels[col_idx]
            center_x = (x0 + x1) // 2
            display_name = labels[col_idx]

            y_cursor = top + _PAD_TOP

            name_surf = self.font(ctx, "extended").render(display_name, True, yellow)
            surface.blit(
                name_surf,
                name_surf.get_rect(center=(center_x, y_cursor + name_surf.get_height() // 2)),
            )
            y_cursor += name_surf.get_height() + _GROUP_GAP

            temp = period.temperature
            if temp is not None:
                temp_surf = self.font(ctx, "normal").render(
                    f"{int(temp)}\N{DEGREE SIGN}", True, white
                )
                surface.blit(
                    temp_surf,
                    temp_surf.get_rect(center=(center_x, y_cursor + temp_surf.get_height() // 2)),
                )
                y_cursor += temp_surf.get_height() + _GROUP_GAP

            detailed = period.detailed_forecast
            forecast_font = self.font(ctx, "forecast")
            lines = self.wrap(forecast_font, str(detailed), x1 - x0 - 2 * _PAD_X)

            content_bottom = bottom - _PAD_BOTTOM
            line_spacing = int(self.layout_token(ctx, "forecast_line_spacing", _LINE_SPACING))
            for line in lines:
                if y_cursor + forecast_font.get_height() > content_bottom:
                    break
                line_surf = forecast_font.render(line, True, white)
                surface.blit(
                    line_surf,
                    line_surf.get_rect(center=(center_x, y_cursor + line_surf.get_height() // 2)),
                )
                y_cursor += line_spacing

    # -- Weather Star 3000 (ws3kp) variant ------------------------------------

    def compose_3000(self, surface: pygame.Surface, ctx: Any, dt: float) -> None:
        """ws3kp Local Forecast: one tall rolling column of forecast pages.

        Each of the first six periods becomes a ``DAYNAME... detailed text``
        block (ws3kp localforecast.mjs), wrapped at the 35px margins and rolled
        upward through the 280px text column so pages flow past like the real
        3000 crawl.
        """
        white = self.color(ctx, "white")
        font = self.font(ctx, "large")
        periods: list[ForecastPeriod] = self.weather_data(ctx, "get_forecast") or []

        lines: list[str] = []
        for period in periods[:6]:
            if not period.detailed_forecast:
                continue
            heading = f"{period.name.upper()}..."
            text = f"{heading} {period.detailed_forecast.upper()}"
            lines.extend(self.wrap(font, text, _3000_WIDTH))
            lines.append("")

        if not any(lines):
            render.draw_centered_text(
                surface, ctx, "NO DATA AVAILABLE", 240, font_name="large", color_key="yellow"
            )
            return

        clip = pygame.Rect(0, _3000_TOP, surface.get_width(), _3000_HEIGHT)
        surface.set_clip(clip)
        total_height = len(lines) * _3000_LINE_SPACING
        offset = (pygame.time.get_ticks() // 40) % total_height
        base = _3000_TOP - offset
        bottom = _3000_TOP + _3000_HEIGHT
        for duplicate in range(2):
            y = base + duplicate * total_height
            for line in lines:
                if line and _3000_TOP <= y <= bottom:
                    self.draw_text(
                        surface, ctx, line, (_3000_LEFT, y), font_name="large", color=white
                    )
                y += _3000_LINE_SPACING
        surface.set_clip(None)

    # -- column selection & labels -----------------------------------------

    @staticmethod
    def _outlook_columns(periods: list[ForecastPeriod]) -> list[ForecastPeriod]:
        """The three columns of a 3-day outlook: daytime periods when present."""
        days = [p for p in periods if p.is_daytime]
        return days[:3] if len(days) >= 3 else periods[:3]

    def _column_labels(self, columns: list[ForecastPeriod]) -> list[str]:
        """Labels for a 3-day outlook: TODAY / TOMORROW / weekday-after.

        When the outlook does not start today, every column is labelled by its
        own weekday instead.
        """
        today = date.today()
        base = columns[0].start_date() if columns else None
        if base == today:
            third = columns[2].start_date() if len(columns) > 2 else None
            if third is None:
                third = today + timedelta(days=2)
            return ["TODAY", "TOMORROW", third.strftime("%A").upper()]
        labels: list[str] = []
        fallback = base or today
        for index, period in enumerate(columns):
            day = period.start_date()
            if day is not None:
                labels.append(day.strftime("%A").upper())
            else:
                labels.append((fallback + timedelta(days=index)).strftime("%A").upper())
        return labels

    # -- block geometry ----------------------------------------------------

    def _panels(self, ctx: Any) -> tuple:
        image = None
        try:
            image = (ctx.assets.get("backgrounds") or {}).get("2")
        except Exception:
            image = None
        return self._panels_for_image(image)

    @memoize
    def _panels_for_image(self, image: Any) -> tuple:
        return self._detect_panels(image) or self._default_panels()

    @staticmethod
    def _default_panels() -> tuple:
        return ((40, 209, 103, 393), (234, 403, 103, 393), (428, 597, 103, 393))

    @staticmethod
    def _detect_panels(image: Any) -> tuple:
        """Locate the three tinted blocks in the background art as (x0, x1, top, bottom)."""
        if image is None:
            return ()
        width, height = image.get_size()

        def is_panel(rgb: tuple) -> bool:
            r, g, b = rgb[:3]
            return b > 120 and b - r > 40

        rows = list(range(140, min(height, 400), 3))
        column_score = [
            sum(1 for y in rows if is_panel(image.get_at((x, y)))) for x in range(width)
        ]
        threshold = len(rows) * 0.5
        runs: list[tuple[int, int]] = []
        start: int | None = None
        for x in range(width + 1):
            active = x < width and column_score[x] > threshold
            if active and start is None:
                start = x
            elif not active and start is not None:
                if x - start >= 40:
                    runs.append((start, x - 1))
                start = None
        if len(runs) != 3:
            return ()

        boxes: list[tuple[int, int, int, int]] = []
        for x0, x1 in runs:
            samples = list(range(x0, x1 + 1, 4))
            rows_present: list[int] = []
            for y in range(height):
                hits = sum(1 for x in samples if is_panel(image.get_at((x, y))))
                if hits > len(samples) * 0.6:
                    rows_present.append(y)
            if not rows_present:
                return ()
            boxes.append((x0, x1, rows_present[0], rows_present[-1]))
        return tuple(boxes)

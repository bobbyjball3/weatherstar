"""Severe Weather Alert screen.

When the ``alerts`` datasource reports active alerts, a pulsing red emergency
screen is drawn with the severity/event, headline, affected areas, action
instructions and expiry.  Otherwise the "all clear" screen is shown.

All alert content is laid out sequentially (each block returns its true bottom
edge, so sections can never collide) and confined above ``y = 430`` where the
engine draws its bottom scrolling-ticker banner.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pygame
from pydantic import PrivateAttr

from weatherstar.datasources.feeds import Alert
from weatherstar.plugin import memoize
from weatherstar.registry import plugin
from weatherstar.screens.base import Screen

_BORDER = 8
_WIDTH, _HEIGHT = 640, 480
# Engine's ticker banner starts here; content must stay above it.
_CONTENT_BOTTOM = 424
_BODY_X = 80
_BODY_WIDTH = 480


@plugin
class SevereWeatherAlertScreen(Screen):
    name = "severe_weather_alert"
    datasources = ("alerts",)

    _elapsed: float = PrivateAttr(default=0.0)

    # -- fonts ---------------------------------------------------------------

    @memoize
    def _font(self, size: int) -> pygame.font.Font:
        return pygame.font.Font(None, size)

    # -- entry ---------------------------------------------------------------

    def draw(self, surface: pygame.Surface, ctx: Any, dt: float) -> None:
        alerts: list[Alert] = []
        ds = self.datasource(ctx, "alerts")
        lat, lon = self.latlon(ctx)
        try:
            alerts = ds.active(lat, lon) or []
        except Exception:  # noqa: BLE001 - data is optional
            alerts = []

        if alerts:
            self._draw_alert(surface, ctx, dt, alerts[0])
        else:
            self._draw_all_clear(surface, ctx)

    # -- all clear -----------------------------------------------------------

    def _draw_all_clear(self, surface: pygame.Surface, ctx: Any) -> None:
        surface.fill(self.color(ctx, "blue_gradient_2", (0, 16, 64)))

        text = self._font(48).render(
            "NO ACTIVE WEATHER ALERTS", True, self.color(ctx, "white", (255, 255, 255))
        )
        surface.blit(text, text.get_rect(center=(_WIDTH // 2, 230)))

        subtext = self._font(30).render(
            "All weather conditions normal", True, self.color(ctx, "white", (255, 255, 255))
        )
        surface.blit(subtext, subtext.get_rect(center=(_WIDTH // 2, 285)))

    # -- emergency alert ------------------------------------------------------

    def _draw_alert(
        self,
        surface: pygame.Surface,
        ctx: Any,
        dt: float,
        alert: Alert,
    ) -> None:
        base_red = self.color(ctx, "red", (255, 0, 0))
        accent = self._pulse_color(base_red, dt)
        white = (255, 255, 255)

        surface.fill((70, 0, 0))
        pygame.draw.rect(surface, accent, (0, 0, _WIDTH, _HEIGHT), _BORDER)

        # Header band.
        pygame.draw.rect(surface, accent, (0, 0, _WIDTH, 88))
        title = self._font(34).render("EMERGENCY ALERT", True, white)
        surface.blit(title, title.get_rect(center=(_WIDTH // 2, 32)))

        severity = alert.severity.upper() or "Unknown"
        event = alert.event or "Weather Alert"
        sev_text = self._font(18).render(f"{severity} - {event}", True, white)
        surface.blit(sev_text, sev_text.get_rect(center=(_WIDTH // 2, 66)))

        expiry = self._format_expiry(alert.expires)
        if expiry:
            exp_text = self._font(15).render(f"VALID UNTIL {expiry}", True, (255, 255, 200))
            surface.blit(exp_text, exp_text.get_rect(topright=(_WIDTH - 24, 26)))

        # Body, laid out sequentially starting just below the header.
        cursor = 120

        headline = alert.headline.strip()
        if headline:
            cursor = self._draw_block(
                surface,
                self._font(20),
                headline,
                center_x=_WIDTH // 2,
                y=cursor,
                max_width=560,
                max_lines=2,
                max_y=_CONTENT_BOTTOM,
                color=white,
            )
            cursor += 12

        areas = alert.areas.strip()
        instruction = alert.instruction.strip()

        for label, body, max_lines in (
            ("AFFECTED AREAS:", areas, 2),
            ("ACTION TO TAKE:", instruction, 3),
        ):
            if not body:
                continue
            cursor = self._draw_block(
                surface,
                self._font(18),
                label,
                x=60,
                y=cursor,
                max_width=560,
                max_lines=1,
                max_y=_CONTENT_BOTTOM,
                color=accent,
            )
            cursor += 4
            cursor = self._draw_block(
                surface,
                self._font(17),
                body,
                x=_BODY_X,
                y=cursor,
                max_width=_BODY_WIDTH,
                max_lines=max_lines,
                max_y=_CONTENT_BOTTOM,
                color=white,
            )
            cursor += 10

    def _draw_block(
        self,
        surface: pygame.Surface,
        font: pygame.font.Font,
        text: str,
        *,
        max_width: int,
        max_lines: int,
        max_y: int,
        color: tuple[int, int, int],
        y: int,
        x: int | None = None,
        center_x: int | None = None,
    ) -> int:
        """Draw wrapped text from ``y`` downward and return the next free row.

        Text never renders past ``max_y``; if the block was truncated for space
        an ellipsis is appended to the last drawn line.
        """
        lines = self.wrap(font, text, max_width)
        truncated = len(lines) > max_lines
        lines = lines[:max_lines]
        if truncated:
            lines[-1] = lines[-1].rstrip() + "..."

        leading = font.get_linesize()
        cursor = y
        for line in lines:
            if cursor + leading > max_y:
                break
            rendered = font.render(line, True, color)
            if center_x is not None:
                surface.blit(rendered, rendered.get_rect(center=(center_x, cursor + leading // 2)))
            else:
                surface.blit(rendered, (x if x is not None else 0, cursor))
            cursor += leading
        return cursor

    # -- helpers ---------------------------------------------------------------

    def _pulse_color(self, base: tuple[int, int, int], dt: float) -> tuple[int, int, int]:
        elapsed = float(getattr(self, "_elapsed", 0.0))
        dt = dt or 0.0
        elapsed = (elapsed + max(dt, 0.0)) % 1000000.0
        self._elapsed = elapsed
        pulse = 0.5 + 0.5 * math.sin(elapsed * 5.0)
        factor = 0.55 + 0.45 * pulse
        return tuple(int(max(0.0, min(255.0, channel * factor))) for channel in base)

    def _format_expiry(self, value: Any) -> str:
        if not value:
            return ""
        try:
            expires = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return ""
        return expires.strftime("%I:%M %p %m/%d")

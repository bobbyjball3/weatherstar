"""Radar screen: animated NOAA/NWS radar cropped around the configured location.

Uses the ``radar`` datasource, which returns regional (location-zoomed) frames
scaled to the radar box.  Frames cycle every ~0.5s like the legacy display.
When no frames are available (offline/startup) a "RADAR UPDATING" placeholder is
shown, and the datasource retries on its own TTL.
"""

from __future__ import annotations

from typing import Any

import pygame
from pydantic import PrivateAttr

from weatherstar.components.base import ComponentSpec
from weatherstar.registry import plugin
from weatherstar.screens.base import Screen
from weatherstar.themes import LayoutVariant

_RADAR_RECT = pygame.Rect(70, 100, 500, 300)
_FRAME_DURATION = 0.5  # seconds per radar frame
_REFRESH_SECONDS = 300.0  # re-fetch the loop every 5 minutes

_LEGEND = (
    ((0, 100, 0), "Light"),
    ((255, 255, 0), "Moderate"),
    ((255, 140, 0), "Heavy"),
    ((255, 0, 0), "Intense"),
)


@plugin
class RadarScreen(Screen):
    name = "radar"
    media = ("fonts", "backgrounds", "logos")
    datasources = ("radar",)

    _frames: list[pygame.Surface] = PrivateAttr(default_factory=list)
    _frame_index: int = PrivateAttr(default=0)
    _frame_timer: float = PrivateAttr(default=0.0)
    _frames_elapsed: float = PrivateAttr(default=0.0)

    variants = {
        LayoutVariant.WS4000: "compose_4000",
    }

    def _fetch_frames(self, ctx: Any) -> list[pygame.Surface]:
        """Fetch the radar loop (``[]`` when offline or locationless)."""
        location = getattr(ctx, "location", None)
        if location is None:
            return []
        try:
            radar = self.datasource(ctx, "radar")
            return radar.frames(location.lat, location.lon) or []
        except Exception:
            return []

    layout = (
        ComponentSpec(component="background", config={"background_name": "6"}),
        ComponentSpec(
            component="header",
            config={"title_top": "Live", "title_bottom": "Radar", "has_noaa": False},
        ),
        ComponentSpec(component="clock"),
    )

    def compose_4000(self, surface: pygame.Surface, ctx: Any, dt: float) -> None:
        rect = _RADAR_RECT
        white = self.color(ctx, "white", (255, 255, 255))
        yellow = self.color(ctx, "yellow", (255, 255, 0))

        # Refresh the loop periodically (the datasource caches for its own TTL);
        # keep the last good frames when a refresh comes back empty.
        self._frames_elapsed += dt
        if not self._frames or self._frames_elapsed >= _REFRESH_SECONDS:
            frames = self._fetch_frames(ctx)
            if frames:
                self._frames = frames
                self._frame_index %= len(frames)
            self._frames_elapsed = 0.0
        frames = self._frames

        if frames:
            self._frame_timer += dt
            if self._frame_timer >= _FRAME_DURATION:
                self._frame_timer = 0.0
                self._frame_index = (self._frame_index + 1) % len(frames)
            surface.blit(frames[self._frame_index], rect)
            self._draw_legend(surface, ctx, rect)
            frame_text = self.font(ctx, "tiny").render(
                f"Frame {self._frame_index + 1}/{len(frames)}", True, white
            )
            surface.blit(frame_text, frame_text.get_rect(topright=(rect.right - 6, rect.top + 6)))
        else:
            pygame.draw.rect(surface, (20, 20, 20), rect)
            msg = self.font(ctx, "large").render("RADAR UPDATING", True, yellow)
            surface.blit(msg, msg.get_rect(center=rect.center))
            msg2 = self.font(ctx, "normal").render("Connecting to NOAA Radar...", True, white)
            surface.blit(msg2, msg2.get_rect(center=(rect.centerx, rect.centery + 30)))

        pygame.draw.rect(surface, yellow, rect, 2)

        # Captions sit inside the frame's lower band (not below y=400) so they
        # never collide with the always-on bottom ticker/scroll band.
        location = self._location_text(ctx)
        if location:
            loc_font = self.font(ctx, "normal")
            loc_text = loc_font.render(location.upper(), True, yellow)
            surface.blit(loc_text, loc_text.get_rect(center=(320, rect.bottom - 24)))

        attr = self.font(ctx, "tiny").render("Radar: NOAA/NWS", True, white)
        surface.blit(attr, (rect.left + 6, rect.bottom - 22))

    def _draw_legend(self, surface: pygame.Surface, ctx: Any, rect: pygame.Rect) -> None:
        legend_y = rect.top + 10
        legend_x = rect.left + 10
        white = self.color(ctx, "white", (255, 255, 255))
        tiny = self.font(ctx, "tiny")
        for i, (color, label) in enumerate(_LEGEND):
            box = pygame.Rect(legend_x, legend_y + i * 20, 15, 15)
            pygame.draw.rect(surface, color, box)
            pygame.draw.rect(surface, white, box, 1)
            text = tiny.render(label, True, white)
            surface.blit(text, (legend_x + 20, legend_y + i * 20))

    def _location_text(self, ctx: Any) -> str:
        location = getattr(ctx, "location", None)
        if location is None:
            return ""
        description = getattr(location, "description", "") or ""
        if description:
            return description
        weather = self.optional_datasource(ctx, "weather")
        if weather is not None:
            try:
                city = weather.get_city(location.lat, location.lon)
                if city.city and city.state:
                    return f"{city.city}, {city.state}"
            except Exception:
                pass
        return ""

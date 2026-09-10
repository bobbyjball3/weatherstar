"""Bottom scrolling text banner, drawn over every slide.

Ports the legacy ``ScrollingText`` behaviour: a fixed-height navy banner at the
bottom of the screen with white text that continuously crawls right-to-left at
``SCROLL_SPEED`` px/s, cycling through a set of messages rebuilt from live
weather data on an interval (falling back to static copy when no weather
datasource/location is available).
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pygame

from weatherstar.datasources.noaa import CurrentConditions, ForecastPeriod
from weatherstar.renderer import blit_text_shadowed

if TYPE_CHECKING:
    from weatherstar.context import AppContext

SCROLL_SPEED = 100.0  # px/s, matches legacy
REFRESH_SECONDS = 90.0
_BANNER_COLOR = (0, 0, 80)
_FALLBACK_ITEMS = ("Weather conditions and forecast information",)


class BottomTicker:
    """Draws and advances the always-on bottom scroller."""

    def __init__(self) -> None:
        self._items: list[str] = []
        self._current = ""
        self._x = 0.0
        self._last_refresh = 0.0
        self._font: pygame.font.Font | None = None

    # -- content -----------------------------------------------------------

    @staticmethod
    def _ds(ctx: Any, name: str) -> Any:
        data = getattr(ctx, "data", None)
        if data is None:
            return None
        try:
            return data.get(name)
        except KeyError:
            return None

    @staticmethod
    def _cardinal(degrees: float | None) -> str:
        if degrees is None:
            return ""
        directions = [
            "N",
            "NNE",
            "NE",
            "ENE",
            "E",
            "ESE",
            "SE",
            "SSE",
            "S",
            "SSW",
            "SW",
            "WSW",
            "W",
            "WNW",
            "NW",
            "NNW",
        ]
        try:
            return directions[int((degrees + 11.25) / 22.5) % 16]
        except Exception:
            return ""

    def _build_items(self, ctx: Any) -> list[str]:
        items: list[str] = []
        location = getattr(ctx, "location", None)
        lat = getattr(location, "lat", None)
        lon = getattr(location, "lon", None)

        weather = self._ds(ctx, "weather")

        # Location label.
        description = ""
        if location is not None:
            description = getattr(location, "description", "") or ""
        city_state = ""
        if weather is not None and lat is not None and lon is not None:
            try:
                city = weather.get_city(lat, lon)
                if city.city and city.state:
                    city_state = f"{city.city.upper()}, {city.state.upper()}"
            except Exception:
                pass
        label = city_state or description.upper()
        if label:
            items.append(f" +++ {label} +++ ")

        # Current conditions.
        current: CurrentConditions | None = None
        if weather is not None and lat is not None and lon is not None:
            try:
                current = weather.get_current(lat, lon)
            except Exception:
                current = None
        if current is not None:
            temp_f = current.temperature_f
            if temp_f is not None:
                line = f"CURRENTLY: {temp_f}\N{DEGREE SIGN}F, {current.text_description}"
                humidity = current.relative_humidity
                if humidity is not None:
                    line += f" ... HUMIDITY: {round(humidity)}%"
                wind_mph = current.wind_mph
                if wind_mph is not None:
                    direction = self._cardinal(current.wind_direction)
                    line += f" ... WIND: {direction + ' ' if direction else ''}{wind_mph} MPH"
                items.append(line)

        # Today / tonight outlook.
        periods: list[ForecastPeriod] = []
        if weather is not None and lat is not None and lon is not None:
            try:
                periods = weather.get_forecast(lat, lon) or []
            except Exception:
                periods = []
        if periods:
            today = periods[0]
            name = today.name
            temp = today.temperature
            if temp is not None and name:
                items.append(f"{name.upper()}: {int(temp)}\N{DEGREE SIGN}, {today.short_forecast}")
            if len(periods) > 1:
                tonight = periods[1]
                temp = tonight.temperature
                if temp is not None:
                    items.append(f"TONIGHT: {int(temp)}\N{DEGREE SIGN}, {tonight.short_forecast}")

        if not items:
            items = list(_FALLBACK_ITEMS)
        return items

    # -- frame update + render ----------------------------------------------

    def _font_for(self, ctx: Any) -> pygame.font.Font:
        if self._font is not None:
            return self._font
        fonts = getattr(ctx, "fonts", None)
        if isinstance(fonts, dict):
            for key in ("scroller", "normal", "small"):
                font = fonts.get(key)
                if font is not None:
                    self._font = font
                    return font
        self._font = pygame.font.Font(None, 24)
        return self._font

    def render(self, surface: pygame.Surface, ctx: AppContext, dt: float) -> None:
        width = surface.get_width()
        height = surface.get_height()

        self._refresh(ctx, width)
        if not self._current:
            return

        font = self._font_for(ctx)
        self._advance(dt, width, font)

        # Banner, opaque so content behind never bleeds through.
        banner_height = 30
        banner_y = height - banner_height - 20
        surface.fill(_BANNER_COLOR, (0, banner_y, width, banner_height))

        text_height = font.get_height()
        text_y = banner_y + (banner_height - text_height) // 2
        rendered = font.render(self._current, True, (255, 255, 255))
        surface.blit(rendered, (int(self._x), text_y))

    # -- shared scroll state -------------------------------------------------

    def _refresh(self, ctx: Any, width: int) -> None:
        now = time.time()
        if not self._items or now - self._last_refresh >= REFRESH_SECONDS:
            self._items = self._build_items(ctx)
            self._last_refresh = now
            if not self._current and self._items:
                self._current = self._items[0]
                self._x = float(width)

    def _advance(self, dt: float, width: int, font: pygame.font.Font) -> None:
        text_width = font.size(self._current)[0]
        # Advance scroll position.
        self._x -= SCROLL_SPEED * dt
        if self._x + text_width < 0:
            self._x = float(width)
            if len(self._items) > 1:
                self._items = self._items[1:] + self._items[:1]
            self._current = self._items[0]
            text_width = font.size(self._current)[0]


#: Vertical layout of the Weather Star 3000 scroll band (ws3kp _weather-display.scss
#: .scroll: a 70px band at the foot of the canvas).  The band is transparent:
#: it draws only the date/time row and the crawling conditions line over the
#: shared background art, so screens reserve the canvas above it.
_BAND_TOP = 405
_BAND_LEFT = 35
_BAND_RIGHT = 605

#: How long one conditions line holds before the next takes its place (ws3kp
#: currentweatherscroll.mjs updates every ~8 half-second ticks).
_MESSAGE_HOLD = 8.0
#: Seconds a long conditions line waits before starting its horizontal reveal.
_REVEAL_DELAY = 1.0
#: Horizontal scroll speed for over-wide conditions lines (ws3kp uses 75px/s).
_REVEAL_SPEED = 75.0


class WeatherStar3000Scroll(BottomTicker):
    """The 3000's always-on bottom scroll: date + time over a conditions line.

    Replaces the navy ``BottomTicker`` when a theme opts in via its
    ``bottom_band`` key set to the ``"3000"`` variant.  Date (left) and time
    (right) run in the real "Star3000
    Small" face at the top of the band; below them the current conditions are
    shown one at a time (ws3kp scroll.ejs + currentweatherscroll.mjs).  Lines
    that fit the band sit static for a few seconds then advance; over-wide lines
    scroll left to reveal their tail before the next one advances.
    """

    def __init__(self) -> None:
        super().__init__()
        self._message_elapsed = 0.0
        self._message_index = 0
        self._revealing = False

    def _build_items(self, ctx: Any) -> list[str]:
        return [str(item).upper() for item in super()._build_items(ctx)]

    def _crawl_font(self, ctx: Any) -> pygame.font.Font:
        fonts = getattr(ctx, "fonts", None)
        if isinstance(fonts, dict):
            for key in ("large", "scroller", "normal"):
                font = fonts.get(key)
                if font is not None:
                    return font
        return self._font_for(ctx)

    def _clock_font(self, ctx: Any) -> pygame.font.Font:
        fonts = getattr(ctx, "fonts", None)
        if isinstance(fonts, dict):
            for key in ("datetime", "small"):
                font = fonts.get(key)
                if font is not None:
                    return font
        return self._font_for(ctx)

    def _conditions(self, ctx: Any) -> list[str]:
        """Rotated conditions lines (uppercased for the all-caps typeface)."""
        if not self._items:
            self._items = self._build_items(ctx)
            self._message_index = 0
        return self._items or list(_FALLBACK_ITEMS)

    def render(self, surface: pygame.Surface, ctx: AppContext, dt: float) -> None:
        self._draw_clock(surface, ctx)
        items = self._conditions(ctx)
        if not items:
            return

        font = self._crawl_font(ctx)
        width = surface.get_width()
        current = items[self._message_index % len(items)]
        text_width = font.size(current)[0]
        max_width = width - 70

        self._message_elapsed += dt
        x = float(_BAND_LEFT)
        if text_width > max_width:
            if not self._revealing:
                self._message_elapsed = 0.0
                self._revealing = True
            elif self._message_elapsed > _REVEAL_DELAY:
                reveal = (self._message_elapsed - _REVEAL_DELAY) * _REVEAL_SPEED
                x = _BAND_LEFT - min(reveal, text_width - max_width)
            hold = _REVEAL_DELAY + (text_width - max_width) / _REVEAL_SPEED + 2.0
            if self._message_elapsed > max(hold, _MESSAGE_HOLD):
                self._next(items)
        elif self._message_elapsed > _MESSAGE_HOLD:
            self._next(items)

        white = (ctx.colors or {}).get("white", (255, 255, 255))
        y = _BAND_TOP + self._clock_font(ctx).get_height() + 6
        blit_text_shadowed(surface, ctx, font, current, white, (int(x), y))

    def _next(self, items: list[str]) -> None:
        self._message_index = (self._message_index + 1) % len(items)
        self._message_elapsed = 0.0
        self._revealing = False

    def _draw_clock(self, surface: pygame.Surface, ctx: AppContext) -> None:
        font = self._clock_font(ctx)
        now = datetime.now()
        white = (ctx.colors or {}).get("white", (255, 255, 255))
        date_str = now.strftime("%a %b %d").upper()
        time_str = now.strftime("%I:%M %p").upper().lstrip("0")
        date_rect = font.render(date_str, True, white).get_rect(topleft=(_BAND_LEFT, _BAND_TOP))
        time_rect = font.render(time_str, True, white).get_rect(top=_BAND_TOP, right=_BAND_RIGHT)
        blit_text_shadowed(surface, ctx, font, date_str, white, date_rect)
        blit_text_shadowed(surface, ctx, font, time_str, white, time_rect)

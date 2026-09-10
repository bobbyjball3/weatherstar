"""Shared rendering helpers for Screens and Components.

Screens and Components both draw onto a pygame surface using the shared
:class:`~weatherstar.context.AppContext` (fonts, colors, assets,
datasources).  Historically every screen re-declared small module-level helpers
(``_font``, ``_color``, ``_ds``, ``_latlon``, ...) with slightly different
fallback semantics.  This mixin moves those concrete helpers onto the interface
so a Screen/Component just calls ``self.font(ctx, ...)`` / ``self.color(ctx,
...)``.

The mixin defines methods only: any plain class attribute here would be
inherited by Pydantic plugin models and rejected as a non-annotated attribute,
so constants live at module scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pygame

from weatherstar.themes import LayoutVariant, coerce_variant

#: Fallback font sizes by name (mirrors media/fonts.py), used when the runtime
#: context has no loaded font for a key.
_FONT_SIZES = {
    "title": 32,
    "large": 32,
    "extended": 32,
    "small": 28,
    "normal": 20,
    "forecast": 24,
    "tiny": 16,
    "scroller": 24,
}

_WHITE = (255, 255, 255)
_YELLOW = (255, 255, 0)


def short_condition_text(text: str, max_len: int = 9) -> str:
    """Abbreviate a wordy NWS condition to fit tight table cells.

    Mirrors ws3kp's ``shortenCurrentConditions`` word swaps, then truncates to
    ``max_len`` characters (e.g. "Partly Cloudy" -> "P Cloudy", "Thunderstorm"
    -> "T'storm").
    """
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= 15:
        return cleaned[:max_len]
    for long, short in (
        ("Freezing Rain", "Frz Rn"),
        ("Thunderstorm", "T'storm"),
        ("Freezing", "Frz"),
        ("Light", "L"),
        ("Heavy", "H"),
        ("Partly", "P"),
        ("Mostly", "M"),
        ("Few", "F"),
        ("Vicinity", ""),
    ):
        cleaned = cleaned.replace(long, short)
    cleaned = cleaned.replace(" in ", " ")
    cleaned = cleaned.replace(" and ", " ")
    cleaned = cleaned.replace(" with ", "/")
    return cleaned[:max_len]


def shadow_offsets(offset: int, outline: int) -> tuple[tuple[int, int], ...]:
    """Pixel offsets that draw a glyph's outline ring plus a right/down drop.

    Mirrors the classic Weather Star CSS ``text-shadow`` stack: a drop shadow at
    ``(offset, offset)`` and an 8-way outline ring ``outline`` px out.  ``offset``
    of 0 disables the drop (pure outline, e.g. hazard banners).
    """
    ring: list[tuple[int, int]] = []
    radius = max(1, outline)
    for dx in (-radius, 0, radius):
        for dy in (-radius, 0, radius):
            if dx == 0 and dy == 0:
                continue
            ring.append((dx, dy))
    if offset:
        drop = (offset, offset)
        if drop not in ring:
            ring.append(drop)
    return tuple(ring)


def blit_text_shadowed(
    surface: pygame.Surface,
    ctx: Any,
    font: pygame.font.Font,
    text: str,
    color: tuple[int, int, int],
    dest,
) -> pygame.Rect:
    """Blit ``text`` in ``color`` with the theme's outline + drop underlay.

    When the active theme disables text shadows this is a plain blit.  ``dest``
    may be a position or rect; the returned rect is where the glyph landed.
    """
    pos = dest.topleft if hasattr(dest, "topleft") else dest
    glyph = font.render(text, True, color)
    rect = glyph.get_rect(topleft=pos)
    theme = getattr(ctx, "theme", None)
    if theme is None or not theme.text_shadow:
        surface.blit(glyph, rect)
        return rect
    shadow_color = theme.colors.get("black", (0, 0, 0))
    shadow = font.render(text, True, shadow_color)
    for dx, dy in shadow_offsets(theme.text_shadow_offset, theme.text_shadow_outline):
        surface.blit(shadow, rect.move(dx, dy))
    surface.blit(glyph, rect)
    return rect


#: The sixteen classic compass points, indexed by a heading in degrees.
_CARDINALS = [
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

#: Common NOAA condition token -> weather icon name (classic Weather Star set).
#: Clear-sky tokens are intentionally absent so the classifier can pick the day
#: "Sunny" vs the night "Clear" icon from the URL's day/night segment.
_ICON_NAMES = {
    "sct": "Partly-Cloudy",
    "bkn": "Cloudy",
    "ovc": "Cloudy",
    "rain": "Rain",
    "rain_showers": "Shower",
    "tsra": "Thunderstorm",
    "snow": "Light-Snow",
    "fog": "Fog",
    "wind": "Windy",
}


@dataclass(frozen=True)
class _IconRule:
    """One flat weather-icon classification rule (ordered, first match wins).

    A rule matches a lower-cased token when it contains every substring in
    ``all``, at least one substring in ``any``, no substring in ``none``, and
    (when ``exact`` is given) the whole token is one of ``exact``.  Provide at
    least one of ``exact``/``any``/``all``.
    """

    icon: str
    exact: tuple[str, ...] = ()
    any: tuple[str, ...] = ()
    all: tuple[str, ...] = ()
    none: tuple[str, ...] = ()
    night_icon: str | None = None

    def matches(self, token: str) -> bool:
        if not (self.exact or self.any or self.all):
            return False
        if self.exact and token not in self.exact:
            return False
        if self.any and not any(part in token for part in self.any):
            return False
        if self.all and not all(part in token for part in self.all):
            return False
        if self.none and any(part in token for part in self.none):
            return False
        return True

    def icon_for(self, night: bool) -> str:
        return self.night_icon if (night and self.night_icon) else self.icon


#: NOAA forecast icons carry coverage/intensity suffixes the classic set has no
#: asset for (``tsra_hi,40``, ``tsra_sct,50``, ``nsct`` ...).  Exact tokens are
#: checked first, then these ordered substring rules classify compound tokens
#: onto the nearest available icon.  Order matters (first match wins) and
#: mirrors the legacy cascade: thunder > winter mixes > sleet > dust/smoke >
#: wind > fog > rain > clear/sunny > partly > cloudy.
_ICON_RULES: tuple[_IconRule, ...] = (
    _IconRule("Thunderstorm", any=("tsra", "thunder", "tstm", "tstorm")),
    _IconRule("Heavy-Snow", any=("blizzard",)),
    # Freezing precipitation family (checked before plain snow/sleet).
    _IconRule("Freezing-Rain-Sleet", any=("fzra", "freezing"), all=("sleet",)),
    _IconRule("Freezing-Rain-Snow", any=("fzra", "freezing"), all=("snow",), none=("sleet",)),
    _IconRule("Freezing-Rain", any=("fzra", "freezing"), none=("snow", "sleet")),
    # Snow family (sub-checks keep the original precedence inside the branch).
    _IconRule("Snow-to-Rain", any=("snow",), all=("rain",)),
    _IconRule("Heavy-Snow", any=("snow",), all=("heavy",), none=("rain",)),
    _IconRule("Snow-Sleet", any=("snow",), all=("sleet",), none=("rain", "heavy")),
    _IconRule(
        "Scattered-Snow-Showers",
        any=("shower", "shra"),
        all=("snow",),
        none=("rain", "heavy", "sleet"),
    ),
    _IconRule("Light-Snow", any=("snow",), none=("rain", "heavy", "sleet", "shower", "shra")),
    # Plain sleet / ice-pellet mix.
    _IconRule("Sleet", any=("sleet",)),
    _IconRule("Sleet", exact=("ip", "mix")),
    # Smoke / blowing dust.
    _IconRule("Smoke", any=("smoke", "dust")),
    _IconRule("Smoke", exact=("du", "fu")),
    _IconRule("Windy", any=("wind",)),
    _IconRule("Fog", any=("fog",)),
    _IconRule("Fog", exact=("br",)),
    # Rain family.
    _IconRule("Shower", any=("shower", "shra")),
    _IconRule("Rain", any=("rain",)),
    _IconRule("Rain", exact=("ra",)),
    # Clear/sunny day vs night and the partly/cloudy fallbacks.
    _IconRule("Sunny", night_icon="Clear", exact=("skc", "fair")),
    # NOAA "few" = a few clouds (day "mostly sunny" / night "mostly clear");
    # the classic night glyph shows a moon behind a wisp of cloud.
    _IconRule("Sunny", night_icon="Mostly-Clear", exact=("few",)),
    _IconRule("Sunny", night_icon="Clear", any=("clear", "sunny")),
    _IconRule("Partly-Cloudy", any=("partly", "sct")),
    _IconRule("Cloudy", any=("cloudy",)),
    _IconRule("Cloudy", exact=("bkn", "ovc", "overcast")),
)


def _icon_for_token(token: str, night: bool = False) -> str | None:
    """Classify a NOAA icon token into a named weather icon (or ``None``)."""
    t = token.lower()
    if t in _ICON_NAMES:
        return _ICON_NAMES[t]
    for rule in _ICON_RULES:
        if rule.matches(t):
            return rule.icon_for(night)
    return None


class Renderer:
    """Concrete drawing/data helpers shared by Screens and Components.

    Every method is stateless and reads from the ``ctx`` argument so subclasses
    (Pydantic plugins) never need per-instance bookkeeping for these helpers.
    """

    # -- fonts / colors ---------------------------------------------------

    def font(self, ctx: Any, name: str = "normal") -> pygame.font.Font:
        """Return the named font, or a usable fallback (never ``None``).

        Prefers the named font, then any loaded font in ``ctx.fonts``, then an
        ad-hoc pygame default sized per ``name``.
        """
        fonts = getattr(ctx, "fonts", None)
        if isinstance(fonts, dict):
            found = fonts.get(name)
            if found is not None:
                return found
            if fonts:
                return next(iter(fonts.values()))
        return pygame.font.Font(None, _FONT_SIZES.get(name, 20))

    def color(
        self, ctx: Any, key: str, fallback: tuple[int, int, int] = _WHITE
    ) -> tuple[int, int, int]:
        """Return a theme color by key, or ``fallback`` when missing."""
        colors = getattr(ctx, "colors", None)
        if isinstance(colors, dict):
            return colors.get(key, fallback)
        return fallback

    # -- theme layout tokens -------------------------------------------------

    def layout_token(self, ctx: Any, key: str, default: Any = None) -> Any:
        """Return one per-screen theme layout token (merged defaults) or default."""
        tokens = getattr(ctx, "layout_for", None)
        if tokens is None:
            return default
        return tokens().get(key, default)

    def variant(self, ctx: Any, default: LayoutVariant = LayoutVariant.WS4000) -> LayoutVariant:
        """Which :class:`LayoutVariant` the active theme requests for this screen.

        Resolution order: the per-screen ``variant`` layout token (coerced; an
        unknown value warns and falls back), then the theme's own ``variant``,
        then ``default``.
        """
        theme = getattr(ctx, "theme", None)
        theme_variant = getattr(theme, "variant", None) or default
        token = self.layout_token(ctx, "variant")
        if token is None:
            return theme_variant if isinstance(theme_variant, LayoutVariant) else default
        return coerce_variant(token, fallback=theme_variant, what="variant layout token")

    def text_surface(
        self,
        ctx: Any,
        text: str,
        *,
        font_name: str = "normal",
        color_key: str = "white",
        color: tuple[int, int, int] | None = None,
    ) -> pygame.Surface:
        """Render ``text`` to a surface using a named font and color."""
        fg = color if color is not None else self.color(ctx, color_key)
        return self.font(ctx, font_name).render(text, True, fg)

    def draw_text(
        self,
        surface: pygame.Surface,
        ctx: Any,
        text: str,
        pos,
        *,
        font_name: str = "normal",
        color_key: str = "white",
        color: tuple[int, int, int] | None = None,
    ) -> pygame.Rect:
        """Render ``text`` at ``pos`` honoring theme text-shadow; returns rect."""
        fg = color if color is not None else self.color(ctx, color_key)
        return blit_text_shadowed(surface, ctx, self.font(ctx, font_name), text, fg, pos)

    # -- context / datasource access -------------------------------------

    def datasource(self, ctx: Any, name: str) -> Any:
        """Return a registered datasource by name (strict).

        Screens/components reference datasources through their declared
        ``datasources`` tuples, so a missing name is a programming error: fail
        loudly (KeyError) instead of silently degrading to "no data".
        """
        data = getattr(ctx, "data", None)
        if data is None:
            raise KeyError(f"No datasource registry on ctx; cannot resolve {name!r}.")
        return data.get(name)

    def optional_datasource(self, ctx: Any, name: str) -> Any:
        """Like :meth:`datasource` but returns ``None`` when the name is absent.

        For genuinely optional reads (e.g. the always-on bottom ticker probing
        for weather) where a missing source is a normal condition.
        """
        try:
            return self.datasource(ctx, name)
        except KeyError:
            return None

    def latlon(self, ctx: Any) -> tuple[float, float]:
        """Return the active (lat, lon), or ``(0.0, 0.0)`` when not set."""
        location = getattr(ctx, "location", None)
        if location is None:
            return 0.0, 0.0
        try:
            return float(location.lat), float(location.lon)
        except (AttributeError, TypeError, ValueError):
            return 0.0, 0.0

    # -- layout helpers ---------------------------------------------------

    def wrap(self, font: pygame.font.Font, text: str, max_width: int) -> list[str]:
        """Greedy word-wrap ``text`` into lines no wider than ``max_width`` px."""
        lines: list[str] = []
        current = ""
        for word in str(text).split():
            candidate = f"{current} {word}".strip() if current else word
            if font.size(candidate)[0] > max_width and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

    def centered(
        self,
        surface: pygame.Surface,
        ctx: Any,
        text: str,
        y: int,
        *,
        font_name: str = "small",
        color_key: str = "white",
        center_x: int | None = None,
    ) -> pygame.Rect:
        """Draw ``text`` centered horizontally at height ``y``; return its rect."""
        font = self.font(ctx, font_name)
        fg = self.color(ctx, color_key)
        width = surface.get_width() if center_x is None else 2 * center_x
        # Center on the un-shadowed width; the underlay extends evenly, so
        # centering the glyph itself keeps the label optically centered.
        rect = font.render(text, True, fg).get_rect(center=(width // 2, y))
        return blit_text_shadowed(surface, ctx, font, text, fg, rect)

    # -- value conversions ------------------------------------------------

    def cardinal(self, degrees: float | None, default: str = "") -> str:
        """Compass point for a heading in degrees ('' when unusable)."""
        if degrees is None:
            return default
        try:
            index = int((degrees + 11.25) / 22.5) % 16
            return _CARDINALS[index]
        except (TypeError, ValueError):
            return default

    def format_date(self, date_str: Any, fmt: str = "%a %m/%d") -> str:
        """Format a ``YYYY-MM-DD`` string as a short date; pass through otherwise."""
        if not date_str:
            return ""
        try:
            return datetime.strptime(str(date_str), "%Y-%m-%d").strftime(fmt)
        except (TypeError, ValueError):
            return str(date_str)

    # -- weather data access -------------------------------------------------

    def weather_data(self, ctx: Any, method: str) -> Any:
        """Call ``weather.<method>(lat, lon)`` for the active location.

        Returns whatever the datasource method returns (a typed model, list, or
        ``None``).  Raises if no ``weather`` datasource is registered; weather
        screens declare it via their ``datasources`` tuple.
        """
        ds = self.datasource(ctx, "weather")
        fn = getattr(ds, method, None)
        if fn is None:
            return None
        location = getattr(ctx, "location", None)
        if location is None:
            return None
        return fn(location.lat, location.lon)

    # -- weather icons -----------------------------------------------------

    @staticmethod
    def icon_name(icon_url: str) -> str | None:
        """Map a NOAA icon URL's condition token to a named icon."""
        if not icon_url:
            return None
        parts = icon_url.split("/")
        if len(parts) >= 2:
            token = parts[-1].split("?")[0].split(",")[0]
            night = "night" in parts[-2].lower() if len(parts) >= 2 else False
            return _icon_for_token(token, night=night)
        return None

    def icon_surface(
        self,
        ctx: Any,
        name: str | None,
        width: int | None = None,
        height: int | None = None,
    ) -> Any:
        """Resolve a named weather icon (icon manager, else asset dict)."""
        if not name:
            return None
        try:
            mgr = getattr(ctx, "icon_manager", None)
            if mgr is None:
                mgr = (ctx.assets or {}).get("icon_manager")
            if mgr is not None:
                if width and height:
                    return mgr.get_icon(name, width, height)
                return mgr.get_icon(name)
        except Exception:  # noqa: BLE001 - fall back to asset dict
            pass
        try:
            surface = ((ctx.assets or {}).get("icons") or {}).get(name)
        except AttributeError:
            return None
        if surface is not None and width and height:
            try:
                return pygame.transform.scale(surface, (width, height))
            except Exception:  # noqa: BLE001 - return unscaled
                return surface
        return surface

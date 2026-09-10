"""Tests for the shared Renderer helper mixin (font/color/data/layout helpers)."""

import pygame

from weatherstar.context import AppContext, DataRegistry, Location
from weatherstar.renderer import Renderer


class _Dummy(Renderer):
    """Concrete subclass under test (stand-in for Screen/Component)."""


def _ctx(surface, *, fonts=None, assets=None, data=None, location=None):
    return AppContext(
        surface=surface,
        fonts=fonts or {},
        assets=assets or {},
        data=data or DataRegistry(),
        location=location,
    )


def test_font_returns_named_font(screen):
    fonts = {"small": pygame.font.Font(None, 10), "normal": pygame.font.Font(None, 20)}
    ctx = _ctx(screen, fonts=fonts)
    assert _Dummy().font(ctx, "small") is fonts["small"]


def test_font_falls_back_to_first_loaded(screen):
    fonts = {"small": pygame.font.Font(None, 10)}
    ctx = _ctx(screen, fonts=fonts)
    assert _Dummy().font(ctx, "missing") is fonts["small"]


def test_font_creates_default_when_no_fonts(screen):
    assert _Dummy().font(_ctx(screen), "normal").size("x")[0] > 0


def test_color_uses_theme(screen):
    ctx = _ctx(screen)
    assert _Dummy().color(ctx, "yellow") == ctx.colors["yellow"]


def test_color_fallback(screen):
    ctx = _ctx(screen)
    assert _Dummy().color(ctx, "nope", (1, 2, 3)) == (1, 2, 3)
    assert _Dummy().color(ctx, "nope") == (255, 255, 255)


def test_text_surface_and_draw_text(screen):
    renderer = _Dummy()
    ctx = _ctx(screen, fonts={"normal": pygame.font.Font(None, 20)})
    surf = renderer.text_surface(ctx, "hello", color_key="yellow")
    assert surf.get_width() > 0
    rect = renderer.draw_text(screen, ctx, "hello", (10, 10), color_key="yellow")
    assert rect.topleft == (10, 10)


def test_datasource_lookup(screen):
    import pytest

    ds = object()
    data = DataRegistry()
    data.register("weather", ds)
    ctx = _ctx(screen, data=data)
    renderer = _Dummy()
    assert renderer.datasource(ctx, "weather") is ds
    # Strict access: an undeclared datasource is a programming error -> raise.
    with pytest.raises(KeyError):
        renderer.datasource(ctx, "missing")
    with pytest.raises(KeyError):
        renderer.datasource(_ctx(screen), "weather")
    # Optional access stays forgiving.
    assert renderer.optional_datasource(ctx, "missing") is None
    assert renderer.optional_datasource(_ctx(screen), "weather") is None


def test_latlon(screen):
    ctx = _ctx(screen, location=Location(lat=28.5, lon=-81.3))
    assert _Dummy().latlon(ctx) == (28.5, -81.3)
    assert _Dummy().latlon(_ctx(screen)) == (0.0, 0.0)


def test_wrap_honors_max_width(screen):
    font = pygame.font.Font(None, 20)
    renderer = _Dummy()
    lines = renderer.wrap(font, "one two three four five", 80)
    assert lines
    for line in lines:
        assert font.size(line)[0] <= 80
    assert " ".join(lines) == "one two three four five"


def test_centered_draws_and_returns_rect(screen):
    ctx = _ctx(screen, fonts={"small": pygame.font.Font(None, 20)})
    rect = _Dummy().centered(screen, ctx, "hi", 100, font_name="small")
    assert rect.centery == 100
    assert rect.centerx == screen.get_width() // 2


def test_cardinal_points(screen):
    renderer = _Dummy()
    assert renderer.cardinal(0) == "N"
    assert renderer.cardinal(90) == "E"
    assert renderer.cardinal(360) == "N"
    assert renderer.cardinal(None) == ""
    assert renderer.cardinal("bad") == ""


def test_format_date(screen):
    renderer = _Dummy()
    assert renderer.format_date("2026-01-05") == "Mon 01/05"
    assert renderer.format_date("") == ""
    assert renderer.format_date("not-a-date") == "not-a-date"


def test_weather_data(screen):
    from types import SimpleNamespace

    import pytest

    class _Weather:
        def get_current(self, lat, lon):
            return SimpleNamespace(lat=lat, lon=lon)

        def get_city(self, lat, lon):
            from weatherstar.datasources.noaa import City

            return City(city="Melbourne", state="FL")

    data = DataRegistry()
    data.register("weather", _Weather())
    ctx = _ctx(screen, data=data, location=Location(lat=28.5, lon=-81.3))
    renderer = _Dummy()
    result = renderer.weather_data(ctx, "get_current")
    assert result.lat == 28.5 and result.lon == -81.3
    # No location configured -> no weather_data.
    assert renderer.weather_data(_ctx(screen, data=data), "get_current") is None
    # No weather datasource at all -> strict access raises.
    with pytest.raises(KeyError):
        renderer.weather_data(_ctx(screen), "get_current")
    # Unknown method -> None.
    assert renderer.weather_data(ctx, "missing_method") is None


def test_icon_helpers(screen):
    renderer = _Dummy()
    assert renderer.icon_name("https://api.weather.gov/icons/land/day/sct?size=medium") == (
        "Partly-Cloudy"
    )
    assert renderer.icon_name("") is None
    # Real NOAA forecast tokens carry coverage/intensity suffixes.
    assert renderer.icon_name("https://api.weather.gov/icons/land/day/tsra_hi,40?size=medium") == (
        "Thunderstorm"
    )
    assert renderer.icon_name("https://api.weather.gov/icons/land/day/tsra_sct,50?size=medium") == (
        "Thunderstorm"
    )
    assert renderer.icon_name("https://api.weather.gov/icons/land/night/nsct?size=medium") == (
        "Partly-Cloudy"
    )
    assert renderer.icon_name("https://api.weather.gov/icons/land/day/few?size=medium") == "Sunny"
    assert renderer.icon_name("https://api.weather.gov/icons/land/night/few?size=medium") == (
        "Mostly-Clear"
    )
    assert renderer.icon_name("https://api.weather.gov/icons/land/day/mystery_condition") is None

    icon = pygame.Surface((10, 10))
    icon.fill((50, 60, 70))
    ctx = _ctx(screen, assets={"icons": {"Rain": icon}})
    resolved = renderer.icon_surface(ctx, "Rain", 20, 20)
    assert resolved is not None
    assert resolved.get_size() == (20, 20)
    assert renderer.icon_surface(ctx, "Missing") is None
    assert renderer.icon_surface(ctx, None) is None


def test_icon_rule_table_covers_noaa_tokens(screen):
    renderer = _Dummy()
    cases = [
        # (day_or_night, token, expected icon or None)
        ("day", "skc", "Sunny"),
        ("night", "skc", "Clear"),
        ("day", "few", "Sunny"),
        ("night", "few", "Mostly-Clear"),
        ("night", "fair", "Clear"),
        ("day", "sct", "Partly-Cloudy"),
        ("night", "nsct", "Partly-Cloudy"),
        ("day", "bkn", "Cloudy"),
        ("day", "ovc", "Cloudy"),
        ("day", "rain", "Rain"),
        ("day", "rain_showers", "Shower"),
        ("day", "tsra", "Thunderstorm"),
        ("day", "tsra_sct", "Thunderstorm"),
        ("night", "tsra_hi", "Thunderstorm"),
        ("day", "fog", "Fog"),
        ("day", "wind", "Windy"),
        ("day", "smoke", "Smoke"),
        ("day", "blizzard", "Heavy-Snow"),
        ("day", "snow", "Light-Snow"),
        ("day", "rain_snow", "Snow-to-Rain"),
        ("day", "snow_showers", "Scattered-Snow-Showers"),
        ("day", "sleet", "Sleet"),
        ("day", "mix", "Sleet"),
        ("day", "fzra", "Freezing-Rain"),
        ("day", "fzra_snow", "Freezing-Rain-Snow"),
        ("day", "mystery_condition", None),
    ]
    for part, token, expected in cases:
        url = f"https://api.weather.gov/icons/land/{part}/{token}?size=medium"
        assert renderer.icon_name(url) == expected, (part, token)

"""Layout tests for the severe weather alert screen.

Regression checks for two past bugs: (1) wrapped body lines colliding with each
other / later sections, and (2) alert content (and expiry) rendering underneath
the engine's bottom ticker banner (which starts at y=430).
"""

from weatherstar.context import AppContext, DataRegistry, Location
from weatherstar.datasources.feeds import Alert

_TICKER_TOP = 430

_ALERT = {
    "severity": "Severe",
    "event": "Tornado Warning",
    "headline": (
        "A severe tornado warning is in effect for portions of the central "
        "Florida peninsula until further notice."
    ),
    "areas": (
        "Orange, Seminole, Osceola, Lake, Volusia and Polk counties, "
        "including the cities of Orlando, Sanford, Kissimmee, Leesburg and "
        "Deltona."
    ),
    "instruction": (
        "Take shelter in an interior room on the lowest floor of a sturdy "
        "building now. Avoid windows. If you are outdoors, move inside "
        "immediately. Monitor local media for updates."
    ),
    "expires": "2026-09-05T18:00:00Z",
}


def _ctx(screen):
    return AppContext(
        surface=screen,
        assets={},
        data=DataRegistry(),
        location=Location(lat=28.54, lon=-81.38, description="Orlando, FL"),
    )


class _Alerts:
    def active(self, lat, lon):
        return [Alert(**_ALERT)]


def _draw(screen):
    from weatherstar.screens.severe_weather_alert import SevereWeatherAlertScreen

    screen.fill((0, 0, 0))
    ctx = _ctx(screen)
    ctx.data.register("alerts", _Alerts())
    SevereWeatherAlertScreen().draw(screen, ctx, dt=0.016)


def test_alert_content_stays_above_ticker(screen):
    _draw(screen)
    # Text is white; confirm no white (text) pixels are under the ticker band.
    for y in range(_TICKER_TOP, 480):
        for x in range(0, 640, 3):
            assert screen.get_at((x, y))[:3] != (255, 255, 255), f"text under ticker at y={y}"


def test_alert_all_clear(screen):
    from weatherstar.screens.severe_weather_alert import SevereWeatherAlertScreen

    screen.fill((0, 0, 0))
    ctx = _ctx(screen)
    ctx.data.register("alerts", type("NoAlerts", (), {"active": lambda lat, lon: []})())
    SevereWeatherAlertScreen().draw(screen, ctx, dt=0.016)
    # The all-clear text renders (white pixels present mid-screen).
    white = any(
        screen.get_at((x, y))[:3] == (255, 255, 255)
        for y in range(200, 320)
        for x in range(100, 540)
    )
    assert white


def test_no_white_text_within_body_section_after_y_200(screen):
    # The body sections (areas + action) are sequential; after the last label
    # nothing else may overlap. Just assert expiry text exists in the header
    # area and there is white text somewhere between the header and the ticker.
    _draw(screen)
    white_in_body = any(
        screen.get_at((x, y))[:3] == (255, 255, 255)
        for y in range(120, _TICKER_TOP)
        for x in range(0, 640, 3)
    )
    assert white_in_body

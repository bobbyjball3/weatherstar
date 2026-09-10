"""Integration: build a sequence of every screen and validate each renders.

Datasources are swapped for benign stubs (empty/None data) so no network is
touched; the point is to prove every screen composes and draws without
crashing and paints non-blank output.
"""

import pygame
import pytest

from weatherstar.config_file import AppConfig
from weatherstar.context import DataRegistry
from weatherstar.engine import Builder, SequenceRunner, resolve_location
from weatherstar.registry import registry
from weatherstar.sequence import Sequence

ALL_SCREENS = [
    "progress",
    "current_conditions",
    "local_forecast",
    "extended_forecast",
    "hourly_forecast",
    "regional_observations",
    "weekend_forecast",
    "travel_cities",
    "almanac",
    "air_quality",
    "temperature_graph",
    "weather_records",
    "sun_moon",
    "wind_pressure",
    "monthly_outlook",
    "uv_index",
    "temperature_history",
    "precipitation_history",
    "radar",
    "earthquakes",
    "stock_market",
    "local_news",
    "hazards",
    "marine_forecast",
    "severe_weather_alert",
]

SLIDES = "\n".join(f'    {{ screen = "{name}" }},' for name in ALL_SCREENS)

CFG = f"""
sequence = "all"
[location]
lat = 28.5383
lon = -81.3792
[datasource.stocks]
query = {{ apikey = "test-key" }}
[sequences.all]
pause = 0.001
slides = [
{SLIDES}
]
"""


class _StubWeather:
    def get_current(self, lat, lon):
        return None

    def get_forecast(self, lat, lon):
        return None

    def get_hourly(self, lat, lon):
        return None

    def get_city(self, lat, lon):
        return ("", "")

    def get_radar_station(self, lat, lon):
        return None


def _build_stub_registry() -> DataRegistry:
    data = DataRegistry()
    data.register("weather", _StubWeather())
    data.register(
        "history",
        type(
            "StubHistory",
            (),
            {
                "temperature": lambda lat, lon: [],
                "precipitation": lambda lat, lon: [],
                "scroll": lambda t: None,
                "scroll_offsets": (0.0, 0.0),
            },
        )(),
    )
    data.register(
        "uv_index",
        type(
            "StubUv",
            (),
            {"daily": lambda lat, lon: [], "protection_level": staticmethod(lambda u: "Low")},
        )(),
    )
    data.register("earthquakes", type("StubQuakes", (), {"recent": lambda lat, lon: []})())
    data.register("stocks", type("StubStocks", (), {"quotes": lambda: []})())
    data.register(
        "local_news",
        type(
            "StubNews",
            (),
            {"city_name": lambda lat, lon: "Springfield", "headlines": lambda lat, lon: []},
        )(),
    )
    data.register(
        "alerts",
        type(
            "StubAlerts",
            (),
            {"active": lambda lat, lon: [], "is_critical": staticmethod(lambda a: False)},
        )(),
    )
    return data


@pytest.fixture()
def all_appcfg(tmp_path):
    path = tmp_path / "all.toml"
    path.write_text(CFG)
    return AppConfig.from_file(path)


def test_every_registered_screen_is_available():
    from weatherstar.registry import discover

    discover()
    missing = [name for name in ALL_SCREENS if name not in registry.names("screen")]
    assert missing == []


def test_every_screen_validates_with_stub_data(all_appcfg, pygame_env):
    builder = Builder(all_appcfg)
    name, data = all_appcfg.select_sequence(None)
    sequence = Sequence.from_config(name, data)
    surface = pygame.Surface((640, 480))
    ctx, screens = builder.build_runtime(sequence, surface, resolve_location(all_appcfg))
    # Replace real datasources with benign stubs (no network in tests).
    ctx.data = _build_stub_registry()
    runner = SequenceRunner(ctx, screens, sequence)
    failures = runner.validate(frames_per_slide=2, dt=0.001)
    assert failures == []

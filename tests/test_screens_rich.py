"""Rich-data screen tests.

The empty-stub integration test only exercises each screen's "no data" path.
This suite swaps in datasources returning realistic, populated payloads and
renders every screen so the data-dependent branches execute.  Stubs return the
typed Pydantic models datasources now own as their public contract.
"""

import pygame
import pytest

from weatherstar.config_file import AppConfig
from weatherstar.context import DataRegistry
from weatherstar.datasources.feeds import (
    Alert,
    Earthquake,
    Quote,
    UvReading,
)
from weatherstar.datasources.history import PrecipRow, TemperatureRow
from weatherstar.datasources.news import Headline
from weatherstar.datasources.noaa import (
    City,
    CurrentConditions,
    ForecastPeriod,
    RegionalForecast,
)
from weatherstar.engine import Builder, SequenceRunner, resolve_location
from weatherstar.sequence import Sequence

ALL_SCREENS = [
    "progress",
    "current_conditions",
    "local_forecast",
    "extended_forecast",
    "hourly_forecast",
    "regional_observations",
    "regional_forecast",
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
description = "Orlando, FL"
[datasource.stocks]
query = {{ apikey = "test-key" }}
[sequences.all]
pause = 0.001
slides = [
{SLIDES}
]
"""


def _value(num):
    return {"value": num, "unitCode": "wmoUnit:degC"}


def current_payload(**overrides):
    payload = {
        "station": "KMLB",
        "timestamp": "2026-09-05T18:30:00Z",
        "temperature": _value(30.0),
        "textDescription": "Partly Cloudy",
        "icon": "https://api.weather.gov/icons/land/day/sct?size=medium",
        "relativeHumidity": _value(58.0),
        "dewpoint": _value(20.0),
        "windSpeed": _value(15.0),
        "windDirection": _value(190.0),
        "windGust": _value(28.0),
        "visibility": _value(16000.0),
        "barometricPressure": _value(101500.0),
        "cloudLayers": [{"amount": "BKN", "base": _value(900)}],
        "heatIndex": _value(33.0),
        "windChill": None,
    }
    payload.update(overrides)
    return payload


_PERIOD_NAMES = [
    ("Today", True),
    ("Tonight", False),
    ("Saturday", True),
    ("Saturday Night", False),
    ("Sunday", True),
    ("Sunday Night", False),
    ("Monday", True),
    ("Monday Night", False),
    ("Tuesday", True),
    ("Tuesday Night", False),
    ("Wednesday", True),
    ("Wednesday Night", False),
    ("Thursday", True),
    ("Thursday Night", False),
]


def forecast_periods():
    periods = []
    for name, is_day in _PERIOD_NAMES:
        periods.append(
            ForecastPeriod(
                name=name,
                is_daytime=is_day,
                temperature=96.0 if is_day else 74.0,
                short_forecast="Sunny and hot" if is_day else "Clear",
                detailed_forecast=(
                    "A severe thunderstorm warning is possible late today "
                    "with damaging wind and heavy rain."
                ),
                icon="https://api.weather.gov/icons/land/day/sct?size=medium",
            )
        )
    return periods


def hourly_periods():
    periods = []
    for hour in range(8):
        periods.append(
            ForecastPeriod(
                name=f"{hour} AM",
                start_time=_parse_hour(hour),
                temperature=float(80 + hour),
                short_forecast="Partly cloudy then becoming sunny",
            )
        )
    return periods


def _parse_hour(hour):
    from datetime import datetime

    return datetime.fromisoformat(f"2026-09-05T{hour:02d}:00:00+00:00")


def history_rows(count=12):
    rows = []
    for day in range(count):
        date = f"2026-08-{27 - day:02d}"
        rows.append(TemperatureRow(date=date, high=float(95 - day), low=float(70 + day)))
    return rows


def precip_rows(count=12):
    amounts = [0.0, 0.05, 0.25, 0.6, 0.0, 0.1, 0.75, 0.02, 0.0, 0.4, 1.2, 0.0]
    rows = []
    for day in range(count):
        rows.append(PrecipRow(date=f"2026-08-{27 - day:02d}", inches=amounts[day % len(amounts)]))
    return rows


_REGION_STATIONS = [
    "Melbourne International",
    "Orlando Executive",
    "Vero Beach Municipal",
    "Daytona Beach International",
    "Kissimmee Gateway",
    "Sanford International",
    "Leesburg Municipal",
]


def region_observations():
    rows = []
    for i, name in enumerate(_REGION_STATIONS):
        props = current_payload(
            station=f"KMLB{i:02d}",
            temperature=_value(30.0 - i * 0.7),
            windSpeed=_value(12.0 + i * 3.0),
            windDirection=_value(190.0 + i * 12.0),
            textDescription="Partly Cloudy" if i % 2 == 0 else "Mostly Clear",
        )
        rows.append(CurrentConditions.from_props(props, station_name=name))
    return rows


def region_forecasts():
    rows = []
    for i, name in enumerate(_REGION_STATIONS):
        rows.append(
            RegionalForecast(
                location=name,
                high=float(94 - i),
                low=float(74 - i % 3),
                weather="Partly Cloudy" if i % 2 == 0 else "Mostly Sunny",
            )
        )
    return rows


class _Weather:
    def __init__(self, current=None, forecast=None, hourly=None):
        self.current = current or current_payload()
        self.forecast = forecast if forecast is not None else forecast_periods()
        self.hourly = hourly if hourly is not None else hourly_periods()

    def get_current(self, lat, lon):
        return CurrentConditions.from_props(self.current)

    def get_forecast(self, lat, lon, units="us"):
        return list(self.forecast)

    def get_hourly(self, lat, lon, units="us"):
        return list(self.hourly)

    def get_city(self, lat, lon):
        return City(city="Melbourne", state="FL")

    def get_observations(self, lat, lon, limit=7):
        return region_observations()[:limit]

    def get_regional_forecast(self, lat, lon, limit=7):
        return region_forecasts()[:limit]


class _History:
    def temperature(self, lat, lon):
        return history_rows()

    def precipitation(self, lat, lon):
        return precip_rows()

    def scroll(self, current_time):
        pass

    @property
    def scroll_offsets(self):
        return (60.0, 60.0)


class _Uv:
    def daily(self, lat, lon):
        values = [2.0, 5.0, 7.0, 10.0, 11.0, 3.0, 6.0]
        return [
            UvReading(date=f"2026-09-{day + 1:02d}", uv_index=values[day])
            for day in range(len(values))
        ]

    def protection_level(self, value):
        if value <= 2:
            return "Low"
        if value <= 5:
            return "Moderate"
        if value <= 7:
            return "High"
        if value <= 10:
            return "Very High"
        return "Extreme"


class _Quakes:
    def recent(self, lat, lon):
        from datetime import datetime

        mags = [2.5, 3.5, 4.5, 5.5, 6.5, 4.0, 5.0, 3.0]
        return [
            Earthquake(
                magnitude=mag,
                place="12 km NW of Some City, FL",
                time=datetime.utcfromtimestamp(1700000000 + i * 100),
            )
            for i, mag in enumerate(mags)
        ]


class _Stocks:
    def quotes(self, *args, **kwargs):
        return [
            Quote(symbol="DIA", price=412.50, change=1.25, change_percent=0.3, direction="up"),
            Quote(symbol="SPY", price=556.10, change=-2.00, change_percent=-0.4, direction="down"),
            Quote(symbol="CUSTOM", price=10.00, change=0.0, change_percent=0.0, direction="flat"),
        ]


class _News:
    def city_name(self, lat, lon):
        return ""

    def headlines(self, lat, lon):
        return [
            Headline(
                title="BREAKING: Severe storms possible this evening", url="https://example.com/1"
            ),
            Headline(title="Council votes on budget: final details", url="https://example.com/2"),
            Headline(
                title="Plain headline without a category separator", url="https://example.com/3"
            ),
        ]


class _Alerts:
    def active(self, lat, lon):
        return [
            Alert(
                severity="Severe",
                event="Tornado Warning",
                headline="A tornado warning is in effect until 8 PM for central counties.",
                areas="Orange, Seminole and Lake counties",
                instruction="Move to an interior room on the lowest floor now.",
                expires="2026-09-05T20:00:00Z",
            )
        ]

    def is_critical(self, alerts):
        return True


class _Radar:
    def frames(self, lat, lon):
        frames = []
        for i in range(2):
            surface = pygame.Surface((500, 300))
            surface.fill((20 + i * 30, 60, 100))
            frames.append(surface)
        return frames

    def frame_times(self, lat, lon):
        from datetime import datetime, timedelta, timezone

        base = datetime(2026, 9, 10, 14, 0, tzinfo=timezone.utc)
        return [base + timedelta(minutes=15 * i) for i in range(2)]


def _registry(weather=None) -> DataRegistry:
    data = DataRegistry()
    data.register("weather", weather or _Weather())
    data.register("history", _History())
    data.register("uv_index", _Uv())
    data.register("earthquakes", _Quakes())
    data.register("stocks", _Stocks())
    data.register("local_news", _News())
    data.register("alerts", _Alerts())
    data.register("radar", _Radar())
    return data


@pytest.fixture()
def all_appcfg(tmp_path):
    path = tmp_path / "rich.toml"
    path.write_text(CFG)
    return AppConfig.from_file(path)


def _validate(all_appcfg, registry):
    builder = Builder(all_appcfg)
    name, data = all_appcfg.select_sequence(None)
    sequence = Sequence.from_config(name, data)
    surface = pygame.Surface((640, 480))
    ctx, screens = builder.build_runtime(sequence, surface, resolve_location(all_appcfg))
    ctx.data = registry
    runner = SequenceRunner(ctx, screens, sequence)
    return runner.validate(frames_per_slide=2, dt=0.001)


def test_all_screens_render_with_populated_data(all_appcfg, pygame_env):
    failures = _validate(all_appcfg, _registry())
    assert failures == []


def test_current_conditions_edge_payloads(all_appcfg, pygame_env):
    # Wind gust present / absent, cloud-layer OVC ceiling, short visibility.
    variants = [
        current_payload(),
        current_payload(relativeHumidity=None, dewpoint=None, cloudLayers=[]),
        current_payload(
            windSpeed=_value(0.0),
            windGust=None,
            visibility=_value(8000.0),
            cloudLayers=[{"amount": "OVC", "base": _value(600)}],
            heatIndex=None,
            barometricPressure=None,
            pressure=_value(101400.0),
        ),
        current_payload(
            temperature=_value(2.0),
            windChill=_value(-1.0),
            heatIndex=None,
        ),
    ]
    for current in variants:
        failures = _validate(all_appcfg, _registry(_Weather(current=current)))
        assert failures == []


def test_weekend_periods_capture_sunday_run_by_date():
    """A feed that starts on a Sunday labels it "Today"; date matching still
    finds both weekend columns (Sunday = today, Saturday = next weekend)."""
    from datetime import datetime, timedelta

    from weatherstar.datasources.noaa import ForecastPeriod
    from weatherstar.screens.weekend_forecast import WeekendForecastScreen

    sunday = datetime.fromisoformat("2026-09-06T00:00:00+00:00")
    periods = []
    names = [
        "Today",
        "Tonight",
        "Monday",
        "Monday Night",
        "Tuesday",
        "Tuesday Night",
        "Wednesday",
        "Wednesday Night",
        "Thursday",
        "Thursday Night",
        "Friday",
        "Friday Night",
        "Saturday",
        "Saturday Night",
    ]
    for i, name in enumerate(names):
        start = sunday + timedelta(days=i // 2)
        periods.append(
            ForecastPeriod(
                name=name,
                start_time=start,
                is_daytime=i % 2 == 0,
                temperature=90.0 if i % 2 == 0 else 72.0,
                short_forecast="Sunny" if i % 2 == 0 else "Clear",
                detailed_forecast="Pleasant weather.",
            )
        )
    saturday, this_sunday = WeekendForecastScreen._weekend_periods(periods)
    assert len(saturday) == 2
    assert len(this_sunday) == 2
    assert saturday[0].name == "Saturday"
    assert this_sunday[0].name == "Today"  # Sunday labelled by its date

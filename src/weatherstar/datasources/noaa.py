"""NOAA weather datasource.

Self-contained replacement for the legacy NOAA client.  All HTTP goes through
the base Datasource helpers with TTL caching.

Public data contract (owned by this datasource, not the upstream API): every
fetch method returns typed Pydantic models so consumers never touch raw NOAA
``{"value": ...}`` observation dicts:

- :meth:`NoaaWeather.get_current` -> ``CurrentConditions | None`` (``None`` when
  no observation is available).
- :meth:`NoaaWeather.get_forecast` / :meth:`get_hourly` -> ``list[ForecastPeriod]``
  (empty when nothing is available).

The upstream API's wrapped ``{"value": <float>, "unitCode": ...}`` quantities
are unwrapped and converted into app-useful metric fields; imperial display
helpers are provided as model properties.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from weatherstar.datasources.base import Datasource, coerce_float
from weatherstar.registry import plugin

BASE_URL = "https://api.weather.gov"

# Unit conversions used to build imperial display helpers from metric fields.
_KMH_TO_MPH = 0.621371
_M_TO_MILES = 0.000621371
_M_TO_FT = 3.28084
_PA_TO_INHG = 0.0002953


def _c_to_f_int(celsius: float) -> int:
    return round(celsius * 9 / 5 + 32)


def _noaa_number(props: dict, key: str) -> float | None:
    """Read a NOAA observation quantity (``{"value": ...}`` or bare scalar)."""
    raw = props.get(key)
    return coerce_float(raw.get("value") if isinstance(raw, dict) else raw)


def _parse_time(value: Any) -> datetime | None:
    """Parse an ISO timestamp (``Z`` or numeric offset) to an aware datetime."""
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class CloudLayer(BaseModel):
    """One NOAA cloud-layer entry with a metric base height."""

    model_config = ConfigDict(extra="forbid")

    amount: str = Field(default="", description="Coverage code (BKN, OVC, SCT, ...).")
    base_m: float | None = Field(default=None, description="Cloud base height in meters.")


class CurrentConditions(BaseModel):
    """Typed snapshot of the current observation (see module docstring).

    All numeric quantities are metric (from the upstream API); imperial display
    helpers are provided as ``..._f`` / ``..._mph`` / etc. properties so screens
    never do unit math themselves.
    """

    model_config = ConfigDict(extra="forbid")

    temperature_c: float | None = Field(default=None)
    dewpoint_c: float | None = Field(default=None)
    heat_index_c: float | None = Field(default=None)
    wind_chill_c: float | None = Field(default=None)
    relative_humidity: float | None = Field(default=None, description="Percent.")
    wind_speed_kmh: float | None = Field(default=None)
    wind_gust_kmh: float | None = Field(default=None)
    wind_direction: float | None = Field(default=None, description="Degrees.")
    barometric_pressure_pa: float | None = Field(default=None)
    visibility_m: float | None = Field(default=None)
    cloud_layers: list[CloudLayer] = Field(default_factory=list)
    ceiling_ft: int | None = Field(
        default=None, description="Lowest BKN/OVC layer base in feet, if any."
    )
    text_description: str = Field(default="")
    icon_url: str = Field(default="")
    station: str = Field(default="")
    station_name: str = Field(default="", description="Display name of the station.")
    timestamp: str = Field(default="")

    # -- imperial display helpers ------------------------------------------

    @property
    def temperature_f(self) -> int | None:
        if self.temperature_c is None:
            return None
        return _c_to_f_int(self.temperature_c)

    @property
    def dewpoint_f(self) -> int | None:
        if self.dewpoint_c is None:
            return None
        return _c_to_f_int(self.dewpoint_c)

    @property
    def heat_index_f(self) -> int | None:
        if self.heat_index_c is None:
            return None
        return _c_to_f_int(self.heat_index_c)

    @property
    def wind_chill_f(self) -> int | None:
        if self.wind_chill_c is None:
            return None
        return _c_to_f_int(self.wind_chill_c)

    @property
    def wind_mph(self) -> int | None:
        if self.wind_speed_kmh is None:
            return None
        return int(self.wind_speed_kmh * _KMH_TO_MPH)

    @property
    def wind_gust_mph(self) -> int | None:
        if self.wind_gust_kmh is None:
            return None
        return int(self.wind_gust_kmh * _KMH_TO_MPH)

    @property
    def pressure_inhg(self) -> float | None:
        if self.barometric_pressure_pa is None:
            return None
        return self.barometric_pressure_pa * _PA_TO_INHG

    @property
    def visibility_miles(self) -> float | None:
        if self.visibility_m is None:
            return None
        return self.visibility_m * _M_TO_MILES

    # -- observation rows (label/value display strings) ---------------------

    def observation_rows(self, pressure_trend: str = "") -> list[tuple[str, str]]:
        """Formatted ``(label, value)`` observation rows for the current screen.

        Centralizes the ceiling/visibility/pressure and heat-index/wind-chill
        presentation decisions so ``compose`` only places the returned strings.
        ``pressure_trend`` is the ephemeral trend glyph (drawn by the screen
        from its own short pressure history) appended to the pressure value.
        """
        degree = "\N{DEGREE SIGN}"
        rows: list[tuple[str, str]] = []
        if self.relative_humidity is not None:
            rows.append(("Humidity:", f"{int(self.relative_humidity)}%"))
        if self.dewpoint_f is not None:
            rows.append(("Dewpoint:", f"{self.dewpoint_f}{degree}"))
        if self.ceiling_ft:
            rows.append(("Ceiling:", f"{self.ceiling_ft} ft"))
        else:
            rows.append(("Ceiling:", "Unlimited"))
        if self.visibility_miles is not None:
            miles = self.visibility_miles
            rows.append(("Visibility:", "10 mi" if miles >= 10 else f"{miles:.1f} mi"))
        if self.pressure_inhg is not None:
            rows.append(("Pressure:", f'{self.pressure_inhg:.2f}" {pressure_trend}'.strip()))
        if (
            self.heat_index_f is not None
            and self.temperature_c is not None
            and self.temperature_c > 26
        ):
            rows.append(("Heat Index:", f"{self.heat_index_f}{degree}"))
        elif (
            self.wind_chill_f is not None
            and self.temperature_c is not None
            and self.temperature_c < 10
        ):
            rows.append(("Wind Chill:", f"{self.wind_chill_f}{degree}"))
        return rows

    # -- construction -------------------------------------------------------

    @classmethod
    def from_props(cls, props: dict, station_name: str = "") -> CurrentConditions:
        """Build from a NOAA observation ``properties`` dict."""
        ceiling_ft: int | None = None
        cloud_layers: list[CloudLayer] = []
        for raw in props.get("cloudLayers") or []:
            amount = str(raw.get("amount") or "")
            base_m = _noaa_number(raw, "base")
            cloud_layers.append(CloudLayer(amount=amount, base_m=base_m))
            if ceiling_ft is None and amount in ("BKN", "OVC") and base_m is not None:
                ceiling_ft = int(base_m * _M_TO_FT)

        pressure = _noaa_number(props, "barometricPressure")
        if pressure is None:
            pressure = _noaa_number(props, "pressure")

        station = str(props.get("station") or "")
        if "/stations/" in station:
            station = station.split("/stations/", 1)[1].rstrip("/").split("/")[-1]

        return cls(
            temperature_c=_noaa_number(props, "temperature"),
            dewpoint_c=_noaa_number(props, "dewpoint"),
            heat_index_c=_noaa_number(props, "heatIndex"),
            wind_chill_c=_noaa_number(props, "windChill"),
            relative_humidity=_noaa_number(props, "relativeHumidity"),
            wind_speed_kmh=_noaa_number(props, "windSpeed"),
            wind_gust_kmh=_noaa_number(props, "windGust"),
            wind_direction=_noaa_number(props, "windDirection"),
            barometric_pressure_pa=pressure,
            visibility_m=_noaa_number(props, "visibility"),
            cloud_layers=cloud_layers,
            ceiling_ft=ceiling_ft,
            text_description=str(props.get("textDescription") or ""),
            icon_url=str(props.get("icon") or ""),
            station=station,
            station_name=station_name,
            timestamp=str(props.get("timestamp") or ""),
        )


class ForecastPeriod(BaseModel):
    """One NOAA forecast/day or hourly period (see module docstring).

    ``temperature`` is the value NOAA reports for the requested units (the app
    renders the default ``us`` forecast, so this is °F).  ``start_time`` is an
    aware datetime parsed from the ISO ``startTime``.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="")
    start_time: datetime | None = Field(default=None)
    is_daytime: bool = Field(default=False)
    temperature: float | None = Field(default=None)
    short_forecast: str = Field(default="")
    detailed_forecast: str = Field(default="")
    icon: str = Field(default="")

    # -- calendar helpers ---------------------------------------------------

    def start_date(self) -> date | None:
        """Local calendar date this period starts on (``None`` when unknown)."""
        if self.start_time is None:
            return None
        return self.start_time.date()

    def weekday_abbrev(self, fallback: date | None = None) -> str:
        """Abbreviated weekday (``SAT``) for this period.

        Derives from ``start_time`` when present (the reliable source), then from
        a weekday name embedded in ``name`` (NOAA drops the weekday for labels
        like "Tonight"/"Labor Day"), then ``fallback`` or today.
        """
        start = self.start_date()
        if start is not None:
            return calendar.day_abbr[start.weekday()].upper()
        name = self.name.lower()
        for index, day in enumerate(calendar.day_name):
            if day.lower() in name:
                return calendar.day_abbr[index].upper()
        chosen = fallback or date.today()
        return calendar.day_abbr[chosen.weekday()].upper()

    # -- construction -------------------------------------------------------

    @classmethod
    def from_props(cls, props: dict) -> ForecastPeriod:
        """Build from a NOAA forecast period dict."""
        return cls(
            name=str(props.get("name") or ""),
            start_time=_parse_time(props.get("startTime")),
            is_daytime=bool(props.get("isDaytime")),
            temperature=coerce_float(props.get("temperature")),
            short_forecast=str(props.get("shortForecast") or ""),
            detailed_forecast=str(props.get("detailedForecast") or ""),
            icon=str(props.get("icon") or ""),
        )


class City(BaseModel):
    """Resolved city/state label for a coordinate (empty strings when unknown)."""

    model_config = ConfigDict(extra="forbid")

    city: str = Field(default="")
    state: str = Field(default="")

    @property
    def label(self) -> str:
        """``"City, ST"`` when both known, else whichever part is present."""
        if self.city and self.state:
            return f"{self.city}, {self.state}"
        return self.city or self.state


class RegionalForecast(BaseModel):
    """One nearby-city row for the regional forecast screen (see module docstring).

    ``location`` is the cleaned display name of a nearby station/city; ``high``
    / ``low`` come from that place's gridpoint forecast (today's daytime high
    and the adjacent night low); ``weather`` is the daytime short condition.
    """

    model_config = ConfigDict(extra="forbid")

    location: str = Field(default="")
    high: float | None = Field(default=None)
    low: float | None = Field(default=None)
    weather: str = Field(default="")

    @property
    def high_f(self) -> int | None:
        return None if self.high is None else int(round(self.high))

    @property
    def low_f(self) -> int | None:
        return None if self.low is None else int(round(self.low))


#: Common trailing tokens stripped from NOAA station display names so regional
#: tables read as place names ("Orlando Executive Airport" -> "ORLANDO
#: EXECUTIVE"), longest first so partial suffixes never truncate first.
_STATION_SUFFIXES = (
    " international airport",
    " regional airport",
    " municipal airport",
    " executive airport",
    " downtown airport",
    " naval air station",
    " air reserve station",
    " air force base",
    " memorial airport",
    " international",
    " regional",
    " municipal",
    " airport",
    " airpark",
    " heliport",
    " annex",
)


def clean_station_name(name: str) -> str:
    """Trim a NOAA station name down to a place label for regional tables."""
    text = " ".join(str(name or "").split())
    lowered = text.lower()
    for suffix in _STATION_SUFFIXES:
        if lowered.endswith(suffix):
            text = text[: len(text) - len(suffix)]
            break
    return text.strip()


def _build_regional_row(location: str, periods: list[ForecastPeriod]) -> RegionalForecast | None:
    """One regional-forecast row from a gridpoint forecast's periods.

    High is the first daytime period's temperature and the low is that period's
    adjacent night period (mirroring ws3kp's buildForecast).
    """
    if not location:
        return None
    first_daytime = next((i for i, p in enumerate(periods) if p.is_daytime), None)
    if first_daytime is None:
        return None
    day = periods[first_daytime]
    night = periods[first_daytime + 1] if first_daytime + 1 < len(periods) else None
    return RegionalForecast(
        location=location,
        high=day.temperature if day.temperature is not None else None,
        low=night.temperature if night is not None else None,
        weather=day.short_forecast or "",
    )


#: How many nearby stations ``get_current`` scans for a usable observation.
_CURRENT_STATION_SCAN = 8


@plugin
class NoaaWeather(Datasource):
    name = "weather"

    _default_cache_ttl: ClassVar[int] = 300

    _grid_cache: dict[str, dict[str, Any]] = PrivateAttr(default_factory=dict)

    # -- grid point ----------------------------------------------------------

    def _cache_key_for(self, *parts: Any) -> str:
        return super()._cache_key("noaa", *parts)

    def get_point(self, lat: float, lon: float) -> dict | None:
        key = self._cache_key_for("point", lat, lon)
        cached = self.cache_get(key, 3600)
        if cached is not None:
            return cached
        url = f"{BASE_URL}/points/{lat:.4f},{lon:.4f}"
        data = self.http_get_json(url)
        if not data:
            return None
        props = data["properties"]
        self.cache_set(key, props)
        return props

    def _station_features(self, lat: float, lon: float) -> list[dict[str, str]]:
        """Nearby observation stations as ``[{"id", "name"}]``, nearest first.

        Prefers 4-letter identifiers that don't start with U/C (kept for
        compatibility with the historic ``_observation_stations`` order), but
        also carries each station's display name for the regional tables.
        """
        point = self.get_point(lat, lon)
        if not point:
            return []
        stations_url = point.get("observationStations")
        if not stations_url:
            return []
        key = self._cache_key_for("stations", stations_url)
        cached = self.cache_get(key, 3600)
        if cached is not None:
            return cached
        data = self.http_get_json(stations_url)
        features: list[dict[str, str]] = []
        if data:
            for feature in data["features"]:
                props = feature["properties"]
                features.append(
                    {
                        "id": props["stationIdentifier"],
                        "name": clean_station_name(props.get("name") or ""),
                    }
                )
            preferred = [f for f in features if len(f["id"]) == 4 and f["id"][0] not in "UC"]
            if preferred:
                features = preferred + [f for f in features if f not in preferred]
        self.cache_set(key, features)
        return features

    def _observation_stations(self, lat: float, lon: float) -> list[str]:
        return [feature["id"] for feature in self._station_features(lat, lon)]

    def _station(self, lat: float, lon: float) -> str | None:
        features = self._station_features(lat, lon)
        return features[0]["id"] if features else None

    # -- typed fetches ---------------------------------------------------------

    def _latest_observation(
        self, station_id: str, station_name: str = ""
    ) -> CurrentConditions | None:
        """Latest observation model for one station (cached by station)."""
        key = self._cache_key_for("current", station_id)
        cached = self.cache_get(key, 300)
        if cached is not None:
            return cached
        url = f"{BASE_URL}/stations/{station_id}/observations/latest"
        props = (self.http_get_json(url) or {}).get("properties")
        if not props:
            return None
        observation = CurrentConditions.from_props(props, station_name=station_name)
        self.cache_set(key, observation)
        return observation

    def get_current(self, lat: float, lon: float) -> CurrentConditions | None:
        """Latest observation for the nearest *usable* station.

        Some nearby automated stations report only a partial observation (e.g. a
        temperature but no ``textDescription`` or ``icon``), which would leave
        the Current Conditions screen with a temperature and nothing else.
        Scan the nearest stations in preference order and return the first
        observation with both a temperature and a usable text/icon; fall back to
        the nearest observation with a temperature, then to ``None``.
        """
        features = self._station_features(lat, lon)[:_CURRENT_STATION_SCAN]
        if not features:
            return None
        first_with_temp: CurrentConditions | None = None
        for feature in features:
            observation = self._latest_observation(feature["id"], feature.get("name", ""))
            if observation is None or observation.temperature_c is None:
                continue
            if first_with_temp is None:
                first_with_temp = observation
            if observation.text_description or observation.icon_url:
                return observation
        return first_with_temp

    def get_observations(self, lat: float, lon: float, limit: int = 7) -> list[CurrentConditions]:
        """Current conditions for the nearest observation stations.

        Skips stations without a usable temperature; at most ``limit`` rows are
        returned so the "Latest Hourly Observations" table fits the screen.
        """
        rows: list[CurrentConditions] = []
        for feature in self._station_features(lat, lon):
            if len(rows) >= limit:
                break
            observation = self._latest_observation(feature["id"], feature.get("name", ""))
            if observation is None or observation.temperature_c is None:
                continue
            rows.append(observation)
        return rows

    def _grid(self, lat: float, lon: float) -> tuple[str, int, int] | None:
        point = self.get_point(lat, lon)
        if not point:
            return None
        office = point.get("gridId")
        grid_x = point.get("gridX")
        grid_y = point.get("gridY")
        if not office or grid_x is None or grid_y is None:
            return None
        return office, int(grid_x), int(grid_y)

    def _periods(
        self,
        lat: float,
        lon: float,
        path: str,
        *,
        units: str,
        cache_ttl: int,
    ) -> list[ForecastPeriod]:
        """Fetch ``path`` forecast props and parse into period models."""
        grid = self._grid(lat, lon)
        if not grid:
            return []
        office, grid_x, grid_y = grid
        key = self._cache_key_for(path, office, grid_x, grid_y, units)
        cached = self.cache_get(key, cache_ttl)
        if cached is not None:
            return cached
        url = f"{BASE_URL}/gridpoints/{office}/{grid_x},{grid_y}/{path}"
        data = self.http_get_json(url, params={"units": units}) or {}
        periods = [
            ForecastPeriod.from_props(raw)
            for raw in data.get("properties", {}).get("periods") or []
        ]
        self.cache_set(key, periods)
        return periods

    def get_forecast(self, lat: float, lon: float, units: str = "us") -> list[ForecastPeriod]:
        return self._periods(lat, lon, "forecast", units=units, cache_ttl=1800)

    def get_hourly(self, lat: float, lon: float, units: str = "us") -> list[ForecastPeriod]:
        return self._periods(lat, lon, "forecast/hourly", units=units, cache_ttl=1800)

    # -- regional tables ---------------------------------------------------------

    def _station_meta(self, station_id: str) -> dict:
        """Full station JSON (top-level ``geometry`` + ``properties``)."""
        key = self._cache_key_for("station_meta", station_id)
        cached = self.cache_get(key, 3600)
        if cached is not None:
            return cached
        data = self.http_get_json(f"{BASE_URL}/stations/{station_id}")
        payload = data or {}
        self.cache_set(key, payload)
        return payload

    def _station_forecast_url(self, station_id: str) -> str | None:
        """Gridpoint forecast URL for one station, or ``None``.

        Station metadata's ``forecast`` link is not always a gridpoint forecast
        (it can point at a zone *text* product that rejects ``units`` and has no
        day/night periods).  Resolve the station's own coordinates (root-level
        GeoJSON ``geometry``) to a point and use that point's gridpoint forecast
        URL; only trust a metadata link that already looks like a gridpoint
        forecast.
        """
        meta = self._station_meta(station_id)
        if not meta:
            return None
        coords = (meta.get("geometry") or {}).get("coordinates") or []
        if len(coords) >= 2:
            point = self.get_point(coords[1], coords[0])
            forecast = (point or {}).get("forecast")
            if forecast:
                return forecast
        forecast = (meta.get("properties") or {}).get("forecast") or ""
        return forecast if "/gridpoints/" in forecast else None

    def _gridpoint_periods(self, forecast_url: str) -> list[ForecastPeriod]:
        """Parse ``periods`` from an explicit gridpoint forecast URL."""
        key = self._cache_key_for("regional_forecast", forecast_url)
        cached = self.cache_get(key, 1800)
        if cached is not None:
            return cached
        data = self.http_get_json(forecast_url, params={"units": "us"}) or {}
        periods = [
            ForecastPeriod.from_props(raw)
            for raw in data.get("properties", {}).get("periods") or []
        ]
        self.cache_set(key, periods)
        return periods

    def get_regional_forecast(
        self, lat: float, lon: float, limit: int = 7
    ) -> list[RegionalForecast]:
        """Today's hi/lo outlook for the nearest stations across the region.

        Each row is built from that station's own gridpoint forecast (the
        daytime high plus the adjacent night low), so nearby places can differ.
        At most ``limit`` rows are returned.
        """
        rows: list[RegionalForecast] = []
        for feature in self._station_features(lat, lon):
            if len(rows) >= limit:
                break
            forecast_url = self._station_forecast_url(feature["id"])
            if not forecast_url:
                continue
            periods = self._gridpoint_periods(forecast_url)
            row = _build_regional_row(feature.get("name", ""), periods)
            if row is not None:
                rows.append(row)
        return rows

    # -- location info ---------------------------------------------------------

    def get_city(self, lat: float, lon: float) -> City:
        """Return the city/state for a point, or an empty ``City`` when unknown."""
        point = self.get_point(lat, lon)
        if not point:
            return City()
        rel = point.get("relativeLocation") or {}
        props = rel.get("properties") or {}
        return City(city=str(props.get("city") or ""), state=str(props.get("state") or ""))

    def get_radar_station(self, lat: float, lon: float) -> str | None:
        return (self.get_point(lat, lon) or {}).get("radarStation")

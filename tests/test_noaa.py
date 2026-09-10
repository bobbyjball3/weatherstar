"""Tests for the NOAA weather datasource (grid/stations/observations/forecast)."""

import httpx

from weatherstar.datasources.noaa import NoaaWeather

BASE = "https://api.weather.gov"

POINT_URL = f"{BASE}/points/28.5383,-81.3792"
STATIONS_URL = f"{BASE}/stations"
STATION = "KMLB"


def _point() -> dict:
    return {
        "properties": {
            "observationStations": STATIONS_URL,
            "gridId": "MLB",
            "gridX": 45,
            "gridY": 32,
            "relativeLocation": {"properties": {"city": "Melbourne", "state": "FL"}},
            "radarStation": "KMLB",
        }
    }


def _stations() -> dict:
    return {
        "features": [
            {"properties": {"stationIdentifier": STATION}},
            {"properties": {"stationIdentifier": "CIVT"}},
            {"properties": {"stationIdentifier": "KLONG"}},
        ]
    }


def _props() -> dict:
    return {"temperature": {"value": 25.0}, "textDescription": "Fair"}


def _router(*, point=_point(), stations=_stations(), props=_props(), forecast=None):
    """Return an HTTP handler keyed by URL."""
    calls = []

    def handler(request):
        url = str(request.url)
        calls.append(url)
        if url == POINT_URL:
            return httpx.Response(200, json=point)
        if url == STATIONS_URL:
            return httpx.Response(200, json=stations)
        if url == f"{BASE}/stations/{STATION}/observations/latest":
            return httpx.Response(200, json={"properties": props})
        if "forecast/hourly" in url:
            return httpx.Response(200, json={"properties": forecast or {"periods": []}})
        if "forecast" in url:
            return httpx.Response(200, json={"properties": forecast or {"periods": []}})
        return httpx.Response(404)

    handler.calls = calls
    return handler


def _ds(monkeypatch, handler) -> NoaaWeather:
    ds = NoaaWeather()
    ds._client = httpx.Client(transport=httpx.MockTransport(handler))
    return ds


def test_get_point_success_and_cache(monkeypatch):
    fake = _router()
    ds = _ds(monkeypatch, fake)
    first = ds.get_point(28.5383, -81.3792)
    second = ds.get_point(28.5383, -81.3792)
    assert first["gridId"] == "MLB"
    assert first is second  # served from cache
    assert fake.calls.count(POINT_URL) == 1


def test_get_point_none_without_properties(monkeypatch):
    ds = _ds(monkeypatch, _router(point={"properties": {}}))
    assert ds.get_point(28.5383, -81.3792) == {}  # empty props cached
    ds2 = _ds(monkeypatch, _router(point=None))
    assert ds2.get_point(28.5383, -81.3792) is None


def test_observation_stations_prefers_4letter_non_uc(monkeypatch):
    fake = _router()
    ds = _ds(monkeypatch, fake)
    stations = ds._observation_stations(28.5383, -81.3792)
    # KMLB (4-letter, not U/C) is moved ahead of the others.
    assert stations[0] == STATION
    assert "CIVT" in stations and "KLONG" in stations


def test_station_none_when_no_stations(monkeypatch):
    fake = _router(stations={"features": []})
    ds = _ds(monkeypatch, fake)
    assert ds._station(28.5383, -81.3792) is None


def test_get_current_returns_and_caches(monkeypatch):
    fake = _router()
    ds = _ds(monkeypatch, fake)
    current = ds.get_current(28.5383, -81.3792)
    assert current.temperature_c == 25.0
    assert current.text_description == "Fair"
    ds.get_current(28.5383, -81.3792)
    # The observation HTTP is served from the transparent fetch cache.
    assert fake.calls.count(f"{BASE}/stations/{STATION}/observations/latest") == 1


def test_get_current_none_when_station_missing(monkeypatch):
    fake = _router(stations={"features": []})
    ds = _ds(monkeypatch, fake)
    assert ds.get_current(28.5383, -81.3792) is None


def _two_station_router(first_props, second_props):
    """Router with two stations (KMLB nearest, KXMR next) of given observations."""
    calls = []

    def handler(request):
        url = str(request.url)
        calls.append(url)
        if url == POINT_URL:
            return httpx.Response(200, json=_point())
        if url == STATIONS_URL:
            return httpx.Response(
                200,
                json={
                    "features": [
                        {
                            "properties": {
                                "stationIdentifier": "KMLB",
                                "name": "Melbourne International Airport",
                            }
                        },
                        {
                            "properties": {
                                "stationIdentifier": "KXMR",
                                "name": "Patrick Space Force Base",
                            }
                        },
                    ]
                },
            )
        if url == f"{BASE}/stations/KMLB/observations/latest":
            return httpx.Response(200, json={"properties": first_props})
        if url == f"{BASE}/stations/KXMR/observations/latest":
            return httpx.Response(200, json={"properties": second_props})
        return httpx.Response(404)

    handler.calls = calls
    return handler


def test_get_current_skips_sparse_station_for_fuller_one(monkeypatch):
    # The nearest station reports only a temperature (no text/icon) - the kind
    # of partial ASOS observation that leaves the screen without an icon.  The
    # scan should fall through to the next station with a full observation.
    sparse = {"temperature": {"value": 24.0}}
    ds = _ds(monkeypatch, _two_station_router(sparse, _props()))
    current = ds.get_current(28.5383, -81.3792)
    assert current.station_name == "Patrick Space Force Base"
    assert current.text_description == "Fair"


def test_get_current_keeps_nearest_when_all_stations_sparse(monkeypatch):
    sparse_near = {"temperature": {"value": 24.0}}
    sparse_far = {"temperature": {"value": 22.0}}
    ds = _ds(monkeypatch, _two_station_router(sparse_near, sparse_far))
    current = ds.get_current(28.5383, -81.3792)
    assert current.station_name == "Melbourne"
    assert current.temperature_c == 24.0


def test_get_forecast_success_and_caches(monkeypatch):
    periods = {"periods": [{"name": "Today", "temperature": 90}]}
    fake = _router(forecast=periods)
    ds = _ds(monkeypatch, fake)
    forecast = ds.get_forecast(28.5383, -81.3792)
    assert len(forecast) == 1
    assert forecast[0].name == "Today"
    assert forecast[0].temperature == 90.0
    # A different units value uses a different cache key -> another fetch.
    ds.get_forecast(28.5383, -81.3792, units="si")
    forecast_fetches = [u for u in fake.calls if "forecast" in u and "hourly" not in u]
    assert len(forecast_fetches) == 2
    # Same key is cached -> no additional fetch.
    ds.get_forecast(28.5383, -81.3792)
    forecast_fetches = [u for u in fake.calls if "forecast" in u and "hourly" not in u]
    assert len(forecast_fetches) == 2


def test_get_hourly_success(monkeypatch):
    periods = {"periods": [{"startTime": "2026-09-05T12:00:00Z"}]}
    fake = _router(forecast=periods)
    ds = _ds(monkeypatch, fake)
    hourly = ds.get_hourly(28.5383, -81.3792)
    assert len(hourly) == 1
    assert hourly[0].start_time is not None
    assert hourly[0].start_time.hour == 12


def test_grid_missing_returns_empty_for_forecast(monkeypatch):
    ds = _ds(monkeypatch, _router(point={"properties": {"observationStations": STATIONS_URL}}))
    assert ds.get_forecast(28.5383, -81.3792) == []
    assert ds.get_hourly(28.5383, -81.3792) == []


def test_get_city_and_missing_point(monkeypatch):
    ds = _ds(monkeypatch, _router())
    city = ds.get_city(28.5383, -81.3792)
    assert (city.city, city.state) == ("Melbourne", "FL")
    ds2 = _ds(monkeypatch, _router(point=None))
    assert ds2.get_city(28.5383, -81.3792).label == ""


def test_get_radar_station(monkeypatch):
    ds = _ds(monkeypatch, _router())
    assert ds.get_radar_station(28.5383, -81.3792) == "KMLB"
    ds2 = _ds(monkeypatch, _router(point=None))
    assert ds2.get_radar_station(28.5383, -81.3792) is None


def _region_router(*, props_per_station=None, forecast_per_station=None):
    """Router that serves regional observation/forecast endpoints for two stations."""
    calls = []

    def handler(request):
        url = str(request.url)
        calls.append(url)
        if url == POINT_URL:
            return httpx.Response(200, json=_point())
        if url == STATIONS_URL:
            return httpx.Response(
                200,
                json={
                    "features": [
                        {
                            "properties": {
                                "stationIdentifier": "KMLB",
                                "name": "Melbourne International Airport",
                            }
                        },
                        {
                            "properties": {
                                "stationIdentifier": "KXMR",
                                "name": "Patrick Space Force Base",
                            }
                        },
                    ]
                },
            )
        if url == f"{BASE}/stations/KMLB":
            return httpx.Response(
                200, json={"properties": {"forecast": f"{BASE}/gridpoints/MLB/45,32/forecast"}}
            )
        if url == f"{BASE}/stations/KXMR":
            return httpx.Response(
                200, json={"properties": {"forecast": f"{BASE}/gridpoints/MLB/44,32/forecast"}}
            )
        if url == f"{BASE}/stations/KMLB/observations/latest":
            return httpx.Response(200, json={"properties": props_per_station or _props()})
        if url == f"{BASE}/stations/KXMR/observations/latest":
            return httpx.Response(200, json={"properties": _props()})
        if "gridpoints" in url:
            props = forecast_per_station or {
                "periods": [
                    {
                        "name": "Today",
                        "isDaytime": True,
                        "temperature": 92,
                        "shortForecast": "Sunny",
                    },
                    {"name": "Tonight", "isDaytime": False, "temperature": 72},
                ]
            }
            return httpx.Response(200, json={"properties": props})
        return httpx.Response(404)

    handler.calls = calls
    return handler


def test_get_observations_multiple_stations(monkeypatch):
    ds = _ds(monkeypatch, _region_router())
    rows = ds.get_observations(28.5383, -81.3792)
    assert len(rows) == 2
    assert rows[0].station_name == "Melbourne"  # cleaned of "International Airport"
    assert rows[1].station_name == "Patrick Space Force Base"
    assert rows[0].temperature_c == 25.0


def test_get_observations_skips_stations_without_temperature(monkeypatch):
    bad = {"properties": {"temperature": {"value": None}, "textDescription": ""}}
    ds = _ds(monkeypatch, _region_router(props_per_station=bad))
    rows = ds.get_observations(28.5383, -81.3792)
    assert len(rows) == 1


def test_get_regional_forecast_rows(monkeypatch):
    ds = _ds(monkeypatch, _region_router())
    rows = ds.get_regional_forecast(28.5383, -81.3792)
    assert len(rows) == 2
    assert rows[0].location == "Melbourne"
    assert rows[0].high == 92.0
    assert rows[0].low == 72.0
    assert rows[0].weather == "Sunny"


def test_regional_forecast_ignores_zone_text_forecast_urls(monkeypatch):
    """Station metadata can link to a zone *text* product (no periods, rejects
    units). The datasource must resolve the station's gridpoint forecast instead
    of fetching that zone URL (which 400s and spams warnings)."""
    calls = []

    def fake(request):
        url = str(request.url)
        calls.append(url)
        if url == POINT_URL:
            return httpx.Response(200, json=_point())
        if url == STATIONS_URL:
            return httpx.Response(
                200,
                json={
                    "features": [
                        {
                            "properties": {
                                "stationIdentifier": "KMLB",
                                "name": "Melbourne International Airport",
                            }
                        }
                    ]
                },
            )
        if url == f"{BASE}/stations/KMLB":
            return httpx.Response(
                200,
                json={
                    "geometry": {"type": "Point", "coordinates": [-80.6, 28.1]},
                    "properties": {
                        # Some stations advertise their *zone* here; it has no periods.
                        "forecast": f"{BASE}/zones/forecast/INZ037",
                    },
                },
            )
        if url == f"{BASE}/points/28.1000,-80.6000":
            return httpx.Response(
                200, json={"properties": {"forecast": f"{BASE}/gridpoints/MLB/45,32/forecast"}}
            )
        if "gridpoints" in url:
            return httpx.Response(
                200,
                json={
                    "properties": {
                        "periods": [
                            {
                                "name": "Today",
                                "isDaytime": True,
                                "temperature": 90,
                                "shortForecast": "Sunny",
                            },
                            {"name": "Tonight", "isDaytime": False, "temperature": 70},
                        ]
                    }
                },
            )
        return httpx.Response(404)

    ds = _ds(monkeypatch, fake)
    rows = ds.get_regional_forecast(28.5383, -81.3792)
    assert len(rows) == 1
    assert rows[0].high == 90.0
    # The zone text endpoint is never fetched.
    assert not any("zones/" in url for url in calls)

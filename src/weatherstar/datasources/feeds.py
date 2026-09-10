"""Datasources for live secondary feeds: alerts, earthquakes, UV, stocks.

Each datasource owns its public data contract: fetch methods return lists of
typed Pydantic models (empty list when nothing is available) so consumers never
touch the raw upstream payloads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from weatherstar.datasources.base import Datasource, coerce_float
from weatherstar.registry import plugin

NOAA_ALERTS_URL = "https://api.weather.gov/alerts/active"
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
OM_UV_URL = "https://api.open-meteo.com/v1/forecast"


class Alert(BaseModel):
    """An active NOAA alert, normalized to the fields the app displays."""

    model_config = ConfigDict(extra="forbid")

    severity: str = Field(default="", description="Capitalized severity (Extreme/Severe/Moderate).")
    event: str = Field(default="")
    headline: str = Field(default="")
    areas: str = Field(default="")
    instruction: str = Field(default="")
    expires: str = Field(default="", description="ISO expiry timestamp.")
    urgency: str = Field(default="")
    description: str = Field(default="")


class Earthquake(BaseModel):
    """A recent earthquake event."""

    model_config = ConfigDict(extra="forbid")

    magnitude: float = Field(default=0.0)
    place: str = Field(default="")
    time: datetime | None = Field(default=None, description="UTC occurrence time.")


#: Classic Weather Star display names for the default market symbols.
_QUOTE_DISPLAY_NAMES = {
    "DIA": "DOW JONES",
    "SPY": "S&P 500",
    "QQQ": "NASDAQ",
}


class Quote(BaseModel):
    """A stock/index quote with a semantic direction for coloring."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(default="")
    price: float | None = Field(default=None)
    change: float | None = Field(default=None)
    change_percent: float | None = Field(default=None)
    direction: Literal["up", "down", "flat"] = Field(default="flat")

    @property
    def display_name(self) -> str:
        """The classic index label for this symbol (falls back to the symbol)."""
        return _QUOTE_DISPLAY_NAMES.get(self.symbol, self.symbol)


class UvReading(BaseModel):
    """One day's maximum UV index forecast."""

    model_config = ConfigDict(extra="forbid")

    date: str = Field(default="", description="YYYY-MM-DD.")
    uv_index: float | None = Field(default=None)


def _parse_alerts(data: dict) -> list[Alert]:
    result: list[Alert] = []
    for feature in data.get("features") or []:
        props = feature["properties"]
        severity = props.get("severity")
        if severity not in {"Extreme", "Severe", "Moderate"}:
            continue
        result.append(
            Alert(
                severity=severity,
                event=str(props.get("event") or ""),
                headline=str(props.get("headline") or ""),
                areas=str(props.get("areaDesc") or ""),
                instruction=str(props.get("instruction") or ""),
                expires=str(props.get("expires") or ""),
                urgency=str(props.get("urgency") or ""),
                description=str(props.get("description") or ""),
            )
        )
    return result


@plugin
class NoaaAlertsDatasource(Datasource):
    """Active NOAA alerts for a point, filtered/sorted like the legacy alert system."""

    name = "alerts"

    severity_priority: str = Field(
        default="extreme:severe:moderate",
        description="Colon-separated severity order used to sort alerts (most severe first).",
    )

    def active(self, lat: float, lon: float) -> list[Alert]:
        data = self.fetch("GET", NOAA_ALERTS_URL, params={"point": f"{lat},{lon}"}, timeout=5)
        alerts = _parse_alerts(data or {})
        priority = [p.strip() for p in self.severity_priority.split(":") if p.strip()]
        alerts.sort(key=lambda a: priority.index(a.severity) if a.severity in priority else 99)
        return alerts

    def is_critical(self, alerts: list[Alert]) -> bool:
        return any(a.severity == "Extreme" for a in alerts) or any(
            a.severity == "Severe" and a.urgency == "Immediate" for a in alerts
        )


@plugin
class EarthquakesDatasource(Datasource):
    name = "earthquakes"

    min_magnitude: float = Field(
        default=3.0, description="Minimum earthquake magnitude to include."
    )
    limit: int = Field(default=10, description="Maximum number of earthquakes to fetch.")

    def recent(self, lat: float, lon: float) -> list[Earthquake]:
        params = {
            "format": "geojson",
            "minmagnitude": self.min_magnitude,
            "limit": self.limit,
            "orderby": "time",
        }
        data = self.fetch("GET", USGS_URL, params=params, timeout=10)
        result: list[Earthquake] = []
        for event in (data or {}).get("features") or []:
            props = event["properties"]
            time_ms = coerce_float(props.get("time"))
            result.append(
                Earthquake(
                    magnitude=coerce_float(props.get("mag")) or 0.0,
                    place=str(props.get("place") or ""),
                    time=(
                        datetime.utcfromtimestamp(time_ms / 1000.0) if time_ms is not None else None
                    ),
                )
            )
        return result


@plugin
class UvIndexDatasource(Datasource):
    name = "uv_index"

    days: int = Field(default=7, description="Number of days of UV index forecast to fetch.")

    def daily(self, lat: float, lon: float) -> list[UvReading]:
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "uv_index_max",
            "timezone": "auto",
            "forecast_days": self.days,
        }
        data = self.fetch("GET", OM_UV_URL, params=params, timeout=10)
        daily = (data or {}).get("daily") or {}
        dates = daily.get("time") or []
        values = daily.get("uv_index_max") or []
        return [
            UvReading(date=str(dates[i]), uv_index=coerce_float(values[i]))
            for i in range(len(dates))
        ]

    @staticmethod
    def protection_level(uv_index: float) -> str:
        if uv_index <= 2:
            return "Low"
        if uv_index <= 5:
            return "Moderate"
        if uv_index <= 7:
            return "High"
        if uv_index <= 10:
            return "Very High"
        return "Extreme"


@plugin
class StockMarketDatasource(Datasource):
    """Alpha Vantage stock quotes for a set of symbols.

    The API key is supplied through the datasource's ``query`` config, e.g.
    ``query = { apikey = "..." }``.
    """

    name = "stocks"

    symbols: str = Field(
        default="DIA,SPY,QQQ", description="Comma-separated stock/index symbols to display."
    )

    def quotes(self, *args: Any, **kwargs: Any) -> list[Quote]:
        """Return quotes for every configured symbol.

        Accepts (and ignores) a location so the shared data_table component can
        call rows uniformly as ``method(lat, lon)``; quotes are not location
        scoped.
        """
        symbols = [s.strip() for s in self.symbols.split(",") if s.strip()]
        result: list[Quote] = []
        for symbol in symbols:
            quote = self._quote(symbol)
            if quote:
                result.append(quote)
        return result

    def _quote(self, symbol: str) -> Quote | None:
        data = self.fetch(
            "GET",
            "https://www.alphavantage.co/query",
            params={"function": "GLOBAL_QUOTE", "symbol": symbol},
            timeout=10,
        )
        quote = (data or {}).get("Global Quote") or {}
        if not quote:
            return None
        change = coerce_float(quote.get("09. change"))
        direction: Literal["up", "down", "flat"] = "flat"
        if change is not None and change > 0:
            direction = "up"
        elif change is not None and change < 0:
            direction = "down"
        return Quote(
            symbol=str(quote.get("01. symbol", symbol)),
            price=coerce_float(quote.get("05. price")),
            change=change,
            change_percent=coerce_float(quote.get("10. change percent")),
            direction=direction,
        )

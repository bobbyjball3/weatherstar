"""History datasource: 30-day temperature/precipitation history.

Self-contained replacement for the legacy ``history_graphs`` client.  Fetches
the last 30 days of daily high/low temperature and precipitation from
Open-Meteo (``/v1/forecast`` with ``past_days=30``) through the base Datasource
HTTP helpers with TTL caching, and returns typed rows most-recent-first.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from weatherstar.datasources.base import Datasource, coerce_float
from weatherstar.plugin import memoize
from weatherstar.registry import plugin

_HISTORY_URL = "https://api.open-meteo.com/v1/forecast"
_DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum"


class TemperatureRow(BaseModel):
    """One day's recorded high/low temperature."""

    model_config = ConfigDict(extra="forbid")

    date: str = Field(default="", description="YYYY-MM-DD.")
    high: float | None = Field(default=None)
    low: float | None = Field(default=None)


class PrecipRow(BaseModel):
    """One day's recorded precipitation total (inches)."""

    model_config = ConfigDict(extra="forbid")

    date: str = Field(default="", description="YYYY-MM-DD.")
    inches: float | None = Field(default=None)


@plugin
class HistoryDatasource(Datasource):
    name = "history"

    _offset_temp: float = PrivateAttr(default=0.0)
    _offset_precip: float = PrivateAttr(default=0.0)
    _last_scroll: float = PrivateAttr(default_factory=time.time)

    # -- fetching ------------------------------------------------------------

    def _daily_request(self, lat: float, lon: float) -> httpx.Request:
        return self.client.build_request(
            "GET",
            _HISTORY_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": _DAILY,
                "temperature_unit": "fahrenheit",
                "precipitation_unit": "inch",
                "past_days": 30,
                "timezone": "auto",
            },
        )

    def _daily_response(self, response: httpx.Response | None) -> dict[str, Any]:
        return (self.response_json(response) or {}).get("daily") or {}

    @memoize(ttl=3600)
    def _daily(self, lat: float, lon: float) -> dict[str, Any]:
        return self.fetch(self._daily_request(lat, lon), self._daily_response)

    def refresh(self, lat: float, lon: float) -> bool:
        daily = self._daily(lat, lon)
        return bool(daily.get("time"))

    def temperature(self, lat: float, lon: float) -> list[TemperatureRow]:
        """Return ``(date, high, low)`` rows, most recent first."""
        daily = self._daily(lat, lon)
        dates = daily.get("time") or []
        highs = daily.get("temperature_2m_max") or []
        lows = daily.get("temperature_2m_min") or []
        rows: list[TemperatureRow] = []
        for i in range(len(dates) - 1, -1, -1):
            rows.append(
                TemperatureRow(
                    date=str(dates[i]),
                    high=coerce_float(highs[i]),
                    low=coerce_float(lows[i]),
                )
            )
        return rows

    def precipitation(self, lat: float, lon: float) -> list[PrecipRow]:
        """Return ``(date, precip_inches)`` rows, most recent first."""
        daily = self._daily(lat, lon)
        dates = daily.get("time") or []
        amounts = daily.get("precipitation_sum") or []
        rows: list[PrecipRow] = []
        for i in range(len(dates) - 1, -1, -1):
            rows.append(PrecipRow(date=str(dates[i]), inches=coerce_float(amounts[i]) or 0.0))
        return rows

    # -- scrolling -----------------------------------------------------------

    def scroll(self, current_time: float, scroll_speed: float = 20) -> None:
        """Advance row-jump scroll offsets (matches the classic text look)."""
        if current_time - self._last_scroll < 3.0:  # scroll delay
            return
        self._offset_temp += scroll_speed * (1 / 60)
        self._offset_precip += scroll_speed * (1 / 60)

    @property
    def scroll_offsets(self) -> tuple[float, float]:
        return self._offset_temp, self._offset_precip

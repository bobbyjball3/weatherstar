"""Datasource abstraction: configurable, optionally authenticated data access.

Concrete datasources fetch from external APIs (NOAA, Open Meteo, USGS, Alpha
Vantage, webz.io, ...).  The base owns every cross-cutting HTTP concern and
splits a fetch into two readable steps:

- :meth:`Datasource.build_request` builds an ``httpx.Request`` with the
  configured headers/query merged in;
- :meth:`Datasource.response_json` / :meth:`response_bytes` read the response.

:meth:`Datasource.send` performs the request itself (timeout, status logging,
graceful ``None`` on failure), so a datasource never touches the HTTP client.
Method results are cached with the base-vended :func:`~weatherstar.plugin.memoize`
decorator, keyed by the method and its arguments rather than the request, so the
cache stays stable as a request's shape changes.

Authentication-related config values are typed ``SecretStr`` and are therefore
masked by ``repr`` / ``str`` / the logging redaction processor.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import Field, PrivateAttr, SecretStr

from weatherstar.logging_setup import get_logger
from weatherstar.plugin import Plugin


def coerce_float(value: Any) -> float | None:
    """Coerce a bare/string number (possibly ``%``/comma formatted) to float."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace("%", "").replace(",", "").strip()
        if not value:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Datasource(Plugin):
    """Base class for plugin datasources.

    Subclasses declare typed config fields and implement fetch methods by
    composing :meth:`build_request` (request construction) with
    :meth:`send` (the base-owned HTTP call) and a response reader, then decorate
    the method with :func:`~weatherstar.plugin.memoize` to cache its result::

        @memoize(ttl=1800)
        def get_forecast(self, lat, lon):
            response = self.send(self.build_request("GET", url, params={"units": "us"}))
            data = self.response_json(response) or {}
            return [ForecastPeriod.from_props(r) for r in data["properties"]["periods"]]
    """

    kind = "datasource"

    # Optional common config: each datasource may override defaults.
    timeout: float = Field(default=10, description="HTTP request timeout in seconds.")
    cache_ttl: int = Field(
        default=300,
        description="Default seconds a memoized fetch is cached (success or failure).",
    )
    headers: dict[str, SecretStr] = Field(
        default_factory=lambda: {"User-Agent": SecretStr("weatherstar (python)")},
        description="Static HTTP headers merged into every request.",
    )
    query: dict[str, SecretStr] = Field(
        default_factory=dict,
        description="Static query parameters merged into every request.",
    )

    # -- runtime state (not config) -----------------------------------------

    _client: httpx.Client | None = PrivateAttr(default=None)
    _log: Any = PrivateAttr(default_factory=lambda: get_logger("weatherstar.datasource"))

    # -- HTTP plumbing ------------------------------------------------------

    @staticmethod
    def _unwrap(values: dict[str, SecretStr]) -> dict[str, str]:
        """Reveal secret config values (only at the HTTP boundary)."""
        return {key: value.get_secret_value() for key, value in values.items()}

    def _client_for(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers=self._unwrap(self.headers),
                params=self._unwrap(self.query),
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    # -- request construction -----------------------------------------------

    def build_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        timeout: float | None = None,
    ) -> httpx.Request:
        """Build an ``httpx.Request`` with configured headers/query merged in.

        Override to customize request construction; the default handles the
        common case.
        """
        return self._client_for().build_request(
            method,
            url,
            params=params,
            json=json,
            timeout=timeout if timeout is not None else self.timeout,
        )

    # -- transport ----------------------------------------------------------

    def send(self, request: httpx.Request) -> httpx.Response | None:
        """Send ``request``, returning the response or ``None`` on failure."""
        try:
            response = self._client_for().send(request)
            self._log.debug(
                "http", method=request.method, url=str(request.url), status=response.status_code
            )
            response.raise_for_status()
            return response
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            self._log.warning("http_failed", url=str(request.url), error=str(exc))
            return None

    # -- response readers ---------------------------------------------------

    @staticmethod
    def response_json(response: httpx.Response | None) -> dict | list | None:
        """Decoded JSON body, or ``None`` when absent or not valid JSON."""
        if response is None:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def response_bytes(response: httpx.Response | None) -> bytes | None:
        """Raw response body, or ``None`` when the request failed."""
        return None if response is None else response.content

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

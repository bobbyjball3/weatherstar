"""Datasource abstraction: configurable, optionally authenticated data access.

Concrete datasources fetch from external APIs (NOAA, Open Meteo, USGS, Alpha
Vantage, webz.io, ...).  The base owns every cross-cutting HTTP concern and
keeps the two halves of a fetch apart:

- ``client`` is an ``httpx.Client`` carrying the configured headers/query/
  timeout; a datasource's own request method builds an ``httpx.Request`` with
  it, deciding method/url/params/body itself;
- ``response_json`` / ``response_bytes`` (called by its response method) read
  the body.

:meth:`Datasource.fetch` sends a built request and hands the response to the
processor, so a datasource never touches the HTTP client.  Method results are
cached with the base-vended :func:`~weatherstar.plugin.memoize` decorator, keyed
by the method and its arguments rather than the request, so the cache stays
stable as a request's shape changes.

Authentication-related config values are typed ``SecretStr`` and are therefore
masked by ``repr`` / ``str`` / the logging redaction processor.
"""

from __future__ import annotations

from collections.abc import Callable
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

    Subclasses implement each operation as a pair of pure methods — one that
    builds the request, one that reads the response — and hand them to
    :meth:`fetch`, which owns the transport.  Decorate the public method with
    :func:`~weatherstar.plugin.memoize` to cache its result::

        def _forecast_request(self, url: str) -> httpx.Request:
            return self.client.build_request("GET", url, params={"units": "us"})

        def _forecast_response(self, response) -> list[ForecastPeriod]:
            data = self.response_json(response) or {}
            return [ForecastPeriod.from_props(r) for r in data["properties"]["periods"]]

        @memoize(ttl=1800)
        def get_forecast(self, lat, lon):
            return self.fetch(self._forecast_request(url), self._forecast_response)
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

    @property
    def client(self) -> httpx.Client:
        """The configured ``httpx.Client`` (headers/query/timeout applied).

        Datasources prepare their requests with ``self.client.build_request``.
        """
        if self._client is None:
            self._client = httpx.Client(
                headers=self._unwrap(self.headers),
                params=self._unwrap(self.query),
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    # -- transport ----------------------------------------------------------

    def send(self, request: httpx.Request) -> httpx.Response | None:
        """Send ``request``, returning the response or ``None`` on failure."""
        try:
            response = self.client.send(request)
            self._log.debug(
                "http", method=request.method, url=str(request.url), status=response.status_code
            )
            response.raise_for_status()
            return response
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            self._log.warning("http_failed", url=str(request.url), error=str(exc))
            return None

    def fetch(
        self,
        request: httpx.Request,
        process: Callable[..., Any],
        **context: Any,
    ) -> Any:
        """Send ``request`` and return ``process(response, **context)``.

        A fetch is kept in two independent halves: building the request (done by
        the caller, usually a dedicated ``_<op>_request`` method) and processing
        the response (``process``, usually a ``_<op>_response`` method).  All
        transport stays here in the base.
        """
        return process(self.send(request), **context)

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

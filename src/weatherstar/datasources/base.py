"""Datasource abstraction: configurable, optionally authenticated data access.

Concrete datasources fetch from external APIs (NOAA, Open Meteo, USGS, Alpha
Vantage, webz.io, ...).  The base owns every cross-cutting HTTP concern so a
datasource only has to (1) build a request and (2) read the response:

- a lazily created ``httpx.Client`` whose headers/query come from config;
- the :meth:`Datasource.fetch` driver, which sends a request and transparently
  caches the result (success or failure) for ``cache_ttl`` seconds;
- graceful ``None`` on transport/HTTP/decode failures.

Authentication-related config values are typed ``SecretStr`` and are therefore
masked by ``repr`` / ``str`` / the logging redaction processor.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from cachetools import TTLCache
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
    composing :meth:`build_request` (interface method 1) with
    :meth:`parse_response` (interface method 2), normally through the
    :meth:`fetch` driver::

        def get_point(self, lat, lon):
            data = self.fetch("GET", f"{BASE_URL}/points/{lat:.4f},{lon:.4f}")
            return data["properties"] if data else None

    All HTTP and caching live here; datasources never touch either directly.
    """

    kind = "datasource"

    # Optional common config: each datasource may override defaults.
    timeout: float = Field(default=10, description="HTTP request timeout in seconds.")
    cache_ttl: int = Field(
        default=300,
        description="Seconds each HTTP response is cached (success or failure).",
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
    _cache: TTLCache | None = PrivateAttr(default=None)
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

    def _cache_for(self) -> TTLCache:
        if self._cache is None:
            self._cache = TTLCache(maxsize=256, ttl=self.cache_ttl)
        return self._cache

    # -- request/response interface -----------------------------------------

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

        Interface method 1.  Override to customize request construction; the
        default handles the common case.
        """
        return self._client_for().build_request(
            method,
            url,
            params=params,
            json=json,
            timeout=timeout if timeout is not None else self.timeout,
        )

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

    def parse_response(self, response: httpx.Response) -> Any:
        """Decode ``response`` into a datasource value.

        Interface method 2.  The default decodes JSON; override for other media
        (e.g. :class:`~weatherstar.datasources.radar.NoaaRadar` returns bytes).
        """
        return self.response_json(response)

    def response_json(self, response: httpx.Response) -> dict | list | None:
        """Decoded JSON body, or ``None`` when the body is not valid JSON."""
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def response_bytes(response: httpx.Response) -> bytes:
        """Raw response body."""
        return response.content

    # -- driver -------------------------------------------------------------

    def fetch(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        timeout: float | None = None,
    ) -> Any:
        """Build, send and parse a request, caching the result for ``cache_ttl``.

        Failures are cached too (negative cache), so an unreachable API is
        retried once per TTL rather than on every call.
        """
        key = self._cache_key(method, url, params, json)
        cache = self._cache_for()
        if key in cache:
            return cache[key]
        value = self._fetch_uncached(method, url, params=params, json=json, timeout=timeout)
        cache[key] = value
        return value

    def _fetch_uncached(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None,
        json: Any,
        timeout: float | None,
    ) -> Any:
        request = self.build_request(method, url, params=params, json=json, timeout=timeout)
        response = self.send(request)
        if response is None:
            return None
        return self.parse_response(response)

    @staticmethod
    def _cache_key(
        method: str,
        url: str,
        params: dict[str, Any] | None,
        body: Any,
    ) -> tuple[str, str, str, str]:
        return (
            method.upper(),
            url,
            json.dumps(params, sort_keys=True, default=str) if params else "",
            json.dumps(body, sort_keys=True, default=str) if body is not None else "",
        )

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

"""Datasource abstraction: configurable, optionally authenticated data access.

Concrete datasources fetch from external APIs (NOAA, Open Meteo, USGS, Alpha
Vantage, Google News RSS, ...).  Authentication-related config fields are typed
``SecretStr`` and are therefore masked by ``repr`` / ``str`` / the logging
redaction processor.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

import requests
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

    Subclasses override their config via typed Pydantic fields and implement
    typed fetch methods.  A thin :meth:`http_get_json` helper centralizes
    logging, header injection and error handling.
    """

    kind = "datasource"

    # Optional common config: each datasource may override defaults.
    timeout: int = Field(default=10, description="HTTP request timeout in seconds.")
    user_agent: str = Field(
        default="weatherstar (python)",
        description="User-Agent header sent with upstream API requests.",
    )

    #: Default TTL (seconds) for the base cache; subclasses override.
    _default_cache_ttl: ClassVar[int] = 300

    # -- runtime state (not config) -----------------------------------------

    _cache: dict[str, Any] = PrivateAttr(default_factory=dict)
    _cache_time: dict[str, float] = PrivateAttr(default_factory=dict)
    _session: requests.Session | None = PrivateAttr(default=None)
    _log: Any = PrivateAttr(default_factory=lambda: get_logger("weatherstar.datasource"))

    # -- HTTP plumbing ------------------------------------------------------

    def _session_for(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": self.user_agent})
            self._apply_auth(self._session)
        return self._session

    def _apply_auth(self, session: requests.Session) -> None:
        """Attach auth derived from sensitive config fields (overridable).

        The base is a no-op; datasources with session-level auth (e.g. a
        Bearer token) override it.
        """

    def _query_params(self, params: dict[str, Any] | None) -> dict[str, Any] | None:
        """Inject an ``api_key`` query parameter when the datasource declares one."""
        fields = type(self).model_fields
        if "api_key_param" not in fields or "api_key" not in fields:
            return params
        param_name = getattr(self, "api_key_param", None)
        api_key = getattr(self, "api_key", None)
        if isinstance(api_key, SecretStr):
            api_key = api_key.get_secret_value()
        if not param_name or not api_key:
            return params
        merged = dict(params or {})
        merged[param_name] = api_key
        return merged

    def http_get_json(
        self, url: str, params: dict[str, Any] | None = None, timeout: int | None = None
    ) -> dict | list | None:
        """GET ``url`` returning decoded JSON or None on any failure."""
        session = self._session_for()
        resolved_params = self._query_params(params)
        try:
            response = session.get(url, params=resolved_params, timeout=timeout or self.timeout)
            self._log.debug("http_get", url=url, status=response.status_code)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            self._log.warning("http_get_failed", url=url, error=str(exc))
            return None

    # -- Simple TTL cache -----------------------------------------------------

    def _cache_key(self, *parts: Any) -> str:
        import json

        return json.dumps(parts, sort_keys=True, default=str)

    def cache_get(self, key: str, max_age: int | None = None) -> Any | None:
        ttl = max_age if max_age is not None else type(self)._default_cache_ttl
        if key in self._cache_time and time.time() - self._cache_time[key] < ttl:
            return self._cache.get(key)
        return None

    def cache_set(self, key: str, data: Any) -> None:
        self._cache[key] = data
        self._cache_time[key] = time.time()

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

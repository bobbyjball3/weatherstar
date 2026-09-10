"""Datasource abstraction: configurable, optionally authenticated data access.

Concrete datasources fetch from external APIs (NOAA, Open Meteo, USGS, Alpha
Vantage, Google News RSS, ...).  Authentication-related config fields are typed
``SecretStr`` and are therefore masked by ``repr`` / ``str`` / the logging
redaction processor.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

import requests
from cachetools import TTLCache
from cachetools.keys import hashkey
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


def cached(ttl: int) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Cache a datasource method's result for ``ttl`` seconds.

    The cache lives on the instance and is keyed by the call arguments, so an
    implementer just decorates a fetch method and never touches cache state::

        @cached(1800)
        def get_forecast(self, lat, lon): ...

    ``None`` results are not cached, so transient failures are retried on the
    next call.  Arguments must be hashable (the coordinates and strings these
    methods take all are).
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(self: Datasource, *args: Any, **kwargs: Any) -> Any:
            cache = self._cache_for(ttl)
            # Include the method name: methods sharing a TTL share one cache.
            key = hashkey(fn.__qualname__, *args, **kwargs)
            try:
                return cache[key]
            except KeyError:
                pass
            value = fn(self, *args, **kwargs)
            if value is not None:
                cache[key] = value
            return value

        return wrapper

    return decorator


class Datasource(Plugin):
    """Base class for plugin datasources.

    Subclasses override their config via typed Pydantic fields and implement
    typed fetch methods.  The base centralizes HTTP (``http_get_json`` /
    ``http_get_bytes`` / ``http_post_json``) and TTL caching (the ``@cached``
    decorator) so fetch methods read as plain API calls.
    """

    kind = "datasource"

    # Optional common config: each datasource may override defaults.
    timeout: int = Field(default=10, description="HTTP request timeout in seconds.")
    user_agent: str = Field(
        default="weatherstar (python)",
        description="User-Agent header sent with upstream API requests.",
    )

    # -- runtime state (not config) -----------------------------------------

    _caches: dict[int, TTLCache] = PrivateAttr(default_factory=dict)
    _session: requests.Session | None = PrivateAttr(default=None)
    _log: Any = PrivateAttr(default_factory=lambda: get_logger("weatherstar.datasource"))

    def _cache_for(self, ttl: int) -> TTLCache:
        """Return this instance's cache for ``ttl`` (created on first use)."""
        cache = self._caches.get(ttl)
        if cache is None:
            cache = TTLCache(maxsize=256, ttl=ttl)
            self._caches[ttl] = cache
        return cache

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

    def http_get_bytes(self, url: str, timeout: int | None = None) -> bytes | None:
        """GET ``url`` returning the raw body or None on any failure."""
        session = self._session_for()
        try:
            response = session.get(url, timeout=timeout or self.timeout)
            self._log.debug("http_get", url=url, status=response.status_code)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            self._log.warning("http_get_failed", url=url, error=str(exc))
            return None

    def http_post_json(
        self,
        url: str,
        body: dict[str, Any],
        timeout: int | None = None,
    ) -> dict | list | None:
        """POST ``body`` as JSON, returning decoded JSON or None on any failure."""
        session = self._session_for()
        try:
            response = session.post(url, json=body, timeout=timeout or self.timeout)
            self._log.debug("http_post", url=url, status=response.status_code)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            self._log.warning("http_post_failed", url=url, error=str(exc))
            return None

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

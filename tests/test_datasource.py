"""Tests for the Datasource base: auth, query params, HTTP, TTL cache."""

import requests
from pydantic import PrivateAttr, SecretStr

from weatherstar.datasources.base import Datasource, cached


class AuthDS(Datasource):
    api_key: SecretStr | None = None
    api_key_param: str | None = None


class CountingDS(Datasource):
    _calls: int = PrivateAttr(default=0)

    @cached(60)
    def value(self, x):
        self._calls += 1
        return x * 2

    @cached(60)
    def maybe(self, x):
        self._calls += 1
        return None


class CollidingDS(Datasource):
    """Two methods with the same TTL and args must not share a cache entry."""

    _dict_calls: int = PrivateAttr(default=0)
    _list_calls: int = PrivateAttr(default=0)

    @cached(60)
    def as_dict(self, x):
        self._dict_calls += 1
        return {"kind": "dict"}

    @cached(60)
    def as_list(self, x):
        self._list_calls += 1
        return ["list"]


def _auth(**values) -> AuthDS:
    return AuthDS.model_validate(values)


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"bad status {self.status_code}")

    def json(self):
        return self._payload


class _Sess:
    def __init__(self, response):
        self.headers = {}
        self.auth = None
        self.response = response
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        return self.response

    def close(self):
        self.response = None


def _make_session(ds, response=None):
    sess = _Sess(response or _Resp({"ok": True}))
    ds._session_for = lambda: sess  # noqa: B023
    return sess


def test_query_params_inject_api_key():
    ds = _auth(api_key="k", api_key_param="apikey")
    params = ds._query_params({"function": "GLOBAL_QUOTE"})
    assert params == {"function": "GLOBAL_QUOTE", "apikey": "k"}


def test_query_params_passthrough_without_key_fields():
    ds = AuthDS()
    assert ds._query_params({"a": 1}) == {"a": 1}
    assert ds._query_params(None) is None


def test_http_get_json_success_and_params(monkeypatch):
    ds = AuthDS()
    sess = _make_session(ds, _Resp({"ok": 1}))
    result = ds.http_get_json("https://x", params={"q": 1}, timeout=5)
    assert result == {"ok": 1}
    assert sess.calls == [("https://x", {"q": 1}, 5)]


def test_http_get_json_http_error_returns_none(monkeypatch):
    ds = AuthDS()
    sess = _make_session(ds, _Resp(None, status=500))
    assert ds.http_get_json("https://x") is None
    assert len(sess.calls) == 1


def test_http_get_json_invalid_json_returns_none(monkeypatch):
    class BadJSON(_Resp):
        def json(self):
            raise ValueError("bad json")

    ds = AuthDS()
    _make_session(ds, BadJSON(None))
    assert ds.http_get_json("https://x") is None


def test_cached_decorator_caches_by_args():
    ds = CountingDS()
    assert ds.value(2) == 4
    assert ds.value(2) == 4  # cache hit -> no second call
    assert ds._calls == 1
    assert ds.value(3) == 6  # distinct args -> miss
    assert ds._calls == 2


def test_cached_decorator_does_not_pin_none():
    ds = CountingDS()
    assert ds.maybe(1) is None
    assert ds.maybe(1) is None  # None not cached -> retried
    assert ds._calls == 2


def test_cached_decorator_uses_a_ttl_cache_per_instance():
    from cachetools import TTLCache

    ds = CountingDS()
    cache = ds._cache_for(60)
    assert isinstance(cache, TTLCache)
    assert cache.ttl == 60
    assert cache is ds._cache_for(60)
    assert CountingDS()._cache_for(60) is not cache


def test_cached_decorator_keys_include_the_method():
    ds = CollidingDS()
    assert ds.as_dict(1) == {"kind": "dict"}
    assert ds.as_list(1) == ["list"]  # same ttl+args must not reuse the dict
    assert ds.as_dict(1) == {"kind": "dict"}
    assert ds._dict_calls == 1
    assert ds._list_calls == 1


def test_close_clears_session():
    ds = AuthDS()
    sess = _make_session(ds)
    assert ds._session is None  # session is created lazily inside _session_for
    ds._session = sess
    ds.close()
    assert ds._session is None

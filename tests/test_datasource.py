"""Tests for the Datasource base: auth, query params, HTTP, TTL cache."""

import time

import requests
from pydantic import SecretStr

from weatherstar.datasources.base import Datasource


class AuthDS(Datasource):
    api_key: SecretStr | None = None
    api_key_param: str | None = None


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


def test_cache_ttl_and_expiry():
    ds = AuthDS()
    ds.cache_set("k", "v")
    assert ds.cache_get("k") == "v"
    assert ds.cache_get("k", max_age=1) == "v"
    ds._cache_time["k"] = time.time() - 1000  # expired beyond default ttl
    assert ds.cache_get("k") is None
    assert ds.cache_get("missing") is None


def test_cache_key_is_stable_json():
    ds = AuthDS()
    assert ds._cache_key("a", 1) == ds._cache_key("a", 1)
    assert ds._cache_key("a", (1, 2)) != ds._cache_key("a", (2, 1))


def test_close_clears_session():
    ds = AuthDS()
    sess = _make_session(ds)
    assert ds._session is None  # session is created lazily inside _session_for
    ds._session = sess
    ds.close()
    assert ds._session is None

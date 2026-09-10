"""Tests for the Datasource base: headers/query, transport, response readers."""

import httpx
from pydantic import PrivateAttr, SecretStr

from weatherstar.datasources.base import Datasource
from weatherstar.plugin import memoize


class PlainDS(Datasource):
    pass


class CountingDS(Datasource):
    _calls: int = PrivateAttr(default=0)

    @memoize(ttl=60)
    def value(self, x):
        self._calls += 1
        return x * 2

    @memoize(ttl=60)
    def maybe(self, x):
        self._calls += 1
        return None


class DefaultTTLDS(Datasource):
    _calls: int = PrivateAttr(default=0)

    @memoize
    def value(self, x):
        self._calls += 1
        return x


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_unwrap_reveals_secret_values():
    ds = PlainDS.model_validate({"headers": {"X-Api": "s3cret"}})
    assert isinstance(ds.headers["X-Api"], SecretStr)
    assert ds._unwrap(ds.headers) == {"X-Api": "s3cret"}


def test_build_request_merges_headers_and_query():
    ds = PlainDS.model_validate(
        {
            "headers": {"X-Api": "s3cret", "User-Agent": "weatherstar (python)"},
            "query": {"apikey": "abc"},
        }
    )
    request = ds.build_request("GET", "https://example.test/x", params={"a": "1"})
    assert request.headers["x-api"] == "s3cret"
    assert request.headers["user-agent"] == "weatherstar (python)"
    url = str(request.url)
    assert "apikey=abc" in url
    assert "a=1" in url


def test_send_returns_response_on_success():
    ds = PlainDS()
    ds._client = _client(lambda request: httpx.Response(200, json={"ok": 1}))
    response = ds.send(ds.build_request("GET", "https://example.test/x"))
    assert response is not None
    assert response.status_code == 200


def test_send_returns_none_for_bad_url():
    ds = PlainDS()
    assert ds.send(ds.build_request("GET", "not-a-url")) is None


def test_send_returns_none_on_http_error():
    ds = PlainDS()
    ds._client = _client(lambda request: httpx.Response(500))
    assert ds.send(ds.build_request("GET", "https://example.test/x")) is None


def test_response_json_reads_and_guards():
    ds = PlainDS()
    assert ds.response_json(httpx.Response(200, json={"a": 1})) == {"a": 1}
    assert ds.response_json(httpx.Response(200, text="not json")) is None
    assert ds.response_json(None) is None


def test_response_bytes_reads_and_guards():
    ds = PlainDS()
    assert ds.response_bytes(httpx.Response(200, content=b"GIF89a")) == b"GIF89a"
    assert ds.response_bytes(None) is None


def test_memoize_caches_by_method_and_args():
    ds = CountingDS()
    assert ds.value(2) == 4
    assert ds.value(2) == 4  # cache hit -> no second call
    assert ds._calls == 1
    assert ds.value(3) == 6  # distinct args -> miss
    assert ds._calls == 2


def test_memoize_caches_none_results():
    ds = CountingDS()
    assert ds.maybe(1) is None
    assert ds.maybe(1) is None
    assert ds._calls == 1


def test_memoize_defaults_ttl_to_cache_ttl():
    ds = DefaultTTLDS.model_validate({"cache_ttl": 42})
    assert ds.value(1) == 1
    assert ds.value(1) == 1
    assert ds._calls == 1
    assert ds._memo_for(42).ttl == 42


def test_close_clears_client():
    ds = PlainDS()
    ds._client = _client(lambda request: httpx.Response(200))
    ds.close()
    assert ds._client is None

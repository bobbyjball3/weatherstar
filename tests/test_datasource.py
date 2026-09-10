"""Tests for the Datasource base: headers/query, HTTP, and the fetch cache."""

import httpx
from pydantic import SecretStr

from weatherstar.datasources.base import Datasource


class PlainDS(Datasource):
    pass


class BytesDS(Datasource):
    """Overrides the response interface to read raw bytes (radar-style)."""

    def parse_response(self, response):
        return self.response_bytes(response)


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


def test_fetch_returns_none_for_bad_url():
    ds = PlainDS()
    assert ds.fetch("GET", "not-a-url") is None


def test_fetch_caches_by_request():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    ds = PlainDS()
    ds._client = _client(handler)
    first = ds.fetch("GET", "https://example.test/x", params={"a": "1"})
    second = ds.fetch("GET", "https://example.test/x", params={"a": "1"})
    assert first == {"ok": True}
    assert second == {"ok": True}
    assert len(calls) == 1
    # Distinct params -> distinct cache entry.
    ds.fetch("GET", "https://example.test/x", params={"a": "2"})
    assert len(calls) == 2


def test_fetch_negative_caches_failures():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500, json={"error": "boom"})

    ds = PlainDS()
    ds._client = _client(handler)
    assert ds.fetch("GET", "https://example.test/x") is None
    assert ds.fetch("GET", "https://example.test/x") is None
    assert len(calls) == 1  # failure cached for cache_ttl


def test_fetch_returns_none_on_bad_json():
    ds = PlainDS()
    ds._client = _client(lambda request: httpx.Response(200, text="not json"))
    assert ds.fetch("GET", "https://example.test/x") is None


def test_parse_response_can_return_bytes():
    ds = BytesDS()
    ds._client = _client(lambda request: httpx.Response(200, content=b"GIF89a"))
    assert ds.fetch("GET", "https://example.test/x") == b"GIF89a"


def test_fetch_posts_json_body():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["body"] = request.content
        return httpx.Response(200, json={"results": []})

    ds = PlainDS()
    ds._client = _client(handler)
    ds.fetch("POST", "https://example.test/x", json={"query": "hi"})
    assert seen["method"] == "POST"
    assert b"hi" in seen["body"]


def test_cache_ttl_config_controls_cache():
    ds = PlainDS.model_validate({"cache_ttl": 42})
    cache = ds._cache_for()
    assert cache.ttl == 42
    assert cache is ds._cache_for()
    assert PlainDS()._cache_for() is not cache


def test_close_clears_client():
    ds = PlainDS()
    ds._client = _client(lambda request: httpx.Response(200))
    ds.close()
    assert ds._client is None

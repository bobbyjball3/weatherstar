"""Tests for datasource plugins (parsing, caching, masking, graceful failure)."""

import json

import httpx

from weatherstar.datasources.feeds import (
    Alert,
    EarthquakesDatasource,
    NoaaAlertsDatasource,
    StockMarketDatasource,
    UvIndexDatasource,
    _parse_alerts,
)
from weatherstar.datasources.news import LocalNewsDatasource


def _stocks(**values):
    defaults = {"symbols": "DIA,SPY,QQQ"}
    defaults.update(values)
    return StockMarketDatasource.model_validate(defaults)


def _install(ds, handler):
    ds._client = httpx.Client(transport=httpx.MockTransport(handler))
    return ds


def _json(payload, status=200):
    return lambda request: httpx.Response(status, json=payload)


def test_stock_query_config_is_masked_in_repr():
    ds = _stocks(query={"apikey": "secret"})
    assert "secret" not in repr(ds)
    assert "*" in repr(ds)


def test_stock_quote_parses():
    ds = _stocks(symbols="DIA")
    payload = {
        "Global Quote": {
            "01. symbol": "DIA",
            "05. price": "300.00",
            "09. change": "1.5",
            "10. change percent": "0.5%",
        }
    }
    _install(ds, _json(payload))
    quotes = ds.quotes()
    assert quotes[0].symbol == "DIA"
    assert quotes[0].price == 300.0
    assert quotes[0].change == 1.5
    assert quotes[0].change_percent == 0.5
    assert quotes[0].direction == "up"


def test_stock_api_key_sent_as_query_param():
    ds = _stocks(query={"apikey": "k"})
    request = ds.client.build_request(
        "GET",
        "https://www.alphavantage.co/query",
        params={"function": "GLOBAL_QUOTE", "symbol": "DIA"},
    )
    assert "apikey=k" in str(request.url)


def test_stock_quote_graceful_when_api_fails():
    ds = _stocks(symbols="DIA")
    _install(ds, lambda request: httpx.Response(500))
    assert ds.quotes() == []


def test_alerts_parse_filters_severity():
    data = {
        "features": [
            {
                "properties": {
                    "id": "1",
                    "event": "Flood",
                    "headline": "Flood Warning",
                    "severity": "Extreme",
                    "urgency": "Immediate",
                    "areaDesc": "County",
                    "instruction": "Move to higher ground",
                    "expires": "2030-01-01T00:00:00Z",
                }
            },
            {"properties": {"id": "2", "event": "Info", "severity": "Minor"}},
        ]
    }
    alerts = _parse_alerts(data)
    assert len(alerts) == 1
    assert alerts[0].event == "Flood"
    assert alerts[0].severity == "Extreme"


def test_alerts_critical():
    ds = NoaaAlertsDatasource()
    assert ds.is_critical([Alert(severity="Extreme")]) is True
    assert ds.is_critical([Alert(severity="Severe", urgency="Immediate")]) is True
    assert ds.is_critical([Alert(severity="Severe", urgency="Expected")]) is False


def test_uv_daily_parsing_and_protection():
    ds = UvIndexDatasource()
    payload = {
        "daily": {
            "time": ["2026-01-01", "2026-01-02"],
            "uv_index_max": [3.5, 9.0],
        }
    }
    _install(ds, _json(payload))
    daily = ds.daily(10.0, 20.0)
    assert len(daily) == 2
    assert daily[0].date == "2026-01-01"
    assert daily[0].uv_index == 3.5
    assert ds.protection_level(daily[0].uv_index) == "Moderate"
    assert ds.protection_level(daily[1].uv_index) == "Very High"
    assert ds.protection_level(11) == "Extreme"


def test_earthquakes_recent_parse():
    ds = EarthquakesDatasource()
    payload = {
        "features": [
            {
                "properties": {
                    "mag": 4.2,
                    "place": "10 km NW of X",
                    "time": 1700000000000,
                }
            },
            {"properties": {"mag": None, "place": "", "time": None}},
        ]
    }
    _install(ds, _json(payload))
    events = ds.recent(0.0, 0.0)
    assert len(events) == 2
    assert events[0].magnitude == 4.2
    assert events[0].place == "10 km NW of X"
    assert events[0].time is not None
    assert events[1].magnitude == 0.0


# -- local_news (webz.io) -------------------------------------------------


def _news(**values):
    defaults = {"news_query": "News in Carmel, Indiana"}
    defaults.update(values)
    return LocalNewsDatasource.model_validate(defaults)


def test_local_news_empty_when_unconfigured():
    ds = LocalNewsDatasource()
    assert ds.headlines(28.5, -81.4) == []


def test_local_news_empty_when_query_missing():
    def boom(request):
        raise AssertionError("should not fetch when unconfigured")

    ds = _news(news_query="")
    _install(ds, boom)
    assert ds.headlines(28.5, -81.4) == []


def test_local_news_headlines_parse_results():
    ds = _news()
    requests = []
    payload = {
        "results": [
            {"article": {"title": "Council votes on budget", "url": "https://e.com/1"}},
            {"article": {"title": "  Storm watch tonight  ", "url": "https://e.com/2"}},
        ]
    }

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    _install(ds, handler)
    headlines = ds.headlines(28.5, -81.4)
    assert [(h.title, h.url) for h in headlines] == [
        ("Council votes on budget", "https://e.com/1"),
        ("Storm watch tonight", "https://e.com/2"),
    ]
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.webz.io/api/news/context"
    body = json.loads(request.content)
    assert body["query"] == "News in Carmel, Indiana"
    assert body["k"] == 10
    assert body["filters"]["language"] == ["english"]
    assert body["filters"]["country"] == ["US"]
    assert body["filters"]["category"] == ["Crime, Law and Justice"]
    assert body["filters"]["published_from"].endswith("Z")


def test_local_news_empty_when_no_results():
    ds = _news()
    _install(ds, _json({"results": None}))
    assert ds.headlines(28.5, -81.4) == []


def test_local_news_skips_results_without_usable_article():
    ds = _news()
    payload = {
        "results": [
            {"article": {"title": "", "url": "u0"}},
            {"score": 1.0},
            "garbage",
            {"article": {"title": "Keep this one", "url": "https://e.com/keep"}},
        ]
    }
    _install(ds, _json(payload))
    headlines = ds.headlines(28.5, -81.4)
    assert [(h.title, h.url) for h in headlines] == [("Keep this one", "https://e.com/keep")]


def test_local_news_graceful_when_api_fails():
    ds = _news()
    _install(ds, lambda request: httpx.Response(500))
    assert ds.headlines(28.5, -81.4) == []


def test_local_news_headlines_request_is_cache_stable():
    """Repeated renders must reuse the memoized result, not re-POST every frame.

    Regression: the request body embeds a timestamp, which used to change the
    request-level cache key every second.  The method-keyed cache is immune.
    """
    ds = _news()
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"results": [{"article": {"title": "T1", "url": "u1"}}]})

    _install(ds, handler)
    assert [h.title for h in ds.headlines(28.5, -81.4)] == ["T1"]
    assert [h.title for h in ds.headlines(28.5, -81.4)] == ["T1"]
    assert len(calls) == 1


def test_local_news_bearer_auth_from_headers_config():
    ds = _news(headers={"Authorization": "Bearer super-secret-key"})
    request = ds.client.build_request("POST", ds._api_endpoint, json={})
    assert request.headers["authorization"] == "Bearer super-secret-key"
    assert "super-secret-key" not in repr(ds)
    assert "*" in repr(ds)


def test_local_news_no_authorization_without_headers():
    ds = LocalNewsDatasource()
    request = ds.client.build_request("POST", ds._api_endpoint, json={})
    assert "authorization" not in request.headers


def test_local_news_city_name_empty_string():
    ds = LocalNewsDatasource()
    assert ds.city_name(28.5, -81.4) == ""

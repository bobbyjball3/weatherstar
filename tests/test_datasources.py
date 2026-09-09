"""Tests for datasource plugins (parsing, caching, masking, graceful failure)."""

import pytest
import requests
from pydantic import ValidationError

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
    defaults = {"api_key": "k", "symbols": "DIA,SPY,QQQ"}
    defaults.update(values)
    return StockMarketDatasource.model_validate(defaults)


def test_stock_datasource_requires_sensitive_api_key():
    with pytest.raises(ValidationError):
        StockMarketDatasource.model_validate({})
    ds = StockMarketDatasource.model_validate({"api_key": "secret"})
    assert "secret" not in repr(ds)
    assert "***" in repr(ds)
    assert ds.api_key.get_secret_value() == "secret"


def test_stock_quote_parses_and_caches(monkeypatch):
    ds = _stocks(symbols="DIA")
    payload = {
        "Global Quote": {
            "01. symbol": "DIA",
            "05. price": "300.00",
            "09. change": "1.5",
            "10. change percent": "0.5%",
        }
    }
    monkeypatch.setattr(ds, "http_get_json", lambda *a, **k: payload)
    quotes = ds.quotes()
    assert quotes[0].symbol == "DIA"
    assert quotes[0].price == 300.0
    assert quotes[0].change == 1.5
    assert quotes[0].change_percent == 0.5
    assert quotes[0].direction == "up"


def test_stock_api_key_injected_as_query_param():
    ds = _stocks(symbols="DIA")
    params = ds._query_params({"function": "GLOBAL_QUOTE", "symbol": "DIA"})
    assert params["apikey"] == "k"


def test_stock_quote_graceful_when_api_fails(monkeypatch):
    ds = _stocks(symbols="DIA")
    monkeypatch.setattr(ds, "http_get_json", lambda *a, **k: None)
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


def test_uv_daily_parsing_and_protection(monkeypatch):
    ds = UvIndexDatasource()

    def fake(url, params=None, timeout=None):
        return {
            "daily": {
                "time": ["2026-01-01", "2026-01-02"],
                "uv_index_max": [3.5, 9.0],
            }
        }

    monkeypatch.setattr(ds, "http_get_json", fake)
    daily = ds.daily(10.0, 20.0)
    assert len(daily) == 2
    assert daily[0].date == "2026-01-01"
    assert daily[0].uv_index == 3.5
    assert ds.protection_level(daily[0].uv_index) == "Moderate"
    assert ds.protection_level(daily[1].uv_index) == "Very High"
    assert ds.protection_level(11) == "Extreme"


def test_earthquakes_recent_parse(monkeypatch):
    ds = EarthquakesDatasource()

    def fake(url, params=None, timeout=None):
        return {
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

    monkeypatch.setattr(ds, "http_get_json", fake)
    events = ds.recent(0.0, 0.0)
    assert len(events) == 2
    assert events[0].magnitude == 4.2
    assert events[0].place == "10 km NW of X"
    assert events[0].time is not None
    assert events[1].magnitude == 0.0


# -- local_news (webz.io) -------------------------------------------------


def _news(**values):
    defaults = {"api_key": "secret-key", "news_query": "News in Carmel, Indiana"}
    defaults.update(values)
    return LocalNewsDatasource.model_validate(defaults)


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _ErrResp(_Resp):
    def raise_for_status(self):
        raise requests.HTTPError("401 Unauthorized")


class _Session:
    """Fake requests.Session capturing post() arguments."""

    def __init__(self, payload=None, *, post_error=None):
        self._payload = payload
        self._post_error = post_error
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self._post_error is not None:
            raise self._post_error
        return _ErrResp(None) if self._payload is None else _Resp(self._payload)


def test_local_news_empty_when_unconfigured():
    ds = LocalNewsDatasource()
    assert ds.headlines(28.5, -81.4) == []


def test_local_news_empty_when_key_or_query_missing(monkeypatch):
    def _no_fetch():
        raise AssertionError("should not fetch when unconfigured")

    for ds in (_news(api_key=None), _news(news_query="")):
        monkeypatch.setattr(ds, "_session_for", _no_fetch)
        assert ds.headlines(28.5, -81.4) == []


def test_local_news_headlines_parse_results(monkeypatch):
    ds = _news()
    session = _Session(
        {
            "results": [
                {"article": {"title": "Council votes on budget", "url": "https://e.com/1"}},
                {"article": {"title": "  Storm watch tonight  ", "url": "https://e.com/2"}},
            ]
        }
    )
    monkeypatch.setattr(ds, "_session_for", lambda: session)
    headlines = ds.headlines(28.5, -81.4)
    assert [(h.title, h.url) for h in headlines] == [
        ("Council votes on budget", "https://e.com/1"),
        ("Storm watch tonight", "https://e.com/2"),
    ]
    call = session.calls[0]
    assert call["url"] == "https://api.webz.io/api/news/context"
    body = call["json"]
    assert body["query"] == "News in Carmel, Indiana"
    assert body["k"] == 10
    assert body["filters"]["language"] == ["english"]
    assert body["filters"]["country"] == ["US"]
    assert body["filters"]["category"] == ["Crime, Law and Justice"]
    assert body["filters"]["published_from"].endswith("Z")
    assert call["timeout"] == ds.timeout


def test_local_news_headlines_are_cached(monkeypatch):
    ds = _news()
    session = _Session({"results": [{"article": {"title": "T1", "url": "u1"}}]})
    monkeypatch.setattr(ds, "_session_for", lambda: session)
    assert ds.headlines(28.5, -81.4) == ds.headlines(28.5, -81.4)
    assert len(session.calls) == 1


def test_local_news_empty_when_no_results(monkeypatch):
    ds = _news()
    monkeypatch.setattr(ds, "_session_for", lambda: _Session({"results": None}))
    assert ds.headlines(28.5, -81.4) == []


def test_local_news_skips_results_without_usable_article(monkeypatch):
    ds = _news()
    payload = {
        "results": [
            {"article": {"title": "", "url": "u0"}},
            {"score": 1.0},
            "garbage",
            {"article": {"title": "Keep this one", "url": "https://e.com/keep"}},
        ]
    }
    monkeypatch.setattr(ds, "_session_for", lambda: _Session(payload))
    headlines = ds.headlines(28.5, -81.4)
    assert [(h.title, h.url) for h in headlines] == [("Keep this one", "https://e.com/keep")]


def test_local_news_graceful_when_api_fails(monkeypatch):
    ds = _news()
    monkeypatch.setattr(
        ds, "_session_for", lambda: _Session(post_error=requests.ConnectionError("down"))
    )
    assert ds.headlines(28.5, -81.4) == []


def test_local_news_graceful_on_http_error(monkeypatch):
    ds = _news()
    monkeypatch.setattr(ds, "_session_for", lambda: _Session(None))
    assert ds.headlines(28.5, -81.4) == []


def test_local_news_bearer_auth_uses_real_secret():
    ds = _news(api_key="super-secret-key")
    session = requests.Session()
    ds._apply_auth(session)
    assert session.headers["Authorization"] == "Bearer super-secret-key"
    assert "super-secret-key" not in repr(ds)
    assert "***" in repr(ds)


def test_local_news_bearer_auth_absent_without_key():
    ds = LocalNewsDatasource()
    session = requests.Session()
    ds._apply_auth(session)
    assert "Authorization" not in session.headers


def test_local_news_city_name_empty_string():
    ds = LocalNewsDatasource()
    assert ds.city_name(28.5, -81.4) == ""

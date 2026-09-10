"""Tests for remaining plumbing: feeds extras, config_file, sequence, context,
render helpers, fonts/backgrounds media, and CLI edge cases."""

import httpx
import pygame
import pytest

from weatherstar.context import AppContext, DataRegistry
from weatherstar.datasources.feeds import (
    EarthquakesDatasource,
    NoaaAlertsDatasource,
    StockMarketDatasource,
    UvIndexDatasource,
)


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_alerts_active_sorts_by_severity_and_caches():
    ds = NoaaAlertsDatasource.model_validate({"severity_priority": "Extreme:Severe:Moderate"})
    payload = {
        "features": [
            {"properties": {"severity": "Severe", "event": "A", "id": "2"}},
            {"properties": {"severity": "Extreme", "event": "B", "id": "1"}},
            {"properties": {"severity": "Minor", "event": "C", "id": "3"}},
        ]
    }
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=payload)

    ds._client = _mock_client(handler)
    alerts = ds.active(10.0, 20.0)
    assert [a.event for a in alerts] == ["B", "A"]
    ds.active(10.0, 20.0)  # served from the transparent fetch cache
    assert len(calls) == 1


def test_feeds_cache_second_calls():
    quakes = EarthquakesDatasource()
    uv = UvIndexDatasource()
    stocks = StockMarketDatasource.model_validate({"query": {"apikey": "k"}, "symbols": "DIA,SPY"})

    quake_payload = {
        "features": [
            {"properties": {"mag": 4.0, "place": "Near X", "time": 1}},
        ]
    }
    uv_payload = {"daily": {"time": ["2026-01-01"], "uv_index_max": [6.0]}}
    stock_payload = {
        "Global Quote": {
            "01. symbol": "DIA",
            "05. price": "300",
            "09. change": "1",
            "10. change percent": "0.3%",
        }
    }
    calls = {"quakes": 0, "uv": 0, "stocks": 0}

    def handler(request):
        url = str(request.url)
        if "earthquake.usgs.gov" in url:
            calls["quakes"] += 1
            return httpx.Response(200, json=quake_payload)
        if "open-meteo.com" in url:
            calls["uv"] += 1
            return httpx.Response(200, json=uv_payload)
        if "alphavantage.co" in url:
            calls["stocks"] += 1
            return httpx.Response(200, json=stock_payload)
        return httpx.Response(404)

    for ds in (quakes, uv, stocks):
        ds._client = _mock_client(handler)

    quakes.recent(0.0, 0.0)
    quakes.recent(0.0, 0.0)
    assert calls["quakes"] == 1

    uv.daily(0.0, 0.0)
    uv.daily(0.0, 0.0)
    assert calls["uv"] == 1

    stocks.quotes()
    stocks.quotes()
    # Two symbols => one HTTP fetch per symbol, cached on the second pass.
    assert calls["stocks"] == 2


# ---------------------------------------------------------------------------
# config_file / sequence branches
# ---------------------------------------------------------------------------


def test_select_sequence_requires_name():
    from weatherstar import ConfigError
    from weatherstar.config_file import AppConfig

    with pytest.raises(ConfigError):
        AppConfig({}).select_sequence(None)


def test_get_sequence_missing_raises():
    from weatherstar import SequenceError
    from weatherstar.config_file import AppConfig

    with pytest.raises(SequenceError):
        AppConfig({"sequence": "main"}).get_sequence("main")


def test_sequence_from_raw_forms():
    from weatherstar import SequenceError
    from weatherstar.sequence import Sequence, Slide

    assert Slide.from_raw("radar", default_pause=3.0) == Slide("radar", 3.0)
    assert Slide.from_raw({"screen": "radar", "pause": 2.0}) == Slide("radar", 2.0)
    with pytest.raises(SequenceError):
        Slide.from_raw({})
    with pytest.raises(SequenceError):
        Slide.from_raw(42)

    seq = Sequence.from_config("x", {"pause": 5.0, "slides": ["a", {"screen": "b"}]})
    assert seq.pause_for(0) == 5.0
    assert seq.pause_for(1) == 5.0
    assert seq.total_duration() == 10.0
    assert seq.screen_names() == ["a", "b"]
    assert Sequence.from_config("x", {"slides": ["a"]}).pause_for(0) == 15.0
    with pytest.raises(SequenceError):
        Sequence.from_config("x", {})
    with pytest.raises(SequenceError):
        Sequence.from_config("x", {"slides": []})


# ---------------------------------------------------------------------------
# context conveniences
# ---------------------------------------------------------------------------


def _ctx(surface):
    return AppContext(surface=surface, fonts={"title": pygame.font.Font(None, 32)})


def test_context_colors_and_size(pygame_env):
    ctx = _ctx(None)
    assert ctx.colors["yellow"][:3] == (255, 255, 0)
    assert ctx.size() == (0, 0)


def test_context_size_with_surface_and_registry_errors(pygame_env, screen):
    ctx = _ctx(screen)
    assert ctx.size() == (640, 480)

    registry = DataRegistry()
    registry.register("a", object())
    assert registry.names() == ["a"]
    registry.clear()
    assert registry.names() == []
    with pytest.raises(KeyError):
        registry.get("a")


# ---------------------------------------------------------------------------
# render helpers
# ---------------------------------------------------------------------------


def test_render_draw_background_paths(pygame_env, screen):
    from weatherstar import render

    ctx = _ctx(screen)
    ctx.assets = {}
    render.draw_background(screen, ctx, "1")  # no backgrounds -> fill

    bg = pygame.Surface((10, 10))
    bg.fill((1, 2, 3))
    ctx.assets = {"backgrounds": {"2": bg}}
    render.draw_background(screen, ctx, "1")  # named missing -> first available
    assert screen.get_at((0, 0))[:3] == (1, 2, 3)


def test_render_header_and_text(pygame_env, screen):
    from weatherstar import render

    ctx = _ctx(screen)
    ctx.assets = {
        "logos": {"logo-corner": pygame.Surface((10, 10)), "noaa": pygame.Surface((10, 10))}
    }
    render.draw_header(screen, ctx, "Weather Star", "4000", has_noaa=True)
    render.draw_header(screen, ctx, "Single", has_noaa=False)
    rect = render.draw_centered_text(screen, ctx, "hi", 100, center_x=50)
    assert rect is not None
    rect2 = render.draw_text(screen, ctx, "hi", (0, 0))
    assert rect2 is not None


# ---------------------------------------------------------------------------
# fonts / backgrounds media
# ---------------------------------------------------------------------------


def test_fonts_fallback_without_asset_fonts(pygame_env, tmp_path):
    from weatherstar.media.fonts import Fonts

    fonts = Fonts.model_validate({"asset_dir": str(tmp_path)})
    ctx = AppContext(surface=None)
    loaded = fonts.load(ctx)
    assert set(loaded) == {
        "title",
        "large",
        "extended",
        "small",
        "normal",
        "forecast",
        "tiny",
        "scroller",
    }
    assert set(ctx.fonts) == set(loaded)


def test_backgrounds_generates_default_gradient(screen):
    from weatherstar.media.backgrounds import Backgrounds, make_default_background

    gradient = make_default_background(4, 4)
    assert gradient.get_size() == (4, 4)

    backgrounds = Backgrounds.model_validate({"asset_dir": "/nonexistent"})
    ctx = _ctx(screen)
    result = backgrounds.load_asset(ctx)
    assert "default" in result
    assert result["default"].get_size() == (640, 480)


# ---------------------------------------------------------------------------
# CLI edge cases
# ---------------------------------------------------------------------------


def test_cli_generate_config_nested_output(tmp_path, capsys):
    from weatherstar.cli import main

    out = tmp_path / "nested" / "dir" / "out.toml"
    assert main(["generate-config", "-o", str(out)]) == 0
    assert out.exists()


def test_cli_config_missing_sequence_returns_2(tmp_path, capsys):
    from weatherstar.cli import main

    path = tmp_path / "cfg.toml"
    path.write_text(
        '[location]\nlat = 1.0\nlon = 2.0\n[sequences.x]\npause=0.001\nslides=[{screen="progress"}]\n'
    )
    code = main(["--config", str(path), "--validate"])
    assert code == 2


def test_cli_keyboard_interrupt_returns_130(tmp_path, monkeypatch, capsys):
    from weatherstar import cli

    path = tmp_path / "cfg.toml"
    path.write_text(
        'sequence="demo"\n'
        "[location]\nlat=28.5383\nlon=-81.3792\n"
        '[sequences.demo]\npause=0.001\nslides=[{screen="progress"}]\n'
    )
    import weatherstar.engine as engine_mod

    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(engine_mod, "run_sequence", boom)
    code = cli.main(["--config", str(path)])
    assert code == 130

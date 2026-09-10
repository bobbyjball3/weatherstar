"""Tests for the NOAA HRRR future-radar datasource."""

from datetime import datetime, timedelta, timezone

import httpx
import pygame
import pytest

from weatherstar.datasources.radar import NoaaRadar

_UTC = timezone.utc


def _png_bytes(tmp_path, size=(64, 64), color=(120, 80, 40)) -> bytes:
    surface = pygame.Surface(size)
    surface.fill(color)
    path = tmp_path / "radar.png"
    pygame.image.save(surface, str(path))
    return path.read_bytes()


@pytest.fixture(autouse=True)
def _init(pygame_env):
    yield


def test_crop_box_centered_in_conus():
    left, top, right, bottom = NoaaRadar.crop_box(37.0, -95.0, (1000, 500))
    assert 0 <= left < right <= 1000
    assert 0 <= top < bottom <= 500
    # ~1/5 window around the centre.
    assert right - left == 200
    assert bottom - top == 100


def test_crop_box_clamps_at_edges():
    left, top, right, bottom = NoaaRadar.crop_box(50.0, -125.0, (1000, 500))
    assert left == 0 and top == 0
    assert right == 200 and bottom == 100


def test_crop_bbox_matches_hrrr_grid():
    west, south, east, north = NoaaRadar._crop_bbox(37.0, -95.0)
    assert (round(west, 4), round(south, 4)) == (-101.1, 34.32)
    assert (round(east, 4), round(north, 4)) == (-88.9, 39.68)


def test_leads_align_to_forecast_grid_and_span_horizon():
    ds = NoaaRadar()
    run = datetime(2026, 9, 10, 12, 0, tzinfo=_UTC)
    now = run + timedelta(minutes=125)  # 14:05
    leads = ds._leads(now, run)
    # First step at/after now (ceil 125 -> 135), then every 15 min for 2 hours.
    assert leads == [135, 150, 165, 180, 195, 210, 225, 240, 255]
    assert len(leads) == 9


def test_leads_respect_custom_horizon_and_interval():
    ds = NoaaRadar(forecast_minutes=60, frame_interval_minutes=30)
    run = datetime(2026, 9, 10, 12, 0, tzinfo=_UTC)
    leads = ds._leads(run, run)  # now == run
    assert leads == [0, 30, 60]


def test_latest_run_walks_back_until_published():
    ds = NoaaRadar()
    probes = []

    def available(run):
        probes.append(run.hour)
        return run.hour == 10

    ds._run_available = available  # type: ignore[method-assign]
    now = datetime(2026, 9, 10, 12, 30, tzinfo=_UTC)
    assert ds._latest_run(now) == datetime(2026, 9, 10, 10, 0, tzinfo=_UTC)
    assert probes == [12, 11, 10]


def test_frames_and_times_run_chronologically(monkeypatch, tmp_path):
    ds = NoaaRadar(show_basemap=False)
    png = _png_bytes(tmp_path)
    run = datetime(2026, 9, 10, 12, 0, tzinfo=_UTC)
    now = run + timedelta(minutes=125)
    calls = []

    monkeypatch.setattr(ds, "_now", lambda: now)
    monkeypatch.setattr(ds, "_latest_run", lambda _now: run)
    monkeypatch.setattr(ds, "_fetch_bytes", lambda url: calls.append(url) or png)

    frames = ds.frames(28.54, -81.38)
    assert len(frames) == 9
    for frame in frames:
        assert frame.get_size() == (500, 300)
    leads = [int(url.rsplit("refd_", 1)[1].split(".", 1)[0]) for url in calls]
    assert leads == [135, 150, 165, 180, 195, 210, 225, 240, 255]

    times = ds.frame_times(28.54, -81.38)
    assert times == [run + timedelta(minutes=lead) for lead in leads]


def test_build_frame_composites_echoes_over_basemap(pygame_env, tmp_path):
    source = pygame.Surface((100, 100))
    source.fill((0, 0, 0))
    pygame.draw.rect(source, (255, 0, 0), pygame.Rect(0, 0, 50, 100))
    path = tmp_path / "frame.png"
    pygame.image.save(source, str(path))

    background = pygame.Surface((500, 300))
    background.fill((0, 200, 0))
    frame = NoaaRadar._build_frame(path.read_bytes(), 37.0, -95.0, background)
    assert frame.get_size() == (500, 300)
    # Left half of the crop carries echo, right half is transparent no-data.
    assert frame.get_at((100, 150))[:3] == (255, 0, 0)
    assert frame.get_at((400, 150))[:3] == (0, 200, 0)


def test_build_frame_without_basemap_keys_out_black(pygame_env, tmp_path):
    png = _png_bytes(tmp_path, color=(0, 0, 0))
    frame = NoaaRadar._build_frame(png, 37.0, -95.0)
    assert tuple(frame.get_colorkey())[:3] == (0, 0, 0)


def test_basemap_reprojects_county_tiles(pygame_env, tmp_path):
    ds = NoaaRadar()
    tile = pygame.Surface((256, 256), pygame.SRCALPHA)
    pygame.draw.line(tile, (0, 0, 0, 255), (0, 0), (255, 255), 3)
    path = tmp_path / "tile.png"
    pygame.image.save(tile, str(path))
    png = path.read_bytes()
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    ds._client = httpx.Client(transport=httpx.MockTransport(handler))
    surface = ds.basemap(37.0, -95.0)
    assert surface is not None and surface.get_size() == (500, 300)
    assert urls and all("/tile.py/1.0.0/uscounties/" in url for url in urls)


def test_basemap_disabled_returns_none(pygame_env):
    assert NoaaRadar(show_basemap=False).basemap(37.0, -95.0) is None


def test_basemap_uses_configured_color(pygame_env, tmp_path):
    ds = NoaaRadar(basemap_color=(10, 20, 30))
    tile = pygame.Surface((256, 256), pygame.SRCALPHA)  # transparent: only the fill shows
    path = tmp_path / "tile.png"
    pygame.image.save(tile, str(path))
    png = path.read_bytes()

    def handler(request):
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    ds._client = httpx.Client(transport=httpx.MockTransport(handler))
    surface = ds.basemap(37.0, -95.0)
    assert surface is not None
    assert surface.get_at((0, 0))[:3] == (10, 20, 30)


def test_frames_offline_returns_empty_and_caches():
    ds = NoaaRadar()
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(404)

    ds._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert ds.frames(28.54, -81.38) == []
    # Cached: a second call must not trigger another network burst.
    after_first = len(calls)
    assert ds.frames(28.54, -81.38) == []
    assert len(calls) == after_first
    assert after_first > 0

"""Tests for the NWS RIDGE radar datasource."""

import httpx
import pygame
import pytest

from weatherstar.datasources.radar import NoaaRadar


@pytest.fixture(autouse=True)
def _init(pygame_env):
    yield


def _png_bytes(tmp_path, size=(64, 64), color=(120, 80, 40)) -> bytes:
    surface = pygame.Surface(size)
    surface.fill(color)
    path = tmp_path / "radar.png"
    pygame.image.save(surface, str(path))
    return path.read_bytes()


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


def test_build_frame_crops_and_scales(pygame_env, tmp_path):
    png = _png_bytes(tmp_path)
    frame = NoaaRadar._build_frame(png, 37.0, -95.0)
    assert frame.get_size() == (500, 300)


def test_frames_fetch_oldest_to_newest(monkeypatch, tmp_path):
    ds = NoaaRadar()
    png = _png_bytes(tmp_path)
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return png

    monkeypatch.setattr(ds, "_fetch_bytes", fake_fetch)
    frames = ds.frames(28.54, -81.38)
    assert len(frames) == 6
    for frame in frames:
        assert frame.get_size() == (500, 300)
    indices = [int(url.rsplit("_", 1)[1].split(".", 1)[0]) for url in calls]
    assert indices == [5, 4, 3, 2, 1, 0]  # oldest -> newest


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

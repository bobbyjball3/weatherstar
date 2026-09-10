"""Tests for the NOAA radar datasource."""

import httpx
import pygame
import pytest

from weatherstar.datasources.radar import NoaaRadar


def _png_bytes(tmp_path) -> bytes:
    surface = pygame.Surface((64, 64))
    surface.fill((120, 80, 40))
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


def test_frames_returns_cropped_still_list(monkeypatch, tmp_path):
    ds = NoaaRadar()
    png = _png_bytes(tmp_path)
    calls = []
    monkeypatch.setattr(ds, "_fetch_bytes", lambda url: calls.append(url) or png)
    frames = ds.frames(28.54, -81.38)
    assert len(frames) == 6
    for frame in frames:
        assert frame.get_size() == (500, 300)
    # Six per-frame fetches, oldest (index 5) first.
    assert len(calls) == 6


def test_frames_offline_returns_empty_and_caches():
    ds = NoaaRadar()
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(404)

    ds._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert ds.frames(28.54, -81.38) == []
    # Cached: a second call must not trigger another network burst.
    assert ds.frames(28.54, -81.38) == []
    # 6 indexes x 3 candidate templates each tried once; failures cached.
    assert len(calls) == 18

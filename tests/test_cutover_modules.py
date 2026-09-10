"""Tests for self-contained modules that replaced legacy top-level dependencies."""

import time

import httpx
import pygame

from weatherstar.datasources.history import HistoryDatasource
from weatherstar.media.icons import AnimatedIcon, IconManager

_DAILY = {
    "time": ["2026-09-01", "2026-09-02", "2026-09-03"],
    "temperature_2m_max": [88.0, 90.0, 92.0],
    "temperature_2m_min": [70.0, 71.0, 72.0],
    "precipitation_sum": [0.0, 0.25, 0.0],
}


def _history_ds(daily) -> HistoryDatasource:
    ds = HistoryDatasource()

    def handler(request):
        return httpx.Response(200, json={"daily": daily})

    ds._client = httpx.Client(transport=httpx.MockTransport(handler))
    return ds


def test_history_temperature_returns_most_recent_first():
    ds = _history_ds(dict(_DAILY))
    rows = ds.temperature(28.5, -81.4)
    assert [(r.date, r.high, r.low) for r in rows] == [
        ("2026-09-03", 92.0, 72.0),
        ("2026-09-02", 90.0, 71.0),
        ("2026-09-01", 88.0, 70.0),
    ]


def test_history_precipitation_most_recent_first():
    ds = _history_ds(dict(_DAILY))
    rows = ds.precipitation(28.5, -81.4)
    assert [(r.date, r.inches) for r in rows] == [
        ("2026-09-03", 0.0),
        ("2026-09-02", 0.25),
        ("2026-09-01", 0.0),
    ]


def test_history_refresh_false_when_empty():
    ds = _history_ds({})
    assert ds.refresh(1.0, 2.0) is False


def test_history_scroll_offsets_advance_after_delay():
    ds = HistoryDatasource()
    assert ds.scroll_offsets == (0.0, 0.0)
    ds.scroll(time.time() + 5.0)
    temp_offset, precip_offset = ds.scroll_offsets
    assert temp_offset > 0.0
    assert precip_offset > 0.0


def test_icon_manager_returns_scaled_and_named(pygame_env, tmp_path):
    icon_dir = tmp_path / "icons"
    icon_dir.mkdir()
    surface = pygame.Surface((10, 10))
    surface.fill((255, 255, 255))
    pygame.image.save(surface, str(icon_dir / "Partly-Cloudy.png"))

    manager = IconManager(icon_dir)
    got = manager.get_icon("Partly-Cloudy", width=40, height=30)
    assert got is not None and got.get_size() == (40, 30)
    # Case-insensitive lookup for a different casing.
    assert manager.get_icon("partly-cloudy") is not None
    assert manager.get_icon("missing-icon") is None


def test_icon_manager_empty_directory(pygame_env, tmp_path):
    manager = IconManager(tmp_path)
    assert manager.get_icon("anything") is None


def test_icons_are_loaded_authentically(pygame_env, tmp_path):
    """Icon artwork must render exactly as shipped, with no recolor/alteration.

    Regression: a legibility pass used to flatten monochrome artwork to white,
    which erased the gray shading of Cloudy / Mostly-Clear.  Icons are now
    loaded unmodified so original colors (including dark outlines) are kept.
    """
    stamp = pygame.Surface((4, 4))
    stamp.fill((255, 255, 255))
    stamp.set_at((0, 0), (0, 0, 0))  # dark outline
    stamp.set_at((1, 1), (175, 175, 175))  # gray cloud fill
    stamp.set_at((2, 2), (73, 102, 161))  # saturated accent

    icon_dir = tmp_path / "icons"
    icon_dir.mkdir()
    pygame.image.save(stamp, str(icon_dir / "stamp.png"))

    manager = IconManager(icon_dir)
    icon = manager.get_icon("stamp")
    assert icon is not None
    assert icon.get_at((0, 0))[:3] == (0, 0, 0)
    assert icon.get_at((1, 1))[:3] == (175, 175, 175)
    assert icon.get_at((2, 2))[:3] == (73, 102, 161)
    # Scaling keeps the artwork intact too.
    scaled = manager.get_icon("stamp", width=40, height=40)
    assert scaled is not None and scaled.get_size() == (40, 40)


def test_icon_gif_colorkey_survives_loading_and_scaling(pygame_env):
    """A GIF's transparent white canvas stays transparent after scaling.

    This is what lets authentic icons (raw artwork) composite onto the navy
    bands without a recolor pass turning the canvas into an opaque box.
    """
    from pathlib import Path

    import pytest

    source = Path("static_assets/weatherstar_4000/icons/Cloudy.gif")
    if not source.exists():
        pytest.skip("icon assets not present")

    manager = IconManager(source.parent)
    icon = manager.get_icon("Cloudy", width=86, height=75)
    assert icon is not None

    navy = pygame.Surface((100, 100))
    navy.fill((0, 0, 80))
    navy.blit(icon, (5, 5))
    # Where the artwork's white canvas was (icon corner), the navy shows through.
    assert navy.get_at((5, 5))[:3] == (0, 0, 80)


def _write_gif(path, colors, duration_ms=100):
    """Write a solid-color animated GIF using Pillow (now a runtime dependency)."""
    from PIL import Image

    frames = [Image.new("RGB", (4, 4), color) for color in colors]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
    )


def _corner(surface):
    return surface.get_at((0, 0))[:3]


def test_icon_manager_animates_multi_frame_gif(pygame_env, tmp_path):
    """A multi-frame GIF cycles frames off the manager's shared dt clock."""
    icon_dir = tmp_path / "icons"
    icon_dir.mkdir()
    _write_gif(icon_dir / "Cycle.gif", [(255, 0, 0), (0, 255, 0), (0, 0, 255)])

    manager = IconManager(icon_dir)
    assert isinstance(manager._find("Cycle"), AnimatedIcon)
    assert _corner(manager.get_icon("Cycle")) == (255, 0, 0)
    manager.tick(0.1)
    assert _corner(manager.get_icon("Cycle")) == (0, 255, 0)
    manager.tick(0.1)
    assert _corner(manager.get_icon("Cycle")) == (0, 0, 255)
    # Past the total duration the animation loops back to the first frame.
    manager.tick(0.1)
    assert _corner(manager.get_icon("Cycle")) == (255, 0, 0)


def test_icon_manager_static_gif_ignores_clock(pygame_env, tmp_path):
    """A single-frame GIF stays put no matter how far the clock advances."""
    icon_dir = tmp_path / "icons"
    icon_dir.mkdir()
    _write_gif(icon_dir / "Still.gif", [(10, 20, 30)])

    manager = IconManager(icon_dir)
    assert not isinstance(manager._find("Still"), AnimatedIcon)
    before = _corner(manager.get_icon("Still"))
    manager.tick(5.0)
    assert _corner(manager.get_icon("Still")) == before


def test_icon_manager_animated_icon_keeps_transparency(pygame_env, tmp_path):
    """Decoded animated frames keep their transparent canvas when blitted."""
    from PIL import Image

    icon_dir = tmp_path / "icons"
    icon_dir.mkdir()
    # A transparent pixel at (0, 0) over an opaque accent at (1, 1).
    frames = []
    for color in ((255, 0, 0), (0, 0, 255)):
        frame = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        frame.putpixel((1, 1), (*color, 255))
        frames.append(frame)
    frames[0].save(
        icon_dir / "Ghost.gif", save_all=True, append_images=frames[1:], duration=100, loop=0
    )

    manager = IconManager(icon_dir)
    navy = pygame.Surface((20, 20))
    navy.fill((0, 0, 80))
    navy.blit(manager.get_icon("Ghost"), (0, 0))
    assert navy.get_at((0, 0))[:3] == (0, 0, 80)
    assert navy.get_at((1, 1))[:3] == (255, 0, 0)


def test_icon_manager_without_pillow_falls_back_to_static(pygame_env, tmp_path, monkeypatch):
    """Without Pillow, a multi-frame GIF still loads as its first frame."""
    import weatherstar.media.icons as icons

    icon_dir = tmp_path / "icons"
    icon_dir.mkdir()
    _write_gif(icon_dir / "Cycle.gif", [(255, 0, 0), (0, 255, 0), (0, 0, 255)])

    monkeypatch.setattr(icons, "Image", None)
    manager = icons.IconManager(icon_dir)
    assert not isinstance(manager._find("Cycle"), AnimatedIcon)
    assert _corner(manager.get_icon("Cycle")) == (255, 0, 0)


def test_shipped_animated_icon_decodes_multiple_frames(pygame_env):
    """The classic condition GIFs really animate (regression: first frame only)."""
    from pathlib import Path

    import pytest

    source = Path("static_assets/weatherstar_4000/icons/Freezing-Rain-Sleet.gif")
    if not source.exists():
        pytest.skip("icon assets not present")

    manager = IconManager(source.parent)
    icon = manager._find("Freezing-Rain-Sleet")
    assert isinstance(icon, AnimatedIcon)
    assert len(icon.frames) > 1
    assert icon.total_duration > 0

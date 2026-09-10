"""Weather Star 3000 theme fidelity tests.

Runs the whole screen inventory under the ``weatherstar3000`` theme (real
Star3000 fonts + ws3kp 1.png) and asserts the theme-driven 3000 layout variants:
Current Conditions as a plain text list, Extended Forecast text columns, and
the red-box Hazards screen, plus the theme's text-shadow underlay.
"""

from pathlib import Path

import pygame
import pytest

from tests.test_screens_rich import (
    ALL_SCREENS,
    _registry,
    _Weather,
    current_payload,
)
from weatherstar.config_file import AppConfig
from weatherstar.engine import Builder, SequenceRunner, resolve_location
from weatherstar.registry import registry
from weatherstar.sequence import Sequence
from weatherstar.themes import Theme, theme_search_dirs


def _reload_registered_plugins():
    """Re-register already-imported built-in plugin classes in the global registry.

    A registry snapshot test (test_skeleton) restores the registry to what was
    imported at collection time, which can drop screens/media/components loaded
    later.  Re-register the classes whose modules are already in sys.modules so
    building screens here never hits an empty registry.
    """
    if registry.names("screen"):
        return
    import sys

    prefixes = tuple(
        f"weatherstar.{bag}"
        for bag in ("screens", "components", "datasources", "media", "sequences")
    )
    seen: set[tuple[str, str]] = set()
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "")
        if not name.startswith(prefixes):
            continue
        for obj in vars(module).values():
            if not isinstance(obj, type):
                continue
            kind = getattr(obj, "kind", None)
            plugin_name = getattr(obj, "name", None)
            if kind and plugin_name and (kind, plugin_name) not in seen:
                registry.register(kind, plugin_name, obj)
                seen.add((kind, plugin_name))


@pytest.fixture(autouse=True)
def _plugins_ready():
    _reload_registered_plugins()


SLIDES = "\n".join(f'    {{ screen = "{name}" }},' for name in ALL_SCREENS)

CFG = f"""
sequence = "all"
theme = "weatherstar3000"
[location]
lat = 28.5383
lon = -81.3792
description = "Orlando, FL"
[datasource.stocks]
query = {{ apikey = "test-key" }}
[sequences.all]
pause = 0.001
slides = [
{SLIDES}
]
"""


@pytest.fixture()
def all_appcfg(tmp_path):
    path = tmp_path / "ws3000.toml"
    path.write_text(CFG)
    return AppConfig.from_file(path)


def _runner(all_appcfg, registry):
    builder = Builder(all_appcfg, cli_theme="weatherstar3000")
    name, data = all_appcfg.select_sequence(None)
    sequence = Sequence.from_config(name, data)
    surface = pygame.Surface((640, 480))
    ctx, screens = builder.build_runtime(sequence, surface, resolve_location(all_appcfg))
    ctx.data = registry
    runner = SequenceRunner(ctx, screens, sequence)
    return runner


def _step(runner, name):
    runner.step(ALL_SCREENS.index(name), 0.001)
    return runner.ctx.surface


def test_ws3000_theme_loads_with_assets(all_appcfg, pygame_env):
    """Star3000 fonts + the ws3kp background are discoverable through the theme."""
    from weatherstar.themes import get_theme

    theme = get_theme("weatherstar3000", dirs=theme_search_dirs())
    assert theme.text_shadow is True
    assert theme.text_shadow_offset == 3
    assert theme.bottom_band == "3000"
    assert theme.colors["hazard_bg"] == (0x70, 0x23, 0x23)
    assert theme.layout_for("hazards")["variant"] == "3000"
    assert theme.layout_for("extended_forecast")["variant"] == "3000"
    assert theme.layout_for("current_conditions")["title_style"] == "hidden"
    assert theme.layout_for("local_forecast")["title_text"] == "Your NWS Forecast"
    assert theme.layout_for("almanac")["title_text"] == "The Weatherstar Almanac"
    assert theme.layout_for("regional_forecast")["variant"] == "3000"
    repo_root = Path(__file__).resolve().parents[1]
    assert (repo_root / "static_assets" / "weatherstar_3000" / "fonts").is_dir()
    assert (repo_root / "static_assets" / "weatherstar_3000" / "backgrounds" / "1.png").is_file()


def test_all_ws3000_screens_render_with_populated_data(all_appcfg, pygame_env):
    runner = _runner(all_appcfg, _registry())
    assert runner.validate(frames_per_slide=2, dt=0.001) == []


def test_ws3000_current_conditions_is_text_list(all_appcfg, pygame_env):
    runner = _runner(all_appcfg, _registry())
    surface = _step(runner, "current_conditions")
    # Header is hidden (3000): no glyphs above y=30 in the left third.
    top_band = [surface.get_at((x, y)) for y in range(0, 30) for x in range(0, 200)]
    assert not any(p == (255, 255, 255, 255) for p in top_band)
    # The observation text block starts at the 35px margin, ~40px down.
    body = [surface.get_at((x, y)) for y in range(40, 320) for x in range(35, 600)]
    assert any(p == (255, 255, 255, 255) for p in body)


def test_ws3000_hazards_red_box(all_appcfg, pygame_env):
    runner = _runner(all_appcfg, _registry())
    surface = _step(runner, "hazards")
    # No header; the whole content area is the deep-red hazard box.
    assert surface.get_at((4, 4))[:3] == (0x70, 0x23, 0x23)
    assert surface.get_at((320, 8))[:3] == (0x70, 0x23, 0x23)
    # White uppercase hazard text inside the box.
    text = [surface.get_at((x, y)) for y in range(110, 400) for x in range(80, 560)]
    assert any(p == (255, 255, 255, 255) for p in text)


def test_ws3000_extended_forecast_renders(all_appcfg, pygame_env):
    runner = _runner(all_appcfg, _registry())
    surface = _step(runner, "extended_forecast")
    # Uppercase day + condition text renders in white across the three boxes.
    text = [surface.get_at((x, y)) for y in range(90, 360) for x in range(40, 600)]
    assert any(p == (255, 255, 255, 255) for p in text)


def test_text_shadow_underlay_rendered(pygame_env):
    """3000 text gets a black outline/drop underlay; classic text does not."""
    from weatherstar import render
    from weatherstar.context import AppContext
    from weatherstar.media.fonts import Fonts

    white = (255, 255, 255)

    def draw(theme):
        surface = pygame.Surface((160, 90))
        surface.fill((255, 0, 255))  # magenta: any black/white ink stands out
        ctx = AppContext(surface=surface, theme=theme)
        Fonts.model_validate({"asset_dir": theme.asset_dir}).load(ctx)
        render.draw_text(surface, ctx, "ABC", (10, 20), font_name="normal", color_key="white")
        return surface

    classic = draw(Theme(name="classic", colors={"white": white}))
    ws3000 = draw(
        Theme(
            name="ws3000",
            colors={"white": white, "black": (0, 0, 0)},
            fonts={},  # asset fonts still load via asset_dir
            asset_dir="static_assets/weatherstar_3000",
            text_shadow=True,
            text_shadow_offset=3,
            text_shadow_outline=2,
        )
    )
    classic_has_black = any(
        classic.get_at((x, y)) == (0, 0, 0, 255) for y in range(90) for x in range(160)
    )
    shadowed_has_black = any(
        ws3000.get_at((x, y)) == (0, 0, 0, 255) for y in range(90) for x in range(160)
    )
    assert classic_has_black is False
    assert shadowed_has_black is True
    # The glyph itself still renders white in both cases.
    assert any(p == (255, 255, 255, 255) for p in _scan(ws3000))
    assert any(p == (255, 255, 255, 255) for p in _scan(classic))


def _has_white(surface, x0, y0, x1, y1):
    return any(
        surface.get_at((x, y)) == (255, 255, 255, 255) for y in range(y0, y1) for x in range(x0, x1)
    )


def test_ws3000_local_forecast_rolls_text_below_left_title(all_appcfg, pygame_env):
    runner = _runner(all_appcfg, _registry())
    surface = _step(runner, "local_forecast")
    # Single left-aligned "Your NWS Forecast" title (uppercased) at the top left.
    assert _has_white(surface, 35, 30, 320, 80)
    # The rolling forecast column occupies the text band below the title.
    assert _has_white(surface, 35, 118, 600, 400)


def test_ws3000_almanac_draws_sun_and_moon(all_appcfg, pygame_env):
    runner = _runner(all_appcfg, _registry())
    surface = _step(runner, "almanac")
    # Centered tall title, then sun rows (sunrise/sunset) and moon rows below.
    assert _has_white(surface, 150, 40, 490, 85)
    assert _has_white(surface, 35, 130, 600, 230)
    assert _has_white(surface, 35, 270, 600, 400)


def test_ws3000_regional_observations_table(all_appcfg, pygame_env):
    runner = _runner(all_appcfg, _registry())
    surface = _step(runner, "regional_observations")
    # Column headers + per-station rows render in the band below the title.
    assert _has_white(surface, 35, 100, 600, 405)


def test_ws3000_regional_forecast_table(all_appcfg, pygame_env):
    runner = _runner(all_appcfg, _registry())
    surface = _step(runner, "regional_forecast")
    assert _has_white(surface, 35, 100, 600, 405)


def _scan(surface):
    return [
        surface.get_at((x, y))
        for y in range(surface.get_height())
        for x in range(surface.get_width())
    ]


def test_current_conditions_text_list_rejects_oversized_data(all_appcfg, pygame_env):
    """A long wind condition is shortened/trimmed, never overflow-crashing."""
    payload = current_payload(textDescription="Light Snow Freezing Rain in the Vicinity")
    runner = _runner(all_appcfg, _registry(_Weather(current=payload)))
    surface = _step(runner, "current_conditions")
    assert surface.get_width() == 640

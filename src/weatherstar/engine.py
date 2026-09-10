"""Engine: build plugins from config, then run or validate a Sequence.

Responsibilities:
- resolve the Sequence (CLI > envvar > config),
- instantiate every referenced Screen and its composed Datasource/Media/
  Component plugins, binding config scopes (raising InvalidConfiguration when a
  required scope is missing),
- run the pygame loop with per-slide pauses, or render a validation pass.

The engine is pygame-optional at import time; pygame is only imported inside
methods that need it.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from weatherstar.config_file import AppConfig
from weatherstar.context import AppContext, DataRegistry, Location
from weatherstar.errors import ConfigError, InvalidConfiguration, ThemeNotSupported
from weatherstar.logging_setup import get_logger
from weatherstar.registry import discover, registry
from weatherstar.sequence import Sequence
from weatherstar.themes import DEFAULT_THEME_NAME, ENV_THEME, LayoutVariant, coerce_variant

#: Media plugins auto-loaded into every context when they are registered.
_BASE_MEDIA = ("fonts",)

_log = get_logger("weatherstar.engine")


def resolve_location(
    appcfg: AppConfig, lat: float | None = None, lon: float | None = None
) -> Location:
    """Resolve coordinates from CLI args > [location] config section.

    Raises ConfigError when no usable coordinates can be found.
    """
    if lat is not None and lon is not None:
        return Location(lat=lat, lon=lon)
    loc = appcfg.location
    if loc.lat is not None and loc.lon is not None:
        return Location(
            lat=loc.lat,
            lon=loc.lon,
            description=loc.description or "",
        )
    raise ConfigError(
        "No location configured. Pass --lat/--lon or add a [location] section "
        "with `lat` and `lon` to the config file."
    )


def select_theme_name(appcfg: AppConfig, cli_theme: str | None = None) -> str:
    """Resolve the active theme name: CLI > env > config ``theme`` key."""
    if cli_theme:
        return cli_theme
    env_theme = os.environ.get(ENV_THEME)
    if env_theme:
        return env_theme
    return str(appcfg.data.get("theme", DEFAULT_THEME_NAME))


def music_enabled(appcfg: AppConfig) -> bool:
    """Whether ambient background music is requested via ``[media.music]``."""
    return bool(appcfg.scope("media", "music").get("enabled"))


def requested_variant(ctx: AppContext, screen_name: str) -> LayoutVariant:
    """The variant the active theme requests for a named screen.

    Mirrors ``Renderer.variant`` but resolves for a screen that is not
    necessarily the one currently being drawn (per-screen ``variant`` layout
    token, else ``Theme.variant``).
    """
    token = ctx.theme.layout_for(screen_name).get("variant")
    if token is not None:
        return coerce_variant(token, fallback=ctx.theme.variant, what="variant layout token")
    return ctx.theme.variant


def validate_screen_variants(screens: Iterable[Any], ctx: AppContext) -> None:
    """Fail fast on a screen whose declared variant method is missing, and warn
    when the active theme requests a variant the screen has not declared (which
    will raise ``ThemeNotSupported`` when that screen draws)."""
    for screen in screens:
        cls = type(screen)
        declared = cls.variants or {}
        for variant, method_name in declared.items():
            method = getattr(cls, method_name, None)
            if not callable(method):
                raise InvalidConfiguration(
                    f"{cls.__name__} declares variant {variant.value!r} via "
                    f"`variants = {{...: {method_name!r}}}`, but has no "
                    f"`{method_name}` method. Add it or fix the mapping."
                )
        if not declared:
            continue
        requested = requested_variant(ctx, cls.name)
        if requested not in declared:
            _log.warning(
                "screen_variant_unimplemented",
                screen=cls.name,
                requested=str(requested.value),
                declared=[str(item.value) for item in declared],
            )


class Builder:
    """Constructs datasources/media/components/screens for a sequence."""

    def __init__(
        self,
        appcfg: AppConfig,
        *,
        cli_theme: str | None = None,
        themes_dir: str | None = None,
    ):
        self.appcfg = appcfg
        self._cli_theme = cli_theme
        self._themes_dir = themes_dir
        self.log = get_logger("weatherstar.engine")
        self._music_player = None
        discover()

    # -- per-plugin instantiation -------------------------------------------

    def make(self, kind: str, name: str) -> Any:
        cls = registry.get(kind, name)
        return cls.from_config(self.appcfg.scope(kind, name))

    def build_data(self, names: Iterable[str]) -> DataRegistry:
        data = DataRegistry()
        for name in sorted(names):
            data.register(name, self.make("datasource", name))
        return data

    def make_media(self, name: str, theme_asset_dir: str | None = None) -> Any:
        """Build one media plugin, defaulting ``asset_dir`` to the active theme's.

        Only media kinds the theme actually provides follow the theme's asset
        directory: a theme supplies fonts/backgrounds/logos/icons by shipping the
        matching subdirectory (see each plugin's ``asset_subdirs``). If the theme
        has no such subdirectory, or the media scope sets a custom ``asset_dir``,
        the configured/default directory is used so icons and fonts never vanish
        under a theme that only recolors. Music is ambient, not visual, and is
        never themed.
        """
        cls = registry.get("media", name)
        scope = self.appcfg.scope("media", name)
        subdirs = tuple(getattr(cls, "asset_subdirs", ()))
        if (
            theme_asset_dir
            and subdirs
            and any((Path(theme_asset_dir) / sub).is_dir() for sub in subdirs)
        ):
            configured = scope.get("asset_dir")
            default_asset_dir = cls.model_fields.get("asset_dir", None)
            builtin = default_asset_dir.default if default_asset_dir is not None else None
            if not configured or configured == builtin:
                scope = {**scope, "asset_dir": theme_asset_dir}
        return cls.from_config(scope)

    def build_media(self, names: Iterable[str], ctx: AppContext) -> None:
        theme_asset_dir = getattr(getattr(ctx, "theme", None), "asset_dir", None)
        for name in sorted(names):
            media = self.make_media(name, theme_asset_dir)
            media.load(ctx)

    def make_component(self, spec: Any) -> Any:
        """Instantiate a component for one ``ComponentSpec`` (scope + spec config)."""
        cls = registry.get("component", spec.component)
        scope = self.appcfg.scope("component", spec.component)
        return cls.from_config({**scope, **spec.config})

    def bind_components(self, screens: Iterable[Any], ctx: AppContext) -> None:
        """Build each screen's layout components and prepare them once."""
        for screen in screens:
            instances = []
            for spec in screen.layout:
                component = self.make_component(spec)
                component.prepare(ctx)
                instances.append(component)
            screen.bind_components(instances)

    def build_screens(self, sequence: Sequence) -> list[Any]:
        return [self.make("screen", name) for name in sequence.screen_names()]

    # -- dependency graph -----------------------------------------------------

    def sequence_dependencies(self, sequence: Sequence) -> dict[str, set[str]]:
        kinds = {"datasource": set(), "media": set(), "component": set()}
        for name in sequence.screen_names():
            cls = registry.get("screen", name)
            kinds["datasource"].update(cls.datasources or ())
            kinds["media"].update(cls.media or ())
        # Auto include registered base media that every screen may rely on.
        available = set(registry.names("media"))
        kinds["media"].update(n for n in _BASE_MEDIA if n in available)
        # Music is ambient/config-driven, not a screen dependency: include it
        # whenever [media.music] enabled = true.
        if music_enabled(self.appcfg) and "music" in available:
            kinds["media"].add("music")
        return kinds

    def build_context(
        self,
        surface: Any,
        *,
        location: Location,
        deps: dict[str, set[str]] | None = None,
    ) -> AppContext:
        """Build a fully-populated AppContext for a set of plugin dependencies."""
        from weatherstar.themes import get_theme, theme_search_dirs

        theme = get_theme(
            select_theme_name(self.appcfg, self._cli_theme),
            dirs=theme_search_dirs(self._themes_dir),
        )
        ctx = AppContext(
            surface=surface,
            theme=theme,
            location=location,
        )
        media_names = set(deps["media"]) if deps else set()
        self.build_media(media_names, ctx)
        ctx.icon_manager = ctx.assets.get("icon_manager")
        if deps:
            ctx.data = self.build_data(deps["datasource"])
        return ctx

    def build_runtime(
        self, sequence: Sequence, surface: Any, location: Location
    ) -> tuple[AppContext, list[Any]]:
        deps = self.sequence_dependencies(sequence)
        ctx = self.build_context(surface, location=location, deps=deps)
        screens = self.build_screens(sequence)
        self.bind_components(screens, ctx)
        for screen in screens:
            screen.prepare(ctx)
        validate_screen_variants(screens, ctx)
        return ctx, screens

    def start_music(self, ctx: AppContext) -> bool:
        """Start ambient background music if configured; returns True if playing."""
        if not music_enabled(self.appcfg) or "music" not in registry.names("media"):
            self._music_player = None
            return False
        music = self.make("media", "music")
        started = music.play(ctx)
        self._music_player = music if started else None
        return started

    def advance_music(self) -> None:
        """Advance to the next shuffled track when the current one ends."""
        if self._music_player is not None:
            self._music_player.advance()

    @staticmethod
    def stop_music() -> None:
        from weatherstar.media.music import Music

        Music.stop()


class SequenceRunner:
    """Drives a built sequence on a pygame surface."""

    def __init__(self, ctx: AppContext, screens: list[Any], sequence: Sequence):
        self.ctx = ctx
        self.screens = screens
        self.sequence = sequence
        self.by_name = {screen.name: screen for screen in screens}
        self.log = get_logger("weatherstar.engine")

    def step(self, index: int, dt: float) -> None:
        name = self.sequence.slides[index].screen
        screen = self.by_name[name]
        self.ctx.active_screen = name
        # Advance the shared weather-icon animation clock once per frame.
        icon_manager = getattr(self.ctx, "icon_manager", None)
        if icon_manager is not None and hasattr(icon_manager, "tick"):
            icon_manager.tick(dt)
        screen.step(self.ctx, dt)
        screen.draw(self.ctx.surface, self.ctx, dt)

    def validate(self, frames_per_slide: int = 1, dt: float = 1 / 30) -> list[str]:
        """Render each slide headlessly; return per-slide failures (empty = pass)."""
        failures: list[str] = []
        for index, slide in enumerate(self.sequence.slides):
            for frame in range(frames_per_slide):
                try:
                    self.step(index, dt)
                except Exception as exc:  # noqa: BLE001 - report per slide
                    failures.append(f"{slide.screen} (frame {frame}): {exc!r}")
                    break
        return failures


def run_sequence(
    ctx: AppContext,
    screens: list[Any],
    sequence: Sequence,
    *,
    fps: int = 30,
    interactive: bool = False,
    max_frames: int | None = None,
    stop_event: Any = None,
    music_controller: Any = None,
) -> int:
    """Execute a sequence, returning the number of frames drawn.

    Non-interactive: slides auto-advance by their pause duration and a single
    full pass is drawn.  Interactive: a pygame event loop until QUIT/ESC.
    When a ``music_controller`` (e.g. an engine ``Builder``) is supplied its
    ``advance_music()`` is polled each frame so the playlist keeps moving.
    """
    import pygame

    from weatherstar.ticker import BottomTicker, WeatherStar3000Scroll

    runner = SequenceRunner(ctx, screens, sequence)
    if (
        getattr(getattr(ctx, "theme", None), "bottom_band", LayoutVariant.WS4000)
        == LayoutVariant.WS3000
    ):
        ticker: Any = WeatherStar3000Scroll()
    else:
        ticker = BottomTicker()
    clock = pygame.time.Clock()
    slide_index = 0
    slide_elapsed = 0.0
    frames = 0
    running = True

    while running:
        dt_ms = clock.tick(fps)
        dt = dt_ms / 1000.0
        frames += 1

        if interactive:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                        delta = -1 if event.key == pygame.K_LEFT else 1
                        slide_index = (slide_index + delta) % len(sequence.slides)
                        slide_elapsed = 0.0

        # Auto-advance by the per-slide pause in both interactive and
        # non-interactive modes. Interactive runs wrap around forever;
        # non-interactive runs stop after a single pass.
        finished = False
        slide_elapsed += dt_ms
        pause_ms = int(sequence.pause_for(slide_index) * 1000)
        if pause_ms > 0:
            while slide_elapsed >= pause_ms:
                slide_elapsed -= pause_ms
                slide_index += 1
                if slide_index >= len(sequence.slides):
                    if interactive:
                        slide_index = 0
                        slide_elapsed = 0.0
                    else:
                        finished = True
                    break
                pause_ms = int(sequence.pause_for(slide_index) * 1000)
                if pause_ms <= 0:
                    break
        elif interactive or slide_index < len(sequence.slides) - 1:
            # A zero pause means "advance immediately", one slide per frame.
            slide_index = (slide_index + 1) % len(sequence.slides)
            slide_elapsed = 0.0
        else:
            finished = True

        if finished:
            running = False
            break

        try:
            runner.step(slide_index, dt)
        except ThemeNotSupported as exc:
            # A screen without the active theme's layout variant degrades to a
            # friendly placeholder instead of a blank slide / traceback.
            from weatherstar import render

            _log.warning("screen_theme_not_supported", screen=exc.screen_name)
            render.draw_centered_text(
                ctx.surface,
                ctx,
                "SCREEN DOES NOT SUPPORT THIS THEME",
                240,
                font_name="large",
                color_key="yellow",
            )
        ticker.render(ctx.surface, ctx, dt)
        if music_controller is not None:
            advance = getattr(music_controller, "advance_music", None)
            if advance is not None:
                advance()
        if pygame.display.get_surface() is not None:
            pygame.display.flip()

        if max_frames is not None and frames >= max_frames:
            running = False
        if stop_event is not None and stop_event.is_set():
            running = False

    return frames

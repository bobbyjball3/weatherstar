# Architecture

This document explains how the Weather Star plugin engine is put together.
Everything lives under `src/weatherstar/`.

## At a glance

The app renders a timed, looping sequence of **screens** on a pygame surface.
Each screen is a *plugin* that declares which **datasources** feed it, which
**media** (fonts, backgrounds, logos, icons, music) it decorates itself with,
and any per-plugin configuration. At runtime the **engine** reads a TOML config,
instantiates the referenced plugins, wires a shared **context**, and drives the
render loop; a bottom **ticker** crawls across every screen and music plays in
the background.

```
        config.toml ──► AppConfig ──► Builder ──► AppContext/DataRegistry
        (XDG/env/CLI)     │                 │            │
                          ▼                 ▼            ▼
                   sequence chosen      plugins      screens built &
                   from [sequences.*]  instantiated   prepared
                                                    │
                         run_sequence ◄─────────────┘
                       (render loop, 30 fps)
                          │      │
                 per-slide pause   ticker overlay  (BottomTicker)
                          │      └── music advance (Builder.advance_music)
                          ▼
                   pygame.display.flip()
```

## The five plugin kinds

Every plugin is a subclass of `Plugin` (in `plugin.py`), which is itself a
Pydantic `BaseModel`. Plugins self-register with the `@plugin` decorator and are
grouped by `kind`:

| Kind | Base class | Example | Purpose |
| --- | --- | --- | --- |
| `screen` | `Screen` | `radar`, `current_conditions` | One full-screen "display" |
| `component` | `Component` | `header`, `background`, `clock`, `headlines`, `data_table` | Reusable renderers placed on screens |
| `media` | `Media` | `fonts`, `backgrounds`, `icons`, `music` | Loads local assets into the context |
| `datasource` | `Datasource` | `weather`, `history`, `stocks` | Fetches data behind a typed API |
| `sequence` | (config-declared) | `main` | Named ordered run of screens |

Both `Screen` and `Component` inherit `Renderer` (in `renderer.py`), a mixin of
*concrete* drawing helpers (`font`, `color`, `datasource`, `latlon`,
`blit_text`, `wrap`, `centered`, `format_date`, …) so renderers share one
implementation instead of re-declaring `_font`/`_color` helpers per file.

### Screens

`Screen` (in `screens/base.py`) subclasses declare metadata as `ClassVar`s —
`layout`, `datasources`, `media` — so Pydantic never treats them as config
fields. A screen's `layout` is an ordered tuple of `ComponentSpec` entries
(component name + per-instance config); the engine builds one component
instance per spec and `Screen.draw` (concrete) steps + renders them before
calling the `compose(surface, ctx, dt)` hook. Screens are therefore mostly
"what components to place", leaving only genuinely screen-specific placement/
animation to `compose`. Screens are deliberately defensive: they read data
through helpers that catch and degrade to a "no data" message, so a missing or
slow datasource never crashes the show.

### Components

`Component` (in `components/base.py`) is the smallest composable renderer. The
engine builds each screen's layout components (merging `[component.<name>]`
config scope with the spec's `config`) and `Screen.draw` renders them in order.
Stateful components (e.g. `headlines`, `data_table`) keep their scroll offsets
as `PrivateAttr`, advance in `step(ctx, dt)` and draw in `render(surface, ctx)`.
Components that fetch their own data take a `datasource_name` config and read
through the context.

### Media

`Media` plugins load local assets from an `asset_dir` (default
`static_assets/weatherstar_4000/…`) and register them on the context:

- `fonts` → `ctx.fonts` (named `pygame.font.Font` objects)
- `backgrounds` / `logos` / `icons` → `ctx.assets` dicts plus
  `ctx.assets["icon_manager"]`
- `music` → discovers tracks; playback is *owned by the engine*, not the media
  plugin (see below).

### Datasources

`Datasource` (in `datasources/base.py`) is a `Plugin` with common config
(`timeout`, `user_agent`) and HTTP plumbing shared by all feeds:

- a `requests.Session` built lazily per instance with the configured
  `User-Agent` and any auth derived from sensitive fields (`_session_for`);
- `http_get_json(...)` / `http_get_bytes(...)` / `http_post_json(...)` with
  timeout, status logging and graceful `None` on failure;
- a per-instance TTL cache applied with the `@cached(ttl)` decorator, so a
  fetch method is written as a plain API call and the cache stays invisible.

Auth fields typed as Pydantic `SecretStr` (e.g. `stocks.api_key`) are unwrapped
only at the point of use (`get_secret_value()`), and query-param style keys
(`api_key_param`) are injected per request via `_query_params`.

## Registry and discovery

`registry.py` holds a process-wide `PluginRegistry` mapping
`(kind, name) -> class`. Built-ins are discovered by importing every module in
the plugin bags (`plugins/__init__.py` walks `screens`, `components`,
`media`, `datasources`, `sequences`). External plugins register through entry
points in the `weatherstar.plugins` group. `registry.discover()` is
idempotent and is called once by the engine/CLI.

## Configuration

Config is loaded by `config_file.py` (`AppConfig`) and applied per plugin via
Pydantic:

- The file is discovered from `--config` > `WEATHERSTAR_CONFIG` >
  `~/.config/weatherstar/config.toml` (`xdg_config_file`).
- `AppConfig.scope(kind, name)` returns the `[<kind>.<name>]` section, which
  `Plugin.from_config(...)` feeds to `model_validate`. Missing required fields
  raise `InvalidConfiguration` with the offending scope and a TOML example.
- Non-plugin sections (`sequence`, `theme`, `[location]`, `[video]`,
  `[logging]`, `[sequences.*]`) are read by small typed accessors on
  `AppConfig`. Theme *bodies* are separate `*.theme.toml` files (see
  `docs/THEMES.md`); the `theme` key only names which to activate.

Because plugins are Pydantic models with `Field(description=...)` annotations,
`skeleton.py` can generate a fully commented example config
(`weatherstar generate-config`) — descriptions are rendered inline as
`#` comments, and required/secret fields appear as commented `# key = "value"`
placeholders. See `docs/CONFIGURATION.md`.

## Context

`context.py` provides the objects threaded through rendering:

- `Location` — resolved lat/lon/label.
- `DataRegistry` — named `Datasource` instances the screens read through
  (`ctx.data.get("weather")`).
- `AppContext` — surface, theme, `fonts`, `assets`, `icon_manager`,
  `location`, and conveniences (`colors`, `font`, `asset`, `size`). It replaces
  the old monolithic `ws` object; screens never reach into a god object.

Themes live in `themes.py` plus one TOML file per theme (`builtin_themes/`
ships the defaults; users add their own next to XDG config). A `Theme` carries a
name/title, a (partial) color palette, an optional `asset_dir`, and optional
font overrides. `AppContext.colors` merges the selected theme over a small
in-code `BASE_COLORS` (the keys screens read directly), so a partial palette
never KeyErrors. When a theme's `asset_dir` is set, the engine builds the media
plugins against it, so themed fonts/backgrounds/logos/icons load automatically.
See `docs/THEMES.md` for the file format and discovery rules.

## Engine

`engine.py` contains the two main pieces:

- `Builder` resolves the sequence, then constructs every referenced plugin from
  config: `build_data`, `build_media`, `build_screens`, `make_component`, and
  `bind_components` (which builds each screen's layout components and prepares
  them), plus `build_context`, which assembles the fully-populated
  `AppContext` for the run. It also owns music lifecycle (`start_music`,
  `advance_music`, `stop_music`).
- `run_sequence(...)` is the render loop (30 fps by default). Each frame it
  steps and draws the current slide, advances on the slide's `pause`, wraps
  around forever in interactive mode (or does one pass in non-interactive
  mode), draws the `BottomTicker`, polls the music controller, and flips the
  display.

`SequenceRunner.validate(...)` reuses the built screens but only *draws* each
slide once headlessly (no window, datasources usually stubbed) — this powers
`weatherstar --validate` and the integration tests.

### Bottom ticker

`ticker.py` (`BottomTicker`) draws the authentic navy banner + white crawling
text over the bottom of every screen. Content is rebuilt from the `weather`
datasource on an interval (`+++ CITY, STATE +++`, current conditions, today /
tonight) with a static fallback.

### Music

Music is **ambient and config-driven**, not a screen dependency: when
`[media.music] enabled = true` the engine includes the `music` media, shuffles
the discovered tracks, starts a random first song, and advances through the
shuffle as each track ends (`Music.advance`, polled every frame). Loading
headless/validate never starts audio.

## Logging

`logging_setup.py` configures structlog over stdlib logging with severity-ANSI
console output, an optional JSON-lines file sink, and a redaction processor that
masks sensitive keys and any `SecretStr` values — so credentials never reach
logs.

## Headless testing

`tests/conftest.py` forces SDL dummy drivers before pygame imports, so the whole
suite (and `--validate`) runs on CI machines without a display. External APIs
are never hit in tests: datasource tests monkeypatch `http_get_json`, and the
integration test swaps the real `DataRegistry` for benign stubs.

## Key design decisions

- **Plugins are Pydantic models.** Typed fields replace hand-rolled config
  descriptors: validation, coercion, defaults and JSON schema come for free,
  and `Field(description=...)` drives generated documentation.
- **Non-config metadata is `ClassVar`.** `kind`, `name`, `media`,
  `datasources`, etc. are annotated `ClassVar` so they never become config
  fields.
- **Secrets are `SecretStr`.** They are masked in `repr`/`str` and by the log
  redactor, and unwrapped only at the HTTP boundary.
- **Runtime state is `PrivateAttr`.** Pydantic forbids undeclared attributes, so
  engine-injected state (sessions, caches, scroll offsets, playlist) is declared
  as private attributes.
- **Screens compose components.** A screen's job is *which* components to place
  and *how/if* to animate them; `layout` + `ComponentSpec` describe that
  declaratively, `Screen.draw` renders the bound components, and heavy
  behaviors (scrolling headline lists, row-jump tables) live in stateful
  components that own their data and scroll state.
- **Config discovery is standard-library.** `--config` > env var > XDG file,
  and plugin discovery via importlib entry points — no framework needed.
- **Rendering is defensive.** Every datasource read is wrapped; missing data
  renders a "NO DATA" message rather than crashing the loop.
- **Themes are data, not code.** A `Theme` is a value object parsed from a
  `*.theme.toml` file; screens/components never branch on the theme name. The
  theme only changes what the shared context resolves (colors, media `asset_dir`,
  fonts) plus the header's product line, so the same screen code renders any look.

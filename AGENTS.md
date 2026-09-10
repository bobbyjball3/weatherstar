# AGENTS.md

Guidance for AI agents working in this repository. It captures how the code is
structured, the non-obvious rules the codebase depends on, and the standards to
follow when changing it.

## Project status: plugin engine

This is **`weatherstar`**, a pygame recreation of The Weather Channel's Weather Star
local forecast. The app is a **plugin-driven engine** living directly under
`src/weatherstar/`. There is no legacy monolith anymore — it was removed,
so do not reintroduce references to legacy modules like `displays`,
`history_graphs`, `get_local_news`, etc. `themes.py` and the `datasources/*`
clients are their self-contained replacements.

Runtime + docs entry points:
- `README.md` — minimal orientation only; links to `docs/`.
- `docs/DEVELOPMENT.md` — tooling, tasks, CI, repo layout, current status.
- `docs/ARCHITECTURE.md` — internal architecture and design decisions.
- `docs/CONFIGURATION.md` — config guide + full commented example.
- `docs/THEMES.md` — theme files: format, discovery, active-theme selection.

## Toolchain & commands

Python 3.10 (`uv`), ruff, pytest, Task, pre-commit. All commands run through
`uv run`. Ruff: line length 100, rules `E4 E7 E9 F I UP W`; first-party import
group `weatherstar`.

```sh
uv sync                # install (project + dev deps, pinned by uv.lock)
task test              # unit suite (excludes ffmpeg integration tests)
task test-integration  # ffmpeg integration tests (requires ffmpeg on PATH)
task coverage          # unit tests with coverage (gate: 85)
task check             # ruff lint + format check
task deadcode          # vulture unused-code report
uv run weatherstar --sequence main --lat 28.5383 --lon -81.3792 --validate  # headless render check
uv run weatherstar generate-config --sequence main                          # regenerates commented config skeleton
```

Run the quality gates with `task check`, tests+coverage with `task coverage`,
real-encoder tests with `task test-integration`, and the dead-code report with
`task deadcode`. CI runs `task check`, `task coverage` (Python 3.10 + 3.12) and
`task test-integration` (with ffmpeg) — a change is not done until those pass.

## Test conventions (important)

- Tests run **headless**: `tests/conftest.py` forces `SDL_VIDEODRIVER=dummy` /
  `SDL_AUDIODRIVER=dummy` before pygame imports. Use the `pygame_env`, `screen`
  (640×480 surface), `display`, and `fonts` fixtures.
- **No network in tests.** Unit-test datasources by installing an
  `httpx.MockTransport` (or `monkeypatch.setattr(ds, "send", fake)`); never
  hit real APIs. Screens that would fetch (e.g. radar) are tested by swapping
  the whole data registry for stubs.
- Two screen-testing styles:
  - Empty/no-data stubs (the "NO DATA" path): `tests/test_integration_screens.py`.
  - **Populated-data** stubs that drive the real rendering branches:
    `tests/test_screens_rich.py`. New data-dependent screen branches belong
    here (or in that style). The rich suite is why coverage is ~85%.
- **Do not add `# pragma: no cover`.** Cover behavior honestly; raise the
  coverage `fail_under` in `pyproject.toml` only when the suite's real coverage
  comfortably exceeds it.
- **No wall-clock time dependence.** Unit tests must not `time.sleep` to let
  work happen or assert on `time.monotonic()` deltas. Inject `clock`/`sleep`
  for rate logic (see `streaming.audio._pace_write`), synchronize threads with
  `threading.Event`/queues, and trigger stop conditions deterministically
  (e.g. hook `write_frame`). The only exception is tests that drive a real
  ffmpeg encoder: mark them `@pytest.mark.integration`, and run them via
  `task test-integration` (the `test`/`coverage` tasks run `-m "not
  integration"`; CI has a separate `test-integration` job with ffmpeg).
- **Plugin import order pollution:** importing a plugin module (via the
  `@plugin` decorator) registers it in the global registry *at import time*.
  Pytest collects test modules alphabetically, so a module-level
  `from weatherstar.screens.… import …` in one test file can change what
  a later file (e.g. `test_skeleton.py`, which snapshots the registry) sees.
  Keep plugin imports *inside test functions* unless the test file is
  self-contained about registry state.

## Architecture map

```
config.toml -> AppConfig (config_file.py) -> Builder -> AppContext/DataRegistry
        -> run_sequence (engine.py) draws each Slide on a pygame surface,
           overlays BottomTicker, advances the music controller
```

`src/weatherstar/`:
- `plugin.py` — `Plugin(BaseModel)`; config helpers; the base-vended `@memoize`
  decorator (per-instance, optional `ttl`) so plugins never hold cache state.
- `registry.py` — `@plugin`, `PluginRegistry`, built-in + entry-point discovery.
- `renderer.py` — `Renderer` mixin: concrete font/color/data/blit/wrap helpers
  shared by both Screens and Components.
- `screens/base.py`, `components/base.py`, `datasources/base.py`, `media/base.py` — the
  plugin-kind bases. Screens declare an ordered `layout` of `ComponentSpec`
  (component name + per-instance config); the engine binds a component instance
  per spec, and `Screen.draw` steps+renders them then calls `compose`.
  (`sequence.py` sequences are config-declared, not plugins.)
  Datasources keep request construction (`_<op>_request`) and response reading
  (`_<op>_response`) in separate methods and pass both to `Datasource.fetch`;
  decorate the public method with `@memoize(ttl=...)` to cache it.
- `context.py` — `AppContext`, `DataRegistry`, `Location`.
- `engine.py` — `Builder` (build runtime from config) + `run_sequence` /
  `SequenceRunner` (render + headless validate).
- `cli.py` — `weatherstar` (run / `--validate` / `generate-config`).
- `skeleton.py` — generates the commented config from field descriptions.
- `logging_setup.py` — structlog with SecretStr/key redaction.
- `ticker.py` — bottom crawling banner over every slide (the classic navy crawler;
  themes may swap it for the Weather Star 3000 scroll band via ``bottom_band``).
- `themes.py` — `Theme` model, TOML loader/discovery; `builtin_themes/` ships
  the data files (default/base theme is `weatherstar4000`).
- `plugins/__init__.py` — `load_builtin_plugins()` imports every module in
  `screens`, `components`, `datasources`, `media`, `sequences` so they register.

Kinds and current inventories:
- **screen (26):** 26 display modules in `screens/` (incl. the regional_forecast
  screen that has no classic WS4000 equivalent but is a Weather Star 3000 staple).
- **datasource (8):** `alerts`, `earthquakes`, `history`, `local_news`,
  `radar`, `stocks`, `uv_index`, `weather`.
- **media (5):** `fonts`, `backgrounds`, `logos`, `icons`, `music`.
- **component (5):** `background`, `clock`, `header`, `headlines`, `data_table`.

## Hard rules for plugin classes (Pydantic `BaseModel`)

These are load-bearing — violating them raises at class definition or runtime:

1. **Config fields are annotated Pydantic fields.** `timeout: int = 10`,
   `api_key: SecretStr`. Defaults → optional; no default → required. Add a
   `Field(description="…")` to *every* config field: the description is emitted
   as a comment by `generate-config`, so config docs stay in sync with code.
2. **Non-config metadata must be `ClassVar`** (annotated or inherited).
   `kind`, `name`, `media`, `datasources`, `components`, `background`,
   `asset_key`, `position`, `status`, … are metadata, not fields. A brand-new
   plain (un-annotated) class attribute is an error
   (`PydanticUserError: non-annotated attribute`). You may *override* an
   inherited `ClassVar` with a plain assignment (`name = "radar"`).
3. **No undeclared instance attributes.** Pydantic raises if you set an
   attribute that is not a field. Runtime state must be declared:
   `_scroll: float = PrivateAttr(default=200.0)` (leading underscore +
   `PrivateAttr`), or `default_factory` for mutable defaults. Do not write
   `self.buffer = {}` unless `_buffer` is a declared `PrivateAttr`.
4. **Build plugins with `cls.model_validate(scope)` / `Plugin.from_config`.**
   Do not hand-instantiate + assign fields. `model_validate` bypasses any custom
   `__init__`, so init-time state belongs in `PrivateAttr` defaults or
   `model_post_init`, not a custom `__init__`.
5. **Instantiate/configure is separate from construct.** Engine builds an
   instance once from config; a screen must not need per-frame config work.
6. **Secrets are `SecretStr`.** Unwrap only at the HTTP boundary
   (`value.get_secret_value()`). `repr`/`str`/logs stay masked automatically;
   the structlog redactor also masks by key name (see `logging_setup.py`).
7. **Keep values descriptive** — datasource config scopes are matched by
   `kind.name` (`[datasource.stocks]`), so a plugin `name` must be unique within
   its kind.
8. **Theme layout variants are declared, not branched.** A screen with alternate
   layout families declares them as a `variants: ClassVar[dict[LayoutVariant,
   str]]` mapping, e.g.
   `{LayoutVariant.WS4000: "compose_4000", LayoutVariant.WS3000: "compose_3000"}`,
   and implements one `compose_<variant>` method per entry. Every `compose_*`
   shares the `(surface, ctx, dt)` signature and fetches its own data (no
   pre-fetched arguments from `compose`). `Screen.compose` dispatches on the
   active theme's requested variant (per-screen `variant` layout token >
   `Theme.variant` > `"4000"`) and raises `ThemeNotSupported` when the variant
   is not declared; the engine degrades to a friendly placeholder at runtime
   and records it as a failure under `--validate`. Component-only screens (no
   `compose` code) leave `variants` empty. Layout-family names come from the
   closed `LayoutVariant` enum (`"4000"`/`"3000"`), never open strings; the same
   enum types `Theme.variant` and `Theme.bottom_band`.

## Data contracts (fabStub targets)

Datasources speak realistic payloads so screens can be driven headlessly:

- `weather.get_current(lat, lon)` → NOAA observation `properties` dict. Numeric
  quantities are `{"value": <float>, ...}`: `temperature`/`dewpoint`/
  `heatIndex`/`windChill` in °C, `windSpeed` in km/h (yes, inconsistent with
  `wind_pressure`'s m/s assumption — read each screen before changing units),
  `visibility` in meters, `barometricPressure`/`pressure` in Pa,
  `cloudLayers` = `[{"amount": "BKN"|"OVC"|…, "base": {"value": meters}}]`,
  plus `textDescription`, `icon` URL, `station`, `timestamp`.
- `weather.get_forecast/get_hourly` → `{"periods": [ … ]}`. Periods carry
  `name`, `isDaytime`, `temperature` (°F), `shortForecast`,
  `detailedForecast`, `icon` URL, `startTime` (ISO).
- `history.temperature` → `[(date, high, low)]`; `history.precipitation` →
  `[(date, inches)]`; both most-recent-first; `scroll(t)` + `scroll_offsets`
  tuple drive row-jump scrolling.
- `uv_index.daily` → `[{"date": "YYYY-MM-DD", "uv_index": <num>}]`.
- `earthquakes.recent` → `[{"magnitude", "place", "time"(ms)}]`.
- `stocks.quotes()` → `[{"symbol", "price", "change", "change_percent"}]`
  (bare numbers for change_percent — the screen does not strip a `%`).
- `local_news.city_name` → str (return `""` to fall back to weather/location);
  `headlines` → `[(title, url)]`.
- `alerts.active` → list of dicts with `severity` (capitalized!),
  `event`, `headline`, `areas`, `instruction`, `expires` (ISO).
- `radar.frames` → list of `pygame.Surface`; `radar.frame_times` → one UTC
  `datetime` per frame, aligned with `frames` (future-radar valid times).

**Screens are defensive:** they wrap every datasource read and degrade to a
"NO DATA" / centered message rather than raising. When adding a screen, follow
that pattern — `ctx.data.get(name)` may raise `KeyError` (unknown or stubbed),
`location` may be `None`, and values may be malformed.

## Engine invariants

- Sequence auto-advance happens in **both** interactive and non-interactive
  modes (interactive wraps forever; non-interactive does one pass). Pause
  comes from config: `[sequences.<name>] pause` global, overridable per slide
  `{ screen = "x", pause = 5.0 }`.
- A bottom band is drawn over every slide (see `ticker.py`): the classic navy
  `BottomTicker` crawler by default (banner top ≈ `height - 50`, i.e. y≈430 on
  480px), or the Weather Star 3000 date/time + crawl scroll when a theme sets
  `bottom_band = "3000"` (that band starts at y≈405). **Screen content must stay
  above ~y=424 (classic) / ~y=400 (3000)** or it will be hidden under the band
  (see the severe-alert layout as the reference solution).
- Music is ambient/config-driven, not a screen dependency: `[media.music]
  enabled = true` → engine includes `music` media, shuffles tracks, starts a
  random first song and advances when each ends. `Builder.advance_music()` is
  polled each frame. `--validate`/headless must never start audio.
- Config discovery: `--config` > `WEATHERSTAR_CONFIG` > XDG
  (`~/.config/weatherstar/config.toml`). Sequence precedence: CLI >
  `WEATHERSTAR_SEQUENCE` > top-level `sequence`. Location: `--lat/--lon` >
  `[location]`.
- `generate-config` output is the source of truth for `docs/CONFIGURATION.md`;
  if you change config fields/descriptions, regenerate both.

## Style & contribution checklist

- Follow ruff (it auto-fixes on commit via pre-commit). Keep diff formatting
  clean: run `uv run ruff check src tests` and `uv run ruff format src tests`.
- Match surrounding style: module docstring, `from __future__ import
  annotations`, no unused imports, descriptive names.
- Every change to plugin config must add/update the `Field(description=…)`.
- New screens/datasources/components must be `@plugin`-decorated with unique
  `name` + correct `kind` base; they auto-register via the module bags — no
  central registration list to edit.
- Keep tests deterministic and offline; prefer behavior over pixel-perfect
  assertions (assert non-blank / no-exception / expected text, not exact
  framebuffers).
- Before committing: `task check` + `task coverage` green (coverage ≥ 80).

# Themes

The Weather Star engine is themed by name. A theme changes the look and
feel of every screen — colors, the fonts/backgrounds/logos/icons asset tree it
loads, and the product line shown in the screen header — without any per-screen
code branching on the theme. Themes are **data** (one TOML file per theme), so
adding or tweaking a look never requires writing Python.

## Choosing the active theme

The active theme is just a name:

```sh
uv run weatherstar --sequence main --theme weatherstar3000
# or in config.toml
theme = "weatherstar3000"
```

Selection precedence: `--theme` > `WEATHERSTAR_THEME` > the top-level `theme`
key > `weatherstar4000` (the authentic Weather Star 4000 look).

## Where theme files live

Each theme is a `*.theme.toml` file whose **file stem is the theme name**
(e.g. `weatherstar3000.theme.toml` → `weatherstar3000`). They are discovered
from these directories, highest precedence first:

1. `--themes-dir` / `WEATHERSTAR_THEMES_DIR`
2. `~/.config/weatherstar/themes/` (XDG user themes)
3. the built-in themes shipped inside the package (`builtin_themes/`)

Earlier directories shadow later ones by name, so a user theme can override a
built-in (or any other theme) of the same name. Malformed theme files are
skipped with a warning rather than aborting the run.

Built-in themes: `weatherstar4000` (default/base), `dark`, `high_contrast`,
`retro_green`, `amber`, and `weatherstar3000`.

## File format

```toml
# <name>.theme.toml  (file stem = theme name)
title = "Weather Star 3000"     # product name (progress/loading text)
title_bottom = "3000"          # header bottom line; blank if unset
asset_dir = "static_assets/weatherstar_3000"  # media tree (default "static_assets/weatherstar_4000")

[colors]
# Palette keys layered over the engine's small built-in base palette
# (white, yellow, blue, cyan, red). Colors are "#RRGGBB" hex or [r, g, b].
yellow = "#FFFFFF"
white = "#FFFFFF"
black = "#000000"
blue_gradient_1 = "#09246F"
blue_gradient_2 = "#364AC0"
cyan = "#8FFDFA"
red = "#FF4D4D"

[fonts]                 # optional: point the named font slots at your own files
title = ["ws3000.ttf", 32]
large = ["ws3000.ttf", 32]
normal = ["ws3000.ttf", 20]
```

### `colors`

Renderers read semantic keys (`white`, `yellow`, `blue`, `cyan`, `red`,
`blue_gradient_1`/`blue_gradient_2`, `purple_header`, `up`, `down`, ...).
`AppContext.colors` layers a theme's palette over a small in-code `BASE_COLORS`
(the keys screens read directly), so a theme file may be **partial** — any key
it omits falls back to the base value. Only define what your look overrides.

### `asset_dir`

When set, the media plugins (`fonts`, `backgrounds`, `logos`, `icons`) load from
`<asset_dir>/fonts/`, `<asset_dir>/backgrounds/`, etc. instead of the repo's
`static_assets/weatherstar_4000/`. This is how a theme supplies its own typeface,
background art, logos and icons with no code changes.

A theme's asset tree applies **per media kind**: the engine only switches a media
plugin to the theme's directory when that subdirectory actually exists there.
A theme that ships `icons/` but no `backgrounds/` themes icons while keeping the
classic backgrounds; a theme with no asset tree at all (a recolor-only theme)
keeps the classic icons, fonts, backgrounds and logos. Precedence for a given
media kind: an explicit `[media.X] asset_dir` in the main config wins over the
theme; otherwise the theme's directory is used when it provides the subdirectory,
falling back to the built-in `static_assets/weatherstar_4000` when it does not.
So icons and fonts never vanish under a theme that merely recolors the palette.

### `fonts`

Optional map of the named font slots (`title`, `large`, `extended`, `small`,
`normal`, `forecast`, `tiny`, `scroller`) to `[file, size]`. A theme that
points these at its own TTF files (e.g. the Weather Star 3000 typeface) uses them
when present; otherwise the classic filenames are used.

A theme may also **add** new slots, not just override existing ones. The 3000
theme introduces a `datetime` slot for its bottom-band date/time block, which
uses the separate short "Star3000 Small" face:

```toml
[fonts]
datetime = ["Star3000 Small.ttf", 24]
```

### `bottom_band`

Which always-on bottom band overlays every slide. Defaults to `"4000"` — the
navy Weather Star 4000 crawler. A theme that reserves the bottom of the canvas
for a different band opts in with a value:

```toml
bottom_band = "3000"   # Weather Star 3000 scroll: date + time over a crawling line
```

`"3000"` draws the real 3000 foot-of-canvas scroll (a small date/time row above a
rotating current-conditions line, all over the shared background art). Screens
must keep content above ~y=405 under that band.

Like `variant`, `bottom_band` is drawn from the closed `LayoutVariant` enum
(`"4000"` / `"3000"`); an unknown value falls back to `"4000"` with a warning.

### `text_shadow`

The 1980s Weather Star 3000 look draws every text glyph with a black outline ring
plus a right/down drop shadow (the ws3kp `text-shadow` stack). Themes opt in:

```toml
text_shadow = true
text_shadow_offset = 3     # drop distance in px (right/down)
text_shadow_outline = 2    # outline stroke width in px
```

When `text_shadow` is false (the default) text renders with no underlay, exactly
as the classic Weather Star 4000 screens do. The outline color comes from the
theme's `black` palette key.

### `layout`

Layout is theme-driven data, not code. A `[layout]` table carries per-screen
tokens that Screens read back at draw time (merged over an optional `default`
entry applied to every screen):

```toml
[layout.default]               # applied to every screen first
show_logo = false              # draw the corner logo?
show_noaa = false              # draw the NOAA mark?
show_clock = false             # draw the top-right live clock/date?
title_style = "tall"           # "dual" | "tall" | "single" | "hidden"
title_align = "center"         # "left" | "center"
title_color = "white"          # palette key for the header title
title_font = "title"           # font slot for the header title

[layout.current_conditions]    # per-screen overrides beat the defaults
title_style = "hidden"
variant = "3000"               # request this screen's Weather Star 3000 layout
```

Header tokens drive the shared header/clock components. A screen with a
genuinely different Weather Star 3000 layout (e.g. Current Conditions as a plain
text list) is *requested* through the `variant` token — but which variants a
screen actually implements is declared in code, never branched in the theme.

Screens declare their layout families and renderers:

```python
class CurrentConditionsScreen(Screen):
    variants = {
        LayoutVariant.WS4000: "compose_4000",  # classic WS4000 layout
        LayoutVariant.WS3000: "compose_3000",  # ws3kp text-list layout
    }

    def compose_4000(self, surface, ctx, dt): ...
    def compose_3000(self, surface, ctx, dt): ...
```

`Screen.compose` resolves the active theme's request (per-screen `variant` token
> the theme's top-level `variant` > `"4000"`) and dispatches to the matching
`compose_<variant>` method. All `compose_*` methods share the `(surface, ctx,
dt)` signature and fetch their own data. A screen that has no alternate layout
declares nothing (empty inherited `variants`) and renders purely through its
`layout` components.

The theme *name* is never the dispatch key — that keeps recolor-only themes
(`dark`, `amber`, …) on the `"4000"` layout with zero code. Layout families are
the closed `LayoutVariant` enum (`"4000"` / `"3000"`), shared by `Theme.variant`
and `Theme.bottom_band`.

Two more header tokens deserve mention:

- `title_text` / `title_sub` override the header *text itself*, so a screen's
  classic two-line title can read differently under a theme without changing the
  screen's layout component (the 3000 Almanac becomes "The Weatherstar Almanac"):
  ```toml
  [layout.almanac]
  title_text = "The Weatherstar Almanac"
  variant = "3000"
  ```
- `show_headline_footer` (default `true`) hides the news screens' "Updated …"
  line, which the 3000 bottom band replaces.

Screens may read any token for their own geometry. For example the 3000 theme
tightens the Weather Records list so its last line clears the taller bottom
band:

```toml
[layout.weather_records]
row_step = 28
section_gap = 12
heading_gap = 30
```

Tokens are optional and default to each screen's in-code constants, so a theme
that sets none of them reproduces the classic layout exactly.

#### Missing variant renderers degrade gracefully

When a theme requests a `variant` a screen has not declared (say `variant =
"3000"` on a screen with no `compose_3000`), drawing that screen raises
`ThemeNotSupported`. The engine catches it: interactive runs draw a centered
`SCREEN DOES NOT SUPPORT THIS THEME` placeholder and log a warning, while
`--validate` records it as a per-slide failure. The builder also fails fast at
startup when a screen's `variants` map names a method that does not exist (a
typo in the mapping).

## Adding your own theme

1. Drop a `<name>.theme.toml` into `~/.config/weatherstar/themes/`
   (or point `--themes-dir` at a directory of your own).
2. Set `theme = "<name>"` in `config.toml` (or pass `--theme <name>`).

You can shadow/extend any built-in by naming your file after it. There is no
central registry to update — discovery is purely file-based.

# Weather Star — Configuration

The engine reads one TOML file that configures the plugin graph: which
sequence to run, where to point the datasources, window/logging behavior, and
overrides for any plugin's typed config fields.

## Where the file lives

| Source | Path / value |
| --- | --- |
| `--config` CLI flag | explicit path |
| `WEATHERSTAR_CONFIG` | explicit path |
| Default (XDG) | `~/.config/weatherstar/config.toml` |

A config file is **not** required if you pass `--sequence`, `--lat` and `--lon`
on the command line.

## Generating a skeleton

Every configurable value is declared on the plugin classes with a description,
so you can always regenerate a fully commented starting point that stays in sync
with the code:

```sh
uv run weatherstar generate-config --sequence main -o ~/.config/weatherstar/config.toml
```

Fill in any `# REQUIRED` keys and uncomment the values you want to change.

## Precedence

* **Sequence**: `--sequence` > `WEATHERSTAR_SEQUENCE` > the top-level
  `sequence` key.
* **Location**: `--lat`/`--lon` > the `[location]` section.
* **Theme**: `--theme` > `WEATHERSTAR_THEME` > the top-level `theme` key >
  `weatherstar4000`.
* **Plugin scopes** (`[datasource.*]`, `[media.*]`, `[component.*]`,
  `[screen.*]`) are matched by plugin `kind.name`; each overrides that plugin's
  declared defaults.

## Themes

The `theme` key only *names* the active theme; the theme body lives in its own
`*.theme.toml` file (see `docs/THEMES.md`). Theme files are discovered from a
`--themes-dir`/`WEATHERSTAR_THEMES_DIR` directory, then
`~/.config/weatherstar/themes/`, then the built-ins shipped with the app.
A theme's `asset_dir` supplies its own fonts/backgrounds/logos/icons and is used
by the media plugins unless a `[media.*] asset_dir` is set explicitly.

## Example

Below is the output of `weatherstar generate-config --sequence main`
with the location filled in for Orlando, FL. Every value is documented inline.
```toml
# Weather Star configuration skeleton.
# Generated per-plugin from declared typed config fields.
# Every configurable value is documented inline; uncomment keys you want
# to change and fill in REQUIRED values.

# Sequence to execute (override with --sequence or WEATHERSTAR_SEQUENCE).
sequence = "main"

# Active visual theme (override with --theme or WEATHERSTAR_THEME).
# Available: amber, dark, high_contrast, retro_green, weatherstar3000, weatherstar4000
theme = "weatherstar4000"

[location]
# Latitude used to center weather data (e.g. 28.5383).
# lat = 28.5383
# Longitude used to center weather data (e.g. -81.3792).
# lon = -81.3792
# Human-readable location label shown on screen (optional).
description = "Orlando, FL"

[video]
# Window width in pixels.
width = 640
# Window height in pixels.
height = 480
# Target frames per second.
fps = 30

[sequences.main]
# Default seconds each slide is shown (per-slide `pause` overrides).
pause = 15.0
slides = [
    { screen = "air_quality" },
    { screen = "almanac" },
    { screen = "current_conditions" },
    { screen = "earthquakes" },
    { screen = "extended_forecast" },
    { screen = "hazards" },
    { screen = "hourly_forecast" },
    { screen = "local_forecast" },
    { screen = "local_news" },
    { screen = "marine_forecast" },
    { screen = "monthly_outlook" },
    { screen = "precipitation_history" },
    { screen = "progress" },
    { screen = "radar" },
    { screen = "regional_forecast" },
    { screen = "regional_observations" },
    { screen = "severe_weather_alert" },
    { screen = "stock_market" },
    { screen = "sun_moon" },
    { screen = "temperature_graph" },
    { screen = "temperature_history" },
    { screen = "travel_cities" },
    { screen = "uv_index" },
    { screen = "weather_records" },
    { screen = "weekend_forecast" },
    { screen = "wind_pressure" },
]

[datasource.alerts]
# HTTP request timeout in seconds.
timeout = 10
# User-Agent header sent with upstream API requests.
user_agent = "weatherstar (python)"
# Colon-separated severity order used to sort alerts (most severe first).
severity_priority = "extreme:severe:moderate"

[datasource.earthquakes]
# HTTP request timeout in seconds.
timeout = 10
# User-Agent header sent with upstream API requests.
user_agent = "weatherstar (python)"
# Minimum earthquake magnitude to include.
min_magnitude = 3.0
# Maximum number of earthquakes to fetch.
limit = 10

[datasource.history]
# HTTP request timeout in seconds.
timeout = 10
# User-Agent header sent with upstream API requests.
user_agent = "weatherstar (python)"

[datasource.local_news]
# HTTP request timeout in seconds.
timeout = 10
# User-Agent header sent with upstream API requests.
user_agent = "weatherstar (python)"
# Webz.io API key (sent as a Bearer token; empty disables live news).
api_key = ""
# Free-text news search query (e.g. 'News in Carmel, Indiana').
news_query = ""
# The number of stories to retrieve from webz (default 10).
story_count = 10
# A list of languages to use for news story searches.
languages = ["english"]
# List of two-letter country codes to use for news story searches.
countries = ["US"]
# List of categories to use when searching news stories from webz.io.
news_categories = ["Crime, Law and Justice"]
# Number of days to look in the past for news stories.
news_day_count = 10

[datasource.radar]
# HTTP request timeout in seconds.
timeout = 10
# User-Agent header sent with upstream API requests.
user_agent = "weatherstar (python)"

[datasource.stocks]
# HTTP request timeout in seconds.
timeout = 10
# User-Agent header sent with upstream API requests.
user_agent = "weatherstar (python)"
# Alpha Vantage API key (required; sent with each request).
# REQUIRED - supply a value for this key.
# api_key = "value"
# Query parameter the API key is sent under.
api_key_param = "apikey"
# Comma-separated stock/index symbols to display.
symbols = "DIA,SPY,QQQ"

[datasource.uv_index]
# HTTP request timeout in seconds.
timeout = 10
# User-Agent header sent with upstream API requests.
user_agent = "weatherstar (python)"
# Number of days of UV index forecast to fetch.
days = 7

[datasource.weather]
# HTTP request timeout in seconds.
timeout = 10
# User-Agent header sent with upstream API requests.
user_agent = "weatherstar (python)"

[media.backgrounds]
# Directory containing this media's assets (project-relative or absolute).
asset_dir = "static_assets/weatherstar_4000"

[media.fonts]
# Directory containing this media's assets (project-relative or absolute).
asset_dir = "static_assets/weatherstar_4000"

[media.icons]
# Directory containing this media's assets (project-relative or absolute).
asset_dir = "static_assets/weatherstar_4000"

[media.logos]
# Directory containing this media's assets (project-relative or absolute).
asset_dir = "static_assets/weatherstar_4000"

[media.music]
# Directory containing this media's assets (project-relative or absolute).
asset_dir = "static_assets/weatherstar_4000"
# Play background music during the show.
enabled = true
# Music volume, from 0.0 (silent) to 1.0 (full).
volume = 0.6

[component.background]
# Background asset key to fill the screen (e.g. '1'..'6').
background_name = "1"

[component.clock]

[component.data_table]
# Datasource whose rows this table shows.
# REQUIRED - supply a value for this key.
# datasource_name = "value"
# Datasource method called with (lat, lon) to fetch rows.
# REQUIRED - supply a value for this key.
# rows_method = "value"
# Ordered column definitions.
# REQUIRED - supply a value for this key.
# columns = "value"
# Index into datasource scroll_offsets used when scrolling.
scroll_offset_index = 0
# Advance via datasource.scroll() when rows exceed max_rows.
scroll = true
# Rows visible before scrolling engages.
max_rows = 8
# Top of the header row.
start_y = 120
# Centered empty message.
empty_text = "Data unavailable"

[component.header]
# Top line of the screen header.
title_top = "Weather Star"
# Bottom line of the screen header. When blank, the active theme's product line (e.g. '3000') is shown instead.
title_bottom = ""
# Show the NOAA mark to the right of the header title.
has_noaa = false

[component.headlines]
# Prefix each headline with a yellow number (1., 2., ...).
numbered = true
# Headline accent style: split categories on ':' and color the prefix.
accent = "category"
# Category keywords drawn in red (category accent only).
red_terms = ["BREAKING", "EMERGENCY", "ALERT"]
# Category keywords drawn in yellow (category accent only).
yellow_terms = ["UPDATE"]
# Optional datasource whose headlines() supplies content each render.
datasource_name = ""
# Centered message shown when there is no content.
empty_text = "No headlines are available right now"

[screen.air_quality]

[screen.almanac]

[screen.current_conditions]

[screen.earthquakes]

[screen.extended_forecast]

[screen.hazards]

[screen.hourly_forecast]

[screen.local_forecast]

[screen.local_news]

[screen.marine_forecast]

[screen.monthly_outlook]

[screen.precipitation_history]

[screen.progress]

[screen.radar]

[screen.regional_forecast]

[screen.regional_observations]

[screen.severe_weather_alert]

[screen.stock_market]

[screen.sun_moon]

[screen.temperature_graph]

[screen.temperature_history]

[screen.travel_cities]

[screen.uv_index]

[screen.weather_records]

[screen.weekend_forecast]

[screen.wind_pressure]

[logging]
# Minimum log level: DEBUG, INFO, WARNING, ERROR or CRITICAL.
level = "INFO"
# Write logs to the console (colorized).
console = true
# Optional JSON-lines log file path; omit to disable file logging.
# file = "logs/weatherstar.jsonl"
```

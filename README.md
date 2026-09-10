# Weather Star

A recreation of The Weather Channel's Weather Star local forecast
presentation — the 1990s Weather Star 4000 and the Weather Star 3000 are both
available as built-in themes.

## Attributions

The genuinely hard parts of this project were never the code. Recreating these
broadcasts means gathering the right typefaces, backgrounds, logos, icons and
radar maps, then endlessly matching colors, geometry, timing, typography and
layout until it *feels* like the real thing. All of that painstaking work sits
on the shoulders of people and projects who documented, preserved and rebuilt
this material long before this repository existed. The code here is the easy
part — a plugin engine and a couple of themes that tie their work together —
and I want to be clear about whose shoulders it stands on.

### Reference implementations & assets

- **[wesellis/weatherstar-4000](https://github.com/wesellis/weatherstar-4000)** —
  this project started as a fork of Wes Ellis's Weather Star 4000 recreation,
  and it has since evolved well beyond it — the architecture, theming and much
  of the code are now our own. But without that project's inspiration and its
  hard work reproducing the WS4K look and feel, none of this would have gotten
  started. It remains the root this tree grew from, and deserves the credit for
  it.
- **[netbymatt/ws3kp](https://github.com/netbymatt/ws3kp)** (MIT) — an
  open-source Weather Star 3000 simulator and the single biggest influence on
  this project. The entire `weatherstar3000` theme is matched against its
  implementation: its SCSS geometry and text-shadow stacks drive our layout
  tokens, scroll band, colors and screen arrangements (Current Conditions as a
  plain text list, the Local Forecast crawl, the Almanac sun/moon table, the
  red Hazards box, the regional observation tables, and more). Its art is also
  vendored directly — the shared deep-blue background it drew from scratch and
  its copies of the Star3000 typeface. See
  [`static_assets/weatherstar_3000/README.md`](static_assets/weatherstar_3000/README.md).
- **[Nick Smith / TWCClassics](http://twcclassics.com)** — the authentic
  Weather Star typefaces. The Star3000 face came into this project via ws3kp,
  and the classic Star4000 face that anchors the default look is drawn from the
  same community archive. Matching layouts to these fonts is most of the visual
  fidelity battle.
- **[The Weather Channel / Weather Star Archive](https://www.twcarchive.com)** —
  the definitive video and wiki record of the actual Weather Star 3000 and 4000
  products. It is the ground truth this project is checked against for product
  names, screen behavior and era-specific details.
- **The Weather Channel itself** — none of the look here is original; it is a
  faithful reproduction of broadcasts The Weather Channel created and aired in
  the 1980s and 1990s. Those belong to them, not to this project.

### Live data

The on-screen weather, history and news content comes from free/public data
providers rather than anything we host:

- **NOAA / National Weather Service** (`api.weather.gov`) — current conditions,
  forecasts, hourly data, alerts and radar imagery.
- **Open-Meteo** — 30-day temperature/precipitation history and UV index.
- **USGS Earthquake Hazards Program** — recent earthquakes.
- **Alpha Vantage** — stock and index quotes (requires a free API key).

### Built on

pygame, pydantic, `ephem` (for the almanac's sun and moon math), structlog,
httpx and cachetools — the unglamorous foundations everything above renders
through.

None of these projects or providers endorse this one. If anything here is
wrong, it is my error, not theirs; if anything looks right, it is because of
them. Vendored assets are used under their own licenses, noted where they
ship.

## AI Disclosure

I used an LLM to write this project. Specifically OpenCode and DeepSeek. If that is of concern to you, I understand totally, you can probably stop here and you should pass on this.

However, if you made it this far into my disclosure, you might be interested to know that I also am at odds with AI. I'm a developer of some 20y and have always prided myself on my abilities to pattern match, rapidly learn new information, and build great things. But there is no denying that when it comes to highly structured, well documented, and objectively measurable outcomes AI does accelerate delivery. I have read every line of code, designed the software itself and the abstractions, and personally use this project. That doesn't mean I agree with every choice the LLM has made, but I'm a believer in "you can have help, or you can have it your way" - you can't have both. So I let go of a good deal of implementation in favor of guiding the overall behaviors, abstractions, and structure of the code in a way I feel pretty good about. Though having used several models, I don't think DeepSeek produces the highest quality admittedly. I have to do the same with real people every day at work as I lead projects and implementations.

For me, LLMs and AI are double-edged swords. There is no getting around that having something or someone else do something for you removes you from some implementation choices and the knowledge gained along the way. But I have come to the conclusion that when it comes to my hobbies (many of which fall into categories where LLMs excel), it is a force multiplier. More importantly for me though, it allows me to enjoy some of my hobbies and design and build solutions that I wouldn't have otherwise had time for. And it does so in a way that let's me be just as or more present and a part of the other, more important parts of my life - My small family, my pets, my friends, my home, etc. There was a time in my life where I'd spend an entire weekend at a computer, rage rewriting or implementing something to solve a problem I had. But I simply cannot do that today and there are other more important things to me.

I wrestle morally with the fact LLMs have undoubtedly stolen and been trained on the material that others fought hard to produce. The technology itself, it's compute, power, water, and space requirements, and the impacts those things have on our world are on my mind pretty constantly as I use it. I also worry deeply about responsible use of AI by us humans and the havoc it is already wreaking on education, social and emotional intelligence, and mental health. And so I try and use it responsibly and efficiently. In my industry there is no escaping LLMs and AI, and I suspect that will be true for all of us whether we know it or not. I look forward to more ethical options for LLMs (that still maintain quality/efficiency), more efficient systems to run those models, and a more responsible social approach to how AI integrates into our lives. I hope that in the future we can use LLMs and AI to accomplish more, solve big problems for humanity, and generally free us up to invest our time in the people and projects around us that uplift us all. At the end of it, I'm choosing to use the tools despite my misgivings and beliefs. That's a personal choice, but at least you know why (for whatever that's worth). Oh, and no AI used at all in this disclosure - ha.

## What it is

`weatherstar` renders the classic Weather Star local forecast show — current
conditions, radar, forecasts, news and more — using pygame. The app is
plugin-driven: every screen, datasource, media type and component is a
discoverable plugin with typed, documented configuration. A theme swaps the
whole visual identity: colors, fonts, assets, and the layout era
(`weatherstar4000` by default, `weatherstar3000` for the 3000 look).

## Running the app

Requires Python 3.10 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync

# Create a commented config (see docs/CONFIGURATION.md), then run:
uv run weatherstar --config ~/.config/weatherstar/config.toml

# Or run ad hoc with command-line location + a built-in default sequence:
uv run weatherstar --sequence main --lat 28.5383 --lon -81.3792
```

Useful flags:

| Flag | Purpose |
| --- | --- |
| `--config PATH` | Config file (default `~/.config/weatherstar/config.toml`) |
| `--theme NAME` | Visual theme (`weatherstar4000`, `weatherstar3000`, …) |
| `--sequence NAME` | Sequence to run (defaults from config) |
| `--lat` / `--lon` | Location coordinates |
| `--validate` | Headless: render every slide once and report failures |
| `generate-config` | Emit a commented config skeleton to stdout or `-o PATH` |

Run `weatherstar --help` for the full list.

## Documentation

| Doc | Contents |
| --- | --- |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Configuring the app — with a fully commented example config |
| [docs/THEMES.md](docs/THEMES.md) | Themes: the 3000/4000 looks and how to add your own |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the plugin engine is put together |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Tooling, tests, CI, and the dev workflow |
| [docs/STREAMING.md](docs/STREAMING.md) | Broadcasting the show as a Jellyfin TV channel (optional) |

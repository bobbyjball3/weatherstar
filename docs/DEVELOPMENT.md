# Development

Everything a developer needs to build, test, and iterate on Weather Star.
This project is managed end-to-end with modern Python tooling:

| Tool | Purpose | Invoked via |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | Build / run / package / dependency management | `uv …` |
| [ruff](https://docs.astral.sh/ruff/) | Linting and formatting | `uv run ruff …` |
| [pytest](https://docs.pytest.org/) | Testing (with coverage via pytest-cov) | `uv run pytest …` |
| [Task](https://taskfile.dev) | Project task runner (checks, tests, CI) | `task …` |
| [pre-commit](https://pre-commit.com) | Git hook framework for commit-time checks | `uv run pre-commit …` |

Everything that runs in CI also runs locally through the same `task` commands,
so results are reproducible between your machine and GitHub Actions.

## Quick start

Prerequisites: Python 3.10 and [uv](https://docs.astral.sh/uv/) installed.

```sh
# Install task (taskfile.dev runner)
sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b "$HOME/bin"
export PATH="$HOME/bin:$PATH"

# Create the environment (project + dev dependencies), pinned by uv.lock
uv sync

# Install the git pre-commit hooks
task install-hooks
```

The Python version is pinned in `.python-version` (`3.10`). `uv sync` reads it
so your local environment matches CI.

## Everyday workflow

```sh
task check            # ruff lint + ruff format --check
task fix              # auto-fix what ruff can (mirrors the pre-commit hooks)
task coverage         # unit test suite with branch coverage + reports
task test-integration # ffmpeg integration tests (requires ffmpeg on PATH)
task deadcode         # report unused code (vulture)
```

### Available tasks

Run `task --list` or see [`Taskfile.yml`](../Taskfile.yml). All tasks execute
their tools through `uv run`, so they work on any machine with uv installed.

| Task | Command | Description |
| --- | --- | --- |
| `install` | `uv sync` | Sync project and dev dependencies |
| `lint` | `uv run ruff check src tests` | Lint the package and tests |
| `lint-fix` | `uv run ruff check --fix src tests` | Auto-fix lint issues |
| `format` | `uv run ruff format src tests` | Format code |
| `format-check` | `uv run ruff format --check src tests` | Verify formatting |
| `check` | `lint` + `format-check` | All quality gates |
| `fix` | `lint-fix` + `format` | Auto-fix everything possible |
| `test` | `uv run pytest -m "not integration"` | Run the unit test suite |
| `test-integration` | `uv run pytest -m integration` | Run the ffmpeg integration tests |
| `coverage` | `uv run pytest -m "not integration" --cov …` | Unit tests with coverage + XML report |
| `deadcode` | `uv run vulture` | Report unused code (config in `pyproject.toml`) |
| `install-hooks` | `uv run pre-commit install` | Install pre-commit hooks |

## Tool configuration

All tool configuration lives in [`pyproject.toml`](../pyproject.toml):

- **ruff** — `[tool.ruff]`, targets Python 3.10, 100-column lines, `src`
  layout. Lint rules enabled (`[tool.ruff.lint]`): `E4`, `E7`, `E9`, `F`,
  `I`, `UP`, `W`; everything fixable is auto-fixed.
- **pytest** — `[tool.pytest.ini_options]`; discovers tests in `tests/`, always
  writes a JUnit report to `reports/junit.xml`, and runs with
  `--continue-on-collection-errors` so one broken test module does not abort
  the whole suite.
- **coverage** — `[tool.coverage.run]` measures only code owned by this package
  (`source = ["src/weatherstar"]`) with branch coverage enabled. The
  `fail_under` gate in `[tool.coverage.report]` is a ratchet: raise it as
  coverage grows.
- **vulture** — `[tool.vulture]` scans `src/weatherstar` and `tests` for unused
  code. Plugin classes (registered by `@plugin` + name) and name-dispatched
  methods (`compose_*`) are excluded via `ignore_decorators`/`ignore_names` and
  the committed [`vulture_whitelist.py`](../vulture_whitelist.py). Run it with
  `task deadcode`; it is not part of the blocking `task check` gate.

### pre-commit

[`.pre-commit-config.yaml`](../.pre-commit-config.yaml) runs ruff in **fix
mode** on every commit: safe lint fixes and formatting are applied
automatically, and the commit is blocked if anything could not be fixed. The
hook ruff version is pinned to match the version uv locked in the dev group.

## CI

GitHub Actions is defined in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml). It runs on push to
`main`/`master` and on pull requests, and is split into two stages:

### Quality stage

Each ruff check runs in its **own job** so failures are easy to isolate:

| Job | Runs | Tool |
| --- | --- | --- |
| `ruff-check` | `task lint` | ruff lint |
| `ruff-format` | `task format-check` | ruff format |

Both run on a single Python version (3.10).

### Testing stage

| Job | Runs | Notes |
| --- | --- | --- |
| `test` | `task coverage` | Unit tests, Python 3.10 + 3.12 matrix |
| `test-integration` | `task test-integration` | Installs ffmpeg, runs the `integration`-marked tests |

The `test` job then:

1. **Publishes a test report** to the PR/commit checks
   (`EnricoMi/publish-unit-test-result-action`), generated from
   `reports/junit.xml`.
2. **Posts a coverage comment** on the PR
   (`MishaKav/pytest-coverage-comment`), generated from `coverage.xml`. The
   report is limited to package-owned code in `src/weatherstar` and
   includes branch coverage.
3. Uploads `reports/junit.xml` and `coverage.xml` as a downloadable artifact.

Reports are only published when the token has write access (same-repo branches
and pushes). On pull requests from external forks the token is read-only, so the
publishing steps are skipped — the artifact is still uploaded.

### Running tests on more Python versions

The `test` job uses a strategy matrix:

```yaml
matrix:
  python-version: ['3.10', '3.12']
```

Add versions to that list to run the unit suite across them. Each matrix cell is
pinned by overwriting `.python-version`, so CI never drifts from the committed
lockfile. The `test-integration` job runs a single version since it exists to
exercise the real ffmpeg encoder, not Python-version behaviour.

## Repository layout

```
pyproject.toml            uv / ruff / pytest / coverage configuration
Taskfile.yml              task runner commands
.pre-commit-config.yaml   commit-time ruff (fix mode) hooks
.github/workflows/ci.yml  Quality + Testing CI pipeline
.github/actions/setup     reusable CI step: uv + task + dependency sync
src/weatherstar/     the plugin-driven engine (see docs/ARCHITECTURE.md)
  builtin_themes/         shipped *.theme.toml files (see docs/THEMES.md)
tests/
  conftest.py             headless SDL dummy drivers + pygame fixtures
  test_*.py               unit + integration tests for the engine
docs/                     user + developer documentation
static_assets/            bundled asset trees, one per era/product
  weatherstar_4000/           fonts, backgrounds, icons, logos, music (classic)
  weatherstar_3000/           fonts + background for the Weather Star 3000 look
reports/                  JUnit output (gitignored, generated)
coverage.xml              coverage output (gitignored, generated)
README.old.md             original project README (features, packaging)
```

## Current status

- The app is a **plugin-driven engine** under `src/weatherstar/` (the
  legacy monolithic implementation was removed). Plugins are Pydantic models
  whose typed fields drive a TOML config, auto-discovery and a generated
  commented config skeleton.
- **Themes are data**: a `Theme` is loaded from a `*.theme.toml` file
  (`themes.py` parses/loads them; `builtin_themes/` ships the defaults — see
  `docs/THEMES.md`). A theme changes colors, the media `asset_dir` (fonts/
  backgrounds/logos/icons) and the header product line; screens never branch on
  the theme name.
- The test suite runs headless via dummy SDL drivers (`tests/conftest.py`) with
  external APIs mocked. Screens are exercised both with empty stubs (the
  no-data path) and with populated-data stubs (`tests/test_screens_rich.py`)
  that drive the real rendering branches. `task coverage` enforces
  `fail_under` in `[tool.coverage.report]` (currently 85 — ratchet up as
  coverage grows); package-wide coverage is ~90%.
- Useful smoke checks:
  ```sh
  uv run weatherstar generate-config --sequence main   # commented TOML
  uv run weatherstar --sequence main --lat 28.54 --lon -81.38 --validate
  ```

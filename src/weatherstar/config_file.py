"""TOML configuration loading for the Weather Star engine.

Discovery order for the config file:
    1. ``--config`` CLI value
    2. ``WEATHERSTAR_CONFIG`` environment variable
    3. ``~/.config/weatherstar/config.toml`` (XDG default)

The engine requires either a discoverable config file or explicit CLI arguments
covering the sequence/location, per the refactor requirements.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

try:  # Python >= 3.11
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 backport
    import tomli as tomllib

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from weatherstar.errors import ConfigError, SequenceError

ENV_CONFIG = "WEATHERSTAR_CONFIG"
ENV_SEQUENCE = "WEATHERSTAR_SEQUENCE"


#: Non-plugin, top-level TOML sections that carry real options.  Each is a
#: Pydantic model so the typed defaults/descriptions (used by ``skeleton.py``
#: and ``generate-config``) live in exactly one place.
class LocationConfig(BaseModel):
    """The ``[location]`` section: where to center weather data."""

    model_config = ConfigDict(extra="forbid")

    lat: float | None = Field(
        default=None,
        description="Latitude used to center weather data (e.g. 28.5383).",
    )
    lon: float | None = Field(
        default=None,
        description="Longitude used to center weather data (e.g. -81.3792).",
    )
    description: str = Field(
        default="",
        description="Human-readable location label shown on screen (optional).",
    )


class VideoConfig(BaseModel):
    """The ``[video]`` section: window dimensions and frame rate."""

    model_config = ConfigDict(extra="forbid")

    width: int = Field(default=640, description="Window width in pixels.")
    height: int = Field(default=480, description="Window height in pixels.")
    fps: int = Field(default=30, description="Target frames per second.")


class LoggingConfig(BaseModel):
    """The ``[logging]`` section: log level and sinks."""

    model_config = ConfigDict(extra="forbid")

    level: str = Field(
        default="INFO",
        description="Minimum log level: DEBUG, INFO, WARNING, ERROR or CRITICAL.",
    )
    console: bool = Field(
        default=True,
        description="Write logs to the console (colorized).",
    )
    file: Path | None = Field(
        default=None,
        description="Optional JSON-lines log file path; omit to disable file logging.",
    )


def xdg_config_file() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "weatherstar" / "config.toml"


def discover_config_path(explicit: str | None = None) -> Path | None:
    """Return the config path to use, or None if none can be found."""
    if explicit:
        return Path(explicit)
    env = os.environ.get(ENV_CONFIG)
    if env:
        return Path(env)
    default = xdg_config_file()
    if default.exists():
        return default
    return None


def load_toml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc


class AppConfig:
    """Typed-ish view over the raw parsed configuration dict."""

    def __init__(self, data: dict[str, Any], *, path: Path | None = None):
        self.data = data
        self.path = path

    # -- sections ----------------------------------------------------------

    def scope(self, kind: str, name: str) -> dict[str, Any]:
        """Return the config scope dict for a plugin, or {} when absent."""
        return dict(self.data.get(kind, {}).get(name, {}) or {})

    # -- sequence selection -------------------------------------------------

    def default_sequence(self) -> str | None:
        value = self.data.get("sequence")
        return str(value) if value else None

    def sequence_names(self) -> list[str]:
        return sorted((self.data.get("sequences") or {}).keys())

    def get_sequence(self, name: str) -> dict[str, Any]:
        sequences = self.data.get("sequences") or {}
        if name not in sequences:
            raise SequenceError(
                f"Sequence {name!r} is not defined in the config. "
                f"Available sequences: {', '.join(sorted(sequences)) or '(none)'}."
            )
        return dict(sequences[name])

    def select_sequence(self, cli_value: str | None = None) -> tuple[str, dict[str, Any]]:
        """Resolve the sequence name from CLI > envvar > config ``sequence`` key."""
        name = cli_value or os.environ.get(ENV_SEQUENCE) or self.default_sequence()
        if not name:
            raise ConfigError(
                "No sequence specified. Pass --sequence, set "
                f"{ENV_SEQUENCE}, or add a top-level `sequence` key to the config."
            )
        return name, self.get_sequence(name)

    # -- top-level option sections -------------------------------------------

    def _section(self, name: str, model: type[BaseModel]) -> BaseModel:
        cache = self.__dict__.setdefault("_typed_sections", {})
        if name not in cache:
            raw = self.data.get(name) or {}
            try:
                cache[name] = model.model_validate(raw)
            except ValidationError as exc:
                details = "; ".join(
                    f"{'.'.join(str(part) for part in error.get('loc') or ())}: "
                    f"{error.get('msg', 'invalid value')}"
                    for error in exc.errors()
                )
                raise ConfigError(f"Invalid [{name}] section in config: {details}") from exc
        return cast(BaseModel, cache[name])

    @property
    def location(self) -> LocationConfig:
        return cast(LocationConfig, self._section("location", LocationConfig))

    @property
    def video(self) -> VideoConfig:
        return cast(VideoConfig, self._section("video", VideoConfig))

    @property
    def logging(self) -> LoggingConfig:
        return cast(LoggingConfig, self._section("logging", LoggingConfig))

    # -- module-level conveniences ------------------------------------------

    @classmethod
    def from_file(cls, path: Path) -> AppConfig:
        return cls(load_toml(path), path=path)

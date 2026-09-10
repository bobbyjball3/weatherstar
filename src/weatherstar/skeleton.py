"""Generate a commented skeleton TOML config for a chosen sequence.

The skeleton enumerates every registered plugin (Screen/Component/Media/
Datasource) with its declared typed config fields and their descriptions
rendered as ``#`` comments, plus the top-level ``[location]`` / ``[video]`` /
``[logging]`` sections and a sample ``[sequences.<name>]`` block, so a user has
a complete, commented starting point.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, SecretStr

from weatherstar import registry
from weatherstar.config_file import (
    ENV_SEQUENCE,
    LocationConfig,
    LoggingConfig,
    VideoConfig,
)

KIND_ORDER = ("datasource", "media", "component", "screen")

#: Top-level (non-plugin) sections rendered straight from the config models in
#: ``config_file.py``.  The dict value maps a key to an example shown commented
#: out (a "fill me in" value like coordinates or an optional log file path).
_TOP_LEVEL_SECTIONS: tuple[tuple[str, type[BaseModel], dict[str, Any]], ...] = (
    ("location", LocationConfig, {"lat": 28.5383, "lon": -81.3792}),
    ("video", VideoConfig, {}),
    ("logging", LoggingConfig, {"file": "logs/weatherstar.jsonl"}),
)


def _toml_repr(value: Any) -> str:
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_repr(v) for v in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{k} = {_toml_repr(v)}" for k, v in value.items())
        return "{" + inner + "}"
    return repr(value)


def _comment_lines(description: str | None) -> list[str]:
    if not description:
        return []
    return [f"# {line}" for line in description.strip().splitlines() if line.strip()]


def _render_model_section(
    parts: list[str],
    section: str,
    model_cls: type[BaseModel],
    examples: dict[str, Any],
) -> None:
    """Render ``[section]`` from a config model; ``examples`` keys are commented."""
    parts.append(f"[{section}]")
    for key, field in model_cls.model_fields.items():
        parts.extend(_comment_lines(field.description))
        if key in examples:
            parts.append(f"# {key} = {_toml_repr(examples[key])}")
        else:
            default = field.get_default(call_default_factory=True)
            parts.append(f"{key} = {_toml_repr(default)}")
    parts.append("")


def _render_plugin_scope_lines(kind: str, name: str, cls: type) -> list[str]:
    lines = [f"[{kind}.{name}]"]
    for key, field in cls.model_fields.items():
        lines.extend(_comment_lines(field.description))
        sensitive = cls.is_sensitive_field(key)
        if field.is_required() or sensitive:
            lines.append("# REQUIRED - supply a value for this key.")
            lines.append(f'# {key} = "value"')
        else:
            default = field.get_default(call_default_factory=True)
            lines.append(f"{key} = {_toml_repr(default)}")
    lines.append("")
    return lines


def render_skeleton(
    sequence_name: str = "main",
    screen_names: Iterable[str] | None = None,
    include_kinds: Iterable[str] = KIND_ORDER,
) -> str:
    """Render a full commented example config as TOML text."""
    screen_names = list(screen_names) if screen_names is not None else None
    parts: list[str] = [
        "# Weather Star configuration skeleton.",
        "# Generated per-plugin from declared typed config fields.",
        "# Every configurable value is documented inline; uncomment keys you want",
        "# to change and fill in REQUIRED values.",
        "",
        f"# Sequence to execute (override with --sequence or {ENV_SEQUENCE}).",
        f'sequence = "{sequence_name}"',
        "",
    ]

    # Active theme.  The theme body lives in its own *.theme.toml file (see
    # docs/THEMES.md); this key only names which one to use.
    from weatherstar.themes import available_themes

    parts.append("# Active visual theme (override with --theme or WEATHERSTAR_THEME).")
    parts.append("# Available: " + ", ".join(available_themes()))
    parts.append('theme = "weatherstar4000"')
    parts.append("")

    # Top-level, non-plugin sections (rendered from the config models).
    for section, model_cls, examples in _TOP_LEVEL_SECTIONS[:2]:
        _render_model_section(parts, section, model_cls, examples)

    # Screen-specific generated skeleton: start from every registered screen.
    screens: list[str] = []
    if screen_names is None:
        screens = registry.registry.names("screen")
    else:
        screens = list(screen_names)

    parts.append(f"[sequences.{sequence_name}]")
    parts.append("# Default seconds each slide is shown (per-slide `pause` overrides).")
    parts.append("pause = 15.0")
    parts.append("slides = [")
    for name in screens:
        parts.append(f'    {{ screen = "{name}" }},')
    parts.append("]")
    parts.append("")

    for kind in include_kinds:
        for name in registry.registry.names(kind):
            cls = registry.registry.get(kind, name)
            parts.extend(_render_plugin_scope_lines(kind, name, cls))

    section, model_cls, examples = _TOP_LEVEL_SECTIONS[2]
    _render_model_section(parts, section, model_cls, examples)

    return "\n".join(parts)

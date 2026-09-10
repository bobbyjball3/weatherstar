"""Tests for skeleton config generation."""

try:  # Python >= 3.11
    import tomllib
except ModuleNotFoundError:  # Python 3.10 backport
    import tomli as tomllib

from pydantic import Field, SecretStr

from weatherstar.plugin import Plugin
from weatherstar.registry import registry
from weatherstar.skeleton import render_skeleton

# Guard: never pollute the real registry between runs.
_BASE_REGISTRY = {k: dict(v) for k, v in registry._plugins.items()}


def _reg(kind, name, fields=None, module="tests.test_skeleton"):
    """Register a plugin; ``fields`` maps field_name -> (type, default)."""
    attrs = {"kind": kind, "name": name, "__module__": module}
    annotations: dict[str, type] = {}
    for field_name, spec in (fields or {}).items():
        annotation = spec[0]
        annotations[field_name] = annotation
        if len(spec) > 1:
            attrs[field_name] = spec[1]
    if annotations:
        attrs["__annotations__"] = annotations
    cls = type(name, (Plugin,), attrs)
    registry.register(kind, name, cls)
    return cls


def _restore():
    registry._plugins.clear()
    registry._plugins.update({k: dict(v) for k, v in _BASE_REGISTRY.items()})


def test_render_skeleton_contains_sections_and_parses():
    _reg("screen", "current_conditions", fields={"header_text": (str, "Now")})
    _reg("screen", "radar", fields={"refresh": (int, 300)})
    _reg("datasource", "noaa", fields={"user_agent": (str, "weatherstar/1.0")})
    _reg("datasource", "alpha_vantage", fields={"api_key": (SecretStr,)})
    try:
        text = render_skeleton(sequence_name="night", screen_names=["current_conditions", "radar"])
        data = tomllib.loads(text)
        assert data["sequence"] == "night"
        seq = data["sequences"]["night"]
        assert seq["pause"] == 15.0
        assert {"screen": "current_conditions"} in seq["slides"]
        assert data["screen"]["current_conditions"]["header_text"] == "Now"
        assert data["screen"]["radar"]["refresh"] == 300
        assert "REQUIRED" in text
        # Required, sensitive key is rendered as a commented-out example.
        assert "[datasource.alpha_vantage]" in text
        assert data["datasource"]["alpha_vantage"] == {}
    finally:
        _restore()


def test_render_skeleton_defaults_to_all_registered_screens():
    _reg("screen", "conditions")
    _reg("screen", "radar")
    try:
        text = render_skeleton()
        data = tomllib.loads(text)
        slides = {s["screen"] for s in data["sequences"]["main"]["slides"]}
        assert slides == {"conditions", "radar"}
    finally:
        _restore()


def test_skeleton_logging_block_defaults():
    text = render_skeleton()
    data = tomllib.loads(text)
    assert data["logging"]["level"] == "INFO"
    assert data["logging"]["console"] is True


def test_skeleton_renders_dict_and_secret_defaults():
    from pydantic import Field

    class _DictPlugin(Plugin):
        kind = "datasource"
        name = "dict_plugin"
        cache_ttl: int = Field(default=300, description="Seconds each response is cached.")
        headers: dict[str, SecretStr] = Field(
            default_factory=lambda: {"User-Agent": SecretStr("weatherstar (python)")},
            description="Static headers.",
        )

    registry.register("datasource", "dict_plugin", _DictPlugin)
    try:
        text = render_skeleton(sequence_name="main", screen_names=[])
        data = tomllib.loads(text)
        scope = data["datasource"]["dict_plugin"]
        assert scope["cache_ttl"] == 300
        assert scope["headers"] == {"User-Agent": "weatherstar (python)"}
    finally:
        registry._plugins.get("datasource", {}).pop("dict_plugin", None)


class _DocScreen(Plugin):
    kind = "screen"
    name = "doc_screen"
    interval: int = Field(default=10, description="Interval between updates, in seconds.")


def test_skeleton_emits_field_descriptions_and_top_level_sections():
    registry.register("screen", "doc_screen", _DocScreen)
    try:
        text = render_skeleton(sequence_name="night", screen_names=["doc_screen"])
        # Field descriptions surface as comments above their keys.
        assert "# Interval between updates, in seconds." in text
        assert "interval = 10" in text
        # Top-level sections and their commented examples are present.
        assert "[location]" in text
        assert "# lat = 28.5383" in text
        assert "# lon = -81.3792" in text
        assert "[video]" in text
        assert "width = 640" in text
        assert "[logging]" in text
        assert "# Minimum log level" in text
        # TOML remains parseable with all comments stripped by the parser.
        data = tomllib.loads(text)
        assert data["video"] == {"width": 640, "height": 480, "fps": 30}
        # lat/lon are commented examples; description carries an empty default.
        assert data["location"] == {"description": ""}
        assert "auto_detect" not in text
    finally:
        registry._plugins.get("screen", {}).pop("doc_screen", None)

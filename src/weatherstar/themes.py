"""Themes: the data model and TOML loading behind the visual identity.

A :class:`Theme` changes the look and feel of every screen through the shared
:class:`~weatherstar.context.AppContext`: which colors resolve, which
asset tree (fonts/backgrounds/logos/icons) the media plugins load from, and the
product name shown in the screen header.  Themes are *data* (one TOML file per
theme), not plugins, so users can add or tweak a look without writing code.

Design notes
------------
- ``BASE_COLORS`` is the small in-code palette every theme layers over via
  ``AppContext.colors``.  It only guarantees the keys renderers read directly,
  so a theme file can be partial.
- The full authentic Weather Star 4000 palette is *not* baked into code: it lives
  in ``builtin_themes/weatherstar4000.theme.toml`` like every other theme.
- :class:`LayoutVariant` is the closed vocabulary of layout families (``"4000"``
  and ``"3000"``).  Themes *select* a variant for a screen; screens *declare*
  which variants they implement (see ``screens/base.py``).  A theme is data,
  but a layout family is code - a new variant needs a new ``compose_*`` method.
- ``FALLBACK_THEME`` is the safety net returned when a name is unknown or no
  theme files can be found.  It is empty-colored, so it renders as
  ``BASE_COLORS``.

Discovery order (highest precedence first): an explicit ``--themes-dir`` /
``WEATHERSTAR_THEMES_DIR`` directory, then the XDG user themes dir
(``~/.config/weatherstar/themes/``), then the built-in themes shipped with
the package.  Earlier directories shadow later ones by theme name.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:  # Python >= 3.11
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 backport
    import tomli as tomllib

from weatherstar.logging_setup import get_logger

log = get_logger("weatherstar.themes")

#: Environment variable that picks the active theme.
ENV_THEME = "WEATHERSTAR_THEME"
#: Environment variable that overrides where theme files are discovered.
ENV_THEMES_DIR = "WEATHERSTAR_THEMES_DIR"

#: Filename suffix that marks a theme definition file.
THEME_SUFFIX = ".theme.toml"

#: The theme used when nothing is configured / loadable.
DEFAULT_THEME_NAME = "weatherstar4000"


#: XDG location users drop their own ``*.theme.toml`` files.
def xdg_themes_dir() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "weatherstar" / "themes"


def builtin_themes_dir() -> Path:
    """Directory of the theme files shipped inside the package."""
    return Path(__file__).resolve().parent / "builtin_themes"


#: Minimal in-code palette guaranteed on every context.  These are exactly the
#: keys screens/components read without an inline fallback (plus ``red``, the
#: load-bearing alert color), so partial theme palettes never KeyError.
BASE_COLORS: dict[str, tuple[int, int, int]] = {
    "white": (255, 255, 255),  # Main text
    "yellow": (255, 255, 0),  # Titles / accents
    "blue": (128, 128, 255),  # Background fill / low temps
    "cyan": (0, 255, 255),  # Accent text
    "red": (255, 0, 0),  # Alerts / breaking
}


class LayoutVariant(str, Enum):
    """A screen's layout family / product era.

    Screens declare which variants they render (see ``screens/base.py``) and
    themes request one per screen via ``Theme.variant`` / ``Theme.bottom_band``
    or the per-screen ``variant`` layout token.  Because members subclass
    ``str`` they compare equal to their plain string value (``"3000"``), so
    TOML values and any ``== "3000"`` checks keep working unchanged.

    A layout family is inherently code (each needs a ``compose_*`` method), so
    the set is closed: adding a variant means adding an enum member *and* the
    screens that implement it.
    """

    WS4000 = "4000"  # Classic Weather Star 4000 look (the default).
    WS3000 = "3000"  # Weather Star 3000 look (ws3kp).


def coerce_variant(
    value: Any,
    fallback: LayoutVariant = LayoutVariant.WS4000,
    *,
    what: str = "layout variant",
) -> LayoutVariant:
    """Coerce a string/TOML value into a :class:`LayoutVariant`.

    Unknown values are logged with the valid choices and resolve to ``fallback``
    so a typo in a theme file degrades gracefully instead of raising.
    """
    if isinstance(value, LayoutVariant):
        return value
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    try:
        return LayoutVariant(text)
    except ValueError:
        log.warning(
            "unknown_layout_variant",
            what=what,
            value=text,
            valid=sorted(member.value for member in LayoutVariant),
        )
        return fallback


def _parse_color(value: Any, key: str) -> tuple[int, int, int]:
    """Parse a TOML color value: ``"#RRGGBB"``/``"RRGGBB"`` or ``[r, g, b]``."""
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if len(text) == 6:
            try:
                return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
            except ValueError:
                pass
        raise ValueError(f"invalid color {value!r} for key {key!r} (want '#RRGGBB')")
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            channels = tuple(int(channel) for channel in value)
        except (TypeError, ValueError):
            channels = ()
        if all(0 <= channel <= 255 for channel in channels):
            return channels  # type: ignore[return-value]
    raise ValueError(f"invalid color {value!r} for key {key!r} (want '#RRGGBB' or [r, g, b])")


def _parse_font_spec(value: Any, key: str) -> tuple[str, int]:
    """Parse a ``[fonts]`` entry: ``[file, size]`` or ``[file, size]`` list."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"invalid font spec {value!r} for {key!r} (want [file, size])")
    file_name, size = value
    if not isinstance(file_name, str) or not file_name:
        raise ValueError(f"invalid font file {file_name!r} for {key!r}")
    try:
        size = int(size)
    except (TypeError, ValueError):
        raise ValueError(f"invalid font size {size!r} for {key!r}") from None
    if size <= 0:
        raise ValueError(f"invalid font size {size!r} for {key!r}")
    return file_name, size


@dataclass(frozen=True)
class Theme:
    """One named visual identity.

    Colors use semantic keys (``white``, ``yellow``, ``blue_gradient_2``, ...);
    ``fonts`` maps the named font slots to ``(file, size)`` overrides used by
    the ``fonts`` media plugin; ``asset_dir`` points at the theme's own
    ``fonts``/``backgrounds``/``logos``/``icons`` tree.

    Layout is data too: ``text_shadow`` turns on the black outline + drop
    shadow under all rendered text (used by the Weather Star 3000 look),
    ``variant`` names the default :class:`LayoutVariant`, and ``layout``
    carries per-screen rendering tokens (header style, alignment, geometry,
    toggles) that Screens read back through :meth:`layout_for`.  A screen with
    no entry falls back to the ``"default"`` entry (usually empty) and then to
    its own in-code constants, so the Weather Star 4000 baseline needs no layout
    table.
    """

    name: str
    title: str = "Weather Star 4000"
    title_bottom: str = ""
    asset_dir: str = "static_assets/weatherstar_4000"
    colors: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    fonts: dict[str, tuple[str, int]] = field(default_factory=dict)
    #: Render every text glyph with a black outline + drop shadow.
    text_shadow: bool = False
    #: Shadow drop distance in px (the black underlay offset right/down).
    text_shadow_offset: int = 3
    #: Outline stroke width in px (black underlay around every glyph edge).
    text_shadow_outline: int = 2
    #: The theme's default layout family (what ``variant`` resolves to when a
    #: screen has no per-screen ``variant`` layout token).  Themes that only
    #: recolor (``dark``, ``amber``, ...) leave this at the WS4000 default.
    variant: LayoutVariant = LayoutVariant.WS4000
    #: Always-on bottom band style: ``"4000"`` (navy crawler) or ``"3000"``
    #: (the Weather Star 3000 scroll: date + time row over a crawling conditions
    #: line). Screens that reserve the bottom of the canvas opt in here.
    bottom_band: LayoutVariant = LayoutVariant.WS4000
    #: Per-screen layout tokens, keyed by screen name (plus a ``"default"``
    #: entry applied to every screen before the screen-specific one).
    layout: dict[str, dict[str, Any]] = field(default_factory=dict)

    def layout_for(self, screen_name: str | None) -> dict[str, Any]:
        """Return merged layout tokens for a screen (defaults + screen entry)."""
        merged: dict[str, Any] = {}
        for entry in ("default", screen_name):
            if not entry:
                continue
            merged.update(self.layout.get(entry) or {})
        return merged


#: Safety-net theme for unknown names / no discoverable files.  Empty-colored so
#: it renders as :data:`BASE_COLORS`.
FALLBACK_THEME = Theme(
    name=DEFAULT_THEME_NAME,
    title="Weather Star 4000",
    title_bottom="4000",
    colors={},
)


def _theme_from_file(path: Path) -> Theme | None:
    """Parse one ``*.theme.toml`` file into a Theme (or None on error)."""
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        log.warning("theme_parse_failed", path=str(path), error=str(exc))
        return None

    try:
        title = str(data.get("title") or "Weather Star 4000")
        title_bottom = str(data.get("title_bottom") or "")
        asset_dir = str(data.get("asset_dir") or "static_assets/weatherstar_4000")
        colors = {
            key: _parse_color(value, key) for key, value in (data.get("colors") or {}).items()
        }
        fonts = {
            key: _parse_font_spec(value, key) for key, value in (data.get("fonts") or {}).items()
        }
        text_shadow = bool(data.get("text_shadow", False))
        text_shadow_offset = int(data.get("text_shadow_offset", 3))
        text_shadow_outline = int(data.get("text_shadow_outline", 2))
        variant = coerce_variant(data.get("variant"), what="theme variant")
        bottom_band = coerce_variant(data.get("bottom_band"), what="theme bottom_band")
        raw_layout = data.get("layout") or {}
        layout: dict[str, dict[str, Any]] = {}
        if isinstance(raw_layout, dict):
            for key, value in raw_layout.items():
                if isinstance(value, dict):
                    layout[str(key)] = dict(value)
    except ValueError as exc:
        log.warning("theme_invalid", path=str(path), error=str(exc))
        return None

    return Theme(
        name=path.name[: -len(THEME_SUFFIX)],
        title=title,
        title_bottom=title_bottom,
        asset_dir=asset_dir,
        colors=colors,
        fonts=fonts,
        text_shadow=text_shadow,
        text_shadow_offset=text_shadow_offset,
        text_shadow_outline=text_shadow_outline,
        variant=variant,
        bottom_band=bottom_band,
        layout=layout,
    )


def _scan_dir(directory: Path) -> dict[str, Theme]:
    """Load every ``*.theme.toml`` in ``directory`` keyed by file stem."""
    found: dict[str, Theme] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob(f"*{THEME_SUFFIX}")):
        theme = _theme_from_file(path)
        if theme is not None:
            found[theme.name] = theme
    return found


def theme_search_dirs(override: str | None = None) -> list[Path]:
    """Resolve theme discovery dirs, highest precedence first.

    An explicit ``--themes-dir``/``WEATHERSTAR_THEMES_DIR`` directory is tried
    first, then the XDG user dir, then the built-ins (so the shipped themes
    always remain available and user themes can shadow them).
    """
    dirs: list[Path] = []
    explicit = override or os.environ.get(ENV_THEMES_DIR)
    if explicit:
        dirs.append(Path(explicit))
    dirs.append(xdg_themes_dir())
    dirs.append(builtin_themes_dir())
    return dirs


#: Process-wide cache of the last-loaded themes, keyed by the dirs they came from.
_load_state: dict[str, Any] = {}


def load_themes(dirs: list[Path] | None = None) -> dict[str, Theme]:
    """Load (and cache) themes from the given dirs, highest precedence first.

    With no ``dirs`` argument the standard search path is used.  Passing an
    explicit dir list rescans (used by tests).
    """
    dirs = dirs or theme_search_dirs()
    key = tuple(str(directory) for directory in dirs)
    if _load_state.get("key") == key:
        return _load_state.get("themes", {})

    themes: dict[str, Theme] = {}
    for directory in dirs:
        for name, theme in _scan_dir(directory).items():
            themes.setdefault(name, theme)
    _load_state["key"] = key
    _load_state["themes"] = themes
    return themes


def get_theme(theme_name: str, dirs: list[Path] | None = None) -> Theme:
    """Resolve a theme by name, falling back to :data:`FALLBACK_THEME`."""
    themes = load_themes(dirs)
    theme = themes.get(theme_name)
    if theme is None:
        log.warning(
            "theme_not_found",
            theme=theme_name,
            available=sorted(themes) or "(none)",
        )
        return FALLBACK_THEME
    return theme


def available_themes(dirs: list[Path] | None = None) -> list[str]:
    """Return the discoverable theme names, sorted."""
    return sorted(load_themes(dirs))

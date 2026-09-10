"""Runtime context shared by Screens and Components.

Replaces the legacy monolithic ``ws`` object.  The context carries the render
surface, resolved theme, named fonts/assets, and a :class:`DataRegistry` of
configured datasources so rendering code never reaches into a god object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pygame

from weatherstar.themes import BASE_COLORS, FALLBACK_THEME, Theme


@dataclass
class Location:
    """Geographic location used to drive weather datasources."""

    lat: float
    lon: float
    description: str = ""


class DataRegistry:
    """Named registry of configured Datasource instances."""

    def __init__(self) -> None:
        self._sources: dict[str, Any] = {}

    def register(self, name: str, datasource: Any) -> None:
        self._sources[name] = datasource

    def get(self, name: str) -> Any:
        try:
            return self._sources[name]
        except KeyError:
            raise KeyError(
                f"No datasource registered as {name!r}. "
                f"Registered: {', '.join(sorted(self._sources)) or '(none)'}"
            ) from None

    def names(self) -> list[str]:
        return sorted(self._sources)

    def clear(self) -> None:
        self._sources.clear()


class AppContext:
    """Shared, immutable-in-use rendering context for one run.

    The engine fills in ``surface``, ``theme``, ``fonts``, ``assets``, and the
    ``data`` registry before the sequence starts; Screens/Components read from
    it and never mutate it.
    """

    def __init__(
        self,
        surface: pygame.Surface | None = None,
        *,
        theme: Theme | None = None,
        fonts: dict[str, pygame.font.Font] | None = None,
        assets: dict[str, Any] | None = None,
        data: DataRegistry | None = None,
        icon_manager: Any = None,
        location: Location | None = None,
        active_screen: str | None = None,
    ):
        self.surface = surface
        self.theme = theme or FALLBACK_THEME
        self.fonts: dict[str, pygame.font.Font] = fonts or {}
        self.assets: dict[str, Any] = assets or {}
        self.data = data or DataRegistry()
        self.icon_manager = icon_manager
        self.location = location
        self.active_screen = active_screen

    # -- conveniences -------------------------------------------------------

    @property
    def colors(self) -> dict[str, tuple[int, int, int]]:
        """Theme colors merged over the minimal base palette.

        Guarantees stable values for the keys renderers read directly
        (``BASE_COLORS``) while letting the configured theme override or add to
        them, so a partial theme palette never KeyErrors at render time.
        """
        merged = dict(BASE_COLORS)
        merged.update(self.theme.colors)
        return merged

    def layout_for(self, name: str | None = None) -> dict[str, Any]:
        """Per-screen layout tokens for ``name`` (or the active screen)."""
        return self.theme.layout_for(name or self.active_screen)

    def layout(self, key: str, default: Any = None, name: str | None = None) -> Any:
        """Return one layout token for the active screen, or ``default``."""
        return self.layout_for(name).get(key, default)

    def size(self) -> tuple[int, int]:
        if self.surface is None:
            return (0, 0)
        return self.surface.get_size()

"""Component abstraction: renderable units placed on a Screen.

Components are small, composable renderers (headers, text, icons, tables,
scrolling tickers, charts).  They receive the shared :class:`AppContext` and the
target surface at render time and read config through their own typed Pydantic
fields.  Screens declare which components they want (and how each is configured)
via :class:`ComponentSpec` entries in their ``layout``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame
from pydantic import BaseModel, ConfigDict, Field

from weatherstar.plugin import Plugin
from weatherstar.renderer import Renderer

if TYPE_CHECKING:
    from weatherstar.context import AppContext


class ComponentSpec(BaseModel):
    """One component placement in a Screen's ``layout``.

    ``component`` names a registered Component plugin (kind=component) and
    ``config`` supplies per-instance field overrides, merged over any
    ``[component.<name>]`` config scope.
    """

    model_config = ConfigDict(extra="forbid")

    component: str = Field(description="Registered component name (kind 'component').")
    config: dict[str, Any] = Field(
        default_factory=dict, description="Per-instance config overrides for the component."
    )


class Component(Renderer, Plugin):
    """Base class for renderable components.

    Subclasses are ``@plugin``-registered Pydantic models: config fields become
    ``[component.<name>]`` config keys, while non-config metadata (``kind``,
    ``name``) stays as ``ClassVar``.
    """

    kind = "component"

    def render(self, surface: pygame.Surface, ctx: AppContext) -> None:
        """Render this component onto ``surface`` using ``ctx``.

        Subclasses override.  ``surface`` is the screen or a sub-surface passed
        by the owning Screen.
        """
        raise NotImplementedError

    def prepare(self, ctx: AppContext) -> None:
        """Hook called once per engine run before the sequence starts."""

    def step(self, ctx: AppContext, dt: float) -> None:
        """Optional per-frame update hook for stateful/animated components."""

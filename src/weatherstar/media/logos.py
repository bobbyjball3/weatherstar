"""Logos media: registers a dict of logo surfaces keyed by stem.

Loads ``<asset_dir>/logos/*.png|*.gif``.  Screens look up e.g.
``ctx.assets["logos"]["logo-corner"]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pygame

from weatherstar.media.base import AssetMedia
from weatherstar.registry import plugin


@plugin
class Logos(AssetMedia):
    name = "logos"
    asset_key = "logos"
    #: Subdirectory of ``asset_dir`` scanned by :meth:`load_asset` (drives
    #: whether a theme supplies its own logos).
    asset_subdirs = ("logos",)

    def load_asset(self, ctx: Any) -> dict[str, pygame.Surface]:
        directory = Path(self.asset_dir) / "logos"
        result: dict[str, pygame.Surface] = {}
        if directory.exists():
            patterns = ("*.png", "*.gif")
            files = sorted(
                file_path for pattern in patterns for file_path in directory.glob(pattern)
            )
            for file_path in files:
                try:
                    result[file_path.stem] = pygame.image.load(str(file_path))
                except pygame.error:  # pragma: no cover - corrupt asset
                    continue
        return result

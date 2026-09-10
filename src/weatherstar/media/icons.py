"""Icons media: registers an icon manager and a static icon dict.

The manager is self-contained (no legacy ``animated_icons`` dependency).  It
preloads ``*.gif`` / ``*.png`` from the icons directory: animated GIFs are
decoded frame-by-frame (via Pillow) and cycle as their per-frame delays elapse,
while PNGs and single-frame GIFs are served as plain static surfaces.  The
engine advances the shared animation clock once per frame through
:meth:`IconManager.tick`, so every instance of an icon stays in sync and
animation is driven by frame delta time rather than wall-clock time.  The
manager is exposed through ``ctx.assets["icon_manager"]`` (and thus
``ctx.icon_manager``) while ``ctx.assets["icons"]`` holds the raw first-frame
surface dict for simple blitting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pygame

from weatherstar.media.base import AssetMedia
from weatherstar.registry import plugin

try:
    from PIL import Image
except ImportError:  # Pillow is optional: degrade to static first frames.
    Image = None


class AnimatedIcon:
    """A decoded animated GIF: frames plus per-frame durations (seconds)."""

    def __init__(self, frames: list[pygame.Surface], durations: list[float]):
        self.frames = frames
        self.durations = durations
        self.total_duration = sum(durations)

    def frame_at(self, elapsed: float) -> pygame.Surface:
        """Return the frame visible ``elapsed`` seconds into the loop."""
        if self.total_duration <= 0:
            return self.frames[0]
        offset = elapsed % self.total_duration
        accumulated = 0.0
        for index, duration in enumerate(self.durations):
            accumulated += duration
            if offset < accumulated:
                return self.frames[index]
        return self.frames[-1]


class IconManager:
    """Serves named weather-icon surfaces, optionally scaled.

    Animated GIFs advance off a shared clock the engine ticks once per frame
    (:meth:`tick`), so animation tracks frame delta time and is deterministic
    under test rather than reading the wall clock.
    """

    def __init__(self, icons_dir: str | Path):
        self._icons: dict[str, AnimatedIcon | pygame.Surface] = _load_icons(Path(icons_dir))
        self._clock = 0.0

    def tick(self, dt: float) -> None:
        """Advance the shared animation clock by ``dt`` seconds."""
        self._clock += dt

    def _find(self, name: str) -> AnimatedIcon | pygame.Surface | None:
        if name in self._icons:
            return self._icons[name]
        lowered = name.lower()
        for key, icon in self._icons.items():
            if key.lower() == lowered:
                return icon
        return None

    def _current(self, icon: AnimatedIcon | pygame.Surface) -> pygame.Surface:
        if isinstance(icon, AnimatedIcon):
            return icon.frame_at(self._clock)
        return icon

    def get_icon(
        self, name: str, width: int | None = None, height: int | None = None
    ) -> pygame.Surface | None:
        """Return the named icon's current frame, scaled to ``(width, height)``."""
        icon = self._find(name)
        if icon is None:
            return None
        surface = self._current(icon)
        if width and height:
            try:
                return pygame.transform.scale(surface, (width, height))
            except pygame.error:  # pragma: no cover - degenerate size
                return surface
        return surface

    def static_icons(self) -> dict[str, pygame.Surface]:
        """First-frame surface for every icon (the ``ctx.assets["icons"]`` dict)."""
        return {
            name: icon.frames[0] if isinstance(icon, AnimatedIcon) else icon
            for name, icon in self._icons.items()
        }


def _decode_gif(path: Path) -> AnimatedIcon | pygame.Surface | None:
    """Decode a GIF into an animated icon, or a static surface when single-frame.

    Returns ``None`` when the file cannot be decoded (the caller falls back to
    ``pygame.image.load``).  Pillow applies the GIF's disposal and transparency
    while seeking, so each converted RGBA frame is ready to blit.  A missing
    Pillow therefore degrades to the first frame, as before.
    """
    if Image is None:
        return None
    try:
        with Image.open(path) as gif:
            frames: list[pygame.Surface] = []
            durations: list[float] = []
            for index in range(getattr(gif, "n_frames", 1)):
                gif.seek(index)
                rgba = gif.convert("RGBA")
                frames.append(pygame.image.frombytes(rgba.tobytes(), rgba.size, "RGBA"))
                durations.append(_frame_duration(gif.info.get("duration", 100)))
    except Exception:  # noqa: BLE001 - corrupt/unsupported asset
        return None
    if len(frames) <= 1:
        return frames[0] if frames else None
    if sum(durations) <= 0:
        durations = [0.1] * len(frames)
    return AnimatedIcon(frames, durations)


def _frame_duration(duration: Any) -> float:
    """A GIF frame delay in seconds (GIF delays are milliseconds)."""
    try:
        return max(int(duration), 0) / 1000.0
    except (TypeError, ValueError):
        return 0.1


def _load_icons(directory: Path) -> dict[str, AnimatedIcon | pygame.Surface]:
    """Load icon artwork exactly as shipped (no recolor/alteration).

    Animated GIFs become :class:`AnimatedIcon` frame lists (via Pillow); PNGs
    and single-frame GIFs stay as plain surfaces.  The classic icon GIFs are
    line art on a transparent canvas; both paths preserve that transparency, so
    blitting keeps the canvas see-through and the original colors — including
    dark outlines — intact.
    """
    result: dict[str, AnimatedIcon | pygame.Surface] = {}
    if not directory.exists():
        return result
    for pattern in ("*.gif", "*.png"):
        for file_path in sorted(directory.glob(pattern)):
            if file_path.stem in result:
                continue
            icon: AnimatedIcon | pygame.Surface | None = None
            if file_path.suffix.lower() == ".gif":
                icon = _decode_gif(file_path)
            if icon is None:
                try:
                    icon = pygame.image.load(str(file_path))
                except pygame.error:  # pragma: no cover - corrupt asset
                    continue
            result[file_path.stem] = icon
    return result


@plugin
class Icons(AssetMedia):
    name = "icons"
    asset_key = "icons"
    #: Subdirectory of ``asset_dir`` scanned by :meth:`load_asset` (drives
    #: whether a theme supplies its own icon set).
    asset_subdirs = ("icons",)

    def load_asset(self, ctx: Any) -> dict[str, pygame.Surface]:
        directory = Path(self.asset_dir) / "icons"
        manager = IconManager(directory)
        ctx.assets["icon_manager"] = manager
        return manager.static_icons()

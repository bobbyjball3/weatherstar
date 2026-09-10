"""Sequence abstraction: an ordered list of Screens with per-slide pauses.

A Sequence is data-declared in the config under ``[sequences.<name>]``::

    [sequences.main]
    pause = 15.0                       # global default seconds per slide
    slides = [
        { screen = "current_conditions" },
        { screen = "radar", pause = 10.0 },   # override global pause
    ]

The engine selects a sequence via CLI ``--sequence`` > ``WEATHERSTAR_SEQUENCE``
> the top-level ``sequence`` key, then instantiates every referenced Screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from weatherstar.errors import SequenceError


@dataclass(frozen=True)
class Slide:
    screen: str
    pause: float | None = None

    @classmethod
    def from_raw(cls, raw: Any, default_pause: float | None = None) -> Slide:
        if isinstance(raw, str):
            return cls(screen=raw, pause=default_pause)
        if isinstance(raw, dict):
            screen = raw.get("screen")
            if not screen:
                raise SequenceError(f"Slide missing 'screen' key: {raw!r}")
            pause = raw.get("pause", default_pause)
            return cls(screen=screen, pause=float(pause) if pause is not None else None)
        raise SequenceError(f"Invalid slide entry (expected str or dict): {raw!r}")


@dataclass
class Sequence:
    """A named, ordered run of screens."""

    name: str
    slides: list[Slide]
    default_pause: float | None = None

    @classmethod
    def from_config(cls, name: str, data: dict[str, Any]) -> Sequence:
        raw_slides = data.get("slides")
        if not raw_slides:
            raise SequenceError(f"Sequence {name!r} has no slides.")
        default_pause = data.get("pause")
        default_pause = float(default_pause) if default_pause is not None else None
        slides = [Slide.from_raw(raw, default_pause) for raw in raw_slides]
        if not slides:
            raise SequenceError(f"Sequence {name!r} has no slides.")
        return cls(name=name, slides=slides, default_pause=default_pause)

    def screen_names(self) -> list[str]:
        seen: list[str] = []
        for slide in self.slides:
            if slide.screen not in seen:
                seen.append(slide.screen)
        return seen

    def pause_for(self, index: int) -> float:
        slide = self.slides[index]
        if slide.pause is not None:
            return slide.pause
        if self.default_pause is not None:
            return self.default_pause
        return 15.0

    def total_duration(self) -> float:
        return sum(self.pause_for(i) for i in range(len(self.slides)))

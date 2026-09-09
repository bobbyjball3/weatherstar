"""Music media: discovers tracks and provides playback for the engine.

The engine owns *when* music plays: it auto-includes this media in the runtime
context whenever ``[media.music] enabled = true``, then calls ``play()`` on the
real (non-validate) run path and ``stop()`` when the run ends.  ``load`` only
discovers files so headless/validate builds never start audio.

Playback mirrors the legacy app: the playlist is shuffled and a random track
starts first, then each track advances to the next in the shuffled order when
it finishes (``Music.advance`` is polled by the engine each frame).
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field, PrivateAttr

from weatherstar.logging_setup import get_logger
from weatherstar.media.base import Media
from weatherstar.registry import plugin

if TYPE_CHECKING:
    from weatherstar.context import AppContext

log = get_logger("weatherstar.music")

MUSIC_GLOB = ("*.mp3", "*.ogg", "*.wav")


@plugin
class Music(Media):
    name = "music"

    enabled: bool = Field(default=True, description="Play background music during the show.")
    volume: float = Field(default=0.6, description="Music volume, from 0.0 (silent) to 1.0 (full).")

    _playlist: list[str] = PrivateAttr(default_factory=list)
    _track_index: int = PrivateAttr(default=0)

    def _tracks(self) -> list[str]:
        directory = Path(self.asset_dir) / "music"
        if not directory.exists():
            return []
        tracks: list[str] = []
        for pattern in MUSIC_GLOB:
            tracks.extend(str(path) for path in sorted(directory.glob(pattern)))
        return tracks

    def load(self, ctx: AppContext) -> list[str]:
        """Discover music files and register them under ``ctx.assets["music"]``.

        Deliberately does not start playback; the engine calls :meth:`play`.
        """
        tracks = self._tracks()
        ctx.assets["music"] = tracks
        return tracks

    # -- playback ------------------------------------------------------------

    def _start_playing(self, index: int) -> bool:
        import pygame

        if not pygame.mixer.get_init():
            pygame.mixer.init()
        track = self._playlist[index]
        pygame.mixer.music.load(track)
        pygame.mixer.music.set_volume(float(self.volume))
        # No infinite loop: the engine advances to the next shuffled track when
        # this one finishes (see Music.advance).
        pygame.mixer.music.play(0)
        self._track_index = index
        log.info("music_started", track=track, index=index, volume=self.volume)
        return True

    def play(self, ctx: AppContext | None = None) -> bool:
        """Start background music from a random first track.

        Returns True when playback was actually started.  Best-effort: audio
        failures are logged, never raised.
        """
        if not self.enabled:
            return False
        try:
            tracks = ctx.assets.get("music") if ctx is not None else None
            if not tracks:
                tracks = self._tracks()
            if not tracks:
                log.warning("music_no_tracks", asset_dir=self.asset_dir)
                return False
            # Shuffle so every launch (and every playlist restart) starts with a
            # different random song, matching the legacy behaviour.
            self._playlist = list(tracks)
            random.shuffle(self._playlist)
            return self._start_playing(0)
        except Exception as exc:  # noqa: BLE001 - audio is best-effort
            log.warning("music_playback_failed", error=str(exc))
            return False

    def advance(self) -> None:
        """Advance to the next shuffled track if the current one has ended."""
        try:
            import pygame

            playlist = getattr(self, "_playlist", None)
            if not playlist:
                return
            if not pygame.mixer.get_init() or pygame.mixer.music.get_busy():
                return
            index = (self._track_index + 1) % len(playlist)
            if self._start_playing(index):
                log.info("music_track_advanced", index=index)
        except Exception as exc:  # noqa: BLE001 - audio is best-effort
            log.warning("music_advance_failed", error=str(exc))

    @staticmethod
    def stop() -> None:
        """Stop any music playback (no-op if mixer is unavailable)."""
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

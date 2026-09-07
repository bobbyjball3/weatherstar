"""Software audio feeder: play the shuffled music playlist into the encoder.

The simulator plays music through ``pygame.mixer`` (music.py), which owns a
sound *device* — something a headless container does not have. The streamer
therefore plays the same shuffled playlist in software and hands raw PCM to the
encoder's audio FIFO, never touching a sound device.

Why not just point ffmpeg's *muxer* at a FIFO fed by per-track ffmpeg decoders?
ffmpeg's HLS muxer is not wall-clock paced: it drains its inputs as fast as it
can, so an un-paced audio source loops far faster than real time. Video is paced
because the render loop feeds one frame per ``1/fps`` second; audio therefore
has to be paced explicitly too. Track selection mirrors the core ``Music`` media
plugin (same globs, shuffle, advance one at a time, wrap forever); pacing is
pure Python:

1. a loader thread decodes the *next* track to a temporary raw-PCM file (ffmpeg
   decode is fast; doing it ahead of time keeps track changes gapless),
2. the feeder thread writes that file's bytes into the audio FIFO, sleeping so
   it never sends more than ``sample_rate * channels * 2`` bytes per second.

Because ffmpeg stamps PCM by sample count, sending bytes at the wall-clock byte
rate keeps the audio timeline glued to the video timeline.
"""

from __future__ import annotations

import os
import queue
import random
import shutil
import subprocess
import threading
import time
from pathlib import Path

from weatherstar.logging_setup import get_logger

log = get_logger("weatherstar.stream.audio")

#: Matches ``weatherstar.media.music.MUSIC_GLOB`` so the same files are streamed.
MUSIC_GLOB = ("*.mp3", "*.ogg", "*.wav")

#: Bytes written per pacing tick (~1/20 s of audio at 48 kHz stereo).
_QUANTUM_SECONDS = 0.05


def discover_tracks(music_dir: str | Path) -> list[str]:
    """Return the sorted music files under ``music_dir`` (empty when absent)."""
    directory = Path(music_dir)
    tracks: list[str] = []
    for pattern in MUSIC_GLOB:
        tracks.extend(str(path) for path in sorted(directory.glob(pattern)))
    return tracks


def build_decode_argv(
    *,
    ffmpeg: str,
    track: str,
    output: str,
    sample_rate: int = 48000,
    channels: int = 2,
    volume: float | None = None,
) -> list[str]:
    """Arguments for the per-track decode to raw interleaved s16le PCM16."""
    argv = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        track,
        "-vn",
    ]
    if volume is not None and volume != 1.0:
        argv += ["-af", f"volume={volume:g}"]
    argv += ["-f", "s16le", "-ac", str(channels), "-ar", str(sample_rate), output]
    return argv


def _decode_to_file(
    ffmpeg: str,
    track: str,
    dest: Path,
    *,
    sample_rate: int,
    channels: int,
    volume: float | None,
) -> Path | None:
    """Decode ``track`` to a raw-PCM file at ``dest``; None on failure."""
    argv = build_decode_argv(
        ffmpeg=ffmpeg,
        track=track,
        output=str(dest),
        sample_rate=sample_rate,
        channels=channels,
        volume=volume,
    )
    try:
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:  # pragma: no cover - ffmpeg vanished mid-run
        log.warning("music_decode_spawn_failed", track=track, error=str(exc))
        return None
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        log.warning("music_decode_failed", track=track, error=detail or f"rc={proc.returncode}")
        return None
    return dest


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _pace_write(
    fd: int, src: Path, *, bytes_per_second: float, stop_event: threading.Event
) -> None:
    """Copy ``src`` to ``fd`` (the audio FIFO) at a real-time byte rate."""
    size = src.stat().st_size
    quantum = max(4096, int(bytes_per_second * _QUANTUM_SECONDS))
    quantum_time = quantum / bytes_per_second
    deadline = time.monotonic()
    sent = 0
    with src.open("rb") as handle:
        while sent < size and not stop_event.is_set():
            deadline += quantum_time
            now = time.monotonic()
            if now < deadline:
                time.sleep(deadline - now)
            data = handle.read(quantum)
            if not data:
                break
            _write_all(fd, data)
            sent += len(data)


class MusicFeed(threading.Thread):
    """Streams a shuffled, wrapping playlist into an audio FIFO on a thread.

    A loader sub-thread decodes the next track while the feeder plays the
    current one, so switching tracks is effectively gapless. ``shutdown()`` sets
    the stop event and unblocks the feeder at the next pacing tick.
    """

    def __init__(
        self,
        *,
        tracks: list[str],
        audio_fifo: str | Path,
        ffmpeg: str | None = None,
        sample_rate: int = 48000,
        channels: int = 2,
        volume: float | None = None,
        work_dir: str | Path | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        super().__init__(name="music-feed", daemon=True)
        self.tracks = list(tracks)
        self.audio_fifo = str(audio_fifo)
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg") or ""
        self.sample_rate = sample_rate
        self.channels = channels
        self.volume = volume
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self._work_dir = Path(work_dir or Path(self.audio_fifo).parent)
        # One decoded track queued ahead while another plays.
        self._ready: queue.Queue[Path | None] = queue.Queue(maxsize=1)
        self._loader_errors = False

    # -- public API --------------------------------------------------------

    @property
    def stopping(self) -> bool:
        return self.stop_event.is_set()

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.channels * 2

    def shutdown(self) -> None:
        """Stop the feeder at the next pacing tick."""
        self.stop_event.set()

    # -- main loop ---------------------------------------------------------

    def run(self) -> None:
        if not self.tracks:
            log.warning("music_feed_no_tracks")
            return
        if not self.ffmpeg:
            log.warning("music_feed_no_ffmpeg")
            return

        playlist = list(self.tracks)
        random.shuffle(playlist)

        loader = threading.Thread(
            target=self._load_loop,
            name="music-decode",
            daemon=True,
            kwargs={"playlist": playlist},
        )
        loader.start()

        self._work_dir.mkdir(parents=True, exist_ok=True)
        while not self.stopping:
            try:
                pcm = self._ready.get(timeout=0.25)
            except queue.Empty:
                continue
            if pcm is None or not pcm.exists():
                continue
            try:
                fd = os.open(self.audio_fifo, os.O_WRONLY)
            except OSError:  # pragma: no cover - encoder already torn down
                log.warning("music_feed_fifo_gone")
                break
            try:
                _pace_write(
                    fd,
                    pcm,
                    bytes_per_second=self.bytes_per_second,
                    stop_event=self.stop_event,
                )
            except OSError as exc:
                # Encoder stopped/closed the FIFO while we were writing.
                log.info("music_feed_write_interrupted", error=str(exc))
                break
            finally:
                os.close(fd)
            try:
                pcm.unlink()
            except FileNotFoundError:  # pragma: no cover - raced cleanup
                pass
        # Drop any PCM files decoded ahead of us when we stopped mid-stream.
        for leftover in self._work_dir.glob("track-*.pcm"):
            try:
                leftover.unlink()
            except FileNotFoundError:  # pragma: no cover - raced cleanup
                pass

    def _load_loop(self, playlist: list[str]) -> None:
        """Decode tracks (wrapping forever) into temp PCM files for the feeder."""
        index = 0
        while not self.stopping:
            track = playlist[index % len(playlist)]
            dest = self._work_dir / f"track-{index:06d}.pcm"
            pcm = _decode_to_file(
                self.ffmpeg,
                track,
                dest,
                sample_rate=self.sample_rate,
                channels=self.channels,
                volume=self.volume,
            )
            if pcm is None:
                self._loader_errors = True
                time.sleep(0.25)  # avoid a hot decode loop when files are unreadable
            else:
                log.info("music_track_ready", track=track)
                # Block until the feeder has taken the previous track, so at most
                # one decoded file is queued ahead of the one currently playing.
                self._ready.put(pcm)
            index += 1

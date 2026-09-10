"""FFmpeg encoder: raw RGB24 frames + PCM16 audio in, rolling HLS window out.

The engine renders Weather Star on an offscreen pygame ``Surface``; this module
owns the single ``ffmpeg`` process that turns those frames (plus the ambient
music as PCM) into an HLS stream. Everything talks to ffmpeg over POSIX named
pipes (FIFOs), which give us two properties for free:

- **Backpressure.** ``os.write`` to a FIFO blocks when ffmpeg has not consumed
  the data yet, so a slow encoder naturally paces the render loop instead of
  dropping frames or buffering forever.
- **Timestamp-correct output.** Because the rawvideo demuxer stamps frames at
  ``-r fps`` and the PCM input stamps samples by sample count, ffmpeg muxes the
  two in timestamp order regardless of *wall-clock* arrival order. Feeding video
  at roughly real time therefore produces a correct, real-time HLS stream even
  though ffmpeg itself never runs in "real time" mode.

Only ``ffmpeg`` (a native binary) and POSIX primitives are used; all other logic
is Python. ``h264_rkmpp`` (RK3588/RK1 VPU) and ``libx264`` (everything else) are
both just values of ``[stream] video_encoder``.
"""

from __future__ import annotations

import fcntl
import os
import select
import shutil
import subprocess
import threading
from collections import deque
from pathlib import Path

from weatherstar.logging_setup import get_logger
from weatherstar.streaming.config import StreamConfig

log = get_logger("weatherstar.stream.encoder")

VIDEO_FIFO_NAME = ".video.fifo"
AUDIO_FIFO_NAME = ".audio.fifo"

_STDERR_LIMIT = 200


class EncoderError(RuntimeError):
    """Raised when ffmpeg cannot start or dies while the stream is running."""


def _fifo_layout(channels: int) -> str:
    """lavfi channel-layout token for a given channel count."""
    return "mono" if channels <= 1 else "stereo"


def build_ffmpeg_argv(
    *,
    ffmpeg: str,
    width: int,
    height: int,
    fps: int,
    video_fifo: Path,
    cfg: StreamConfig,
    audio_fifo: Path | None = None,
) -> list[str]:
    """Build the ffmpeg argument vector that muxes video + audio into HLS.

    ``audio_fifo`` is the FIFO the music feeder writes PCM16 into; pass ``None``
    to substitute an endless digital-silence source (``anullsrc``) so the
    container always carries an audio track even when no music is configured.
    """
    argv = [
        ffmpeg,
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        str(video_fifo),
    ]
    if audio_fifo is None:
        layout = _fifo_layout(cfg.audio_channels)
        argv += [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout={layout}:sample_rate={cfg.audio_rate}",
        ]
    else:
        argv += [
            "-f",
            "s16le",
            "-ac",
            str(cfg.audio_channels),
            "-ar",
            str(cfg.audio_rate),
            "-i",
            str(audio_fifo),
        ]

    argv += ["-c:v", cfg.video_encoder]
    if cfg.uses_preset():
        argv += ["-preset", cfg.preset]
    # The Rockchip rkmpp encoders want NV12 and negotiate it themselves; every
    # other encoder (libx264/5, etc.) must be pinned to 4:2:0 so Jellyfin and
    # the CRT hardware decoder can always handle the stream.
    if "rkmpp" not in cfg.video_encoder:
        argv += ["-pix_fmt", "yuv420p"]
    gop = max(1, round(fps * cfg.hls_time))
    argv += ["-g", str(gop), "-keyint_min", str(gop)]
    if "libx264" in cfg.video_encoder or "libx265" in cfg.video_encoder:
        argv += ["-sc_threshold", "0"]
    argv += ["-c:a", cfg.audio_encoder, "-b:a", cfg.audio_bitrate]
    argv += [
        "-f",
        "hls",
        "-hls_time",
        f"{cfg.hls_time:g}",
        "-hls_list_size",
        str(cfg.hls_list_size),
        "-hls_flags",
        "delete_segments+independent_segments",
        "-hls_segment_filename",
        str(cfg.hls_dir / "segment_%05d.ts"),
        str(cfg.hls_dir / "index.m3u8"),
    ]
    return argv


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:  # pragma: no cover - raced cleanup
        pass


class FFmpegEncoder:
    """Manages one muxing ffmpeg subprocess writing a rolling HLS window."""

    def __init__(
        self,
        *,
        cfg: StreamConfig,
        width: int,
        height: int,
        fps: int,
        feed_audio: bool = True,
        ffmpeg: str | None = None,
    ) -> None:
        self.cfg = cfg
        self.width = width
        self.height = height
        self.fps = fps
        self.feed_audio = feed_audio
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg") or ""
        if not self.ffmpeg:
            raise EncoderError(
                "ffmpeg executable not found. Install ffmpeg (or set it on "
                "PATH); on the RK1 use a Rockchip build with rkmpp support."
            )
        self.video_fifo = cfg.hls_dir / VIDEO_FIFO_NAME
        self.audio_fifo = cfg.hls_dir / AUDIO_FIFO_NAME if feed_audio else None

        self._video_fd: int | None = None
        self._audio_fd: int | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr_thread: threading.Thread | None = None
        self._tail: deque[str] = deque(maxlen=_STDERR_LIMIT)
        self._started = False

    # -- properties --------------------------------------------------------

    @property
    def frame_bytes(self) -> int:
        return self.width * self.height * 3

    @property
    def started(self) -> bool:
        return self._started

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Create the FIFOs, spawn ffmpeg and block until it is feeding."""
        if self._started:
            return
        hls_dir = self.cfg.hls_dir
        hls_dir.mkdir(parents=True, exist_ok=True)
        _unlink(self.video_fifo)
        os.mkfifo(self.video_fifo)
        if self.audio_fifo is not None:
            _unlink(self.audio_fifo)
            os.mkfifo(self.audio_fifo)

        # Open our own ends read-write: the open never blocks, and holding the
        # write side open guarantees ffmpeg's read-only open of each FIFO
        # (below) succeeds immediately instead of waiting for a writer.
        self._video_fd = os.open(self.video_fifo, os.O_RDWR)
        self._audio_fd = os.open(self.audio_fifo, os.O_RDWR) if self.audio_fifo else None
        self._set_nonblocking(self._video_fd)
        if self._audio_fd is not None:
            self._set_nonblocking(self._audio_fd)

        argv = build_ffmpeg_argv(
            ffmpeg=self.ffmpeg,
            width=self.width,
            height=self.height,
            fps=self.fps,
            video_fifo=self.video_fifo,
            cfg=self.cfg,
            audio_fifo=self.audio_fifo,
        )
        log.info("encoder_start", argv=argv, hls_dir=str(hls_dir))
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            # Own session/process group: a terminal Ctrl-C (or any group signal)
            # must not kill ffmpeg behind our back mid-write. We terminate it
            # explicitly in stop().
            start_new_session=True,
        )
        self._drain_stderr()
        self._started = True
        # Give ffmpeg a moment to fail on bad arguments before the caller starts
        # feeding frames; a healthy process is left running (it cannot write the
        # first HLS segment until frames arrive).
        if not self._initial_check(timeout=3.0):
            self._join_stderr()
            detail = self._tail_stderr()
            self.stop()
            raise EncoderError(
                "ffmpeg exited at startup. " + (f"stderr: {detail}" if detail else "")
            )

    def _initial_check(self, timeout: float = 3.0) -> bool:
        """Return False if ffmpeg exits during startup (bad args, etc.)."""
        import time

        # Argument errors make ffmpeg exit almost immediately; a process still
        # alive after a short stabilization window is assumed healthy. We never
        # wait the full timeout for a healthy encoder.
        stable_for = 0.7
        deadline = time.monotonic() + timeout
        alive_since: float | None = None
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                return False
            now = time.monotonic()
            if alive_since is None:
                alive_since = now
            elif now - alive_since >= stable_for:
                return True
            time.sleep(0.05)
        return True

    def write_frame(self, data: bytes) -> None:
        """Push one RGB24 frame to the encoder, blocking under backpressure."""
        expected = self.frame_bytes
        if len(data) != expected:
            raise EncoderError(
                f"frame is {len(data)} bytes, expected {expected} (RGB24 "
                f"{self.width}x{self.height})"
            )
        if self._video_fd is None:
            raise EncoderError("encoder not started")
        self._pump(self._video_fd, data)

    def stop(self, timeout: float = 10.0) -> None:
        """Terminate ffmpeg, close FIFO ends and remove the FIFO files."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout)
            except subprocess.TimeoutExpired:  # pragma: no cover - hung ffmpeg
                proc.kill()
                proc.wait()
            self._proc = None
        if self._video_fd is not None:
            os.close(self._video_fd)
            self._video_fd = None
        if self._audio_fd is not None:
            os.close(self._audio_fd)
            self._audio_fd = None
        _unlink(self.video_fifo)
        if self.audio_fifo is not None:
            _unlink(self.audio_fifo)
        self._started = False

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _set_nonblocking(fd: int) -> None:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def _check_alive(self) -> None:
        if self._proc is not None and self._proc.poll() is not None:
            # Give the stderr drain a moment so the *real* ffmpeg error line
            # (not just the tail we happened to read before it died) makes it
            # into the message.
            self._join_stderr()
            raise EncoderError(
                f"ffmpeg exited during stream with code {self._proc.returncode}. "
                + self._tail_stderr()
            )

    def _join_stderr(self, timeout: float = 0.5) -> None:
        thread = self._stderr_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    def _pump(self, fd: int, data: bytes) -> None:
        """Write ``data`` to ``fd`` without ever blocking past a health check."""
        view = memoryview(data)
        while view:
            self._check_alive()
            try:
                written = os.write(fd, view)
                view = view[written:]
            except BlockingIOError:
                # No space in the FIFO right now: wait a moment for ffmpeg to
                # drain it, but keep checking it has not died so a dead encoder
                # can never wedge the render loop forever.
                _, writable, _ = select.select([], [fd], [], 1.0)
                if not writable:
                    self._check_alive()

    def _drain_stderr(self) -> None:
        """Read ffmpeg's stderr on a thread so a full pipe can never stall it."""
        if self._proc is None or self._proc.stderr is None:
            return
        proc = self._proc
        tail = self._tail

        def _reader() -> None:
            assert proc.stderr is not None
            for raw in proc.stderr:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line:
                    tail.append(line)
                    log.warning("ffmpeg_stderr", line=line)

        thread = threading.Thread(target=_reader, name="ffmpeg-stderr", daemon=True)
        thread.start()
        self._stderr_thread = thread

    def _tail_stderr(self) -> str:
        return " | ".join(self._tail)

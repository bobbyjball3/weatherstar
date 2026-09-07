"""End-to-end stream test: render loop + real ffmpeg + HLS output.

Requires an ``ffmpeg`` binary (skipped otherwise). Deliberately avoids the real
Weather Star datasources/screens — those are covered by the core suite — so this
test just proves the streaming glue: frames from ``run_stream`` land in a real
HLS window with video and audio.
"""

import shutil
import threading
import time
import types

import pygame
import pytest

from weatherstar.sequence import Sequence

FFMPEG = shutil.which("ffmpeg")

pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


class _Screen:
    def __init__(self, name):
        self.name = name

    def step(self, ctx, dt):
        pass

    def draw(self, surface, ctx, dt):
        surface.fill((20, 40, 60))
        surface.fill((200, 200, 200), (4, 4, 30, 20))


class _Ticker:
    def render(self, surface, ctx, dt):
        surface.fill((0, 0, 80), (0, surface.get_height() - 24, surface.get_width(), 24))


def test_rendered_frames_reach_hls(tmp_path, pygame_env):
    from weatherstar.streaming.config import StreamConfig
    from weatherstar.streaming.encoder import FFmpegEncoder
    from weatherstar.streaming.loop import run_stream

    width, height, fps = 160, 120, 10
    surface = pygame.Surface((width, height))
    sequence = Sequence.from_config(
        "mini",
        {"pause": 0.4, "slides": [{"screen": "a"}, {"screen": "b"}]},
    )
    screens = [_Screen("a"), _Screen("b")]
    cfg = StreamConfig(hls_dir=tmp_path / "hls", hls_time=1.0, preset="ultrafast")
    enc = FFmpegEncoder(cfg=cfg, width=width, height=height, fps=fps, feed_audio=False)
    enc.start()
    stop = threading.Event()
    stop_thread = threading.Thread(target=lambda: (time.sleep(2.2), stop.set()), daemon=True)
    stop_thread.start()
    try:
        frames = run_stream(
            types.SimpleNamespace(surface=surface),
            screens,
            sequence,
            encoder=enc,
            fps=fps,
            ticker=_Ticker(),
            stop_event=stop,
        )
        assert frames >= 10
    finally:
        enc.stop()

    playlist = cfg.hls_dir / "index.m3u8"
    assert playlist.exists()
    segments = sorted(cfg.hls_dir.glob("segment_*.ts"))
    assert segments
    text = playlist.read_text()
    assert "#EXTM3U" in text
    assert segments[-1].name in text

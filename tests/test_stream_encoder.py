"""Tests for the ffmpeg encoder: arg building and subprocess lifecycle."""

import shutil
import time

import pytest

from weatherstar.streaming.config import StreamConfig
from weatherstar.streaming.encoder import (
    AUDIO_FIFO_NAME,
    VIDEO_FIFO_NAME,
    EncoderError,
    FFmpegEncoder,
    build_ffmpeg_argv,
)

FFMPEG = shutil.which("ffmpeg")


def _cfg(tmp_path, **overrides):
    base = {
        "hls_dir": tmp_path / "hls",
        "hls_time": 4.0,
        "hls_list_size": 6,
        "video_encoder": "libx264",
        "channel_number": "5",
    }
    base.update(overrides)
    return StreamConfig(**base)


def _video_fifo(cfg):
    return cfg.hls_dir / VIDEO_FIFO_NAME


def test_argv_build_with_music_fifo(tmp_path):
    cfg = _cfg(tmp_path)
    audio_fifo = cfg.hls_dir / AUDIO_FIFO_NAME
    argv = build_ffmpeg_argv(
        ffmpeg="ffmpeg",
        width=640,
        height=480,
        fps=30,
        video_fifo=_video_fifo(cfg),
        cfg=cfg,
        audio_fifo=audio_fifo,
    )
    joined = " ".join(argv)
    assert argv[0] == "ffmpeg"
    # video input spec
    assert "-f rawvideo -pix_fmt rgb24 -s 640x480 -r 30 -i" in joined
    assert str(_video_fifo(cfg)) in argv
    # audio input spec (PCM FIFO)
    assert "-f s16le -ac 2 -ar 48000 -i" in joined
    assert str(audio_fifo) in argv
    # encoder + 4:2:0 for software encoders
    assert "-c:v libx264 -preset veryfast" in joined
    assert "-pix_fmt yuv420p" in joined
    # keyframe interval aligned to segment length (30fps * 4s)
    assert "-g 120" in joined
    assert "-keyint_min 120" in joined
    # audio encode
    assert "-c:a aac -b:a 128k" in joined
    # HLS output
    assert "-f hls -hls_time 4 -hls_list_size 6" in joined
    assert "delete_segments+independent_segments" in joined
    assert joined.endswith("index.m3u8")
    assert str(cfg.hls_dir / "segment_%05d.ts") in joined


def test_argv_silent_uses_anullsrc(tmp_path):
    cfg = _cfg(tmp_path)
    argv = build_ffmpeg_argv(
        ffmpeg="ffmpeg",
        width=320,
        height=240,
        fps=15,
        video_fifo=_video_fifo(cfg),
        cfg=cfg,
        audio_fifo=None,
    )
    joined = " ".join(argv)
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in joined
    assert "-f s16le" not in joined


def test_argv_rkmpp_omits_preset_and_pix_fmt(tmp_path):
    cfg = _cfg(tmp_path, video_encoder="h264_rkmpp")
    argv = build_ffmpeg_argv(
        ffmpeg="ffmpeg",
        width=640,
        height=480,
        fps=30,
        video_fifo=_video_fifo(cfg),
        cfg=cfg,
        audio_fifo=None,
    )
    joined = " ".join(argv)
    assert "-c:v h264_rkmpp" in joined
    assert "-preset" not in joined
    assert "-pix_fmt yuv420p" not in joined
    assert "-sc_threshold" not in joined


def test_argv_x265_keeps_sc_threshold(tmp_path):
    cfg = _cfg(tmp_path, video_encoder="libx265")
    argv = build_ffmpeg_argv(
        ffmpeg="ffmpeg",
        width=320,
        height=240,
        fps=30,
        video_fifo=_video_fifo(cfg),
        cfg=cfg,
        audio_fifo=None,
    )
    assert "-sc_threshold 0" in " ".join(argv)


def test_encoder_requires_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr("weatherstar.streaming.encoder.shutil.which", lambda _name: None)
    with pytest.raises(EncoderError, match="ffmpeg executable not found"):
        FFmpegEncoder(cfg=_cfg(tmp_path), width=1, height=1, fps=1)


def test_frame_bytes(tmp_path):
    enc = FFmpegEncoder(cfg=_cfg(tmp_path), width=10, height=8, fps=5, ffmpeg="true")
    assert enc.frame_bytes == 10 * 8 * 3


def test_write_frame_size_mismatch(tmp_path):
    enc = FFmpegEncoder(cfg=_cfg(tmp_path), width=10, height=8, fps=5, ffmpeg="true")
    with pytest.raises(EncoderError, match="expected 240"):
        enc.write_frame(b"x" * 10)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_live_encode_produces_hls_window(tmp_path):
    cfg = _cfg(tmp_path, hls_time=1.0, preset="ultrafast")
    enc = FFmpegEncoder(cfg=cfg, width=160, height=120, fps=10, feed_audio=False, ffmpeg=FFMPEG)
    enc.start()
    try:
        for i in range(25):  # ~2.5s of video at 10 fps
            rgb = bytes(((i * 7) % 256, (i * 3) % 256, 128)) * (160 * 120)
            enc.write_frame(rgb)
            time.sleep(0.1)
        assert enc.running
        playlist = cfg.hls_dir / "index.m3u8"
        assert playlist.exists()
        assert list(cfg.hls_dir.glob("segment_*.ts"))
    finally:
        enc.stop()
    # FIFOs are cleaned up on stop.
    assert not (cfg.hls_dir / VIDEO_FIFO_NAME).exists()
    assert not (cfg.hls_dir / AUDIO_FIFO_NAME).exists()


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_start_fails_loudly_on_bad_encoder(tmp_path):
    # ffmpeg only discovers an unknown encoder once the first frame arrives, so
    # the failure surfaces from write_frame rather than start().
    cfg = _cfg(tmp_path, video_encoder="definitely_not_an_encoder")
    enc = FFmpegEncoder(cfg=cfg, width=160, height=120, fps=10, feed_audio=False, ffmpeg=FFMPEG)
    enc.start()
    rgb = bytes((0, 0, 0)) * (160 * 120)
    with pytest.raises(EncoderError, match="exited during stream"):
        # The first frame may just fill the FIFO before ffmpeg chokes on it, so
        # keep feeding until the encoder's death is observed.
        for _ in range(10):
            enc.write_frame(rgb)
            time.sleep(0.05)
    enc.stop()
    # Failed runs must not leave FIFOs behind.
    assert not (cfg.hls_dir / VIDEO_FIFO_NAME).exists()

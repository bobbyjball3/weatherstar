"""Tests for the software audio feeder (no real ffmpeg required)."""

import os
import threading
from pathlib import Path

from weatherstar.streaming import audio as audio_mod
from weatherstar.streaming.audio import MusicFeed, build_decode_argv, discover_tracks


def test_discover_tracks_matches_music_globs(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "b.ogg").write_bytes(b"x")
    (tmp_path / "c.wav").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("nope")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "d.mp3").write_bytes(b"x")
    tracks = discover_tracks(tmp_path)
    assert tracks == [
        str(tmp_path / "a.mp3"),
        str(tmp_path / "b.ogg"),
        str(tmp_path / "c.wav"),
    ]


def test_discover_tracks_empty_when_dir_missing():
    assert discover_tracks(Path("/definitely/not/here")) == []


def test_decode_argv_defaults_and_volume():
    argv = build_decode_argv(ffmpeg="ffmpeg", track="a.mp3", output="/fifo")
    i = argv.index("-i")
    assert argv[i : i + 2] == ["-i", "a.mp3"]
    assert "-vn" in argv
    assert argv[-1] == "/fifo"
    assert "-af" not in argv
    assert "-af" not in build_decode_argv(ffmpeg="f", track="t", output="o", volume=1.0)

    argv_vol = build_decode_argv(ffmpeg="f", track="t", output="o", volume=0.6)
    assert argv_vol[argv_vol.index("-af") + 1] == "volume=0.6"


def test_pace_write_writes_all_bytes_and_paces(tmp_path):
    from weatherstar.streaming.audio import _pace_write

    bps = 100_000
    src = tmp_path / "slice.pcm"
    src.write_bytes(b"\x00\x00" * (bps // 2))  # ~0.5s of audio at bps
    sink = tmp_path / "out.bin"
    fd = os.open(sink, os.O_WRONLY | os.O_CREAT, 0o644)
    sleeps: list[float] = []
    try:
        _pace_write(
            fd,
            src,
            bytes_per_second=bps,
            stop_event=threading.Event(),
            clock=lambda: 0.0,
            sleep=sleeps.append,
        )
    finally:
        os.close(fd)

    # Every byte is delivered...
    assert sink.stat().st_size == src.stat().st_size
    # ...and it was paced one sleep per quantum, not written instantly.
    quantum = max(4096, int(bps * 0.05))
    assert len(sleeps) == -(-src.stat().st_size // quantum)
    assert all(duration > 0 for duration in sleeps)


def test_pace_write_stops_on_event(tmp_path):
    from weatherstar.streaming.audio import _pace_write

    bps = 100_000
    src = tmp_path / "long.pcm"
    src.write_bytes(b"\x00\x00" * (bps * 5))  # 5s at bps
    sink = tmp_path / "out.bin"
    fd = os.open(sink, os.O_WRONLY | os.O_CREAT, 0o644)
    stop = threading.Event()
    ticks = 0

    def sleep_then_stop(_seconds: float) -> None:
        nonlocal ticks
        ticks += 1
        if ticks >= 3:
            stop.set()

    try:
        _pace_write(
            fd,
            src,
            bytes_per_second=bps,
            stop_event=stop,
            clock=lambda: 0.0,
            sleep=sleep_then_stop,
        )
    finally:
        os.close(fd)

    # The stop event halts pacing after a few quanta, far short of the source.
    assert ticks == 3
    assert 0 < sink.stat().st_size < src.stat().st_size


def test_music_feed_plays_tracks_and_stops_cleanly(tmp_path, monkeypatch):
    # A fake decode + pacing stub keep this deterministic: no ffmpeg, no sleeps.
    def fake_decode(ffmpeg, track, dest, *, sample_rate, channels, volume):
        dest.write_bytes(b"\x00\x00" * 1024)
        return dest

    monkeypatch.setattr(audio_mod, "_decode_to_file", fake_decode)

    pacing = threading.Event()

    def fake_pace(fd, src, *, bytes_per_second, stop_event, **kwargs):
        os.write(fd, b"\x00\x00" * 512)
        pacing.set()
        stop_event.wait(timeout=5)

    monkeypatch.setattr(audio_mod, "_pace_write", fake_pace)

    (tmp_path / "song.mp3").write_bytes(b"x")
    sink = tmp_path / "out.pcm"
    sink.write_bytes(b"")

    feed = MusicFeed(
        tracks=[str(tmp_path / "song.mp3")],
        audio_fifo=str(sink),
        ffmpeg="not-used",
        sample_rate=1000,
        channels=1,
        work_dir=tmp_path,
    )
    feed.start()
    assert pacing.wait(timeout=5)  # audio is flowing
    assert feed.is_alive()
    feed.shutdown()
    feed.join(timeout=5)
    assert not feed.is_alive()

    # Audio actually flowed through the sink.
    assert sink.stat().st_size > 0
    # Decoded temp files are cleaned up.
    assert not list(tmp_path.glob("track-*.pcm"))


def test_music_feed_no_tracks(tmp_path):
    sink = tmp_path / "out.pcm"
    sink.write_bytes(b"")
    feed = MusicFeed(tracks=[], audio_fifo=str(sink), ffmpeg="ffmpeg")
    feed.start()
    feed.join(timeout=5)
    assert not feed.is_alive()

"""Tests for the software audio feeder (no real ffmpeg required)."""

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from weatherstar_stream import audio as audio_mod
from weatherstar_stream.audio import MusicFeed, build_decode_argv, discover_tracks


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


@pytest.fixture()
def fifo(tmp_path):
    path = tmp_path / "audio.fifo"
    os.mkfifo(path)
    yield path


def _drain(path: Path, dest: Path) -> subprocess.Popen:
    """Open the FIFO for reading and copy whatever arrives into ``dest``."""
    with dest.open("wb") as handle:
        return subprocess.Popen(["cat", str(path)], stdout=handle)


def test_pace_write_approximates_real_time(tmp_path, fifo):
    from weatherstar_stream.audio import _pace_write

    sink = tmp_path / "captured.bin"
    reader = _drain(fifo, sink)
    try:
        writer = os.open(fifo, os.O_RDWR)
        stop = threading.Event()
        pcm = tmp_path / "slice.pcm"
        bps = 100_000
        pcm.write_bytes(b"\x00\x00" * (bps // 2))  # ~0.5s of audio at bps
        start = time.monotonic()
        _pace_write(writer, pcm, bytes_per_second=bps, stop_event=stop)
        elapsed = time.monotonic() - start
        # 0.5s of audio must NOT be delivered instantly.
        assert elapsed >= 0.30
        reader.terminate()
        reader.wait()
        assert sink.stat().st_size == pcm.stat().st_size
    finally:
        try:
            os.close(writer)
        except OSError:
            pass


def test_pace_write_stops_on_event(tmp_path, fifo):
    from weatherstar_stream.audio import _pace_write

    reader = _drain(fifo, tmp_path / "x.bin")
    try:
        writer = os.open(fifo, os.O_RDWR)
        stop = threading.Event()
        pcm = tmp_path / "long.pcm"
        bps = 100_000
        pcm.write_bytes(b"\x00\x00" * (bps * 5))  # 5s at bps

        def _halt():
            time.sleep(0.2)
            stop.set()

        threading.Thread(target=_halt, daemon=True).start()
        start = time.monotonic()
        _pace_write(writer, pcm, bytes_per_second=bps, stop_event=stop)
        assert time.monotonic() - start < 4.0
        reader.terminate()
        reader.wait()
    finally:
        try:
            os.close(writer)
        except OSError:
            pass


def test_music_feed_plays_tracks_and_stops_cleanly(tmp_path, fifo, monkeypatch):
    # A real 0.4s PCM file stands in for an ffmpeg decode, so no ffmpeg needed.
    def fake_decode(ffmpeg, track, dest, *, sample_rate, channels, volume):
        bps = sample_rate * channels * 2
        dest.write_bytes(b"\x00\x00" * int(bps * 0.4))
        return dest

    monkeypatch.setattr(audio_mod, "_decode_to_file", fake_decode)
    (tmp_path / "song.mp3").write_bytes(b"x")
    sink = tmp_path / "captured.bin"
    reader = _drain(fifo, sink)

    feed = MusicFeed(
        tracks=[str(tmp_path / "song.mp3")],
        audio_fifo=str(fifo),
        ffmpeg="not-used",
        sample_rate=1000,  # small, so the test stays fast
        channels=1,
        work_dir=tmp_path,
    )
    feed.start()
    time.sleep(1.0)
    assert feed.is_alive()
    feed.shutdown()
    feed.join(timeout=5)
    assert not feed.is_alive()

    reader.terminate()
    reader.wait()
    # Audio actually flowed through the FIFO.
    assert sink.stat().st_size > 0
    # Decoded temp files are cleaned up.
    assert not list(tmp_path.glob("track-*.pcm"))


def test_music_feed_no_tracks(tmp_path, fifo):
    feed = MusicFeed(tracks=[], audio_fifo=str(fifo), ffmpeg="ffmpeg")
    feed.start()
    feed.join(timeout=5)
    assert not feed.is_alive()

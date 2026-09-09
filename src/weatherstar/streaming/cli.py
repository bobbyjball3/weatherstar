"""Command-line entrypoint for the Weather Star Jellyfin streamer.

Usage::

    weatherstar-stream [--config PATH] [--sequence NAME] [--theme NAME]
                       [--lat F --lon F] [--host HOST] [--port PORT]
                       [--public-url URL] [--hls-dir DIR]
                       [--video-encoder NAME] [--no-music] [--frames N]

The streamer reuses the simulator's own configuration discovery (``--config`` >
``WEATHERSTAR_CONFIG`` > XDG), sequence selection and ``[video]`` resolution;
only the extra ``[stream]`` table (and ``WEATHERSTAR_STREAM_*`` env vars / the
flags above) are read by this package. Like the core CLI, a config file is
required unless ``--sequence`` + ``--lat``/``--lon`` are supplied.

SDL is forced to the dummy drivers before pygame is imported: nothing here ever
opens a window or a sound device, so this runs happily inside a headless
container.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from weatherstar.config_file import (  # noqa: E402
    AppConfig,
    discover_config_path,
)
from weatherstar.errors import ConfigError, WeatherStarError  # noqa: E402
from weatherstar.streaming.audio import MusicFeed, discover_tracks  # noqa: E402
from weatherstar.streaming.config import load_stream_config  # noqa: E402
from weatherstar.streaming.encoder import EncoderError, FFmpegEncoder  # noqa: E402
from weatherstar.streaming.loop import run_stream  # noqa: E402
from weatherstar.streaming.m3u import Channel  # noqa: E402
from weatherstar.streaming.server import start_server  # noqa: E402

#: Music asset directory is always ``<asset_dir>/music`` (mirrors Music._tracks).
_MUSIC_SUBDIR = "music"
#: Matches the core Music plugin's default asset_dir.
_DEFAULT_ASSET_DIR = "static_assets/weatherstar_4000"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="weatherstar-stream",
        description="Broadcast Weather Star as an HLS channel for Jellyfin Live TV.",
    )
    parser.add_argument("--config", help="Path to config TOML (overrides env/default)")
    parser.add_argument("--sequence", help="Sequence name (overrides env/config)")
    parser.add_argument("--theme", help="Theme name (overrides config `theme`)")
    parser.add_argument("--themes-dir", help="Directory containing *.theme.toml theme files")
    parser.add_argument("--lat", type=float, help="Latitude (when no config file)")
    parser.add_argument("--lon", type=float, help="Longitude (when no config file)")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING, ERROR or CRITICAL")
    parser.add_argument("--log-file", help="Also write structured JSON logs to PATH")

    group = parser.add_argument_group("stream")
    group.add_argument("--host", help="Interface to bind the HTTP server to")
    group.add_argument("--port", type=int, help="TCP port for the HTTP server")
    group.add_argument(
        "--public-url",
        dest="public_url",
        help="Externally reachable base URL of this stream (scheme://host[:port])",
    )
    group.add_argument("--hls-dir", dest="hls_dir", help="Directory for HLS output files")
    group.add_argument("--hls-time", dest="hls_time", type=float, help="Target HLS segment seconds")
    group.add_argument(
        "--hls-list-size",
        dest="hls_list_size",
        type=int,
        help="Number of segments in the rolling window",
    )
    group.add_argument(
        "--video-encoder",
        dest="video_encoder",
        help="ffmpeg video encoder (-c:v), e.g. libx264 or h264_rkmpp",
    )
    group.add_argument("--preset", help="Software-encoder preset (e.g. veryfast)")
    group.add_argument("--audio-encoder", dest="audio_encoder", help="ffmpeg audio encoder (-c:a)")
    group.add_argument(
        "--music-dir",
        help="Directory of music files to stream (implies music on)",
    )
    group.add_argument(
        "--channel-number",
        dest="channel_number",
        help="Channel number for the M3U/XMLTV (required; e.g. 5.1)",
    )
    group.add_argument(
        "--no-music",
        action="store_true",
        help="Stream digital silence instead of the ambient music playlist",
    )
    group.add_argument("--frames", type=int, help="Stop after N frames (smoke testing)")
    return parser


def _load_app_config(args: argparse.Namespace) -> AppConfig:
    """Mirror the core CLI: config file, else explicit sequence + coordinates."""
    path = discover_config_path(args.config)
    if path is not None:
        return AppConfig.from_file(path)
    if args.sequence and args.lat is not None and args.lon is not None:
        return AppConfig({"sequence": args.sequence})
    raise ConfigError(
        "No config file found. Create one (see `weatherstar generate-config`), "
        "pass --config PATH, or supply --sequence, --lat and --lon."
    )


def _cli_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Map stream CLI flags onto StreamConfig field names (None flags omitted)."""
    keys = [
        "host",
        "port",
        "public_url",
        "hls_dir",
        "hls_time",
        "hls_list_size",
        "video_encoder",
        "preset",
        "audio_encoder",
        "channel_number",
    ]
    return {key: getattr(args, key) for key in keys if getattr(args, key) is not None}


def _music_settings(args: argparse.Namespace, appcfg: AppConfig) -> tuple[Path, bool, float]:
    """Resolve (music_dir, enabled, volume) from config > CLI overrides."""
    scope = appcfg.scope("media", "music")
    enabled = bool(scope.get("enabled", False))
    asset_dir = str(scope.get("asset_dir", _DEFAULT_ASSET_DIR))
    music_dir = Path(asset_dir) / _MUSIC_SUBDIR
    volume = float(scope.get("volume", 0.6))
    if args.music_dir:
        music_dir = Path(args.music_dir)
        enabled = True
    if args.no_music:
        enabled = False
    return music_dir, enabled, volume


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except (WeatherStarError, EncoderError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def _run(args: argparse.Namespace) -> int:
    import logging

    from weatherstar.engine import Builder, resolve_location
    from weatherstar.logging_setup import setup_logging
    from weatherstar.registry import discover
    from weatherstar.sequence import Sequence

    appcfg = _load_app_config(args)
    level_name = (args.log_level or "INFO").upper()
    setup_logging(
        getattr(logging, level_name, logging.INFO),
        console=True,
        log_file=args.log_file,
    )
    discover()

    cfg = load_stream_config(app_config=appcfg, overrides=_cli_overrides(args))

    seq_name, seq_data = appcfg.select_sequence(args.sequence)
    sequence = Sequence.from_config(seq_name, seq_data)
    location = resolve_location(appcfg, args.lat, args.lon)
    video = appcfg.video
    width, height, fps = video.width, video.height, video.fps

    music_dir, music_enabled, music_volume = _music_settings(args, appcfg)
    tracks = discover_tracks(music_dir) if music_enabled else []
    feed_audio = bool(tracks)

    import pygame

    pygame.init()
    surface = pygame.Surface((width, height))
    builder = Builder(appcfg, cli_theme=args.theme, themes_dir=args.themes_dir)
    ctx, screens = builder.build_runtime(sequence, surface, location)

    encoder = FFmpegEncoder(cfg=cfg, width=width, height=height, fps=fps, feed_audio=feed_audio)
    stop_event = threading.Event()
    audio: MusicFeed | None = None

    def _signal_handler(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    encoder.start()
    if feed_audio:
        audio = MusicFeed(
            tracks=tracks,
            audio_fifo=encoder.audio_fifo,
            sample_rate=cfg.audio_rate,
            channels=cfg.audio_channels,
            volume=music_volume,
            stop_event=stop_event,
        )
        audio.start()

    channel = Channel(
        name=cfg.channel_name,
        channel_id=cfg.channel_id,
        number=cfg.channel_number,
        logo=cfg.channel_logo,
    )
    server, _thread = start_server(
        host=cfg.host,
        port=cfg.port,
        hls_dir=cfg.hls_dir,
        channel=channel,
        public_url=cfg.public_url,
        guide_days=cfg.guide_days,
    )

    try:
        print(
            f"streaming {seq_name!r} at {width}x{height}@{fps} fps to "
            f"http://{cfg.host}:{cfg.port}/channel.m3u "
            f"(encoder={cfg.video_encoder}, music={'on' if feed_audio else 'off'})"
        )
        run_stream(
            ctx,
            screens,
            sequence,
            encoder=encoder,
            fps=fps,
            stop_event=stop_event,
            max_frames=args.frames,
        )
    finally:
        if audio is not None:
            audio.shutdown()
        encoder.stop()
        server.shutdown()
        server.server_close()
        if audio is not None:
            audio.join(timeout=5.0)
        pygame.quit()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""Tests for the weatherstar-stream CLI (heavy stubbing, no real encoding)."""

import signal

from weatherstar.streaming import cli as cli_mod
from weatherstar.streaming.cli import _cli_overrides, _music_settings, build_parser


def _write_config(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
sequence = "mini"
[location]
lat = 28.5
lon = -81.3
description = "Orlando, FL"
[video]
width = 160
height = 120
fps = 5
[media.music]
enabled = false
[sequences.mini]
pause = 0.5
slides = [
    { screen = "current_conditions" },
]
"""
    )
    return cfg


def test_cli_overrides_omits_nones():
    args = build_parser().parse_args(["--port", "9999"])
    overrides = _cli_overrides(args)
    assert overrides == {"port": 9999}


def test_music_settings_defaults(tmp_path):
    cfg = _write_config(tmp_path)
    from weatherstar.config_file import AppConfig

    appcfg = AppConfig.from_file(cfg)
    args = build_parser().parse_args([])
    music_dir, enabled, volume = _music_settings(args, appcfg)
    assert enabled is False
    assert str(music_dir).endswith("static_assets/weatherstar_4000/music")
    assert volume == 0.6


def test_music_settings_cli_force_and_disable(tmp_path):
    cfg = _write_config(tmp_path)
    from weatherstar.config_file import AppConfig

    appcfg = AppConfig.from_file(cfg)
    args = build_parser().parse_args(["--music-dir", "/tmp/music"])
    _dir, enabled, _vol = _music_settings(args, appcfg)
    assert enabled is True
    assert str(_dir) == "/tmp/music"

    args = build_parser().parse_args(["--no-music", "--music-dir", "/tmp/music"])
    _dir, enabled, _vol = _music_settings(args, appcfg)
    assert enabled is False


def test_main_config_error_returns_two(tmp_path, capsys):
    rc = cli_mod.main(["--config", str(tmp_path / "missing.toml")])
    assert rc == 2
    assert "error:" in capsys.readouterr().err


class _FakeBuilder:
    def __init__(self, appcfg, cli_theme=None, themes_dir=None):
        self.appcfg = appcfg

    def build_runtime(self, sequence, surface, location):
        return object(), []


class _FakeEncoder:
    def __init__(self, *args, **kwargs):
        self.audio_fifo = None
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class _FakeServer:
    def __init__(self, *args, **kwargs):
        self.shutdown_called = False

    def shutdown(self):
        self.shutdown_called = True

    def server_close(self):
        pass


def test_run_happy_path(tmp_path, monkeypatch):
    cfg = _write_config(tmp_path)
    monkeypatch.setattr("weatherstar.engine.Builder", _FakeBuilder)
    monkeypatch.setattr("weatherstar.registry.discover", lambda: None)
    monkeypatch.setattr("weatherstar.logging_setup.setup_logging", lambda *a, **k: None)

    encoder = _FakeEncoder()
    monkeypatch.setattr(cli_mod, "FFmpegEncoder", lambda *a, **k: encoder)
    servers = []
    monkeypatch.setattr(
        cli_mod,
        "start_server",
        lambda **kw: (servers.append(_FakeServer()) or servers[-1], None),
    )

    def _fake_run_stream(ctx, screens, sequence, **kwargs):
        kwargs["stop_event"].set()
        return 2

    monkeypatch.setattr(cli_mod, "run_stream", _fake_run_stream)

    try:
        rc = cli_mod.main(["--config", str(cfg)])
    finally:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
    assert rc == 0
    assert encoder.started and encoder.stopped
    assert servers and servers[0].shutdown_called

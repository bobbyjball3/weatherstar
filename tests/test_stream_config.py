"""Tests for the stream configuration model and its precedence rules."""

import types

import pytest
from pydantic import ValidationError

from weatherstar.streaming.config import (
    ENV_PREFIX,
    StreamConfig,
    env_overrides,
    load_stream_config,
)


def _with_env(monkeypatch, **values):
    for key, value in values.items():
        monkeypatch.setenv(f"{ENV_PREFIX}{key}", value)


def test_defaults():
    cfg = StreamConfig(channel_number="5")
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8080
    assert cfg.public_url is None
    assert cfg.hls_time == 4.0
    assert cfg.hls_list_size == 6
    assert cfg.video_encoder == "libx264"
    assert cfg.audio_encoder == "aac"
    assert cfg.audio_rate == 48000
    assert cfg.audio_channels == 2
    assert cfg.channel_name == "Weather Star 4000"
    assert cfg.channel_number == "5"
    assert cfg.guide_days == 7


def test_channel_number_required():
    with pytest.raises(ValidationError):
        StreamConfig()


def test_subchannel_number_string_accepted():
    cfg = StreamConfig(channel_number="5.2")
    assert cfg.channel_number == "5.2"


def test_file_section_overrides_defaults():
    appcfg = types.SimpleNamespace(
        data={"stream": {"channel_number": "5", "port": 8123, "video_encoder": "h264_rkmpp"}}
    )
    cfg = load_stream_config(app_config=appcfg)
    assert cfg.port == 8123
    assert cfg.video_encoder == "h264_rkmpp"
    # Unset fields still fall back to defaults.
    assert cfg.host == "0.0.0.0"


def test_env_overrides_file_section(monkeypatch):
    appcfg = types.SimpleNamespace(data={"stream": {"channel_number": "5", "port": 8123}})
    _with_env(monkeypatch, PORT="9090")
    cfg = load_stream_config(app_config=appcfg)
    assert cfg.port == 9090


def test_env_supplies_required_channel_number(monkeypatch):
    _with_env(monkeypatch, CHANNEL_NUMBER="5")
    cfg = load_stream_config(app_config=types.SimpleNamespace(data={}))
    assert cfg.channel_number == "5"


def test_explicit_overrides_beat_env_and_file(monkeypatch):
    appcfg = types.SimpleNamespace(
        data={"stream": {"channel_number": "5", "port": 8123, "hls_time": 4.0}}
    )
    _with_env(monkeypatch, PORT="9090", HLS_TIME="6")
    cfg = load_stream_config(app_config=appcfg, overrides={"port": 7000, "channel_number": "9.2"})
    assert cfg.port == 7000
    assert cfg.channel_number == "9.2"
    assert cfg.hls_time == 6.0  # from env (no CLI override supplied)


def test_env_overrides_reads_all_fields(monkeypatch):
    _with_env(
        monkeypatch,
        HOST="127.0.0.1",
        PORT="1234",
        PUBLIC_URL="http://rk1:8080",
        HLS_TIME="2",
        HLS_LIST_SIZE="3",
        VIDEO_ENCODER="libx265",
        CHANNEL_NUMBER="42",
        GUIDE_DAYS="3",
    )
    overrides = env_overrides()
    assert overrides["port"] == "1234"
    assert overrides["public_url"] == "http://rk1:8080"
    assert overrides["channel_number"] == "42"
    assert overrides["guide_days"] == "3"


def test_unknown_file_keys_ignored():
    appcfg = types.SimpleNamespace(
        data={"stream": {"channel_number": "5", "bogus_key": 1, "port": 9999}}
    )
    cfg = load_stream_config(app_config=appcfg)
    assert cfg.port == 9999


def test_uses_preset():
    assert StreamConfig(channel_number="5", video_encoder="libx264").uses_preset()
    assert StreamConfig(channel_number="5", video_encoder="libx265").uses_preset()
    assert not StreamConfig(channel_number="5", video_encoder="h264_rkmpp").uses_preset()
    assert not StreamConfig(channel_number="5", video_encoder="hevc_rkmpp").uses_preset()

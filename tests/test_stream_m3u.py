"""Tests for the Jellyfin M3U playlist generation."""

from weatherstar_stream.m3u import Channel, channel_m3u


def test_default_channel_playlist():
    text = channel_m3u("http://rk1:8080/stream/index.m3u8")
    assert text.startswith("#EXTM3U\n")
    assert 'tvg-id="weatherstar-4000"' in text
    assert 'tvg-name="Weather Star"' in text
    assert text.rstrip().endswith("http://rk1:8080/stream/index.m3u8")


def test_custom_channel_metadata():
    channel = Channel(
        name="Local Radar", channel_id="ws-radar", logo="http://x/logo.png", group="TV"
    )
    text = channel_m3u("http://h/stream/index.m3u8", channel)
    assert 'tvg-id="ws-radar"' in text
    assert 'tvg-name="Local Radar"' in text
    assert 'tvg-logo="http://x/logo.png"' in text
    assert 'group-title="TV"' in text


def test_no_logo_omits_attribute():
    text = channel_m3u("http://h/stream/index.m3u8", Channel(logo=None))
    assert "tvg-logo=" not in text

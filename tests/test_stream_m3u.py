"""Tests for the Jellyfin M3U playlist generation."""

import pytest

from weatherstar.streaming.m3u import Channel, channel_m3u


def test_default_channel_playlist():
    text = channel_m3u("http://rk1:8080/stream/index.m3u8", Channel(number="5"))
    assert text.startswith("#EXTM3U\n")
    assert 'tvg-id="weatherstar-4000"' in text
    assert 'tvg-name="Weather Star 4000"' in text
    assert 'tvg-chno="5"' in text
    assert "url-tvg=" not in text
    assert text.rstrip().endswith("http://rk1:8080/stream/index.m3u8")


def test_custom_channel_metadata():
    channel = Channel(
        number="42",
        name="Local Radar",
        channel_id="ws-radar",
        logo="http://x/logo.png",
        group="TV",
    )
    text = channel_m3u("http://h/stream/index.m3u8", channel)
    assert 'tvg-id="ws-radar"' in text
    assert 'tvg-name="Local Radar"' in text
    assert 'tvg-chno="42"' in text
    assert 'tvg-logo="http://x/logo.png"' in text
    assert 'group-title="TV"' in text


def test_no_logo_omits_attribute():
    text = channel_m3u("http://h/stream/index.m3u8", Channel(number="5", logo=None))
    assert "tvg-logo=" not in text


def test_subchannel_number_passthrough():
    channel = Channel(number="5.2", channel_id="ws-3000")
    text = channel_m3u("http://h/stream/index.m3u8", channel)
    assert 'tvg-chno="5.2"' in text


def test_channel_requires_number():
    with pytest.raises(TypeError):
        Channel()


def test_guide_url_on_header_line():
    text = channel_m3u(
        "http://h/stream/index.m3u8", Channel(number="5"), guide_url="http://h/guide.xml"
    )
    assert text.startswith('#EXTM3U url-tvg="http://h/guide.xml"\n')
    assert 'url-tvg="http://h/guide.xml"' in text

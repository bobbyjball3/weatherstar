"""Tests for the XMLTV guide generation."""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from weatherstar.streaming.m3u import Channel
from weatherstar.streaming.xmltv import guide_xml

_UTC = timezone.utc

_DEFAULT_CHANNEL = Channel(number="5")


def _parse(text: str) -> ET.Element:
    return ET.fromstring(text)


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d%H%M%S +0000").replace(tzinfo=_UTC)


def test_default_channel_document():
    root = _parse(guide_xml(_DEFAULT_CHANNEL))
    assert root.tag == "tv"
    assert root.get("generator-info-name") == "weatherstar"

    channels = root.findall("channel")
    assert len(channels) == 1
    channel = channels[0]
    assert channel.get("id") == "weatherstar-4000"
    names = [d.text for d in channel.findall("display-name")]
    assert names == ["Weather Star 4000", "5"]


def test_subchannel_number_is_emitted_verbatim():
    root = _parse(guide_xml(Channel(number="5.2", name="Weather Star 3000", channel_id="ws-3000")))
    names = [d.text for d in root.findall("channel/display-name")]
    assert names == ["Weather Star 3000", "5.2"]


def test_programmes_cover_now():
    now = datetime(2026, 9, 7, 10, 37, tzinfo=_UTC)
    root = _parse(guide_xml(_DEFAULT_CHANNEL, now=now))
    programme = root.findall("programme")
    assert programme

    first_start = _parse_time(programme[0].get("start"))
    first_stop = _parse_time(programme[0].get("stop"))
    # The block containing "now" is first and must be playing right now.
    assert first_start <= now < first_stop
    assert first_stop - first_start == timedelta(hours=1)

    for prog in programme:
        assert prog.get("channel") == "weatherstar-4000"
        assert prog.findtext("title") == "Weather Star 4000"
        assert prog.findtext("desc")


def test_programme_window_and_contiguity():
    now = datetime(2026, 9, 7, 10, 0, tzinfo=_UTC)
    days = 7
    root = _parse(guide_xml(_DEFAULT_CHANNEL, now=now, days=days))
    programme = root.findall("programme")

    # Anchored at the hour, a whole number of hourly blocks covers days*24.
    assert len(programme) == days * 24

    last_stop = _parse_time(programme[-1].get("stop"))
    assert last_stop - now == timedelta(days=days)

    # Blocks are contiguous: no gaps, no overlap.
    for prev, prog in zip(programme, programme[1:]):
        assert _parse_time(prev.get("stop")) == _parse_time(prog.get("start"))


def test_custom_channel_and_description():
    channel = Channel(number="42", name="Local Radar", channel_id="ws-radar")
    root = _parse(
        guide_xml(channel, now=datetime(2026, 1, 1, tzinfo=_UTC), description="Radar loop.")
    )
    assert root.find("channel").get("id") == "ws-radar"
    names = [d.text for d in root.findall("channel/display-name")]
    assert names == ["Local Radar", "42"]
    programme = root.find("programme")
    assert programme.get("channel") == "ws-radar"
    assert programme.findtext("title") == "Local Radar"
    assert programme.findtext("desc") == "Radar loop."


def test_times_are_utc():
    root = _parse(guide_xml(_DEFAULT_CHANNEL, now=datetime(2026, 9, 7, 3, 30, tzinfo=_UTC)))
    for prog in root.findall("programme"):
        for attr in ("start", "stop"):
            value = prog.get(attr)
            assert value.endswith(" +0000")
            _parse_time(value)  # raises if malformed

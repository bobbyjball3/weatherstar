"""XMLTV guide generation for the Weather Star channel.

Jellyfin (and IPTV apps like MisterFin/InFuse/Neptune that read the M3U's
``url-tvg``) need an Electronic Program Guide to show what is "on now". This
module renders the XMLTV document for the single always-on channel.

The channel is 24/7, so the guide is generated **per request anchored to
"now"**: the first programme opens at the current hour and hourly blocks roll
forward for a window (``days``), which means the programme covering the instant
the file is fetched always says the channel is playing. No periodic
regeneration is required — a client that re-fetches the guide always sees the
current block.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from weatherstar.streaming.m3u import Channel

#: Default copy shown under every programme entry.
_DESCRIPTION = "The Weather Star 4000 local forecast, broadcasting 24 hours a day, 7 days a week."

#: XMLTV times are wall-clock in a named offset: ``YYYYMMDDHHMMSS +0000``.
_TIME_FORMAT = "%Y%m%d%H%M%S +0000"


def _xmltv_time(moment: datetime) -> str:
    return moment.strftime(_TIME_FORMAT)


def _programmes(channel: Channel, now: datetime, days: int) -> list[tuple[datetime, datetime]]:
    """Return hourly (start, stop) UTC blocks covering ``days`` from ``now``."""
    anchor = now.replace(minute=0, second=0, microsecond=0)
    horizon = now + timedelta(days=days)
    start = anchor
    blocks: list[tuple[datetime, datetime]] = []
    while start < horizon:
        stop = start + timedelta(hours=1)
        blocks.append((start, stop))
        start = stop
    return blocks


def guide_xml(
    channel: Channel,
    *,
    now: datetime | None = None,
    days: int = 7,
    description: str | None = None,
) -> str:
    """Render an XMLTV document for ``channel`` playing around-the-clock.

    ``now`` is used to anchor the rolling programme window and defaults to the
    current UTC time; pass a fixed value in tests for deterministic output.
    ``days`` is how many days of hourly programmes are emitted ahead of ``now``.
    """
    now = (now if now is not None else datetime.now(timezone.utc)).astimezone(timezone.utc)
    desc = description or _DESCRIPTION

    channel_el = [
        f'  <channel id="{html.escape(channel.channel_id, quote=True)}">',
        f"    <display-name>{html.escape(channel.name)}</display-name>",
        f"    <display-name>{channel.number}</display-name>",
        "  </channel>",
    ]

    programme_els: list[str] = []
    for start, stop in _programmes(channel, now, days):
        programme_els.append(
            f'  <programme start="{_xmltv_time(start)}" '
            f'stop="{_xmltv_time(stop)}" '
            f'channel="{html.escape(channel.channel_id, quote=True)}">'
        )
        programme_els.append(f'    <title lang="en">{html.escape(channel.name)}</title>')
        programme_els.append(f'    <desc lang="en">{html.escape(desc)}</desc>')
        programme_els.append("  </programme>")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE tv SYSTEM "xmltv.dtd">',
        '<tv generator-info-name="weatherstar" source-info-name="Weather Star">',
        *channel_el,
        *programme_els,
        "</tv>",
        "",
    ]
    return "\n".join(lines)

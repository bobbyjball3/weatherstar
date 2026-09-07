"""M3U playlist generation for Jellyfin Live TV.

Jellyfin's built-in "M3U Tuner" ingests a plain ``.m3u`` file whose entries are
HTTP stream URLs. The server publishes one such playlist (``/channel.m3u``)
that points at the rolling HLS playlist of the encoded channel, so adding the
channel to Jellyfin is a matter of pointing an M3U tuner at that single URL.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Channel:
    """Metadata for one channel advertised in the M3U playlist."""

    name: str = "Weather Star"
    channel_id: str = "weatherstar-4000"
    logo: str | None = None
    group: str = "Local"


def channel_m3u(stream_url: str, channel: Channel | None = None) -> str:
    """Render an ``#EXTM3U`` playlist for ``channel`` streaming at ``stream_url``.

    ``stream_url`` should be the absolute URL of the HLS master playlist
    (``index.m3u8``) that ffmpeg is writing.
    """
    channel = channel or Channel()
    logo = ""
    if channel.logo:
        logo = f' tvg-logo="{channel.logo}"'
    return (
        "#EXTM3U\n"
        f'#EXTINF:-1 tvg-id="{channel.channel_id}" '
        f'tvg-name="{channel.name}" tvg-chno="1"'
        f'{logo} group-title="{channel.group}",{channel.name}\n'
        f"{stream_url}\n"
    )

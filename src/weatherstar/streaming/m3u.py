"""M3U playlist generation for Jellyfin Live TV.

Jellyfin's built-in "M3U Tuner" ingests a plain ``.m3u`` file whose entries are
HTTP stream URLs. The server publishes one such playlist (``/channel.m3u``)
that points at the rolling HLS playlist of the encoded channel and advertises
the XMLTV guide (``url-tvg``), so adding the channel to Jellyfin is a matter of
pointing an M3U tuner at that single URL.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Channel:
    """Metadata for one channel advertised in the M3U playlist.

    ``number`` is required — it has no default because every deployment must
    choose its own channel number (see ``[stream] channel_number``).
    """

    number: str
    name: str = "Weather Star 4000"
    channel_id: str = "weatherstar-4000"
    logo: str | None = None
    group: str = "Local"


def channel_m3u(
    stream_url: str,
    channel: Channel,
    guide_url: str | None = None,
) -> str:
    """Render an ``#EXTM3U`` playlist for ``channel`` streaming at ``stream_url``.

    ``stream_url`` should be the absolute URL of the HLS master playlist
    (``index.m3u8``) that ffmpeg is writing. ``guide_url`` is the absolute URL
    of the XMLTV guide (``/guide.xml``); when given it is advertised as the
    playlist's ``url-tvg`` so IPTV apps can auto-discover the EPG.
    """
    logo = ""
    if channel.logo:
        logo = f' tvg-logo="{channel.logo}"'
    guide = ""
    if guide_url:
        guide = f' url-tvg="{guide_url}"'
    return (
        f"#EXTM3U{guide}\n"
        f'#EXTINF:-1 tvg-id="{channel.channel_id}" '
        f'tvg-name="{channel.name}" tvg-chno="{channel.number}"'
        f'{logo} group-title="{channel.group}",{channel.name}\n'
        f"{stream_url}\n"
    )

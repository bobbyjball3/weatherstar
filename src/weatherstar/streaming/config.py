"""Stream configuration: network, HLS and encoder options for the broadcaster.

The stream has no hard dependency on the simulator's ``[video]`` section; the
resolution and frame rate it encodes are *passed in* by the caller (the CLI
defaults them to ``[video]``). Everything that is purely about broadcasting
lives here so it can be documented and validated in one place.

Configuration precedence (lowest to highest):

1. built-in defaults,
2. the ``[stream]`` table of the Weather Star ``config.toml`` (when the caller
   passes the app config in),
3. ``WEATHERSTAR_STREAM_*`` environment variables (one per field, uppercase),
4. explicit CLI overrides.

There is no cross-dependency on the simulator's plugin config machinery: this is
a plain Pydantic model read straight from a dict, so removing the streaming
package never touches the core.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ENV_PREFIX = "WEATHERSTAR_STREAM_"

#: Encoders that understand ffmpeg's generic ``-preset`` knob.
_PRESET_ENCODERS = ("libx264", "libx265", "libsvtav1")


def _default_hls_dir() -> Path:
    return Path(tempfile.gettempdir()) / "weatherstar-hls"


class StreamConfig(BaseModel):
    """Options controlling how the Weather Star channel is broadcast."""

    model_config = ConfigDict(extra="ignore")

    host: str = Field(
        default="0.0.0.0",
        description="Interface the HLS/HTTP server binds to.",
    )
    port: int = Field(
        default=8080,
        description="TCP port the HLS/HTTP server listens on.",
    )
    public_url: str | None = Field(
        default=None,
        description=(
            "Externally reachable base URL (scheme://host[:port]) that Jellyfin "
            "should use to fetch this stream. Defaults to the Host header of the "
            "request that asks for the M3U playlist, which is right in most "
            "setups; set this when Jellyfin reaches the stream through a "
            "different name than the one it uses to fetch the playlist."
        ),
    )
    hls_dir: Path = Field(
        default_factory=_default_hls_dir,
        description=(
            "Directory where ffmpeg writes the rolling HLS window "
            "(index.m3u8 + segment files). Cleared of old segments by ffmpeg."
        ),
    )
    hls_time: float = Field(
        default=4.0,
        description="Target HLS segment duration in seconds.",
    )
    hls_list_size: int = Field(
        default=6,
        description="Number of segments kept in the rolling playlist window.",
    )
    video_encoder: str = Field(
        default="libx264",
        description=(
            "ffmpeg video encoder/codec name passed to -c:v. Use libx264 for "
            "development and h264_rkmpp on the RK3588/RK1 to hardware-encode."
        ),
    )
    preset: str = Field(
        default="veryfast",
        description="Encoder preset (software encoders such as libx264 only).",
    )
    audio_encoder: str = Field(
        default="aac",
        description="ffmpeg audio encoder/codec name passed to -c:a.",
    )
    audio_bitrate: str = Field(
        default="128k",
        description="Audio bitrate passed to -b:a (e.g. 128k).",
    )
    audio_rate: int = Field(
        default=48000,
        description="Audio sample rate fed to the encoder, in Hz.",
    )
    audio_channels: int = Field(
        default=2,
        description="Number of interleaved audio channels (2 = stereo).",
    )
    channel_name: str = Field(
        default="Weather Star 4000",
        description="Channel name advertised in the M3U playlist and XMLTV guide.",
    )
    channel_id: str = Field(
        default="weatherstar-4000",
        description="Stable channel id used as the M3U tvg-id and XMLTV channel id.",
    )
    channel_number: str = Field(
        description=(
            "Channel number advertised in the M3U (tvg-chno) and XMLTV guide. "
            "REQUIRED: supply a value here or via the WEATHERSTAR_STREAM_CHANNEL_NUMBER "
            "environment variable. Any string is accepted, so sub-channels are possible "
            "— use a decimal like '5.1' or '5.2'. A bare hyphenated form ('5-1') is not "
            "honoured by Jellyfin's M3U tuner, which only keeps channel numbers it can "
            "parse as a number."
        ),
    )
    channel_logo: str | None = Field(
        default=None,
        description="Optional absolute URL for the channel logo (tvg-logo).",
    )
    guide_days: int = Field(
        default=7,
        description=(
            "Days of hourly XMLTV guide emitted ahead of 'now' at /guide.xml. "
            "The guide is regenerated per request and always covers the present."
        ),
    )

    def uses_preset(self) -> bool:
        return any(tag in self.video_encoder for tag in _PRESET_ENCODERS)


def env_overrides() -> dict[str, Any]:
    """Read ``WEATHERSTAR_STREAM_<FIELD>`` environment variables."""
    out: dict[str, Any] = {}
    for field_name in StreamConfig.model_fields:
        value = os.environ.get(f"{ENV_PREFIX}{field_name.upper()}")
        if value is not None:
            out[field_name] = value
    return out


def load_stream_config(
    *,
    app_config: Any | None = None,
    overrides: dict[str, Any] | None = None,
) -> StreamConfig:
    """Build a :class:`StreamConfig` from file/env/CLI, in that precedence order.

    ``app_config`` is the simulator's ``AppConfig``; only its ``[stream]`` table
    is read (via ``.data``), never anything the core engine owns.
    """
    raw: dict[str, Any] = {}
    if app_config is not None:
        raw.update(app_config.data.get("stream") or {})
    raw.update(env_overrides())
    raw.update(overrides or {})
    return StreamConfig.model_validate(raw)

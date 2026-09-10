"""NOAA/NWS radar frames, cropped to a regional view around the location.

Mirrors the legacy behaviour: fetch the CONUS radar stills from
``radar.weather.gov`` (newest..oldest), crop each to a ~1/5 window centred on
the configured coordinates, and rescale to the radar box.  The base
:meth:`~weatherstar.datasources.base.Datasource.fetch` caches responses
(failures included), so an offline box only retries every ``cache_ttl`` seconds.
"""

from __future__ import annotations

import io

import pygame

from weatherstar.datasources.base import Datasource
from weatherstar.registry import plugin

# Candidate image templates, newest first ordering handled per-frame below.
# NOAA ridge serves one still per index; higher-res first like the legacy app.
_INDEX_URLS = [
    "https://radar.weather.gov/ridge/standard/CONUS-LARGE_{i}.gif",
    "https://radar.weather.gov/ridge/standard/CONUS_{i}.gif",
    "https://radar.weather.gov/ridge/lite/N0R/CONUS_{i}.png",
]

# CONUS geographic bounds used to map lon/lat -> pixel.
_LON_WEST, _LON_EAST = -125.0, -65.0
_LAT_SOUTH, _LAT_NORTH = 24.0, 50.0

_CROP_TARGET = (500, 300)
_FRAME_COUNT = 6


@plugin
class NoaaRadar(Datasource):
    """Fetch cropped NOAA CONUS radar frames for a lat/lon."""

    name = "radar"

    # -- crop math (also unit-tested directly) --------------------------------

    @staticmethod
    def crop_box(lat: float, lon: float, size: tuple[int, int]) -> tuple[int, int, int, int]:
        """Return the (left, top, right, bottom) regional crop around ``lat/lon``."""
        width, height = size
        x_norm = max(0.0, min(1.0, (lon - _LON_WEST) / (_LON_EAST - _LON_WEST)))
        y_norm = max(0.0, min(1.0, (_LAT_NORTH - lat) / (_LAT_NORTH - _LAT_SOUTH)))
        center_x = int(width * x_norm)
        center_y = int(height * y_norm)

        box_width = max(1, width // 5)
        box_height = max(1, height // 5)
        left = max(0, center_x - box_width // 2)
        top = max(0, center_y - box_height // 2)
        if left + box_width > width:
            left = width - box_width
        if top + box_height > height:
            top = height - box_height
        right = min(width, left + box_width)
        bottom = min(height, top + box_height)
        return (left, top, right, bottom)

    # -- fetching -------------------------------------------------------------

    def parse_response(self, response) -> bytes | None:
        """Radar stills are images, so read the body as raw bytes."""
        return self.response_bytes(response)

    def _fetch_bytes(self, url: str) -> bytes | None:
        data = self.fetch("GET", url)
        return data if data and len(data) > 1000 else None

    @staticmethod
    def _build_frame(data: bytes, lat: float, lon: float) -> pygame.Surface:
        image = pygame.image.load(io.BytesIO(data))
        left, top, right, bottom = NoaaRadar.crop_box(lat, lon, image.get_size())
        crop = image.subsurface((left, top, right - left, bottom - top)).copy()
        return pygame.transform.scale(crop, _CROP_TARGET)

    def _fetch_frames(self, lat: float, lon: float) -> list[pygame.Surface]:
        """Return cropped frames oldest-first; empty list when offline."""
        frames: list[pygame.Surface] = []
        for index in range(_FRAME_COUNT - 1, -1, -1):  # oldest -> newest
            for template in _INDEX_URLS:
                url = template.format(i=index)
                data = self._fetch_bytes(url)
                if data:
                    try:
                        frames.append(self._build_frame(data, lat, lon))
                        break
                    except Exception as exc:  # noqa: BLE001
                        self._log.debug("radar_decode_failed", url=url, error=str(exc))
        return frames

    def frames(self, lat: float, lon: float) -> list[pygame.Surface]:
        """Return the radar frames, cropped to the regional view (empty offline)."""
        return self._fetch_frames(lat, lon)

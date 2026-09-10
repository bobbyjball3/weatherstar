"""NOAA HRRR future-radar frames, cropped to a regional view around the location.

The classic RIDGE stills only reach ~20 minutes into the past, so a multi-hour
loop is built from NOAA's HRRR model composite reflectivity (simulated radar),
mirrored by the Iowa Environmental Mesonet (IEM).  HRRR runs hourly with
15-minute forecast steps, so the freshest published run renders the window from
now out to ``forecast_minutes`` ahead.

Each frame is cropped to a ~1/5 window centred on the configured coordinates and
rescaled to the radar box, then composited over a county-border basemap.  The
basemap is built from IEM's transparent Web-Mercator tile service and reprojected
onto the HRRR's equirectangular grid, so it lines up with the echoes without any
of the header/logo chrome the IEM's dynamic map renderer bakes in.  The base
:meth:`~weatherstar.datasources.base.Datasource.fetch` caches responses
(failures included), so an offline box only retries every ``cache_ttl`` seconds.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import pygame
from PIL import Image
from pydantic import Field

from weatherstar.datasources.base import Datasource
from weatherstar.plugin import memoize
from weatherstar.registry import plugin

# IEM archive of NOAA HRRR composite reflectivity (simulated radar).  ``lead`` is
# the forecast offset from the run time in minutes (0000, 0015, ...).
_RUN_URL = (
    "https://mesonet.agron.iastate.edu/archive/data/"
    "{year:04d}/{month:02d}/{day:02d}/GIS/hrrr/{hour:02d}/refd_{lead:04d}.png"
)

# IEM transparent Web-Mercator (EPSG:3857) county-border tiles, reprojected to
# the HRRR grid for the basemap.
_TILE_URL = "https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/uscounties/{z}/{x}/{y}.png"
_TILE_SIZE = 256
_MAX_TILE_ZOOM = 7
_BASEMAP_BG = (0, 0, 160)
_BORDER_COLOR = 130

# HRRR CONUS geographic bounds (from the product's ``.wld``: 0.02 deg pixels with
# a top-left of (-126, 50) over a 3050x1340 image).
_LON_WEST, _LON_EAST = -126.0, -65.0
_LAT_SOUTH, _LAT_NORTH = 23.2, 50.0
_GRID_SIZE = (3050, 1340)
_GRID_PIXEL_DEG = 0.02

_CROP_TARGET = (500, 300)
#: How many hours back to look for the newest HRRR run that has been published.
_MAX_RUN_LOOKBACK_HOURS = 6
#: The basemap art only changes when the tiles do; cache it for a day.
_BASEMAP_TTL = 86_400


@dataclass(frozen=True)
class RadarFrame:
    """One future-radar frame: its valid time (UTC) and composited surface."""

    time: datetime
    surface: pygame.Surface


@plugin
class NoaaRadar(Datasource):
    """Fetch cropped NOAA HRRR future-radar frames for a lat/lon."""

    name = "radar"

    forecast_minutes: int = Field(
        default=120,
        description="How far ahead the future-radar loop runs, in minutes.",
    )
    frame_interval_minutes: int = Field(
        default=15,
        description="Minutes between future-radar frames (the HRRR forecast step).",
    )
    show_basemap: bool = Field(
        default=True,
        description="Composite frames over an IEM county-border map background.",
    )

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

    @staticmethod
    def _crop_bbox(lat: float, lon: float) -> tuple[float, float, float, float]:
        """Lat/lon (west, south, east, north) of the regional crop window."""
        left, top, right, bottom = NoaaRadar.crop_box(lat, lon, _GRID_SIZE)
        return (
            _LON_WEST + left * _GRID_PIXEL_DEG,
            _LAT_NORTH - bottom * _GRID_PIXEL_DEG,
            _LON_WEST + right * _GRID_PIXEL_DEG,
            _LAT_NORTH - top * _GRID_PIXEL_DEG,
        )

    # -- run discovery --------------------------------------------------------

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _run_url(run: datetime, lead_minutes: int) -> str:
        return _RUN_URL.format(
            year=run.year, month=run.month, day=run.day, hour=run.hour, lead=lead_minutes
        )

    def _run_available(self, run: datetime) -> bool:
        """Whether the HRRR ``run`` has been published (its lead-0000 frame exists)."""
        request = self.client.build_request("HEAD", self._run_url(run, 0))
        return self.exists(request)

    def _latest_run(self, now: datetime) -> datetime | None:
        """Newest published HRRR run at/behind ``now`` (hourly), or ``None``."""
        hour = now.replace(minute=0, second=0, microsecond=0)
        for hours_back in range(_MAX_RUN_LOOKBACK_HOURS + 1):
            run = hour - timedelta(hours=hours_back)
            if self._run_available(run):
                return run
        return None

    def _leads(self, now: datetime, run: datetime) -> list[int]:
        """Forecast lead minutes from ``now`` out to ``forecast_minutes``.

        Aligned to the model's forecast step: the first frame is the first step
        at or after ``now`` and the last is ``forecast_minutes`` ahead.
        """
        step = max(1, self.frame_interval_minutes)
        ahead = max(0.0, (now - run).total_seconds() / 60.0)
        start = math.ceil(ahead / step) * step
        span = max(0, self.forecast_minutes)
        return [start + offset for offset in range(0, span + 1, step)]

    # -- basemap (IEM tiles reprojected to the HRRR grid) ---------------------

    @staticmethod
    def _lon_to_px(lon: float, zoom: int) -> float:
        return (lon + 180.0) / 360.0 * _TILE_SIZE * (2**zoom)

    @staticmethod
    def _lat_to_px(lat: float, zoom: int) -> float:
        lat = max(-85.05112878, min(85.05112878, lat))
        return (
            (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * _TILE_SIZE * (2**zoom)
        )

    @staticmethod
    def _basemap_zoom(west: float, east: float) -> int:
        """A tile zoom whose resolution is at least as fine as the target."""
        span = max(1e-6, east - west)
        zoom = math.ceil(math.log2(360.0 * _CROP_TARGET[0] / (_TILE_SIZE * span)))
        return max(0, min(_MAX_TILE_ZOOM, zoom))

    def _tile_request(self, zoom: int, x: int, y: int) -> httpx.Request:
        return self.client.build_request("GET", _TILE_URL.format(z=zoom, x=x, y=y))

    def _tile_response(self, response: httpx.Response | None) -> bytes | None:
        return self.response_bytes(response)

    def _fetch_tile(self, zoom: int, x: int, y: int) -> bytes | None:
        return self.fetch(self._tile_request(zoom, x, y), self._tile_response)

    def _stitch_tiles(
        self, zoom: int, tx0: int, ty0: int, tx1: int, ty1: int
    ) -> Image.Image | None:
        stitched = Image.new(
            "RGBA", ((tx1 - tx0 + 1) * _TILE_SIZE, (ty1 - ty0 + 1) * _TILE_SIZE), (0, 0, 0, 0)
        )
        got = False
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                data = self._fetch_tile(zoom, tx, ty)
                if not data:
                    continue
                try:
                    tile = Image.open(io.BytesIO(data)).convert("RGBA")
                except Exception:  # noqa: BLE001 - skip unreadable tile
                    continue
                stitched.paste(tile, ((tx - tx0) * _TILE_SIZE, (ty - ty0) * _TILE_SIZE))
                got = True
        return stitched if got else None

    def _basemap_surface(self, lat: float, lon: float) -> pygame.Surface | None:
        """Reproject the Web-Mercator county tiles onto the HRRR crop grid."""
        west, south, east, north = self._crop_bbox(lat, lon)
        zoom = self._basemap_zoom(west, east)
        ix0, iy0 = math.floor(self._lon_to_px(west, zoom)), math.floor(self._lat_to_px(north, zoom))
        ix1, iy1 = math.ceil(self._lon_to_px(east, zoom)), math.ceil(self._lat_to_px(south, zoom))
        tx0, ty0 = ix0 // _TILE_SIZE, iy0 // _TILE_SIZE
        tx1, ty1 = (ix1 - 1) // _TILE_SIZE, (iy1 - 1) // _TILE_SIZE
        stitched = self._stitch_tiles(zoom, tx0, ty0, tx1, ty1)
        if stitched is None:
            return None

        crop = stitched.crop(
            (
                ix0 - tx0 * _TILE_SIZE,
                iy0 - ty0 * _TILE_SIZE,
                ix1 - tx0 * _TILE_SIZE,
                iy1 - ty0 * _TILE_SIZE,
            )
        )
        # Longitude maps linearly in Mercator, so scale horizontally; latitude
        # does not, so resample each output row from its Mercator position.
        horiz = crop.resize((_CROP_TARGET[0], crop.height), Image.NEAREST)
        lines = Image.new("RGBA", _CROP_TARGET, (0, 0, 0, 0))
        for oy in range(_CROP_TARGET[1]):
            row_lat = north - (oy + 0.5) / _CROP_TARGET[1] * (north - south)
            sy = int(round(self._lat_to_px(row_lat, zoom) - iy0))
            sy = max(0, min(horiz.height - 1, sy))
            lines.paste(horiz.crop((0, sy, _CROP_TARGET[0], sy + 1)), (0, oy))

        # The tiles are black line art: recolor to gray over the radar blue.
        alpha = lines.getchannel("A")
        gray = Image.new("L", lines.size, _BORDER_COLOR)
        border = Image.merge("RGBA", (gray, gray, gray, alpha))
        background = Image.new("RGBA", _CROP_TARGET, (*_BASEMAP_BG, 255))
        background.alpha_composite(border)
        return pygame.image.frombytes(background.convert("RGB").tobytes(), _CROP_TARGET, "RGB")

    @memoize(ttl=_BASEMAP_TTL)
    def basemap(self, lat: float, lon: float) -> pygame.Surface | None:
        """The county-border basemap for the regional crop, or ``None`` offline."""
        if not self.show_basemap:
            return None
        try:
            return self._basemap_surface(lat, lon)
        except Exception as exc:  # noqa: BLE001 - a bad basemap must not kill radar
            self._log.debug("basemap_failed", error=str(exc))
            return None

    # -- frames ---------------------------------------------------------------

    def _frame_request(self, url: str) -> httpx.Request:
        return self.client.build_request("GET", url)

    def _frame_response(self, response: httpx.Response | None) -> bytes | None:
        data = self.response_bytes(response)
        return data if data and len(data) > 1000 else None

    def _fetch_bytes(self, url: str) -> bytes | None:
        return self.fetch(self._frame_request(url), self._frame_response)

    @staticmethod
    def _build_frame(
        data: bytes, lat: float, lon: float, background: pygame.Surface | None = None
    ) -> pygame.Surface:
        """Crop/scale one reflectivity still and lay it over ``background``.

        The HRRR no-data color is exact black, so it is keyed out to let the
        basemap (or the screen) show through.
        """
        image = pygame.image.load(io.BytesIO(data))
        left, top, right, bottom = NoaaRadar.crop_box(lat, lon, image.get_size())
        crop = image.subsurface((left, top, right - left, bottom - top)).copy()
        scaled = pygame.transform.scale(crop, _CROP_TARGET)
        scaled.set_colorkey((0, 0, 0))
        if background is None:
            return scaled
        composited = background.copy()
        composited.blit(scaled, (0, 0))
        return composited

    @memoize()
    def _loop(self, lat: float, lon: float) -> list[RadarFrame]:
        """Return cropped forecast frames (oldest-first) with their valid times."""
        now = self._now()
        run = self._latest_run(now)
        if run is None:
            return []
        background = self.basemap(lat, lon)
        frames: list[RadarFrame] = []
        for lead in self._leads(now, run):
            url = self._run_url(run, lead)
            data = self._fetch_bytes(url)
            if not data:
                continue
            try:
                surface = self._build_frame(data, lat, lon, background)
            except Exception as exc:  # noqa: BLE001
                self._log.debug("radar_decode_failed", url=url, error=str(exc))
                continue
            frames.append(RadarFrame(time=run + timedelta(minutes=lead), surface=surface))
        return frames

    def frames(self, lat: float, lon: float) -> list[pygame.Surface]:
        """Return the future-radar frames, cropped to the regional view."""
        return [frame.surface for frame in self._loop(lat, lon)]

    def frame_times(self, lat: float, lon: float) -> list[datetime]:
        """Return the UTC valid time for each frame from :meth:`frames`."""
        return [frame.time for frame in self._loop(lat, lon)]

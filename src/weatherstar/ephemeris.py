"""Sun/moon calculator for display screens (thin wrapper over ``ephem``).

Pure functions of a date and coordinate so screens stay offline and tests
deterministic.  Times are expressed in the location's standard local clock
(derived from longitude), matching the US-centric displays this feeds.

- :func:`sun_clock_minutes`: sunrise/sunset as minutes since local midnight.
- :func:`next_moon_phases`: the next four primary moon phases from a date.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import ephem

#: Primary moon phase name -> the ephem ``next_*`` function that finds it.
_MOON_EVENTS = (
    ("NEW", ephem.next_new_moon),
    ("FIRST", ephem.next_first_quarter_moon),
    ("FULL", ephem.next_full_moon),
    ("LAST", ephem.next_last_quarter_moon),
)


def _local_offset(lon: float) -> int:
    """Location's standard-time offset from UTC in minutes (longitude-derived)."""
    return round(lon / 15.0) * 60


def _minutes_local(moment: ephem.Date, offset: int) -> int:
    """UTC ``moment`` as minutes since local midnight, wrapped to one day."""
    utc = moment.datetime()
    return (utc.hour * 60 + utc.minute + offset) % 1440


def sun_clock_minutes(day: date, lat: float, lon: float) -> tuple[int, int]:
    """Local sunrise/sunset minutes-since-midnight for ``day`` at (lat, lon)."""
    offset = _local_offset(lon)
    start = ephem.Date(datetime(day.year, day.month, day.day) - timedelta(minutes=offset))
    observer = ephem.Observer()
    observer.lat = str(lat)
    observer.lon = str(lon)
    sun = ephem.Sun()

    observer.date = start
    rise = _minutes_local(observer.next_rising(sun), offset)
    observer.date = start
    setting = _minutes_local(observer.next_setting(sun), offset)
    return rise, setting


def next_moon_phases(start: date) -> list[tuple[str, date]]:
    """The next four primary phases from ``start`` as ``(name, date)``.

    Names follow ws3kp's almanac ("NEW", "FIRST", "FULL", "LAST"), in
    chronological order.
    """
    events = [(name, finder(start)) for name, finder in _MOON_EVENTS]
    events.sort(key=lambda item: item[1])
    return [(name, moment.datetime().date()) for name, moment in events]

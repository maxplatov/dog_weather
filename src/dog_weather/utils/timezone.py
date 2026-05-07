from __future__ import annotations

import logging

from timezonefinder import TimezoneFinder

logger = logging.getLogger(__name__)

_finder = TimezoneFinder()


def get_timezone(lat: float, lon: float) -> str:
    """Return IANA timezone name for given coordinates.

    Falls back to "UTC" when no timezone can be determined.
    """
    try:
        tz = _finder.timezone_at(lat=lat, lng=lon)
        if tz:
            return tz
        logger.warning("timezonefinder returned None for (%s, %s), using UTC", lat, lon)
    except Exception as exc:
        logger.warning("timezonefinder error for (%s, %s): %s", lat, lon, exc)
    return "UTC"

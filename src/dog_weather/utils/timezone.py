from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_finder = None


def _get_finder():
    global _finder
    if _finder is None:
        from timezonefinder import TimezoneFinder
        _finder = TimezoneFinder()
    return _finder


def get_timezone(lat: float, lon: float) -> str:
    """Return IANA timezone name for given coordinates.

    Falls back to "UTC" when no timezone can be determined.
    """
    try:
        tf = _get_finder()
        tz = tf.timezone_at(lat=lat, lng=lon)
        if tz:
            return tz
        logger.warning("timezonefinder returned None for (%s, %s), using UTC", lat, lon)
    except Exception as exc:
        logger.warning("timezonefinder error for (%s, %s): %s", lat, lon, exc)
    return "UTC"

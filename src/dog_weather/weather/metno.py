from __future__ import annotations

import logging
from datetime import date, datetime, timezone as dt_timezone

import pytz

from .base import HourlyWeather, WeatherProvider

logger = logging.getLogger(__name__)

_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
# MET Norway ToS requires a descriptive User-Agent
_USER_AGENT = "dog_weather_bot/1.0 github.com/maxplatov/dog_weather"


class MetNoProvider(WeatherProvider):
    """MET Norway (yr.no) — free, no API key, AROME/MEPS Nordic models."""

    name = "MET Norway"

    async def get_hourly(
        self,
        lat: float,
        lon: float,
        hours: list[int],
        target_date: date,
        timezone: str,
    ) -> list[HourlyWeather]:
        params = {"lat": round(lat, 4), "lon": round(lon, 4)}
        headers = {"User-Agent": _USER_AGENT}

        data = await self._fetch(_URL, params=params, headers=headers)
        if not data:
            return []

        try:
            tz = pytz.timezone(timezone)
            results: list[HourlyWeather] = []
            seen: set[int] = set()

            for entry in data["properties"]["timeseries"]:
                # MET Norway times are UTC ISO 8601
                dt_utc = datetime.fromisoformat(
                    entry["time"].replace("Z", "+00:00")
                )
                dt_local = dt_utc.astimezone(tz)

                if dt_local.date() != target_date:
                    continue

                local_hour = dt_local.hour
                if local_hour not in hours or local_hour in seen:
                    continue

                instant = entry["data"]["instant"]["details"]
                next1h = entry["data"].get("next_1_hours", {}).get("details", {})

                # wind_speed from MET Norway is m/s → km/h
                wind_ms = instant.get("wind_speed")
                wind_kmh = wind_ms * 3.6 if wind_ms is not None else None

                # MET Norway compact does not provide feels_like or precip probability;
                # precipitation_amount is available but not a probability — skip it.
                results.append(
                    HourlyWeather(
                        hour=local_hour,
                        temperature=instant.get("air_temperature"),
                        feels_like=None,
                        precipitation_probability=None,
                        wind_speed=wind_kmh,
                    )
                )
                seen.add(local_hour)

            return results

        except Exception as exc:
            logger.warning("[%s] parse error: %s", self.name, exc)
            return []

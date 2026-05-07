from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from .base import HourlyWeather, WeatherProvider

logger = logging.getLogger(__name__)

_URL = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoProvider(WeatherProvider):
    """Open-Meteo — free, no API key, uses ECMWF/GFS ensemble models."""

    name = "Open-Meteo"

    async def get_hourly(
        self,
        lat: float,
        lon: float,
        hours: list[int],
        target_date: date,
        timezone: str,
    ) -> list[HourlyWeather]:
        date_str = target_date.isoformat()
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,apparent_temperature,precipitation_probability,windspeed_10m",
            "wind_speed_unit": "kmh",
            "timezone": timezone,
            "start_date": date_str,
            "end_date": date_str,
        }

        data = await self._fetch(_URL, params=params)
        if not data:
            return []

        try:
            hourly = data["hourly"]
            times: list[str] = hourly["time"]          # "YYYY-MM-DDTHH:00"
            temps: list[float] = hourly["temperature_2m"]
            feels: list[float] = hourly["apparent_temperature"]
            precip: list[float] = hourly["precipitation_probability"]
            wind: list[float] = hourly["windspeed_10m"]

            results: list[HourlyWeather] = []
            for i, t in enumerate(times):
                h = int(t[11:13])  # extract hour from "YYYY-MM-DDTHH:00"
                if h in hours:
                    results.append(
                        HourlyWeather(
                            hour=h,
                            temperature=temps[i],
                            feels_like=feels[i],
                            precipitation_probability=precip[i],
                            wind_speed=wind[i],
                        )
                    )
            return results
        except Exception as exc:
            logger.warning("[%s] parse error: %s", self.name, exc)
            return []

    async def get_sunset(
        self,
        lat: float,
        lon: float,
        target_date: date,
        timezone: str,
    ) -> Optional[str]:
        date_str = target_date.isoformat()
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "sunset",
            "timezone": timezone,
            "start_date": date_str,
            "end_date": date_str,
        }
        data = await self._fetch(_URL, params=params)
        if not data:
            return None
        try:
            sunset_iso = data["daily"]["sunset"][0]  # "YYYY-MM-DDTHH:MM"
            return sunset_iso[11:16]
        except Exception as exc:
            logger.warning("[%s] sunset parse error: %s", self.name, exc)
            return None

from __future__ import annotations

import logging
from datetime import date, datetime, timezone as dt_timezone

import pytz

from dog_weather.config import WeatherConfig

from .base import HourlyWeather, WeatherProvider

logger = logging.getLogger(__name__)

_URL = "https://api.openweathermap.org/data/2.5/forecast"


class OpenWeatherProvider(WeatherProvider):
    """OpenWeatherMap 5-day/3h forecast — free tier, proprietary NWP models."""

    name = "OpenWeatherMap"

    def __init__(self, config: WeatherConfig) -> None:
        super().__init__(config)
        self._api_key = config.providers.openweathermap.api_key

    async def get_hourly(
        self,
        lat: float,
        lon: float,
        hours: list[int],
        target_date: date,
        timezone: str,
    ) -> list[HourlyWeather]:
        if not self._api_key:
            return []

        params = {
            "lat": lat,
            "lon": lon,
            "appid": self._api_key,
            "units": "metric",
            "cnt": 40,  # max slots (5 days × 8 per day)
        }

        data = await self._fetch(_URL, params=params)
        if not data:
            return []

        try:
            tz = pytz.timezone(timezone)
            results: list[HourlyWeather] = []

            for item in data.get("list", []):
                # Convert UTC unix timestamp to local time
                dt_utc = datetime.fromtimestamp(item["dt"], tz=dt_timezone.utc)
                dt_local = dt_utc.astimezone(tz)

                if dt_local.date() != target_date:
                    continue

                local_hour = dt_local.hour
                # OWM gives 3-hour slots; match the slot whose hour is closest
                for h in hours:
                    if abs(local_hour - h) <= 1:  # within 1 hour
                        main = item.get("main", {})
                        wind = item.get("wind", {})
                        # pop = probability of precipitation (0..1)
                        pop = item.get("pop", 0.0) * 100

                        results.append(
                            HourlyWeather(
                                hour=h,
                                temperature=main.get("temp"),
                                feels_like=main.get("feels_like"),
                                precipitation_probability=pop,
                                # OWM wind is m/s → km/h
                                wind_speed=(wind.get("speed", 0) * 3.6)
                                if wind.get("speed") is not None
                                else None,
                            )
                        )

            # Deduplicate: keep first match per hour
            seen: set[int] = set()
            deduped: list[HourlyWeather] = []
            for hw in results:
                if hw.hour not in seen:
                    seen.add(hw.hour)
                    deduped.append(hw)
            return deduped

        except Exception as exc:
            logger.warning("[%s] parse error: %s", self.name, exc)
            return []

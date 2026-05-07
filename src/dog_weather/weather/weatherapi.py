from __future__ import annotations

import logging
from datetime import date

from dog_weather.config import WeatherConfig

from .base import HourlyWeather, WeatherProvider

logger = logging.getLogger(__name__)

_URL = "https://api.weatherapi.com/v1/forecast.json"


class WeatherAPIProvider(WeatherProvider):
    """WeatherAPI.com — free tier, proprietary models, hourly resolution."""

    name = "WeatherAPI"

    def __init__(self, config: WeatherConfig) -> None:
        super().__init__(config)
        self._api_key = config.providers.weatherapi.api_key

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
            "key": self._api_key,
            "q": f"{lat},{lon}",
            "days": 2,
            "aqi": "no",
            "alerts": "no",
        }

        data = await self._fetch(_URL, params=params)
        if not data:
            return []

        try:
            results: list[HourlyWeather] = []
            date_str = target_date.isoformat()

            for day in data.get("forecast", {}).get("forecastday", []):
                if day.get("date") != date_str:
                    continue
                for slot in day.get("hour", []):
                    # "time" format: "2024-01-15 07:00"
                    slot_hour = int(slot["time"][11:13])
                    if slot_hour not in hours:
                        continue
                    results.append(
                        HourlyWeather(
                            hour=slot_hour,
                            temperature=slot.get("temp_c"),
                            feels_like=slot.get("feelslike_c"),
                            precipitation_probability=slot.get("chance_of_rain"),
                            wind_speed=slot.get("wind_kph"),
                        )
                    )
            return results

        except Exception as exc:
            logger.warning("[%s] parse error: %s", self.name, exc)
            return []

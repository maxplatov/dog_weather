from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

import httpx
from pydantic import BaseModel

from dog_weather.config import WeatherConfig

logger = logging.getLogger(__name__)


class HourlyWeather(BaseModel):
    """Weather snapshot for a single hour."""

    hour: int  # 0-23 in the user's local timezone
    temperature: Optional[float] = None          # °C
    feels_like: Optional[float] = None           # °C
    precipitation_probability: Optional[float] = None  # 0-100 %
    wind_speed: Optional[float] = None           # km/h


class WeatherProvider(ABC):
    """Abstract base for weather data providers."""

    name: str = "unknown"

    def __init__(self, config: WeatherConfig) -> None:
        self._timeout = config.request_timeout
        self._retry_count = config.retry_count

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_hourly(
        self,
        lat: float,
        lon: float,
        hours: list[int],
        target_date: date,
        timezone: str,
    ) -> list[HourlyWeather]:
        """Return HourlyWeather objects for the requested hours.

        Implementations must never raise — return an empty list on failure.
        """

    # ------------------------------------------------------------------
    # Protected helpers
    # ------------------------------------------------------------------

    async def _fetch(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> dict | list | None:
        """GET *url* with automatic retry and structured error handling."""
        last_exc: Exception | None = None
        for attempt in range(self._retry_count + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(url, params=params, headers=headers)
                    resp.raise_for_status()
                    return resp.json()
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "[%s] timeout on attempt %d/%d: %s",
                    self.name, attempt + 1, self._retry_count + 1, exc,
                )
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                logger.warning(
                    "[%s] HTTP %s for %s",
                    self.name, exc.response.status_code, url,
                )
                # Don't retry 4xx errors
                if exc.response.status_code < 500:
                    break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "[%s] request error on attempt %d/%d: %s",
                    self.name, attempt + 1, self._retry_count + 1, exc,
                )

            if attempt < self._retry_count:
                await asyncio.sleep(2 ** attempt)

        logger.error("[%s] all retries exhausted: %s", self.name, last_exc)
        return None

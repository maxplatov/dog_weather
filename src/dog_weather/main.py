from __future__ import annotations

import logging
import sys

from dog_weather.bot import create_application
from dog_weather.config import load_config
from dog_weather.database import Database
from dog_weather.weather.metno import MetNoProvider
from dog_weather.weather.openmeteo import OpenMeteoProvider
from dog_weather.weather.openweather import OpenWeatherProvider
from dog_weather.weather.weatherapi import WeatherAPIProvider

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
# Silence noisy loggers, keep httpx at DEBUG to see request bodies
for _noisy in ("apscheduler", "telegram", "httpcore", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def main() -> None:
    config = load_config()

    if not config.bot.token:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Exiting.")
        sys.exit(1)

    db = Database(config.database.path)

    # Build provider list — providers without credentials are skipped gracefully
    providers = [OpenMeteoProvider(config.weather)]

    if config.weather.providers.openweathermap.api_key:
        providers.append(OpenWeatherProvider(config.weather))
        logger.info("OpenWeatherMap provider enabled")
    else:
        logger.info("OpenWeatherMap provider disabled (no OWM_API_KEY)")

    if config.weather.providers.weatherapi.api_key:
        providers.append(WeatherAPIProvider(config.weather))
        logger.info("WeatherAPI provider enabled")
    else:
        logger.info("WeatherAPI provider disabled (no WEATHERAPI_KEY)")

    # MET Norway is always enabled (no key required)
    providers.append(MetNoProvider(config.weather))

    logger.info(
        "Starting dog_weather bot with %d provider(s): %s",
        len(providers),
        ", ".join(p.name for p in providers),
    )

    app = create_application(config, db, providers)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

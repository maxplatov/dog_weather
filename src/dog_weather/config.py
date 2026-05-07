from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel


class OpenWeatherMapConfig(BaseModel):
    api_key: str = ""


class WeatherAPIConfig(BaseModel):
    api_key: str = ""


class WeatherProvidersConfig(BaseModel):
    openweathermap: OpenWeatherMapConfig = OpenWeatherMapConfig()
    weatherapi: WeatherAPIConfig = WeatherAPIConfig()


class WeatherConfig(BaseModel):
    providers: WeatherProvidersConfig = WeatherProvidersConfig()
    request_timeout: int = 10
    retry_count: int = 2


class DatabaseConfig(BaseModel):
    path: str = "/data/dog_weather.db"


class BotConfig(BaseModel):
    token: str


class AppConfig(BaseModel):
    bot: BotConfig
    weather: WeatherConfig = WeatherConfig()
    database: DatabaseConfig = DatabaseConfig()


def load_config(config_path: str = "config.yaml") -> AppConfig:
    data: dict = {}
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}

    # Environment variables override YAML values
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        data.setdefault("bot", {})["token"] = token

    owm_key = os.environ.get("OWM_API_KEY", "")
    if owm_key:
        (
            data.setdefault("weather", {})
            .setdefault("providers", {})
            .setdefault("openweathermap", {})
        )["api_key"] = owm_key

    wapi_key = os.environ.get("WEATHERAPI_KEY", "")
    if wapi_key:
        (
            data.setdefault("weather", {})
            .setdefault("providers", {})
            .setdefault("weatherapi", {})
        )["api_key"] = wapi_key

    db_path = os.environ.get("DATABASE_PATH", "")
    if db_path:
        data.setdefault("database", {})["path"] = db_path

    return AppConfig(**data)

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot
from telegram.error import TelegramError

from dog_weather.database import Database, UserData
from dog_weather.weather.base import WeatherProvider
from dog_weather.weather.consensus import average_sunset, build_consensus_message

logger = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone="UTC")


def schedule_user_job(
    scheduler: AsyncIOScheduler,
    user: UserData,
    bot: Bot,
    db: Database,
    providers: list[WeatherProvider],
) -> None:
    """Register (or replace) a daily forecast job for *user*."""
    job_id = f"weather_{user.telegram_id}"

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if not user.is_fully_configured():
        return

    try:
        tz = pytz.timezone(user.timezone)
    except Exception:
        logger.warning("Unknown timezone %r for user %s", user.timezone, user.telegram_id)
        tz = pytz.UTC

    scheduler.add_job(
        _send_forecast,
        trigger=CronTrigger(
            hour=user.notify_hour,
            minute=user.notify_minute or 0,
            timezone=tz,
        ),
        id=job_id,
        kwargs={
            "telegram_id": user.telegram_id,
            "bot": bot,
            "db": db,
            "providers": providers,
        },
        replace_existing=True,
        misfire_grace_time=300,  # tolerate up to 5 min delay
    )
    logger.info(
        "Scheduled forecast for user %s at %02d:%02d %s",
        user.telegram_id,
        user.notify_hour,
        user.notify_minute or 0,
        user.timezone,
    )


def remove_user_job(scheduler: AsyncIOScheduler, telegram_id: int) -> None:
    job_id = f"weather_{telegram_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


async def trigger_now(
    telegram_id: int,
    bot: Bot,
    db: Database,
    providers: list[WeatherProvider],
) -> None:
    """Manually trigger forecast delivery (used by /forecast command)."""
    await _send_forecast(telegram_id, bot, db, providers)


# ---------------------------------------------------------------------------
# Internal job function
# ---------------------------------------------------------------------------

async def _send_forecast(
    telegram_id: int,
    bot: Bot,
    db: Database,
    providers: list[WeatherProvider],
) -> None:
    try:
        user = await db.get_user(telegram_id)
        if not user or not user.is_fully_configured():
            logger.warning("User %s not fully configured, skipping forecast", telegram_id)
            return

        tz = pytz.timezone(user.timezone)
        now = datetime.now(tz)
        # If all requested intervals have already passed target_date, show tomorrow's forecast
        target_date = (
            now.date() + timedelta(days=1)
            if all(h < now.hour for h in user.intervals)
            else now.date()
        )

        # Fetch hourly forecasts and sunset times from all providers concurrently
        hourly_tasks = [
            p.get_hourly(user.latitude, user.longitude, user.intervals, target_date, user.timezone)
            for p in providers
        ]
        sunset_tasks = [
            p.get_sunset(user.latitude, user.longitude, target_date, user.timezone)
            for p in providers
        ]
        raw_hourly, raw_sunsets = await asyncio.gather(
            asyncio.gather(*hourly_tasks, return_exceptions=True),
            asyncio.gather(*sunset_tasks, return_exceptions=True),
        )

        provider_results: dict[str, list] = {}
        failed_providers: list[str] = []
        for provider, result in zip(providers, raw_hourly):
            if isinstance(result, Exception):
                logger.warning("[%s] raised exception: %s", provider.name, result)
                failed_providers.append(provider.name)
            elif result:
                provider_results[provider.name] = result
            else:
                failed_providers.append(provider.name)

        if not provider_results:
            await _safe_send(bot, telegram_id, "⚠️ Все провайдеры погоды недоступны, попробую позже.")
            return

        sunsets = [r for r in raw_sunsets if isinstance(r, str)]
        sunset = average_sunset(sunsets)

        message = build_consensus_message(user.intervals, provider_results, target_date, failed_providers, sunset=sunset)
        await _safe_send(bot, telegram_id, message, parse_mode="HTML")

    except Exception as exc:
        logger.error("Unhandled error in forecast job for %s: %s", telegram_id, exc, exc_info=True)


async def _safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> None:
    """Send a message, swallowing Telegram errors so the job never crashes."""
    try:
        await bot.send_message(chat_id, text, **kwargs)
    except TelegramError as exc:
        logger.warning("TelegramError sending to %s: %s", chat_id, exc)
    except Exception as exc:
        logger.error("Unexpected error sending to %s: %s", chat_id, exc)

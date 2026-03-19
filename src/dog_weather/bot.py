from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from dog_weather.config import AppConfig
from dog_weather.database import Database
from dog_weather.scheduler import (
    create_scheduler,
    remove_user_job,
    schedule_user_job,
    trigger_now,
)
from dog_weather.utils.timezone import get_timezone
from dog_weather.weather.base import WeatherProvider

logger = logging.getLogger(__name__)

# Conversation states
AWAITING_LOCATION, AWAITING_TIME, AWAITING_INTERVALS = range(3)

# Keys stored in context.user_data during onboarding
_FLOW = "flow"          # 'start' | 'location' | 'time' | 'intervals'
_LAT = "lat"
_LON = "lon"
_TZ = "tz"
_HOUR = "hour"
_MINUTE = "minute"


# ---------------------------------------------------------------------------
# Helper: parse "HH:MM"
# ---------------------------------------------------------------------------

def _parse_time(text: str) -> Optional[tuple[int, int]]:
    text = text.strip()
    if ":" not in text:
        return None
    parts = text.split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except ValueError:
        pass
    return None


# ---------------------------------------------------------------------------
# Helper: parse interval / hour input
# ---------------------------------------------------------------------------

def _parse_hours(text: str) -> Optional[list[int]]:
    """Return sorted list of start-hours from user input.

    Supported formats:
      "6-9"   → [6, 7, 8, 9]  (inclusive range)
      "6,7,8" → [6, 7, 8]
      "7"     → [7]
    """
    text = text.strip()
    hours: list[int] = []

    if "-" in text and "," not in text:
        parts = text.split("-")
        if len(parts) == 2:
            try:
                start, end = int(parts[0].strip()), int(parts[1].strip())
                if 0 <= start <= 23 and 0 <= end <= 23 and start <= end:
                    hours = list(range(start, end + 1))
            except ValueError:
                pass
    elif "," in text:
        try:
            hours = [int(h.strip()) for h in text.split(",")]
            if not all(0 <= h <= 23 for h in hours):
                hours = []
        except ValueError:
            hours = []
    else:
        try:
            h = int(text)
            if 0 <= h <= 23:
                hours = [h]
        except ValueError:
            pass

    return sorted(set(hours)) if hours else None


def _format_intervals(hours: list[int]) -> str:
    return ", ".join(f"{h:02d}:00–{(h+1)%24:02d}:00" for h in hours)


def _format_settings(user) -> str:
    if not user:
        return "Настройки не найдены. Используйте /start для начала."
    lines = ["⚙️ <b>Ваши настройки</b>\n"]
    if user.latitude is not None:
        lines.append(f"📍 Координаты: {user.latitude:.4f}°, {user.longitude:.4f}°")
        lines.append(f"🌍 Часовой пояс: {user.timezone}")
    if user.notify_hour is not None:
        lines.append(f"⏰ Уведомление: {user.notify_hour:02d}:{user.notify_minute or 0:02d}")
    if user.intervals:
        lines.append(f"📊 Интервалы: {_format_intervals(user.intervals)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generic error guard decorator
# ---------------------------------------------------------------------------

def _safe_handler(fn):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await fn(update, context)
        except TelegramError as exc:
            logger.warning("TelegramError in %s: %s", fn.__name__, exc)
        except Exception as exc:
            logger.error("Unhandled error in %s: %s", fn.__name__, exc, exc_info=True)
            try:
                await update.effective_message.reply_text(
                    "⚠️ Что-то пошло не так. Попробуйте ещё раз или используйте /start."
                )
            except Exception:
                pass
    return wrapper


# ---------------------------------------------------------------------------
# Entry point handlers
# ---------------------------------------------------------------------------

@_safe_handler
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[_FLOW] = "start"
    kb = [[KeyboardButton("📍 Поделиться местоположением", request_location=True)]]
    await update.message.reply_text(
        "👋 Привет! Я буду присылать тебе ежедневный прогноз погоды.\n\n"
        "Для начала поделись своим <b>местоположением</b>:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
    )
    return AWAITING_LOCATION


@_safe_handler
async def cmd_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[_FLOW] = "location"
    kb = [[KeyboardButton("📍 Поделиться местоположением", request_location=True)]]
    await update.message.reply_text(
        "Отправь своё местоположение:",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
    )
    return AWAITING_LOCATION


@_safe_handler
async def cmd_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Database = context.bot_data["db"]
    user = await db.get_user(update.effective_user.id)
    if not user or user.latitude is None:
        await update.message.reply_text(
            "❌ Сначала укажи местоположение с помощью /location."
        )
        return ConversationHandler.END
    context.user_data[_FLOW] = "time"
    await update.message.reply_text(
        "В какое время присылать прогноз?\nВведи время в формате <b>ЧЧ:ММ</b> (например: <code>07:00</code>):",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return AWAITING_TIME


@_safe_handler
async def cmd_intervals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Database = context.bot_data["db"]
    user = await db.get_user(update.effective_user.id)
    if not user or user.notify_hour is None:
        await update.message.reply_text(
            "❌ Сначала задай время уведомления с помощью /time."
        )
        return ConversationHandler.END
    context.user_data[_FLOW] = "intervals"
    await update.message.reply_text(
        "За какие часы показывать погоду?\n\n"
        "Введи диапазон часов, например:\n"
        "• <code>6-9</code> — часы 6, 7, 8, 9 (каждый по часу)\n"
        "• <code>6,8,10</code> — конкретные часы\n"
        "• <code>7</code> — один час\n\n"
        "Каждый час будет показан как интервал, например 07:00–08:00.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return AWAITING_INTERVALS


@_safe_handler
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Операция отменена.", reply_markup=_main_menu()
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# State handlers
# ---------------------------------------------------------------------------

@_safe_handler
async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    if loc is None:
        await update.message.reply_text(
            "Пожалуйста, используй кнопку для отправки местоположения.",
        )
        return AWAITING_LOCATION

    lat, lon = loc.latitude, loc.longitude
    tz = get_timezone(lat, lon)

    db: Database = context.bot_data["db"]
    tg_user = update.effective_user

    await db.update_identity(tg_user.id, tg_user.username, tg_user.first_name)
    await db.update_location(tg_user.id, lat, lon, tz)

    await update.message.reply_text(
        f"✅ Местоположение сохранено.\n🌍 Часовой пояс: <b>{tz}</b>",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )

    flow = context.user_data.get(_FLOW, "start")

    # If only updating location and user is already configured → reschedule & done
    if flow == "location":
        user = await db.get_user(tg_user.id)
        if user and user.is_fully_configured():
            _reschedule(context, user)
            await update.message.reply_text("🔄 Расписание обновлено.", reply_markup=_main_menu())
            return ConversationHandler.END

    # Continue onboarding: ask for notification time
    await update.message.reply_text(
        "В какое время присылать прогноз?\nВведи время в формате <b>ЧЧ:ММ</b> (например: <code>07:00</code>):",
        parse_mode="HTML",
    )
    return AWAITING_TIME


@_safe_handler
async def handle_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = _parse_time(update.message.text or "")
    if parsed is None:
        await update.message.reply_text(
            "❌ Неверный формат. Введи время как <b>ЧЧ:ММ</b>, например <code>07:30</code>.",
            parse_mode="HTML",
        )
        return AWAITING_TIME

    hour, minute = parsed
    tg_user = update.effective_user
    db: Database = context.bot_data["db"]

    await db.update_notify_time(tg_user.id, hour, minute)
    context.user_data[_HOUR] = hour
    context.user_data[_MINUTE] = minute

    await update.message.reply_text(
        f"✅ Время уведомления: <b>{hour:02d}:{minute:02d}</b>",
        parse_mode="HTML",
    )

    flow = context.user_data.get(_FLOW, "start")

    # If only updating time and user already has intervals → reschedule & done
    if flow == "time":
        user = await db.get_user(tg_user.id)
        if user and user.is_fully_configured():
            _reschedule(context, user)
            await update.message.reply_text("🔄 Расписание обновлено.", reply_markup=_main_menu())
            return ConversationHandler.END

    # Ask for intervals
    await update.message.reply_text(
        "За какие часы показывать погоду?\n\n"
        "Введи диапазон, например:\n"
        "• <code>6-9</code> — часы 6, 7, 8, 9\n"
        "• <code>6,8,10</code> — конкретные часы\n"
        "• <code>7</code> — один час",
        parse_mode="HTML",
    )
    return AWAITING_INTERVALS


@_safe_handler
async def handle_intervals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hours = _parse_hours(update.message.text or "")
    if hours is None:
        await update.message.reply_text(
            "❌ Не понял формат. Попробуй: <code>6-9</code> или <code>6,7,8</code>.",
            parse_mode="HTML",
        )
        return AWAITING_INTERVALS

    tg_user = update.effective_user
    db: Database = context.bot_data["db"]

    await db.update_intervals(tg_user.id, hours)
    user = await db.get_user(tg_user.id)

    _reschedule(context, user)

    await update.message.reply_text(
        f"✅ Интервалы: <b>{_format_intervals(hours)}</b>\n\n"
        + _format_settings(user)
        + "\n\n🎉 Всё готово! Прогноз будет приходить по расписанию.",
        parse_mode="HTML",
        reply_markup=_main_menu(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Standalone commands (outside conversation)
# ---------------------------------------------------------------------------

@_safe_handler
async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Database = context.bot_data["db"]
    user = await db.get_user(update.effective_user.id)
    kb = _main_menu()
    logger.info("CMD_SETTINGS: sending reply_markup=%s", kb.to_dict())
    msg = await update.message.reply_text(_format_settings(user), parse_mode="HTML", reply_markup=kb)
    logger.info("CMD_SETTINGS: message sent, id=%s", msg.message_id)
    return ConversationHandler.END


@_safe_handler
async def cmd_forecast_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("CMD_FORECAST_NOW: called by user %s", update.effective_user.id)
    db: Database = context.bot_data["db"]
    providers: list[WeatherProvider] = context.bot_data["providers"]
    user = await db.get_user(update.effective_user.id)
    logger.info("CMD_FORECAST_NOW: user=%s configured=%s", user, user.is_fully_configured() if user else False)

    if not user or not user.is_fully_configured():
        await update.message.reply_text("❌ Сначала настрой бота с помощью /start.")
        return

    kb = _main_menu()
    logger.info("CMD_FORECAST_NOW: keyboard=%s", kb.to_dict())
    msg = await update.message.reply_text("⏳ Запрашиваю погоду...", reply_markup=kb)
    logger.info("CMD_FORECAST_NOW: sent message_id=%s", msg.message_id)

    await trigger_now(update.effective_user.id, context.bot, db, providers)
    logger.info("CMD_FORECAST_NOW: done")


@_safe_handler
async def cmd_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Database = context.bot_data["db"]
    providers: list[WeatherProvider] = context.bot_data["providers"]
    user = await db.get_user(update.effective_user.id)

    if not user or not user.is_fully_configured():
        await update.message.reply_text(
            "❌ Сначала настрой бота с помощью /start."
        )
        return

    await update.message.reply_text("⏳ Запрашиваю погоду...", reply_markup=_main_menu())
    await trigger_now(
        update.effective_user.id,
        context.bot,
        db,
        providers,
    )


@_safe_handler
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>Команды бота</b>\n\n"
        "/start — первоначальная настройка\n"
        "/location — обновить местоположение\n"
        "/time — изменить время уведомления\n"
        "/intervals — изменить часовые интервалы\n"
        "/forecast — получить прогноз прямо сейчас\n"
        "/settings — показать текущие настройки\n"
        "/cancel — отменить текущую операцию\n"
        "/help — эта справка",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _main_menu() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton("🌤 Прогноз"), KeyboardButton("⚙️ Настройки")],
        [KeyboardButton("🕐 Время"), KeyboardButton("📊 Интервалы"), KeyboardButton("📍 Локация")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)


# ---------------------------------------------------------------------------
# Helper: reschedule via bot_data
# ---------------------------------------------------------------------------

def _reschedule(context: ContextTypes.DEFAULT_TYPE, user) -> None:
    if not user or not user.is_fully_configured():
        return
    scheduler = context.bot_data.get("scheduler")
    db: Database = context.bot_data["db"]
    providers: list[WeatherProvider] = context.bot_data["providers"]
    if scheduler:
        schedule_user_job(scheduler, user, context.bot, db, providers)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_application(
    config: AppConfig,
    db: Database,
    providers: list[WeatherProvider],
) -> Application:
    async def post_init(app: Application) -> None:
        await db.init()

        await app.bot.set_my_commands([
            ("forecast",  "Прогноз сейчас"),
            ("settings",  "Мои настройки"),
            ("time",      "Изменить время уведомлений"),
            ("intervals", "Изменить интервалы"),
            ("location",  "Изменить локацию"),
        ])

        scheduler = create_scheduler()
        app.bot_data["scheduler"] = scheduler
        app.bot_data["db"] = db
        app.bot_data["config"] = config
        app.bot_data["providers"] = providers

        # Re-schedule existing users on startup
        users = await db.get_all_users()
        for user in users:
            if user.is_fully_configured():
                schedule_user_job(scheduler, user, app.bot, db, providers)

        scheduler.start()
        logger.info("Scheduler started with %d user job(s)", len(users))

    async def post_shutdown(app: Application) -> None:
        scheduler: AsyncIOScheduler | None = app.bot_data.get("scheduler")
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)

    app = (
        Application.builder()
        .token(config.bot.token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Conversation handler covers onboarding + re-configuration commands
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CommandHandler("location", cmd_location),
            CommandHandler("time", cmd_time),
            CommandHandler("intervals", cmd_intervals),
            CommandHandler("settings", cmd_settings),
            CommandHandler("forecast", cmd_forecast),
            MessageHandler(filters.Regex(r"^📍 Локация$"), cmd_location),
            MessageHandler(filters.Regex(r"^🕐 Время$"), cmd_time),
            MessageHandler(filters.Regex(r"^📊 Интервалы$"), cmd_intervals),
            MessageHandler(filters.Regex(r"^⚙️ Настройки$"), cmd_settings),
            MessageHandler(filters.Regex(r"^🌤 Прогноз$"), cmd_forecast),
        ],
        states={
            AWAITING_LOCATION: [
                MessageHandler(filters.LOCATION, handle_location),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & ~filters.Regex(r"^(🌤 Прогноз|⚙️ Настройки|🕐 Время|📊 Интервалы|📍 Локация)$"),
                    lambda u, c: u.message.reply_text(
                        "Используй кнопку ниже для отправки местоположения."
                    ),
                ),
            ],
            AWAITING_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(r"^(🌤 Прогноз|⚙️ Настройки|🕐 Время|📊 Интервалы|📍 Локация)$"), handle_time),
            ],
            AWAITING_INTERVALS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(r"^(🌤 Прогноз|⚙️ Настройки|🕐 Время|📊 Интервалы|📍 Локация)$"), handle_intervals),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("settings", cmd_settings),
            CommandHandler("forecast", cmd_forecast),
            MessageHandler(filters.Regex(r"^⚙️ Настройки$"), cmd_settings),
            MessageHandler(filters.Regex(r"^🌤 Прогноз$"), cmd_forecast),
        ],
        allow_reentry=True,
        per_user=True,
        per_chat=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("forecast", cmd_forecast))
    app.add_handler(CommandHandler("forecast_now", cmd_forecast_now), group=1)
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.Regex(r"^🌤 Прогноз$"), cmd_forecast))
    app.add_handler(MessageHandler(filters.Regex(r"^⚙️ Настройки$"), cmd_settings))

    return app

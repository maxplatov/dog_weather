from __future__ import annotations

from datetime import date
from typing import Optional

from .base import HourlyWeather

_MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def _mean(values: list[float]) -> Optional[float]:
    non_none = [v for v in values if v is not None]
    return sum(non_none) / len(non_none) if non_none else None


def build_consensus_message(
    hours: list[int],
    provider_results: dict[str, list[HourlyWeather]],
    target_date: date,
    failed_providers: list[str] | None = None,
) -> str:
    """Aggregate provider results and format a Russian-language forecast message."""
    date_str = f"{target_date.day} {_MONTHS_RU[target_date.month]} {target_date.year}"
    lines: list[str] = [f"📅 <b>Прогноз погоды на {date_str}</b>\n"]

    for hour in sorted(set(hours)):
        temps, feels, precips, winds = [], [], [], []

        for hourly_list in provider_results.values():
            for hw in hourly_list:
                if hw.hour == hour:
                    if hw.temperature is not None:
                        temps.append(hw.temperature)
                    if hw.feels_like is not None:
                        feels.append(hw.feels_like)
                    if hw.precipitation_probability is not None:
                        precips.append(hw.precipitation_probability)
                    if hw.wind_speed is not None:
                        winds.append(hw.wind_speed)
                    break

        if not temps:
            continue  # no data for this hour

        avg_temp = _mean(temps)
        avg_feels = _mean(feels)
        avg_precip = _mean(precips)
        avg_wind = _mean(winds)

        end_hour = (hour + 1) % 24
        lines.append(f"🕐 <b>{hour:02d}:00–{end_hour:02d}:00</b>")

        feels_str = f" (ощущается как {avg_feels:+.0f}°C)" if avg_feels is not None else ""
        lines.append(f"🌡 Температура: {avg_temp:+.0f}°C{feels_str}")

        if avg_precip is not None:
            icon = "🌧" if avg_precip >= 30 else "☁️" if avg_precip >= 10 else "☀️"
            lines.append(f"{icon} Вероятность осадков: {avg_precip:.0f}%")

        if avg_wind is not None:
            lines.append(f"💨 Ветер: {avg_wind:.0f} км/ч")

        lines.append("")

    if not any("🌡" in l for l in lines):
        return "⚠️ Не удалось получить данные о погоде ни от одного из провайдеров."

    parts = [", ".join(provider_results.keys())]
    if failed_providers:
        parts.append(f"⚠️ недоступны: {', '.join(failed_providers)}")
    lines.append(f"📊 <i>Источники: {' | '.join(parts)}</i>")
    return "\n".join(lines)

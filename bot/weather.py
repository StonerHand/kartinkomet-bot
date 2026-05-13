from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

import aiohttp

MALA_TOKMACHKA_LATITUDE = 47.53563
MALA_TOKMACHKA_LONGITUDE = 35.89293
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_CACHE_TTL = timedelta(minutes=10)
HTTP_TIMEOUT_SECONDS = 6

WEATHER_CODES = {
    0: "ясно",
    1: "почти ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь и туман",
    51: "лёгкая морось",
    53: "морось",
    55: "сильная морось",
    56: "ледяная морось",
    57: "сильная ледяная морось",
    61: "небольшой дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "ледяной дождь",
    67: "сильный ледяной дождь",
    71: "небольшой снег",
    73: "снег",
    75: "сильный снег",
    77: "снежная крупа",
    80: "небольшой ливень",
    81: "ливень",
    82: "сильный ливень",
    85: "небольшой снегопад",
    86: "сильный снегопад",
    95: "гроза",
    96: "гроза с градом",
    99: "сильная гроза с градом",
}
WEATHER_EMOJIS = {
    0: "☀️",
    1: "🌤",
    2: "⛅️",
    3: "☁️",
    45: "🌫",
    48: "🌫",
    51: "🌦",
    53: "🌦",
    55: "🌧",
    56: "🌧",
    57: "🌧",
    61: "🌦",
    63: "🌧",
    65: "🌧",
    66: "🌧",
    67: "🌧",
    71: "🌨",
    73: "🌨",
    75: "❄️",
    77: "🌨",
    80: "🌦",
    81: "🌧",
    82: "⛈",
    85: "🌨",
    86: "❄️",
    95: "⛈",
    96: "⛈",
    99: "⛈",
}


@dataclass(frozen=True)
class WeatherReport:
    place: str
    temperature: float
    apparent_temperature: float
    wind_speed: float
    weather_code: int
    daily_min: float
    daily_max: float
    precipitation_probability: int | None
    fetched_at: str


_cached_weather: tuple[WeatherReport, datetime] | None = None


async def get_mala_tokmachka_weather() -> WeatherReport:
    global _cached_weather

    now = datetime.now(UTC)
    if _cached_weather is not None:
        report, cached_at = _cached_weather
        if now - cached_at < WEATHER_CACHE_TTL:
            return report

    report = await fetch_mala_tokmachka_weather()
    _cached_weather = (report, now)
    return report


async def fetch_mala_tokmachka_weather() -> WeatherReport:
    params = {
        "latitude": MALA_TOKMACHKA_LATITUDE,
        "longitude": MALA_TOKMACHKA_LONGITUDE,
        "current": ",".join(
            [
                "temperature_2m",
                "apparent_temperature",
                "weather_code",
                "wind_speed_10m",
            ]
        ),
        "daily": ",".join(
            [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
            ]
        ),
        "timezone": "auto",
        "forecast_days": 1,
    }
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(OPEN_METEO_URL, params=params) as response:
            response.raise_for_status()
            payload = await response.json()

    return parse_weather_report(payload)


def parse_weather_report(payload: dict[str, Any]) -> WeatherReport:
    current = payload.get("current")
    daily = payload.get("daily")
    if not isinstance(current, dict) or not isinstance(daily, dict):
        raise ValueError("Open-Meteo returned an unexpected weather payload")

    return WeatherReport(
        place="Малая Токмачка",
        temperature=_float_field(current, "temperature_2m"),
        apparent_temperature=_float_field(current, "apparent_temperature"),
        wind_speed=_float_field(current, "wind_speed_10m"),
        weather_code=int(_float_field(current, "weather_code")),
        daily_min=_first_float(daily, "temperature_2m_min"),
        daily_max=_first_float(daily, "temperature_2m_max"),
        precipitation_probability=_optional_int(daily.get("precipitation_probability_max")),
        fetched_at=str(current.get("time") or datetime.now(UTC).isoformat(timespec="minutes")),
    )


def format_weather_report(report: WeatherReport) -> str:
    condition = WEATHER_CODES.get(report.weather_code, f"код погоды {report.weather_code}")
    emoji = WEATHER_EMOJIS.get(report.weather_code, "🌦")
    verdict = weather_verdict(report)
    rain_line = (
        "• Осадки: <b>нет данных</b>"
        if report.precipitation_probability is None
        else f"• Осадки: <b>{report.precipitation_probability}%</b>"
    )
    return (
        f"<b>{emoji} {escape(report.place)}</b>\n"
        "<i>погодный доклад без лишней бюрократии</i>\n\n"
        "<b>🌡 Сейчас</b>\n"
        f"• Температура: <b>{format_degrees(report.temperature)}</b>\n"
        f"• Ощущается: <b>{format_degrees(report.apparent_temperature)}</b>\n"
        f"• Небо: <b>{escape(condition)}</b>\n\n"
        "<b>📍 Сегодня</b>\n"
        f"• Коридор: <b>{format_degrees(report.daily_min)}</b> → "
        f"<b>{format_degrees(report.daily_max)}</b>\n"
        f"{rain_line}\n"
        f"• Ветер: <b>{report.wind_speed:.0f} км/ч</b>\n\n"
        "<b>Вердикт</b>\n"
        f"{escape(verdict)}"
    )


def format_weather_error() -> str:
    return (
        "<b>🌦 Погода не прилетела</b>\n\n"
        "Погодный источник сейчас не отвечает. Попробуйте ещё раз чуть позже"
    )


def format_degrees(value: float) -> str:
    return f"{value:+.0f}°C"


def weather_verdict(report: WeatherReport) -> str:
    if report.weather_code in {95, 96, 99}:
        return "небо шумит, геройствовать без нужды не надо"
    if report.weather_code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "зонт не понты, сегодня он почти броня"
    if report.weather_code in {71, 73, 75, 77, 85, 86}:
        return "снег включён, обувь выбирай без самоуважения"
    if report.wind_speed >= 30:
        return "ветер бодрый, кепку держать руками"
    if report.apparent_temperature <= 0:
        return "холод кусается, куртку не игнорируй"
    if report.apparent_temperature >= 28:
        return "жара давит, воду держи ближе к телу"
    if report.weather_code in {0, 1}:
        return "погода ведёт себя прилично, подозрительно даже"

    return "можно жить, но без лишнего героизма"


def _optional_int(values: object) -> int | None:
    if not isinstance(values, list) or not values:
        return None

    try:
        return int(values[0])
    except (TypeError, ValueError):
        return None


def _float_field(data: dict[str, Any], field: str) -> float:
    try:
        return float(data[field])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Open-Meteo payload misses {field}") from error


def _first_float(data: dict[str, Any], field: str) -> float:
    values = data.get(field)
    if not isinstance(values, list) or not values:
        raise ValueError(f"Open-Meteo payload misses {field}")

    try:
        return float(values[0])
    except (TypeError, ValueError) as error:
        raise ValueError(f"Open-Meteo payload has invalid {field}") from error

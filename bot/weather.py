from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any

import aiohttp

MALA_TOKMACHKA_LATITUDE = 47.53563
MALA_TOKMACHKA_LONGITUDE = 35.89293
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

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
    timeout = aiohttp.ClientTimeout(total=8)
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
        temperature=float(current["temperature_2m"]),
        apparent_temperature=float(current["apparent_temperature"]),
        wind_speed=float(current["wind_speed_10m"]),
        weather_code=int(current["weather_code"]),
        daily_min=float(daily["temperature_2m_min"][0]),
        daily_max=float(daily["temperature_2m_max"][0]),
        precipitation_probability=_optional_int(daily.get("precipitation_probability_max")),
        fetched_at=str(current.get("time") or datetime.now().isoformat(timespec="minutes")),
    )


def format_weather_report(report: WeatherReport) -> str:
    condition = WEATHER_CODES.get(report.weather_code, f"код погоды {report.weather_code}")
    rain_line = (
        "• Осадки: <b>нет данных</b>"
        if report.precipitation_probability is None
        else f"• Осадки: <b>{report.precipitation_probability}%</b>"
    )
    return (
        f"<b>🌦 Погода: {escape(report.place)}</b>\n\n"
        f"• Сейчас: <b>{format_degrees(report.temperature)}</b>, {escape(condition)}\n"
        f"• Ощущается как: <b>{format_degrees(report.apparent_temperature)}</b>\n"
        f"• День: <b>{format_degrees(report.daily_min)}</b> / <b>{format_degrees(report.daily_max)}</b>\n"
        f"• Ветер: <b>{report.wind_speed:.0f} км/ч</b>\n"
        f"{rain_line}\n\n"
        f"<i>Малая Токмачка, прогноз Open-Meteo</i>"
    )


def format_weather_error() -> str:
    return (
        "<b>🌦 Погода не прилетела</b>\n\n"
        "Open-Meteo сейчас не отвечает. Попробуйте ещё раз чуть позже"
    )


def format_degrees(value: float) -> str:
    return f"{value:+.0f}°C"


def _optional_int(values: object) -> int | None:
    if not isinstance(values, list) or not values:
        return None

    try:
        return int(values[0])
    except (TypeError, ValueError):
        return None

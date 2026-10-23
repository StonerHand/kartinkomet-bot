"""Seasons: one calendar month in the chats' local time.

The season score is the coins a player earned by taking part (votes, likes, uploads, quests,
bosses, the daily bonus): ledger rows with earn = 1. Casino wins, gifts and chests don't count.
When a month ends the top three keep a season badge forever and every balance, except the
admins', goes back to the starting coins.
"""

from datetime import UTC, datetime, timedelta

PODIUM = 3
MONTHS = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)
MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def local(now: int, tz_offset_hours: int) -> datetime:
    return datetime.fromtimestamp(now, UTC) + timedelta(hours=tz_offset_hours)


def season_of(now: int, tz_offset_hours: int) -> str:
    """'2026-10'."""
    return local(now, tz_offset_hours).strftime("%Y-%m")


def bounds(season: str, tz_offset_hours: int) -> tuple[int, int]:
    """Unix time of the season's first local midnight and of the next season's."""
    year, month = (int(part) for part in season.split("-"))
    start = datetime(year, month, 1, tzinfo=UTC) - timedelta(hours=tz_offset_hours)
    end = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=UTC) - timedelta(hours=tz_offset_hours)
    return int(start.timestamp()), int(end.timestamp())


def name(season: str) -> str:
    """'2026-10' → 'октябрь 2026'."""
    year, month = season.split("-")
    return f"{MONTHS[int(month) - 1]} {year}"


def last_day(now: int, tz_offset_hours: int) -> bool:
    today = local(now, tz_offset_hours)
    return (today + timedelta(days=1)).month != today.month


def next_season(season: str) -> str:
    year, month = (int(part) for part in season.split("-"))
    return f"{year + month // 12}-{month % 12 + 1:02d}"

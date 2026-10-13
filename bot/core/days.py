"""Event of the day: one rule of the game bends from START_HOUR until midnight (local time).

The game asks `active(code)`; texts live in bot.texts.days. Rolled once a day, never the same
event two days in a row.
"""

import random
from dataclasses import dataclass

START_HOUR = 10


@dataclass(frozen=True)
class DayEvent:
    code: str
    weight: int


EVENTS = (
    DayEvent("inflation", 6),  # shop prices ×2
    DayEvent("black_friday", 6),  # shop −50%
    DayEvent("plague", 6),  # the first 🖕🏻 sends a pic to court
    DayEvent("amnesty", 5),  # courts never execute
    DayEvent("blood_moon", 5),  # arena death threshold 1000 instead of 900
    DayEvent("lucky_day", 6),  # casino wins ×1.5
    DayEvent("double_coins", 7),  # activity rewards ×2
    DayEvent("tax", 5),  # the three richest pay 10%, the poor split it
    DayEvent("invasion", 5),  # a double boss arrives with the announcement
    DayEvent("gold_rush", 6),  # golden pics ×10 more often
    DayEvent("hunting_season", 5),  # bounties pay double
    DayEvent("upside_down", 5),  # in duels the pic with FEWER votes wins
    DayEvent("thieves_day", 5),  # robbery succeeds 70% of the time
    DayEvent("wedding_day", 4),  # weddings are free
    DayEvent("dead_day", 5),  # resurrection costs 300
    DayEvent("quest_mania", 6),  # quest rewards ×2
    DayEvent("sniper_day", 6),  # guessing the winner pays ×3
    DayEvent("quiet_day", 3),  # nothing happens. Suspicious
)
CODES = {event.code for event in EVENTS}

# Effects, in one place so the rules and the help text agree.
GOLD_RUSH_CHANCE_FACTOR = 10
GOLD_RUSH_COOLDOWN = 600
BLOOD_MOON_DEATH_RATING = 1000.0
THIEVES_DAY_CHANCE = 0.7
DEAD_DAY_RESURRECTION = 300
TAX_SHARE = 0.10
TAX_RICH_COUNT = 3
TAX_POOR_BELOW = 500


def roll(rng: random.Random, yesterday: str | None) -> str:
    pool = [event for event in EVENTS if event.code != yesterday]
    total = sum(event.weight for event in pool)
    point = rng.uniform(0, total)
    for event in pool:
        if point < event.weight:
            return event.code
        point -= event.weight
    return pool[-1].code


def tax(balances: list[tuple[int, int]]) -> tuple[dict[int, int], dict[int, int]]:
    """balances: (user, coins). Returns (taken from the rich, given to the poor)."""
    rich = sorted((item for item in balances if item[1] >= TAX_POOR_BELOW), key=lambda item: -item[1])
    rich = rich[:TAX_RICH_COUNT]
    rich_ids = {user for user, _ in rich}
    poor = [user for user, coins in balances if coins < TAX_POOR_BELOW and user not in rich_ids]
    taken = {user: int(coins * TAX_SHARE) for user, coins in rich if int(coins * TAX_SHARE) > 0}
    if not poor or not taken:
        return {}, {}
    share = sum(taken.values()) // len(poor)
    if share <= 0:
        return {}, {}
    return taken, {user: share for user in poor}

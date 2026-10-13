"""Mini-game rules: caption contest, golden pic, wheel of fortune (Telegram 🎰), horoscope."""

import random
from dataclasses import dataclass

# Caption contest
CAPTION_COLLECT_SECONDS = 60
CAPTION_VOTE_SECONDS = 45
CAPTION_MAX_ENTRIES = 8
CAPTION_MAX_LENGTH = 100

# Golden pic
GOLD_CHANCE = 0.01
GOLD_COOLDOWN_SECONDS = 3600


def caption_winner(entries: list[dict], votes: dict[int, int]) -> int | None:
    """Author with most votes; a tie goes to whoever wrote first. None if nobody voted."""
    if not votes:
        return None
    tally: dict[int, int] = {}
    for author in votes.values():
        tally[author] = tally.get(author, 0) + 1
    best = max(tally.values())
    for entry in entries:  # entries are ordered by time
        if tally.get(entry["user_id"]) == best:
            return entry["user_id"]
    return None


# Wheel of fortune. Telegram's 🎰 dice returns 1..64: value-1 in base 4 gives three reels,
# each 0 = BAR, 1 = grapes, 2 = lemon, 3 = seven. 64 is 7-7-7.
@dataclass(frozen=True)
class Spin:
    kind: str  # jackpot | triple | pair | small | loss | curse | bless | legend
    coins: int


SPIN_WEIGHTS = (("small", 35), ("loss", 20), ("curse", 15), ("bless", 15), ("legend", 15))
SPIN_COINS = {"jackpot": 100, "triple": 40, "pair": 10, "small": 3, "loss": -10, "curse": 0, "bless": 0, "legend": 0}
CURSE_RATING = -20
BLESS_RATING = 20


def reels(value: int) -> tuple[int, int, int]:
    index = value - 1
    return index % 4, index // 4 % 4, index // 16 % 4


def spin_outcome(value: int, rng: random.Random) -> Spin:
    first, second, third = reels(value)
    if value == 64:
        kind = "jackpot"
    elif first == second == third:
        kind = "triple"
    elif first == second or second == third or first == third:
        kind = "pair"
    else:
        roll = rng.uniform(0, sum(weight for _, weight in SPIN_WEIGHTS))
        kind = SPIN_WEIGHTS[-1][0]
        for name, weight in SPIN_WEIGHTS:
            if roll < weight:
                kind = name
                break
            roll -= weight
    return Spin(kind, SPIN_COINS[kind])

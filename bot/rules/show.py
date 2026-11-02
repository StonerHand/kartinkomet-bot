"""The evening show at 21:00: a bank heist one day, the big cup the next."""

import random
from dataclasses import dataclass

SHOW_HOUR = 21

# ── the heist ─────────────────────────────────────────────────────────
RECRUIT_SECONDS = 120
STAGE_SECONDS = 60
STAGES = 3
MIN_CREW = 2
MAX_CREW = 8
ROLES = ("hacker", "driver", "decoy", "muscle")  # handed out in the order people join
ROLE_BONUS = 0.2  # a stage's option is this much likelier when its role is in the crew
LOOT_PER_MEMBER = 300  # base coins each member takes from a clean job


@dataclass(frozen=True)
class Option:
    code: str
    chance: float
    role: str  # the crew member who makes it likelier


# Each event offers two ways through.
EVENTS = {
    "guards": (Option("rush", 0.5, "muscle"), Option("wait", 0.6, "decoy")),
    "vault": (Option("drill", 0.55, "hacker"), Option("blast", 0.5, "muscle")),
    "alarm": (Option("cut", 0.55, "hacker"), Option("run", 0.5, "driver")),
    "chase": (Option("speed", 0.55, "driver"), Option("hide", 0.55, "decoy")),
    "dog": (Option("feed", 0.6, "decoy"), Option("sneak", 0.5, "driver")),
    "camera": (Option("loop", 0.55, "hacker"), Option("mask", 0.55, "decoy")),
}


def role_of(index: int) -> str:
    return ROLES[index % len(ROLES)]


def plan(rng: random.Random) -> list[str]:
    """The night's events, one per stage."""
    return rng.sample(sorted(EVENTS), STAGES)


def chance(option: Option, roles: set[str]) -> float:
    return min(0.95, option.chance + (ROLE_BONUS if option.role in roles else 0))


def chosen(votes: list[int], rng: random.Random) -> int:
    """The crew's choice: the majority; a tie or silence is a coin toss."""
    counts = [votes.count(0), votes.count(1)]
    if counts[0] == counts[1]:
        return rng.randrange(2)
    return 0 if counts[0] > counts[1] else 1


# ── the big cup ───────────────────────────────────────────────────────
CUP_SIZE = 8  # pics: quarter-finals, semi-finals, the final
CUP_DUEL_SECONDS = 90
CUP_PRIZE = 500  # base coins to the champion's uploader
CUP_RATING_BONUS = 20  # the champion pic's rating, on top of its wins
CUP_ROUNDS = {8: "четвертьфинал", 4: "полуфинал", 2: "финал"}


def show_of(local_day: int) -> str:
    """Which show tonight: they take turns."""
    return "heist" if local_day % 2 == 0 else "cup"

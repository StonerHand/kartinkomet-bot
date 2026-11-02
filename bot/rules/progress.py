"""Daily bonus, daily quests, weekly challenges and chests. Pure rules, no storage.

Progress is counted by "kinds" of actions the game reports (vote, like, casino_bet…).
Daily quests are personal and seeded by (user, day); weekly challenges are the same for
everyone and seeded by the week, so the chat can race for them together.
"""

import random
from dataclasses import dataclass

# ── daily bonus ────────────────────────────────────────────────────────

DAILY_REWARDS = (50, 60, 70, 80, 100, 120, 150)  # day 1..7 of a streak; day 7+ stays at 150
DAILY_CHEST_EVERY = 7  # every 7th day in a row brings a rare chest
MARRIED_DAILY_BONUS = 0.2  # +20% when the spouse already claimed today


def daily_reward(streak_day: int) -> int:
    return DAILY_REWARDS[min(streak_day, len(DAILY_REWARDS)) - 1]


def daily_chest(streak_day: int) -> bool:
    return streak_day % DAILY_CHEST_EVERY == 0


# ── quests ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Task:
    kind: str
    target: int
    reward: int


# kind → (possible targets, reward). Texts: bot.texts.progress.QUEST_NAMES.
QUEST_POOL = {
    "vote": ((2, 3), 50),
    "like": ((3, 5), 40),
    "pic": ((5, 8), 30),
    "court_vote": ((1,), 50),
    "guess": ((1, 2), 60),
    "casino_bet": ((3, 5), 40),
    "arena_bet": ((1,), 50),
    "boss_hit": ((10, 15), 50),
    "upload": ((1, 3), 40),
    "caption": ((1,), 60),
    "give": ((1,), 30),
    "horoscope": ((1,), 20),
    "battle_start": ((1, 2), 30),
}
QUESTS_PER_DAY = 3
ALL_QUESTS_BONUS = 50  # plus a wooden chest


def daily_quests(user_id: int, day: int) -> list[Task]:
    rng = random.Random(f"quests:{user_id}:{day}")
    kinds = rng.sample(sorted(QUEST_POOL), QUESTS_PER_DAY)
    return [Task(kind, rng.choice(QUEST_POOL[kind][0]), QUEST_POOL[kind][1]) for kind in kinds]


# ── weekly challenges ──────────────────────────────────────────────────

CHALLENGE_POOL = {
    "like": 25,
    "vote": 12,
    "guess": 6,
    "casino_win": 10,
    "boss_damage": 60,
    "bet_won": 3,
    "upload": 10,
    "court_vote": 4,
    "chest": 3,
    "daily": 5,
    "quest": 9,
    "challenge_win": 2,
    "rob_success": 2,
}
CHALLENGES_PER_WEEK = 3
CHALLENGE_REWARD = 250  # plus a rare chest; all three in a week add a legendary chest


def weekly_challenges(week: int) -> list[Task]:
    rng = random.Random(f"challenges:{week}")
    kinds = rng.sample(sorted(CHALLENGE_POOL), CHALLENGES_PER_WEEK)
    return [Task(kind, CHALLENGE_POOL[kind], CHALLENGE_REWARD) for kind in kinds]


# ── chests ─────────────────────────────────────────────────────────────

WOOD, RARE, LEGEND = "wood", "rare", "legend"
TIERS = (WOOD, RARE, LEGEND)
RANDOM_CHEST_CHANCE = 0.03  # on a vote or a like, at most one random chest per day


@dataclass(frozen=True)
class Loot:
    kind: str  # empty | coins | boost | shield | chest | frame | title
    coins: int = 0
    prize: str = ""  # the frame or the title won


# tier → [(weight, kind, coins range)]
LOOT = {
    WOOD: ((15, "empty", (0, 0)), (60, "coins", (40, 150)), (15, "coins", (150, 300)), (10, "boost", (0, 0))),
    RARE: ((5, "empty", (0, 0)), (50, "coins", (200, 500)), (17, "coins", (500, 900)), (10, "shield", (0, 0)),
           (10, "chest", (0, 0)), (8, "frame", (0, 0))),
    LEGEND: ((40, "coins", (1000, 2500)), (20, "coins", (2500, 5000)), (15, "shield", (0, 0)), (15, "frame", (0, 0)),
             (10, "title", (0, 0))),
}
# Cosmetic frames drawn around a pic in battles: code → (adjective for texts, RGB).
FRAMES = {
    "gold": ("золотой", (255, 196, 0)),
    "neon": ("неоновой", (0, 229, 255)),
    "fire": ("огненной", (255, 87, 34)),
    "rose": ("розовой", (236, 64, 122)),
}
CHEST_BOOST_RATING = 30
CHEST_SHIELD_SECONDS = 3 * 86400


def open_chest(tier: str, rng: random.Random) -> Loot:
    table = LOOT[tier]
    point = rng.uniform(0, sum(weight for weight, _, _ in table))
    for weight, kind, (low, high) in table:
        if point < weight:
            return Loot(kind, rng.randint(low, high) if high else 0)
        point -= weight
    _, kind, (low, high) = table[-1]
    return Loot(kind, rng.randint(low, high) if high else 0)

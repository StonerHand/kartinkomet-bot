"""Pic boss: the chat beats it with buttons before it escapes.

Free hits do 1–3 damage (10% crit ×2), a paid super hit 6–10. Every COUNTER_EVERY hits the
boss strikes back and takes coins from a random fighter into the loot. Win: the loot is split
by damage share. Escape: the loot burns and the boss pic gets stronger.
"""

import random
from dataclasses import dataclass

DURATION_SECONDS = 600
SUMMON_COOLDOWN_SECONDS = 3 * 3600
HIT_COOLDOWN_SECONDS = 2.0
BASE_HP = 40
HP_PER_PLAYER = 15  # per player active in the last week: a boss should take the chat a few minutes
MIN_HP = 80
SUPER_PRICE = 25
BASE_LOOT = 200
LOOT_PER_HP = 2
LAST_HIT_BONUS = 50
COUNTER_EVERY = 15
COUNTER_FINE = 15
ESCAPE_RATING_BONUS = 30


def max_hp(active_players: int, double: bool = False) -> int:
    hp = max(MIN_HP, BASE_HP + HP_PER_PLAYER * active_players)
    return hp * 2 if double else hp


def loot(hp: int, double: bool = False) -> int:
    value = BASE_LOOT + LOOT_PER_HP * hp
    return value * 2 if double else value


@dataclass(frozen=True)
class Hit:
    damage: int
    crit: bool


def hit(rng: random.Random, super_hit: bool = False) -> Hit:
    if super_hit:
        return Hit(rng.randint(6, 10), False)
    damage = rng.randint(1, 3)
    if rng.random() < 0.1:
        return Hit(damage * 2, True)
    return Hit(damage, False)


def split_loot(pool: int, damage: dict[int, int]) -> dict[int, int]:
    total = sum(damage.values())
    if not total:
        return {}
    return {user: pool * dealt // total for user, dealt in damage.items() if pool * dealt // total > 0}

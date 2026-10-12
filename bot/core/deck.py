"""Mixed random: 70% deck, 20% fresh uploads, 10% hall-of-fame legends."""

import random
from collections.abc import Sequence
from typing import Protocol

from bot.db.repo import Pic

BUCKETS: tuple[tuple[str, float], ...] = (("deck", 0.70), ("fresh", 0.20), ("legend", 0.10))
FRESH_SECONDS = 7 * 24 * 3600


class DeckSource(Protocol):
    def draw(
        self,
        scope: str,
        bucket: str,
        now: int,
        limit: int = 1,
        exclude: Sequence[str] = (),
        fresh_seconds: int = FRESH_SECONDS,
    ) -> list[Pic]: ...

    def clear_seen(self, scope: str) -> None: ...

    def mark_shown(self, scope: str, pic_ids: Sequence[str], now: int) -> None: ...

    def count_pics(self, status: str = "alive") -> int: ...


def roll_bucket(rng: random.Random) -> str:
    roll = rng.random()
    total = 0.0
    for bucket, weight in BUCKETS:
        total += weight
        if roll < total:
            return bucket
    return BUCKETS[0][0]


def draw_one(source: DeckSource, scope: str, now: int, rng: random.Random) -> tuple[Pic, str] | None:
    """Returns (pic, bucket it actually came from) and marks it as shown."""
    picks = draw_many(source, scope, now, 1, bucket=roll_bucket(rng))
    return picks[0] if picks else None


def draw_many(
    source: DeckSource,
    scope: str,
    now: int,
    count: int,
    bucket: str = "deck",
    exclude: Sequence[str] = (),
) -> list[tuple[Pic, str]]:
    if source.count_pics() - len(exclude) < count:
        return []

    result: list[tuple[Pic, str]] = []
    taken = list(exclude)
    if bucket != "deck":
        for pic in source.draw(scope, bucket, now, limit=count, exclude=taken):
            result.append((pic, bucket))
            taken.append(pic.id)

    for attempt in range(2):
        missing = count - len(result)
        if missing <= 0:
            break
        for pic in source.draw(scope, "deck", now, limit=missing, exclude=taken):
            result.append((pic, "deck"))
            taken.append(pic.id)
        if len(result) < count and attempt == 0:
            # Deck exhausted in this scope: new cycle.
            source.clear_seen(scope)

    if len(result) < count:
        return []
    source.mark_shown(scope, [pic.id for pic, _ in result], now)
    return result

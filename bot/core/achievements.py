"""Achievement rules. Names and descriptions live in bot.texts.achievements."""

from collections.abc import Callable
from dataclasses import dataclass

from bot.db.repo import UserStats


@dataclass(frozen=True)
class Rule:
    code: str
    threshold: int
    metric: Callable[[UserStats], int]


def _tiers(prefix: str, metric: Callable[[UserStats], int], *thresholds: int) -> list[Rule]:
    return [Rule(f"{prefix}_{threshold}", threshold, metric) for threshold in thresholds]


RULES: list[Rule] = [
    *_tiers("up", lambda s: s.uploads, 1, 10, 50, 100, 250, 500, 1000),
    *_tiers("night", lambda s: s.night_uploads, 1, 25, 100),
    *_tiers("liked", lambda s: s.likes_received, 10, 50, 200),
    *_tiers("hated", lambda s: s.dislikes_received, 5, 25, 100),
    *_tiers("exec", lambda s: s.pics_executed, 1, 10, 50),
    *_tiers("killer", lambda s: s.kill_votes, 1, 10, 50),
    *_tiers("lawyer", lambda s: s.spare_votes, 1, 10, 50),
    *_tiers("streak", lambda s: s.best_streak, 3, 5, 10),
    *_tiers("legend", lambda s: s.legends, 1, 5),
]
RULE_CODES = [rule.code for rule in RULES]
UPLOAD_RULES = [rule for rule in RULES if rule.code.startswith("up_")]


def earned(stats: UserStats, owned: set[str]) -> list[str]:
    return [rule.code for rule in RULES if rule.code not in owned and rule.metric(stats) >= rule.threshold]


def upload_title_code(uploads: int) -> str | None:
    """Current title = highest upload tier reached."""
    reached = [rule.code for rule in UPLOAD_RULES if uploads >= rule.threshold]
    return reached[-1] if reached else None


def next_upload_goal(uploads: int) -> Rule | None:
    for rule in UPLOAD_RULES:
        if uploads < rule.threshold:
            return rule
    return None

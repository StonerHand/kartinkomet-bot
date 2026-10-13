"""Results the game hands to the Telegram layer."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Note:
    """Something worth announcing besides achievements: a finished quest, a dropped chest…"""

    kind: str  # quest | quests_all | challenge | challenges_all | chest
    code: str = ""  # quest kind or chest tier
    amount: int = 0  # coins paid
    target: int = 0


@dataclass(frozen=True)
class Granted:
    user_id: int
    codes: list[str]
    level_up: str | None = None  # name of the new level, if the player just reached one
    notes: list[Note] = field(default_factory=list)

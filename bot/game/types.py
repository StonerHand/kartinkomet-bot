"""Results the game hands to the Telegram layer."""

from dataclasses import dataclass, field

from bot.core import arena
from bot.db.repo import Battle, Court, Pic


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


@dataclass(frozen=True)
class ReactResult:
    pic: Pic
    changed: bool
    court_due: bool
    granted: list[Granted] = field(default_factory=list)


@dataclass(frozen=True)
class StartResult:
    status: str  # 'started' | 'active' | 'shortage' | 'stale'
    battle: Battle | None = None


@dataclass(frozen=True)
class BattleReport:
    battle: Battle
    counted: bool
    winner: int | None
    executed: Pic | None
    rating_before: list[float]
    rating_after: list[float]
    streak: int  # winner's streak after a duel (0 for tournaments / draws without champion)
    milestone: int | None
    granted: list[Granted]
    guessers: list[int] = field(default_factory=list)  # voters who picked the winner
    guess_reward: int = 0
    flipped: bool = False  # "upside down" day: the pic with fewer votes won
    bets: dict[int, tuple[int, int]] = field(default_factory=dict)  # user → (staked, paid back)
    bets_burned: int = 0
    bounty: dict[int, int] = field(default_factory=dict)  # hunter → coins
    evolved: list[tuple[int, int, int]] = field(default_factory=list)  # (slot, old stage, new stage)
    challenge: dict | None = None
    champion: int | None = None  # the player who won a challenge
    death_rating: float = arena.DEATH_RATING  # 1000 on a blood-moon day


@dataclass(frozen=True)
class CourtStart:
    status: str  # 'started' | 'active' | 'immune' | 'gone'
    court: Court | None = None


@dataclass(frozen=True)
class CourtReport:
    court: Court
    verdict: str  # 'executed' | 'pardoned'
    granted: list[Granted]
    amnesty: bool = False
    bounty: dict[int, int] = field(default_factory=dict)
    bail_back: int = 0  # bail returned after a won appeal

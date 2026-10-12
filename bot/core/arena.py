"""Battle outcomes: who won, new ratings, who dies, streaks. No Telegram, no SQL."""

from collections.abc import Sequence
from dataclasses import dataclass

from bot.core import elo

DUEL_SECONDS = 60
TOURNAMENT_SECONDS = 90
TOURNAMENT_SIZE = 4
DEATH_RATING = 900.0
DEATH_LOSS_STREAK = 3
STREAK_MILESTONES = (3, 5, 10)


@dataclass(frozen=True)
class Fighter:
    pic_id: str
    rating: float
    games: int
    loss_streak: int


@dataclass(frozen=True)
class DuelOutcome:
    winner: int | None  # slot, None = draw or nobody voted
    counted: bool  # False when nobody voted: nothing changes
    ratings: tuple[float, float]
    outcomes: tuple[str, str]  # 'win' | 'loss' | 'draw' per slot
    executed: int | None  # slot of the loser if it dies
    streak: int  # champion streak after this duel (for the winner / survivor)


@dataclass(frozen=True)
class TournamentOutcome:
    winner: int | None
    counted: bool
    ratings: list[float]
    outcomes: list[str]


def resolve_duel(fighters: Sequence[Fighter], votes: Sequence[int], streak: int) -> DuelOutcome:
    """streak: champion streak of slot 0 before the duel (0 if no champion)."""
    left, right = fighters
    if sum(votes) == 0:
        return DuelOutcome(
            winner=None,
            counted=False,
            ratings=(left.rating, right.rating),
            outcomes=("draw", "draw"),
            executed=None,
            streak=streak,
        )

    if votes[0] == votes[1]:
        ratings = elo.duel((left.rating, right.rating), (left.games, right.games), 0.5)
        return DuelOutcome(
            winner=None,
            counted=True,
            ratings=ratings,
            outcomes=("draw", "draw"),
            executed=None,
            streak=streak,
        )

    winner = 0 if votes[0] > votes[1] else 1
    loser = 1 - winner
    ratings = elo.duel(
        (left.rating, right.rating),
        (left.games, right.games),
        1.0 if winner == 0 else 0.0,
    )
    loser_fighter = fighters[loser]
    dies = ratings[loser] < DEATH_RATING or loser_fighter.loss_streak + 1 >= DEATH_LOSS_STREAK
    # Champion sits in slot 0. If it wins, the streak grows; a new winner starts at 1.
    new_streak = streak + 1 if winner == 0 and streak > 0 else 1
    outcomes = ("win", "loss") if winner == 0 else ("loss", "win")
    return DuelOutcome(
        winner=winner,
        counted=True,
        ratings=ratings,
        outcomes=outcomes,
        executed=loser if dies else None,
        streak=new_streak,
    )


def resolve_tournament(fighters: Sequence[Fighter], votes: Sequence[int]) -> TournamentOutcome:
    ratings = [fighter.rating for fighter in fighters]
    if sum(votes) == 0:
        return TournamentOutcome(
            winner=None, counted=False, ratings=ratings, outcomes=["draw"] * len(fighters)
        )

    best = max(votes)
    leaders = [slot for slot, count in enumerate(votes) if count == best]
    winner = leaders[0] if len(leaders) == 1 else None
    new_ratings = elo.tournament(ratings, [fighter.games for fighter in fighters], votes)
    outcomes = []
    for slot, count in enumerate(votes):
        if winner is not None and slot == winner:
            outcomes.append("win")
        elif count == best:
            outcomes.append("draw")
        else:
            outcomes.append("loss")
    return TournamentOutcome(winner=winner, counted=True, ratings=new_ratings, outcomes=outcomes)


def streak_milestone(streak: int) -> int | None:
    """Largest milestone hit exactly at this streak (3, 5, 10, then every 5 after 10)."""
    if streak in STREAK_MILESTONES:
        return streak
    if streak > 10 and streak % 5 == 0:
        return 10
    return None

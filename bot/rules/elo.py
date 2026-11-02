"""Elo rating for pics."""

from collections.abc import Sequence

PROVISIONAL_GAMES = 10
K_PROVISIONAL = 32.0
K_STABLE = 16.0


def k_factor(games: int) -> float:
    return K_PROVISIONAL if games < PROVISIONAL_GAMES else K_STABLE


def expected(rating: float, opponent: float) -> float:
    return 1.0 / (1.0 + 10 ** ((opponent - rating) / 400.0))


def duel(
    ratings: tuple[float, float],
    games: tuple[int, int],
    score_first: float,
) -> tuple[float, float]:
    """score_first: 1 = first won, 0 = second won, 0.5 = draw."""
    first, second = ratings
    new_first = first + k_factor(games[0]) * (score_first - expected(first, second))
    new_second = second + k_factor(games[1]) * ((1 - score_first) - expected(second, first))
    return new_first, new_second


def tournament(
    ratings: Sequence[float],
    games: Sequence[int],
    votes: Sequence[int],
) -> list[float]:
    """Every pair is a mini-duel decided by votes; K is split across opponents."""
    size = len(ratings)
    deltas = [0.0] * size
    for i in range(size):
        k = k_factor(games[i]) / max(1, size - 1)
        for j in range(size):
            if i == j:
                continue
            if votes[i] > votes[j]:
                score = 1.0
            elif votes[i] < votes[j]:
                score = 0.0
            else:
                score = 0.5
            deltas[i] += k * (score - expected(ratings[i], ratings[j]))
    return [rating + delta for rating, delta in zip(ratings, deltas)]

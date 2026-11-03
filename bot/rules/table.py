"""Table games of the chat: the spy among us, the minefield, the safe with a code."""

import random

from bot.rules.party import poll_winners

# ── the spy ───────────────────────────────────────────────────────────
SPY_RECRUIT_SECONDS = 90
SPY_TALK_SECONDS = 150  # everyone writes a word about the word; the spy bluffs
SPY_VOTE_SECONDS = 60
SPY_MIN = 3  # the spy and two who know the word
SPY_MAX = 8
SPY_COOLDOWN_SECONDS = 20 * 60
SPY_CATCH_REWARD = 40  # base coins to each player who knew the word, when the spy is caught
SPY_ESCAPE_REWARD = 150  # base coins to the spy who got away


def spy_caught(votes: dict[int, int], spy: int) -> bool:
    """Caught only by the most votes of their own: a tie lets the spy slip away."""
    return poll_winners(votes) == [spy]


# ── the minefield ─────────────────────────────────────────────────────
MINES_SIDE = 4  # a 4×4 field fits a phone in buttons
MINES_COUNT = 2
MINES_SECONDS = 300
MINES_COOLDOWN_SECONDS = 20 * 60
MINES_STEP = 10  # base coins: the n-th safe cell of the field is worth n steps


def minefield(rng: random.Random) -> list[int]:
    return sorted(rng.sample(range(MINES_SIDE * MINES_SIDE), MINES_COUNT))


def cell_value(opened: int) -> int:
    """What the next safe cell brings when `opened` are open already: the deeper, the dearer."""
    return MINES_STEP * (opened + 1)


# ── the safe ──────────────────────────────────────────────────────────
SAFE_DIGITS = 4  # all different
SAFE_SECONDS = 30 * 60
SAFE_COOLDOWN_SECONDS = 45 * 60
SAFE_GUESS_PRICE = 20  # × the chat's prices; every try goes into the safe
SAFE_SEED = 150  # base coins the bot puts in, paid to whoever cracks it
SAFE_GUESS_GAP = 10  # seconds between one player's tries
SAFE_LOG = 8  # tries the card shows, the latest last


def safe_code(rng: random.Random) -> str:
    return "".join(rng.sample("0123456789", SAFE_DIGITS))


def valid_guess(text: str) -> bool:
    return len(text) == SAFE_DIGITS and text.isdigit() and len(set(text)) == SAFE_DIGITS


def safe_hint(code: str, guess: str) -> tuple[int, int]:
    """(digits in their place, digits in the code but elsewhere): bulls and cows."""
    exact = sum(1 for a, b in zip(code, guess) if a == b)
    return exact, len(set(code) & set(guess)) - exact

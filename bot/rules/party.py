"""Games about the people in the chat: "who of us" polls, the bomb, bets on life."""

import random

# ── who of us ─────────────────────────────────────────────────────────
WHO_SECONDS = 30 * 60
WHO_OPTIONS = 6  # people on the buttons
WHO_COOLDOWN_SECONDS = 2 * 3600  # between polls started by hand; the daily one ignores it
WHO_QUESTION_PRICE = 300  # a question of your own, × the chat's prices
WHO_QUESTION_MAX = 100  # characters
BADGE_SECONDS = 24 * 3600  # a poll's title, the bomb's shame: worn for a day

# ── the bomb ──────────────────────────────────────────────────────────
BOMB_PASS_SECONDS = 15  # the holder's time to pass it on
BOMB_FUSE_SECONDS = (40, 120)  # the whole bomb's hidden fuse
BOMB_COOLDOWN_SECONDS = 30 * 60
BOMB_FINE = 150  # base coins the one it blows up on loses (burned)
BOMB_PASS_REWARD = 10  # base coins once per bomb for everyone who passed it on
BOMB_PLAYERS_SECONDS = 24 * 3600  # who can get it: people seen in the chat lately

# ── bets on life ──────────────────────────────────────────────────────
BET_STAKES = (100, 500)  # × the chat's prices
BET_DAYS = 7  # an unsettled bet is called off and everyone gets their stake back
BET_OPEN_MAX = 5  # open bets per chat
BET_CLAIM_MAX = 120  # characters


def poll_winners(votes: dict[int, int]) -> list[int]:
    """The people with the most votes (a tie: all of them), in the order of their ids."""
    counts: dict[int, int] = {}
    for choice in votes.values():
        counts[choice] = counts.get(choice, 0) + 1
    if not counts:
        return []
    top = max(counts.values())
    return sorted(person for person, count in counts.items() if count == top)


def fuse(rng: random.Random) -> int:
    return rng.randint(*BOMB_FUSE_SECONDS)


def bet_payouts(stakes: dict[int, tuple[int, int]], outcome: int) -> dict[int, int]:
    """What each player gets back when the bet settles: stakes are (side, coins), outcome 1 = it
    came true. The winners take their stake back plus the losers' pool, shared by stake (the
    rounding's leftovers go to the biggest stake). With nobody on one of the sides, everyone gets
    their stake back."""
    winners = {user: coins for user, (side, coins) in stakes.items() if side == outcome}
    pool = sum(coins for side, coins in stakes.values() if side != outcome)
    if not winners or not pool:
        return {user: coins for user, (_, coins) in stakes.items()}
    total = sum(winners.values())
    payouts = {user: coins + pool * coins // total for user, coins in winners.items()}
    biggest = max(winners, key=lambda user: (winners[user], -user))
    payouts[biggest] += pool - sum(payouts[user] - winners[user] for user in winners)
    return payouts

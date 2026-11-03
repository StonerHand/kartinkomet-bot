"""The blind auction: a chest a day, sealed bids, the winner pays the second price."""

import random

OPEN_HOUR = 15
CLOSE_HOUR = 22
RAISES = (50, 200, 1000)  # base coins a button adds to one's bid, × the chat's prices
MIN_PRICE = 50  # base coins: what a lone bidder pays
LOTS = (("rare", 7), ("legend", 3))  # chest tiers and their weights


def lot(rng: random.Random) -> str:
    tiers, weights = zip(*LOTS)
    return rng.choices(tiers, weights)[0]


def settle(bids: dict[int, tuple[int, int]], min_price: int) -> tuple[int | None, int]:
    """bids: player → (coins, when they last raised). (winner, price): the highest bid wins, a
    tie goes to whoever got there first; the winner pays the second-highest bid, at least
    min_price, never more than their own."""
    live = {user: bid for user, bid in bids.items() if bid[0] > 0}
    if not live:
        return None, 0
    ranked = sorted(live.items(), key=lambda item: (-item[1][0], item[1][1], item[0]))
    winner, (top, _) = ranked[0]
    second = ranked[1][1][0] if len(ranked) > 1 else 0
    return winner, min(top, max(second, min_price))

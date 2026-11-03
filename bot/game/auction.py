"""The blind auction: a chest a day from OPEN_HOUR to CLOSE_HOUR. Bids are reserved as they are
made (round_votes: choice = when last raised, stake = the bid), nobody sees anyone else's, and the
winner pays the second-highest bid: what they pay burns, everyone else gets their bid back."""

import json
from dataclasses import dataclass

from bot.game.types import Granted
from bot.rules import auction


@dataclass(frozen=True)
class AuctionResult:
    round: dict
    lot: str  # the chest's tier
    winner: int | None
    price: int
    bidders: int
    granted: tuple[Granted, ...] = ()


class AuctionMixin:
    def open_auction(self, chat_id: int, closes_at: int) -> tuple[str, dict | None]:
        """'opened' | 'active'."""
        active = self.repo.open_rounds(chat_id, "auction")
        if active:
            return "active", active[0]
        state = {"lot": auction.lot(self.rng)}
        round_id = self.repo.create_round(chat_id, "auction", self.now(), closes_at, text=json.dumps(state))
        return "opened", self.repo.get_round(round_id)

    def auction_lot(self, found: dict) -> str:
        return json.loads(found["text"])["lot"]

    def auction_raises(self) -> list[int]:
        return [self.scaled(amount) for amount in auction.RAISES]

    def auction_min_price(self) -> int:
        return self.scaled(auction.MIN_PRICE)

    def auction_bidders(self, found: dict) -> int:
        return sum(1 for _, bid in found["votes"].values() if bid > 0)

    def my_bid(self, round_id: str, user_id: int) -> int:
        found = self.repo.get_round(round_id)
        return found["votes"].get(user_id, (0, 0))[1] if found else 0

    def _auction_open(self, round_id: str) -> tuple[str, dict | None]:
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "auction":
            return "gone", None
        if found["status"] != "open" or self.now() >= found["ends_at"]:
            return "closed", None
        return "open", found

    def raise_bid(self, round_id: str, user_id: int, index: int) -> tuple[str, int]:
        """('ok', the bid now) | ('poor', the raise) | ('closed', 0) | ('gone', 0). The raise is
        taken from the wallet at once and comes back if the bid loses."""
        raises = self.auction_raises()
        status, found = self._auction_open(round_id)
        if found is None:
            return status, 0
        if not 0 <= index < len(raises):
            return "gone", 0
        amount = raises[index]
        if not self.repo.spend(user_id, amount, "auction_bid", self.now()):
            return "poor", amount
        bid = found["votes"].get(user_id, (0, 0))[1] + amount
        self.repo.put_round_vote(round_id, user_id, self.now(), bid)
        return "ok", bid

    def withdraw_bid(self, round_id: str, user_id: int) -> tuple[str, int]:
        """('ok', coins back) | ('empty', 0) | ('closed', 0) | ('gone', 0)."""
        status, found = self._auction_open(round_id)
        if found is None:
            return status, 0
        bid = found["votes"].get(user_id, (0, 0))[1]
        if not bid:
            return "empty", 0
        self.repo.put_round_vote(round_id, user_id, self.now(), 0)
        self.repo.add_coins(user_id, bid, "auction_refund", self.now(), earn=False)
        return "ok", bid

    def settle_auction(self, round_id: str) -> AuctionResult | None:
        """The highest bid takes the chest for the second price; every other bid goes back."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "auction":
            return None
        bids = {user: (bid, at) for user, (at, bid) in found["votes"].items()}
        winner, price = auction.settle(bids, self.auction_min_price())
        if not self.repo.close_round(round_id, winner):
            return None
        for user_id, (bid, _) in bids.items():
            back = bid - price if user_id == winner else bid
            if back > 0:
                self.repo.add_coins(user_id, back, "auction_refund", self.now(), earn=False)
        lot = self.auction_lot(found)
        granted = ()
        if winner is not None:
            self.grant_chest(winner, lot)
            self.repo.incr_counter(winner, "auctions_won")
            granted = tuple(self.check_achievements([winner]))
        return AuctionResult(self.repo.get_round(round_id), lot, winner, price, self.auction_bidders(found), granted)

    def settle_due_auctions(self) -> list[AuctionResult]:
        results = []
        for round_id in self.repo.due_rounds("auction", self.now()):
            result = self.settle_auction(round_id)
            if result is not None:
                results.append(result)
        return results

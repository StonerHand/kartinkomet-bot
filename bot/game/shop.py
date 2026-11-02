"""Shop: shields, boosts, ordered courts, curses, resurrection, titles, bounties."""

from bot.models.records import Pic
from bot.rules import court, shop


class ShopMixin:
    def cursed_until(self, pic_id: str) -> int:
        until = self.repo.meta_int(f"curse:{pic_id}")
        return until if until > self.now() else 0

    def curse(self, pic: Pic) -> None:
        self.repo.shift_rating(pic.id, -shop.CURSE_RATING)
        self.repo.set_meta(f"curse:{pic.id}", self.now() + shop.CURSE_SECONDS)

    def buy(self, user_id: int, item: str, pic_id: str) -> tuple[str, Pic | None]:
        """Buy something for a pic. Statuses: ok, broke, gone, alive, dead, not_cursed, immune,
        on_trial, boosted. On 'ok' for 'court' the caller still has to open the court."""
        pic = self.repo.get_pic(pic_id)
        if pic is None:
            return "gone", None
        price = self.price(item)
        now = self.now()
        if item == "resurrect":
            if pic.status == "alive":
                return "alive", pic
            if pic.status != "executed":
                return "gone", pic
        elif pic.status != "alive":
            return "dead", pic
        if item == "uncurse" and not self.cursed_until(pic.id):
            return "not_cursed", pic
        if item == "court":
            if self.repo.active_court_for_pic(pic.id):
                return "on_trial", pic
            if not court.can_be_tried(pic.status, pic.immune_until, now):
                return "immune", pic
        if item == "shield" and self.repo.active_court_for_pic(pic.id):
            return "on_trial", pic
        if item == "boost" and self.repo.meta_int(f"boost:{pic.id}") == self.local_day():
            return "boosted", pic
        if not self.repo.spend(user_id, price, f"shop_{item}", now):
            return "broke", pic

        if item == "shield":
            self.repo.set_immunity(pic.id, max(now, pic.immune_until or 0) + shop.SHIELD_SECONDS)
        elif item == "boost":
            self.repo.shift_rating(pic.id, shop.BOOST_RATING)
            self.repo.set_meta(f"boost:{pic.id}", self.local_day())
        elif item == "uncurse":
            self.repo.shift_rating(pic.id, shop.CURSE_RATING)
            self.repo.set_meta(f"curse:{pic.id}", 0)
        elif item == "resurrect":
            self.repo.revive_pic(pic.id, now + shop.RESURRECT_IMMUNITY)
            self.repo.set_rating(pic.id, max(pic.rating, shop.RESURRECT_RATING))
            self.repo.incr_counter(user_id, "resurrections")
            if isinstance(pic.added_by, int) and pic.added_by != user_id:
                self._pending_events.setdefault(pic.added_by, []).append("necromancer")
        self.repo.incr_counter(user_id, "purchases")
        return "ok", self.repo.get_pic(pic.id)

    def refund(self, user_id: int, item: str) -> None:
        self.repo.add_coins(user_id, self.price(item), "shop_refund", self.now(), earn=False)

    def buy_title(self, user_id: int, text: str) -> str:
        """'ok' | 'broke' | 'empty'."""
        clean = " ".join(text.split())[: shop.TITLE_MAX_LENGTH]
        if not clean:
            return "empty"
        if not self.repo.spend(user_id, self.price("title"), "shop_title", self.now()):
            return "broke"
        self.repo.set_title(user_id, clean)
        self.repo.incr_counter(user_id, "purchases")
        self.repo.set_counter(user_id, "titled", 1)
        return "ok"

    # ── bounties ───────────────────────────────────────────────────────

    def put_bounty(self, user_id: int, pic_id: str, amount: int) -> tuple[str, int]:
        """('ok' | 'broke' | 'dead' | 'gone' | 'own', total bounty on the pic)."""
        pic = self.repo.get_pic(pic_id)
        if pic is None:
            return "gone", 0
        if pic.status != "alive":
            return "dead", 0
        if pic.added_by == user_id:
            return "own", self.repo.bounty_on(pic_id)
        if not self.repo.spend(user_id, amount, "bounty_put", self.now()):
            return "broke", self.repo.bounty_on(pic_id)
        total = self.repo.add_bounty(pic_id, user_id, amount, self.now())
        if total >= 500 and isinstance(pic.added_by, int):
            self._pending_events.setdefault(pic.added_by, []).append("wanted")
        return "ok", total

    def _pay_bounty(self, pic_id: str, hunters: list[int]) -> dict[int, int]:
        """Split the bounty of a dead pic among its killers. Hunting season doubles it."""
        total = self.repo.take_bounty(pic_id)
        if not total or not hunters:
            return {}
        if self.day_is("hunting_season"):
            total *= 2
        share = total // len(hunters)
        paid = {}
        for user_id in hunters:
            if share:
                self.pay(user_id, share, "bounty")
                paid[user_id] = share
                self._pending_events.setdefault(user_id, []).append("bounty_hunter")
        return paid

    # ── owning pics ────────────────────────────────────────────────────

    def own_price(self, pic_id: str) -> int:
        pic = self.repo.get_pic(pic_id)
        owned = self.repo.owner_of(pic_id)
        if pic is None:
            return 0
        if owned is not None:  # what the owner paid is already in today's money
            return max(int(owned[1] * shop.OWN_RESALE), self.scaled(shop.own_price(pic.rating, None)))
        return self.scaled(shop.own_price(pic.rating, None))

    def buy_ownership(self, user_id: int, pic_id: str) -> tuple[str, int, int | None]:
        """('ok' | 'own' | 'dead' | 'poor' | 'taken', price, previous owner). Buying out an owner
        pays them the price."""
        pic = self.repo.get_pic(pic_id)
        if pic is None or pic.status != "alive":
            return "dead", 0, None
        owned = self.repo.owner_of(pic_id)
        previous = owned[0] if owned else None
        if previous == user_id:
            return "own", 0, None
        price = self.own_price(pic_id)
        if not self.repo.spend(user_id, price, "own_buy", self.now()):
            return "poor", price, previous
        if not self.repo.set_owner(pic_id, user_id, price, self.now(), previous):
            self.repo.add_coins(user_id, price, "own_refund", self.now(), earn=False)  # someone was quicker
            return "taken", price, previous
        if previous is not None:
            self.repo.add_coins(previous, price, "own_sold", self.now(), earn=False)
        return "ok", price, previous

    def pay_pic_owner(self, pic_id: str) -> tuple[int, int] | None:
        """A counted win of an owned pic: its owner earns. (owner, coins)."""
        owned = self.repo.owner_of(pic_id)
        if owned is None:
            return None
        return owned[0], self.pay(owned[0], shop.OWN_WIN_INCOME, "own_income")

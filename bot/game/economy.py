"""Seasons and prices that follow the chat's wealth."""

import bisect
import json
from collections import defaultdict
from dataclasses import dataclass

from bot.game.progress import STARTER_BONUS
from bot.rules import boss, casino, court, days, economy, seasons, shop

STARTER_COINS = STARTER_BONUS  # a fresh season starts everyone where the v4 starter bonus did
WEALTH_CACHE_SECONDS = 60


@dataclass(frozen=True)
class SeasonReport:
    season: str
    podium: list[tuple[int, int]]  # (user, score) by place
    reset: int  # balances set back to STARTER_COINS


@dataclass(frozen=True)
class Redistribution:
    victim: int
    total: int
    shares: list[tuple[int, int]]  # (player, coins), the biggest first
    burned: int = 0  # what was over the cap: taken from the victim, given to nobody


# The great redistribution's first victim, chosen by the admin: (local date, username).
FIRST_REDISTRIBUTION = ("2026-10-28", "toyota_celica_fun")
REDISTRIBUTION_ACTIVE_DAYS = 14
# Boss loot once counted for levels in inflated coins (one October kill: 100 million XP). The
# repair runs once and keeps every changed player's old XP under this key, to undo it.
XP_REPAIR_KEY = "xp_repair:2026_11"


class EconomyMixin:
    admins: frozenset[int]
    _wealth: tuple[int, int, float] | None  # (when, typical wallet, factor)

    # ── seasons ────────────────────────────────────────────────────────

    def season(self) -> str:
        return seasons.season_of(self.now(), self.tz_offset_hours)

    def season_bounds(self, season: str | None = None) -> tuple[int, int]:
        return seasons.bounds(season or self.season(), self.tz_offset_hours)

    def season_top(self, limit: int = 10) -> list[tuple[int, int]]:
        return self.repo.season_scores(*self.season_bounds(), limit=limit)

    def season_standing(self, user_id: int) -> tuple[int, int | None]:
        return self.repo.season_standing(user_id, *self.season_bounds())

    def season_last_day(self) -> bool:
        return seasons.last_day(self.now(), self.tz_offset_hours)

    def roll_season(self) -> SeasonReport | None:
        """Once the month has changed: save the finished season's podium and reset every balance
        except the admins'. Safe to call every minute; returns a report only when it closed one."""
        current = self.season()
        last = self.repo.meta_str("season")
        if last is None:
            self.repo.set_meta("season", current)  # the first start begins the count
            return None
        if last == current:
            return None
        podium = self.repo.season_scores(*self.season_bounds(last), limit=seasons.PODIUM)
        self.repo.save_podium(last, podium)
        reset = self.repo.reset_coins(STARTER_COINS, self.admins, "season_reset", self.now())
        self.repo.set_meta("season", current)
        self._wealth = None
        return SeasonReport(last, podium, reset)

    # ── the great redistribution ───────────────────────────────────────

    def redistribute(self) -> Redistribution | None:
        """Once a day: one player's whole balance goes to everyone else who played in the last two
        weeks, in random shares. Admins are neither spared nor left out. The day's result is
        kept, so every chat announces the same one and nobody is robbed twice. None when there is
        nobody to take from or to give to."""
        key = f"redistribution:{self.local_day()}"
        if raw := self.repo.meta_str(key):
            data = json.loads(raw)
            shares = [tuple(share) for share in data["shares"]]
            return Redistribution(data["victim"], data["total"], shares, data.get("burned", 0))
        wallets = dict(self.repo.active_wallets(self.now() - REDISTRIBUTION_ACTIVE_DAYS * 86400))
        victim = self._redistribution_victim(wallets)
        recipients = [player for player in wallets if player != victim]
        if victim is None or not recipients:
            return None
        total = self.repo.player(victim)[0]
        given = min(total, economy.redistribution_cap(self.reward_factor()))
        weights = [self.rng.expovariate(1.0) for _ in recipients]  # different, sometimes very different, shares
        amounts = [int(given * weight / sum(weights)) for weight in weights]
        amounts[weights.index(max(weights))] += given - sum(amounts)  # the rounding's leftovers: to the luckiest
        shares = sorted(((player, amount) for player, amount in zip(recipients, amounts) if amount), key=lambda s: -s[1])
        burned = total - given
        # Marked first: a crash half-way must not take a second wallet today.
        self.repo.set_meta(key, json.dumps({"victim": victim, "total": total, "shares": shares, "burned": burned}))
        self.repo.add_coins(victim, -total, "redistribution", self.now(), earn=False)
        for player, amount in shares:
            self.repo.add_coins(player, amount, "redistribution_share", self.now(), earn=False)
        self._wealth = None
        return Redistribution(victim, total, shares, burned)

    def _redistribution_victim(self, wallets: dict[int, int]) -> int | None:
        day, username = FIRST_REDISTRIBUTION
        if seasons.local(self.now(), self.tz_offset_hours).date().isoformat() == day:
            chosen = self.repo.user_by_name(username)
            if chosen is not None and self.repo.player(chosen)[0] > 0:
                return chosen
        rich = sorted(player for player, coins in wallets.items() if coins > 0)
        return rich[self.rng.randrange(len(rich))] if rich else None

    # ── prices ─────────────────────────────────────────────────────────

    def _measure_wealth(self) -> tuple[int, int, float]:
        """(when, the median balance of active players, its factor), cached for a minute."""
        now = self.now()
        if self._wealth and now - self._wealth[0] < WEALTH_CACHE_SECONDS:
            return self._wealth
        median = self.repo.median_balance(now - economy.WEALTH_ACTIVE_DAYS * 86400, self.admins)
        self._wealth = (now, median, economy.wealth_factor(median))
        return self._wealth

    def wealth(self) -> float:
        """How much richer than usual the chat is (≥ 1): prices grow by this much."""
        return self._measure_wealth()[2]

    def typical_wallet(self) -> int:
        """The median balance of players active in the last two weeks, admins left out."""
        return self._measure_wealth()[1]

    def reward_factor(self) -> float:
        """How much the game's own rewards grow: like prices, but at most ×REWARD_FACTOR_CAP."""
        return economy.reward_factor(self.wealth())

    def scaled(self, amount: int) -> int:
        return economy.scaled(amount, self.wealth())

    def reward_scaled(self, amount: int) -> int:
        return economy.scaled(amount, self.reward_factor())

    # ── one-off repairs ────────────────────────────────────────────────

    def repair_boss_xp(self) -> int:
        """Once: recount the XP of every boss payout in base coins. Each payout is divided by how
        much its boss's loot had been scaled (the loot over the loot rule for its health), so a
        100-million kill counts like a normal one. Old XP is kept under XP_REPAIR_KEY. Returns
        how many players' XP changed."""
        if self.repo.meta_str(XP_REPAIR_KEY):
            return 0
        settled, factors = [], []
        for at, max_hp, loot, raid in self.repo.won_bosses():
            health = max_hp // boss.RAID_HP_FACTOR if raid else max_hp
            base = boss.loot(health) * (boss.RAID_LOOT_FACTOR if raid else 1)
            factor = loot / base if base else 1.0
            settled.append(at)
            factors.append(factor if factor > 2 else 1.0)  # ×2 is a double-loot day or a few super hits
        excess: dict[int, int] = defaultdict(int)
        for user_id, amount, at in self.repo.earned_rows("boss"):
            factor = _nearest(settled, factors, at, within=3600)
            if factor > 1:
                excess[user_id] += amount - round(amount / factor)
        old = self.repo.reduce_xp(dict(excess))
        self.repo.set_meta(XP_REPAIR_KEY, json.dumps({str(user): xp for user, xp in old.items()}))
        return len(old)

    def price(self, item: str) -> int:
        return self.scaled(
            shop.price(
                item,
                inflation=self.day_is("inflation"),
                sale=self.day_is("black_friday"),
                dead_day_price=days.DEAD_DAY_RESURRECTION if self.day_is("dead_day") else None,
            )
        )

    def wedding_price(self) -> int:
        return 0 if self.day_is("wedding_day") else self.scaled(shop.WEDDING_PRICE)

    def super_price(self) -> int:
        return self.scaled(boss.SUPER_PRICE)

    def bet_step(self) -> int:
        return self.scaled(casino.BET_STEP)

    def bet_max(self) -> int:
        return self.bet_step() * (casino.BET_MAX // casino.BET_STEP)

    def bounty_amounts(self) -> tuple[int, int]:
        small, big = shop.BOUNTY_AMOUNTS
        return self.scaled(small), self.scaled(big)

    def appeal_bail(self) -> int:
        return self.scaled(court.APPEAL_BAIL)

    def rob_cap(self) -> int:
        return self.scaled(shop.ROB_CAP)


def _nearest(times: list[int], values: list[float], at: int, within: int) -> float:
    """The value recorded closest to `at` (times sorted), or 1.0 when none is within `within` s."""
    index = bisect.bisect_left(times, at)
    best = min((i for i in (index - 1, index) if 0 <= i < len(times)), key=lambda i: abs(times[i] - at), default=None)
    return values[best] if best is not None and abs(times[best] - at) <= within else 1.0

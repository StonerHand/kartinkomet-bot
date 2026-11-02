"""Seasons and prices that follow the chat's wealth."""

import json
from dataclasses import dataclass

from bot.core import boss, casino, court, days, economy, seasons, shop
from bot.services.progress import STARTER_BONUS

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


# The great redistribution's first victim, chosen by the admin: (local date, username).
FIRST_REDISTRIBUTION = ("2026-10-28", "toyota_celica_fun")
REDISTRIBUTION_ACTIVE_DAYS = 14


class EconomyMixin:
    admins: frozenset[int]
    _wealth: tuple[int, float] | None

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
            return Redistribution(data["victim"], data["total"], [tuple(share) for share in data["shares"]])
        wallets = dict(self.repo.active_wallets(self.now() - REDISTRIBUTION_ACTIVE_DAYS * 86400))
        victim = self._redistribution_victim(wallets)
        recipients = [player for player in wallets if player != victim]
        if victim is None or not recipients:
            return None
        total = self.repo.player(victim)[0]
        weights = [self.rng.expovariate(1.0) for _ in recipients]  # different, sometimes very different, shares
        amounts = [int(total * weight / sum(weights)) for weight in weights]
        amounts[weights.index(max(weights))] += total - sum(amounts)  # the rounding's leftovers: to the luckiest
        shares = sorted(((player, amount) for player, amount in zip(recipients, amounts) if amount), key=lambda s: -s[1])
        # Marked first: a crash half-way must not take a second wallet today.
        self.repo.set_meta(key, json.dumps({"victim": victim, "total": total, "shares": shares}))
        self.repo.add_coins(victim, -total, "redistribution", self.now(), earn=False)
        for player, amount in shares:
            self.repo.add_coins(player, amount, "redistribution_share", self.now(), earn=False)
        self._wealth = None
        return Redistribution(victim, total, shares)

    def _redistribution_victim(self, wallets: dict[int, int]) -> int | None:
        day, username = FIRST_REDISTRIBUTION
        if seasons.local(self.now(), self.tz_offset_hours).date().isoformat() == day:
            chosen = self.repo.user_by_name(username)
            if chosen is not None and self.repo.player(chosen)[0] > 0:
                return chosen
        rich = sorted(player for player, coins in wallets.items() if coins > 0)
        return rich[self.rng.randrange(len(rich))] if rich else None

    # ── prices ─────────────────────────────────────────────────────────

    def wealth(self) -> float:
        """How much richer than usual the chat is (≥ 1). Cached for a minute."""
        now = self.now()
        if self._wealth and now - self._wealth[0] < WEALTH_CACHE_SECONDS:
            return self._wealth[1]
        median = self.repo.median_balance(now - economy.WEALTH_ACTIVE_DAYS * 86400, self.admins)
        factor = economy.wealth_factor(median)
        self._wealth = (now, factor)
        return factor

    def scaled(self, amount: int) -> int:
        return economy.scaled(amount, self.wealth())

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

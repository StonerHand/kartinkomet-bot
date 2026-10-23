"""Seasons and prices that follow the chat's wealth."""

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

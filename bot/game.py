"""Game service: one object composed of domain mixins (bot/services). Knows nothing about Telegram.

Every mixin works through self.repo, self.now(), self.pay() and check_achievements(); this module
keeps only the clock and the coin rules they share.
"""

import random
import time
from collections.abc import Callable

from bot.core import economy
from bot.db.repo import Repo
from bot.services.arena import ArenaMixin
from bot.services.boss import BossMixin
from bot.services.casino import CasinoMixin
from bot.services.court import CourtMixin
from bot.services.minigames import MiniGamesMixin
from bot.services.pics import PicsMixin
from bot.services.progress import STARTER_BONUS, ProgressMixin
from bot.services.shop import ShopMixin
from bot.services.social import SocialMixin
from bot.services.statuses import StatusMixin
from bot.services.types import (
    BattleReport,
    CourtReport,
    CourtStart,
    Granted,
    Note,
    ReactResult,
    StartResult,
)

__all__ = [
    "BattleReport", "CourtReport", "CourtStart", "Game", "Granted", "Note", "ReactResult", "StartResult",
]

# Rewards for taking part: the day events "double coins" and "sniper" multiply these.
ACTIVITY_REASONS = {"vote", "guess", "court_vote", "like", "upload"}


class Game(PicsMixin, ArenaMixin, CourtMixin, MiniGamesMixin, StatusMixin, ProgressMixin, CasinoMixin, ShopMixin, SocialMixin, BossMixin):

    def __init__(
        self,
        repo: Repo,
        tz_offset_hours: int = 3,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.repo = repo
        self.rng = rng or random.SystemRandom()
        self.clock = clock
        self.tz_offset_hours = tz_offset_hours
        # Event achievements earned by actions that don't announce themselves (votes):
        # delivered with the next announcement for that user.
        self._pending_events: dict[int, list[str]] = {}
        self._pending_notes: dict[int, list[Note]] = {}
        # Quests, challenges and random chests. Tests of other mechanics switch them off
        # so their coin balances stay exact.
        self.quests_enabled = True
        self.starter_bonus = STARTER_BONUS
        self._boss_hit_at: dict[tuple[str, int], float] = {}
        # Local 00:00–04:59 expressed in UTC hours, for night-upload achievements.
        self.night_hours_utc = [(hour - tz_offset_hours) % 24 for hour in range(0, 5)]

    def now(self) -> int:
        return int(self.clock())

    def local_day(self) -> int:
        return (self.now() + self.tz_offset_hours * 3600) // 86400

    def local_hour(self) -> int:
        return (self.now() + self.tz_offset_hours * 3600) % 86400 // 3600

    # ── activity & coins ───────────────────────────────────────────────

    def touch_activity(self, user_id: int) -> list[str]:
        """Daily activity streak. Returns event achievements (coming back after a week = ghost)."""
        today = self.local_day()
        last_day = self.repo.counter(user_id, "last_active_day")
        if last_day == today:
            return []
        events = ["ghost"] if last_day and today - last_day >= 7 else []
        streak = self.repo.counter(user_id, "active_streak") + 1 if last_day == today - 1 else 1
        self.repo.set_counter(user_id, "active_streak", streak)
        self.repo.raise_counter(user_id, "best_active_streak", streak)
        self.repo.set_counter(user_id, "last_active_day", today)
        return events

    def pay(self, user_id: int | None, amount: int, reason: str, earn: bool = True) -> None:
        if not isinstance(user_id, int) or not amount:
            return
        if reason in ACTIVITY_REASONS and amount > 0:
            amount *= self.activity_multiplier(reason)
        self.repo.add_coins(user_id, amount, reason, self.now(), earn=earn)

    def activity_multiplier(self, reason: str) -> int:
        event = self.day_event()
        if reason == "guess" and event == "sniper_day":
            return 3
        return 2 if event == "double_coins" else 1

    def guess_reward(self) -> int:
        return economy.GUESS * self.activity_multiplier("guess") + economy.VOTE * self.activity_multiplier("vote")

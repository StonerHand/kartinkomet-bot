"""Game: one object composed of the mechanics' mixins (bot/game/*). Knows nothing about Telegram.

Every mixin works through self.repo, self.now(), self.pay() and check_achievements(); this module
keeps only the clock and the coin rules they share.
"""

import random
import time
from collections.abc import Callable

from bot.db.repo import Repo
from bot.game.arena import ArenaMixin
from bot.game.boss import BossMixin
from bot.game.casino import CasinoMixin
from bot.game.challenges import ChallengesMixin
from bot.game.court import CourtMixin
from bot.game.economy import EconomyMixin
from bot.game.minigames import MiniGamesMixin
from bot.game.pics import PicsMixin
from bot.game.progress import STARTER_BONUS, ProgressMixin
from bot.game.quiz import QuizMixin
from bot.game.shop import ShopMixin
from bot.game.social import SocialMixin
from bot.game.statuses import StatusMixin
from bot.game.types import Note
from bot.rules import economy

# Rewards for taking part: the day events "double coins" and "sniper" multiply these.
ACTIVITY_REASONS = {"vote", "guess", "court_vote", "like", "upload"}
# Coins the game creates (not moved between players, not a share of a pool): they grow with the
# chat's wealth. The wheel's spin_* reasons too.
REWARD_REASONS = ACTIVITY_REASONS | {
    "quest", "challenge", "daily", "daily_family", "caption_win", "gold", "whose", "hl", "chest",
}


class Game(
    PicsMixin, ArenaMixin, CourtMixin, MiniGamesMixin, QuizMixin, StatusMixin, ProgressMixin, CasinoMixin, ShopMixin,
    SocialMixin, ChallengesMixin, BossMixin, EconomyMixin,
):

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
        # Admins test everything: their coins survive the season reset and don't count as chat wealth.
        self.admins: frozenset[int] = frozenset()
        self._wealth: tuple[int, float] | None = None
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

    def track(self, name: str) -> None:
        """Count a use of a mechanic for the admin's weekly stats."""
        self.repo.track(name, self.local_day())

    def usage(self, days: int = 7) -> dict[str, int]:
        today = self.local_day()
        day_start = today * 86400 - self.tz_offset_hours * 3600
        return self.repo.usage(self.now() - days * 86400, day_start, today - days + 1)

    def pay(self, user_id: int | None, amount: int, reason: str, earn: bool = True) -> int:
        """Credit coins; returns what was paid. Rewards the game creates out of thin air (votes,
        quests, the daily bonus, chests, the wheel…) grow with the chat's wealth, like prices do:
        when everyone holds a million, a vote isn't worth 4 coins. The level counts their base
        amount, so it doesn't grow with them. Shares of a pool (boss loot, bounties) come from
        money that already grew and are paid as they are."""
        if not isinstance(user_id, int) or not amount:
            return 0
        if reason in ACTIVITY_REASONS and amount > 0:
            amount *= self.activity_multiplier(reason)
        base = amount
        if reason in REWARD_REASONS or reason.startswith("spin_"):
            amount = self.reward(amount)
        self.repo.add_coins(user_id, amount, reason, self.now(), earn=earn, xp=base)
        return amount

    def reward(self, amount: int) -> int:
        """A reward in today's money: the base amount × the chat's wealth (losses too)."""
        return self.scaled(amount) if amount >= 0 else -self.scaled(-amount)

    def activity_multiplier(self, reason: str) -> int:
        event = self.day_event()
        if reason == "guess" and event == "sniper_day":
            return 3
        return 2 if event == "double_coins" else 1

    def guess_reward(self) -> int:
        """What a right guess brings, the vote included, in today's money."""
        return (self.reward(economy.GUESS * self.activity_multiplier("guess"))
                + self.reward(economy.VOTE * self.activity_multiplier("vote")))

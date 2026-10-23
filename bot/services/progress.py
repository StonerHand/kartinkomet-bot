"""Daily bonus, quests, weekly challenges, chests, the event of the day and the starter bonus."""

from dataclasses import dataclass

from bot.core import days, progress
from bot.services.types import Granted, Note

STARTER_BONUS = 1111
STARTER_KEY = "starter_v4"
# One-time gifts to everyone already playing, (key, coins): each is handed out once, at the first
# start after it is added. Players who come later don't get it.
GIFTS = (("gift_2026_10_20", 1_000_000),)


@dataclass(frozen=True)
class Daily:
    status: str  # 'ok' | 'already'
    reward: int = 0
    streak: int = 0
    chest: bool = False
    family_bonus: int = 0
    granted: list[Granted] | None = None


@dataclass(frozen=True)
class TaskState:
    kind: str
    target: int
    reward: int
    done: int

    @property
    def finished(self) -> bool:
        return self.done >= self.target


@dataclass(frozen=True)
class Opened:
    tier: str
    loot: progress.Loot
    pic: object | None  # the pic a boost/shield landed on
    granted: list[Granted]


class ProgressMixin:
    # ── calendar ───────────────────────────────────────────────────────

    def local_week(self) -> int:
        """Monday-based week number (1970-01-01 was a Thursday)."""
        return (self.local_day() + 3) // 7

    # ── starter bonus ──────────────────────────────────────────────────

    def give_starter(self, user_id: int) -> bool:
        """1111 coins once per player, for the v4 casino. Doesn't count towards levels."""
        if not self.starter_bonus or self.repo.counter(user_id, STARTER_KEY):
            return False
        self.repo.set_counter(user_id, STARTER_KEY, 1)
        self.repo.add_coins(user_id, self.starter_bonus, "starter", self.now(), earn=False)
        return True

    def give_starters(self) -> int:
        return sum(self.give_starter(user_id) for user_id in self.repo.all_user_ids())

    def give_gifts(self, gifts=GIFTS) -> int:
        """Every gift once per existing player; the per-player mark keeps a crash mid-way from
        paying anyone twice. Doesn't count towards levels. Returns how many players got one."""
        given = 0
        for key, amount in gifts:
            if self.repo.meta_str(f"gift:{key}"):
                continue
            for user_id in self.repo.all_user_ids():
                if not self.repo.counter(user_id, key):
                    self.repo.set_counter(user_id, key, 1)
                    self.repo.add_coins(user_id, amount, "gift", self.now(), earn=False)
                    given += 1
            self.repo.set_meta(f"gift:{key}", self.now())
        return given

    # ── event of the day ───────────────────────────────────────────────

    def day_event(self) -> str | None:
        if self.local_hour() < days.START_HOUR:
            return None
        return self.repo.meta_str(f"day_event:{self.local_day()}")

    def day_is(self, code: str) -> bool:
        return self.day_event() == code

    def roll_day_event(self) -> tuple[str, bool]:
        """Today's event, rolling it on first call. (code, rolled_now)."""
        today = self.local_day()
        current = self.repo.meta_str(f"day_event:{today}")
        if current:
            return current, False
        code = days.roll(self.rng, self.repo.meta_str(f"day_event:{today - 1}"))
        self.repo.set_meta(f"day_event:{today}", code)
        if code == "tax":
            taken, given = days.tax(self.repo.balances())
            for user_id, amount in taken.items():
                self.repo.add_coins(user_id, -amount, "tax", self.now(), earn=False)
            for user_id, amount in given.items():
                self.repo.add_coins(user_id, amount, "tax_share", self.now(), earn=False)
            share = next(iter(given.values()), 0)
            self.repo.set_meta(f"tax:{today}", f"{sum(taken.values())}:{share}:{len(given)}")
        # Old quest progress is useless after the day ends.
        self.repo.forget_counters("q:", f"q:{today}:")
        self.repo.forget_counters("w:", f"w:{self.local_week()}:")
        self.repo.forget_meta("pm:")  # 🛒 menus and title prompts don't outlive a day
        self.repo.forget_usage(today - 14)  # the admin's stats look one week back
        self.repo.forget_meta("title_prompt:")
        return code, True

    def tax_report(self) -> tuple[int, int, int] | None:
        raw = self.repo.meta_str(f"tax:{self.local_day()}")
        if not raw:
            return None
        total, share, people = (int(part) for part in raw.split(":"))
        return total, share, people

    # ── quests & challenges ────────────────────────────────────────────

    def progress(self, user_id: int | None, kind: str, by: int = 1) -> None:
        """Count an action towards today's quests and this week's challenges.
        Rewards are paid right away; the notes ride along with the next announcement."""
        if not isinstance(user_id, int) or by <= 0 or not self.quests_enabled:
            return
        day, week = self.local_day(), self.local_week()
        for task in progress.daily_quests(user_id, day):
            if task.kind != kind:
                continue
            before = self.repo.counter(user_id, f"q:{day}:{kind}")
            after = self.repo.incr_counter(user_id, f"q:{day}:{kind}", by)
            if before < task.target <= after:
                reward = task.reward * (2 if self.day_is("quest_mania") else 1)
                self.pay(user_id, reward, "quest")
                self._note(user_id, Note("quest", kind, reward, task.target))
                self.repo.incr_counter(user_id, "quests_done")
                if self.repo.incr_counter(user_id, f"q:{day}:done") == progress.QUESTS_PER_DAY:
                    self.pay(user_id, progress.ALL_QUESTS_BONUS, "quest")
                    self._note(user_id, Note("quests_all", progress.WOOD, progress.ALL_QUESTS_BONUS))
                    self.grant_chest(user_id, progress.WOOD, announce=False)
                self.progress(user_id, "quest")
        for task in progress.weekly_challenges(week):
            if task.kind != kind:
                continue
            before = self.repo.counter(user_id, f"w:{week}:{kind}")
            after = self.repo.incr_counter(user_id, f"w:{week}:{kind}", by)
            if before < task.target <= after:
                self.pay(user_id, task.reward, "challenge")
                self._note(user_id, Note("challenge", kind, task.reward, task.target))
                self.grant_chest(user_id, progress.RARE, announce=False)
                self.repo.incr_counter(user_id, "challenges_done")
                if self.repo.incr_counter(user_id, f"w:{week}:done") == progress.CHALLENGES_PER_WEEK:
                    self._note(user_id, Note("challenges_all", progress.LEGEND))
                    self.grant_chest(user_id, progress.LEGEND, announce=False)
                    self._pending_events.setdefault(user_id, []).append("week_perfect")

    def quests_of(self, user_id: int) -> tuple[list[TaskState], list[TaskState]]:
        day, week = self.local_day(), self.local_week()
        daily = [
            TaskState(task.kind, task.target, task.reward, self.repo.counter(user_id, f"q:{day}:{task.kind}"))
            for task in progress.daily_quests(user_id, day)
        ]
        weekly = [
            TaskState(task.kind, task.target, task.reward, self.repo.counter(user_id, f"w:{week}:{task.kind}"))
            for task in progress.weekly_challenges(week)
        ]
        return daily, weekly

    def _note(self, user_id: int, note: Note) -> None:
        self._pending_notes.setdefault(user_id, []).append(note)

    def flush(self, user_ids: list[int | None]) -> list[Granted]:
        """Announce whatever is pending for these users (quest notes, event achievements)."""
        waiting = [
            user_id for user_id in user_ids
            if isinstance(user_id, int) and (self._pending_notes.get(user_id) or self._pending_events.get(user_id))
        ]
        return self.check_achievements(waiting) if waiting else []

    # ── chests ─────────────────────────────────────────────────────────

    def grant_chest(self, user_id: int, tier: str, announce: bool = True) -> None:
        self.repo.incr_counter(user_id, f"chest_{tier}")
        if announce:
            self._note(user_id, Note("chest", tier))

    def maybe_random_chest(self, user_id: int) -> None:
        """A small chance of a wooden chest for votes and likes, at most one a day."""
        today = self.local_day()
        if not self.quests_enabled or self.repo.counter(user_id, "chest_drop_day") == today:
            return
        if self.rng.random() < progress.RANDOM_CHEST_CHANCE:
            self.repo.set_counter(user_id, "chest_drop_day", today)
            self.grant_chest(user_id, progress.WOOD)

    def chests_of(self, user_id: int) -> dict[str, int]:
        return {tier: self.repo.counter(user_id, f"chest_{tier}") for tier in progress.TIERS}

    def open_chest(self, user_id: int, tier: str) -> Opened | None:
        if tier not in progress.TIERS or not self.repo.take_counter(user_id, f"chest_{tier}"):
            return None
        loot = progress.open_chest(tier, self.rng)
        pic = None
        events: list[str] = []
        if loot.kind == "boost":
            pic = self.repo.random_alive_of(user_id)
            if pic is None:
                loot = progress.Loot("coins", 100)
            else:
                self.repo.shift_rating(pic.id, progress.CHEST_BOOST_RATING)
        elif loot.kind == "shield":
            weakest = self.repo.pics_of(user_id, limit=1, weakest=True)
            pic = weakest[0] if weakest else None
            if pic is None:
                loot = progress.Loot("coins", 300)
            else:
                until = max(self.now(), pic.immune_until or 0) + progress.CHEST_SHIELD_SECONDS
                self.repo.set_immunity(pic.id, until)
        elif loot.kind == "chest":
            self.repo.incr_counter(user_id, f"chest_{progress.WOOD}")
        elif loot.kind == "frame":
            pic = next((candidate for candidate in self.repo.pics_of(user_id, limit=5) if not candidate.frame), None)
            if pic is None:
                loot = progress.Loot("coins", 300)
            else:
                frame = sorted(progress.FRAMES)[self.rng.randrange(len(progress.FRAMES))]
                self.repo.set_frame(pic.id, frame)
                loot = progress.Loot("frame", prize=frame)
        elif loot.kind == "title":
            title = self.give_prize_title(user_id)
            loot = progress.Loot("title", prize=title) if title else progress.Loot("coins", 1000)
        elif loot.kind == "empty":
            events.append("empty_chest")
        if loot.coins:
            self.pay(user_id, loot.coins, "chest", earn=False)
        self.repo.incr_counter(user_id, "chests_opened")
        self.progress(user_id, "chest")
        return Opened(tier, loot, pic, self.check_achievements([user_id], {user_id: events}))

    # ── daily bonus ────────────────────────────────────────────────────

    def claim_daily(self, user_id: int) -> Daily:
        today = self.local_day()
        last = self.repo.counter(user_id, "daily_day")
        if last == today:
            return Daily("already", streak=self.repo.counter(user_id, "daily_streak"))
        streak = self.repo.counter(user_id, "daily_streak") + 1 if last == today - 1 else 1
        self.repo.set_counter(user_id, "daily_day", today)
        self.repo.set_counter(user_id, "daily_streak", streak)
        self.repo.raise_counter(user_id, "best_daily_streak", streak)
        reward = progress.daily_reward(streak)
        family = 0
        spouse = self.repo.spouse_of(user_id)
        if spouse and self.repo.counter(spouse[0], "daily_day") == today:
            family = int(reward * progress.MARRIED_DAILY_BONUS)
            self.pay(spouse[0], family, "daily_family")
        self.pay(user_id, reward + family, "daily")
        chest = progress.daily_chest(streak)
        if chest:
            self.grant_chest(user_id, progress.RARE, announce=False)
        self.progress(user_id, "daily")
        events = self.touch_activity(user_id)
        return Daily("ok", reward, streak, chest, family, self.check_achievements([user_id], {user_id: events}))


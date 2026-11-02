"""Random pics, reactions and uploads."""

import sqlite3

from bot.core import court, deck, economy
from bot.db.repo import Pic
from bot.services.types import Granted, ReactResult

UPLOAD_LIMIT_PER_HOUR = 1000


class PicsMixin:
    def draw_pic(self, chat_id: int) -> tuple[Pic, str] | None:
        return deck.draw_one(self.repo, f"pic:{chat_id}", self.now(), self.rng)

    def draw_for(self, chat_id: int, user_id: int | None) -> tuple[Pic, str, list[Granted]] | None:
        """A random pic requested by a person: also checks 'lucky' and 'déjà vu'."""
        drawn = self.draw_pic(chat_id)
        if drawn is None:
            return None
        pic, bucket = drawn
        events: list[str] = []
        if user_id is not None:
            if pic.added_by == user_id:
                events.append("deja_vu")
            if bucket == "legend" and self.repo.incr_counter(user_id, f"legends_day:{self.local_day()}") >= 3:
                events.append("lucky")
        self.progress(user_id, "pic")
        granted = self.check_achievements([], {user_id: events}) if events else self.flush([user_id])
        return pic, bucket, granted


    def react(self, pic_id: str, user_id: int, value: int) -> ReactResult | None:
        before = self.repo.get_pic(pic_id)
        if before is None:
            return None
        if before.status != "alive":
            return ReactResult(pic=before, changed=False, court_due=False)
        first_on_pic = self.repo.reaction_count(pic_id) == 0
        previous = self.repo.react(pic_id, user_id, value, self.now())
        changed = previous is not None
        events: list[str] = []
        if changed:
            events = self.touch_activity(user_id)
            if previous:
                self.repo.incr_counter(user_id, "reaction_switches")
            elif first_on_pic:
                self.repo.incr_counter(user_id, "first_reacts")
            # Coins only for a first-ever like: switching back and forth can't farm them.
            if previous == 0 and value == 1 and before.added_by not in (None, user_id):
                self.pay(before.added_by, economy.LIKE_RECEIVED, "like")
            if previous == 0 and value == 1:
                self.progress(user_id, "like")
            if previous == 0:
                self.maybe_random_chest(user_id)
        pic = self.repo.get_pic(pic_id)
        assert pic is not None
        threshold = 1 if self.day_is("plague") else court.DISLIKES_FOR_COURT
        court_due = (
            changed
            and court.dislikes_trigger_court(before.dislikes, pic.dislikes, threshold)
            and court.can_be_tried(pic.status, pic.immune_until, self.now())
            and self.repo.active_court_for_pic(pic_id) is None
        )
        granted = self.check_achievements([pic.added_by, user_id], {user_id: events}) if changed else []
        return ReactResult(pic=pic, changed=changed, court_due=court_due, granted=granted)


    def upload_rate_limited(self, user_id: int) -> bool:
        return self.repo.uploads_since(user_id, self.now() - 3600) >= UPLOAD_LIMIT_PER_HOUR

    def add_pic(
        self, file_id: str, file_unique_id: str, user_id: int, visual_hash: str | None
    ) -> tuple[Pic, list[Granted]] | None:
        """None if the same file slipped in concurrently (album messages run in parallel)."""
        try:
            pic = self.repo.add_pic(file_id, file_unique_id, user_id, visual_hash, self.now())
        except sqlite3.IntegrityError:
            return None
        self.pay(user_id, economy.UPLOAD, "upload")
        self.progress(user_id, "upload")
        self.repo.set_counter(user_id, "dup_streak", 0)
        return pic, self.check_achievements([user_id])

    def note_duplicate(self, user_id: int) -> None:
        streak = self.repo.incr_counter(user_id, "dup_streak")
        self.repo.raise_counter(user_id, "best_dup_streak", streak)

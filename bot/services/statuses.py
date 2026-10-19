"""Achievements, level-ups and weekly crowns."""

from bot.core import achievements, economy
from bot.services.types import Granted


class StatusMixin:
    def crown_week(self) -> dict[str, tuple[int, int]]:
        """Hand out this week's crowns (stored in meta) and return them."""
        crowns = self.repo.week_crowns(self.now() - 7 * 86400)
        self.repo.set_meta("crowns", ",".join(f"{kind}:{user_id}" for kind, (user_id, _) in crowns.items()))
        self.repo.set_meta("crowns_until", self.now() + economy.CROWN_SECONDS)
        return crowns

    def crowns_of(self, user_id: int) -> list[str]:
        """Crown kinds this user currently wears."""
        if self.repo.meta_int("crowns_until") <= self.now():
            return []
        raw = self.repo.meta_str("crowns") or ""
        return [
            kind for kind, _, holder in (item.partition(":") for item in raw.split(",") if item)
            if holder == str(user_id)
        ]

    def badges(self, user_id: int | None) -> str:
        """Crown emojis to show next to a name, e.g. ' 👑🪓'."""
        if user_id is None:
            return ""
        marks = "".join(economy.CROWNS[kind][0] for kind in self.crowns_of(user_id))
        return f" {marks}" if marks else ""


    BACKFILL_KEY = "achievements_backfilled_v4"  # bump when new metric achievements are added

    def backfill_achievements(self) -> int:
        """Silently grant everything already earned, so old progress doesn't flood the chat."""
        if self.repo.meta_str(self.BACKFILL_KEY):
            return 0
        granted = self.check_achievements(self.repo.all_user_ids())
        self.repo.set_meta(self.BACKFILL_KEY, self.now())
        return sum(len(item.codes) for item in granted)

    def check_achievements(
        self,
        user_ids: list[int | None],
        events: dict[int | None, list[str]] | None = None,
    ) -> list[Granted]:
        """Metric achievements, event achievements and level-ups for these users."""
        granted = []
        now = self.now()
        events = {uid: codes for uid, codes in (events or {}).items() if isinstance(uid, int)}
        candidates = [uid for uid in user_ids if isinstance(uid, int)] + list(events)
        for user_id in dict.fromkeys(candidates):
            owned = self.repo.achievements_of(user_id)
            stats = self.repo.user_stats(user_id, self.night_hours_utc, self.tz_offset_hours, now)
            wanted = achievements.earned(stats, owned)
            wanted += events.get(user_id, []) + self._pending_events.pop(user_id, [])
            notes = self._pending_notes.pop(user_id, [])
            fresh = [
                code
                for code in dict.fromkeys(wanted)
                if code not in owned and self.repo.grant_achievement(user_id, code, now)
            ]
            coins, earned, level_seen = self.repo.player(user_id)
            level = economy.level_for(earned)
            level_up = None
            if level.index > level_seen:
                self.repo.set_level_seen(user_id, level.index)
                level_up = level.name
            if fresh or level_up or notes:
                granted.append(Granted(user_id, fresh, level_up, notes))
        return granted

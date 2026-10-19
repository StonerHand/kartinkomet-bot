"""People's court and appeals."""

from bot.core import court, economy
from bot.db.repo import Court
from bot.services.types import CourtReport, CourtStart


class CourtMixin:
    def start_court(
        self,
        chat_id: int,
        pic_id: str,
        reason: str,
        started_by: int | None,
        title: str = "",
        pic_message_id: int | None = None,
    ) -> CourtStart:
        """Courts open on the second 🖕🏻, from the bottom, on schedule or bought in the shop."""
        pic = self.repo.get_pic(pic_id)
        if pic is None or pic.status != "alive":
            return CourtStart("gone")
        active = self.repo.active_court_for_pic(pic_id)
        if active:
            return CourtStart("active", active)
        if not court.can_be_tried(pic.status, pic.immune_until, self.now()):
            return CourtStart("immune")
        court_id = self.repo.create_court(
            chat_id,
            pic_id,
            reason,
            started_by,
            self.now(),
            court.COURT_SECONDS,
            title=title,
            pic_message_id=pic_message_id,
        )
        return CourtStart("started", self.repo.get_court(court_id))

    def cancel_court(self, court_id: str) -> None:
        self.repo.drop_court(court_id)

    def vote_court(self, court_id: str, user_id: int, vote: str) -> tuple[str, Court | None]:
        trial = self.repo.get_court(court_id)
        if trial is None:
            return "gone", None
        if trial.status != "active":
            return "closed", trial
        if self.now() >= trial.ends_at:
            return "expired", trial
        first_vote = user_id not in trial.votes
        if not self.repo.vote_court(court_id, user_id, vote):
            return "same", trial
        if first_vote:
            self.progress(user_id, "court_vote")
        pending = self._pending_events.setdefault(user_id, [])
        pending.extend(self.touch_activity(user_id))
        if 3 <= self.local_hour() < 5:
            pending.append("night_court")
        return "ok", self.repo.get_court(court_id)

    def last_word(self, chat_id: int, message_id: int, user_id: int, text: str) -> Court | None:
        """Only the uploader may speak, once, while the court is open."""
        trial = self.repo.court_by_message(chat_id, message_id)
        if trial is None or trial.status != "active" or trial.pic.added_by != user_id:
            return None
        if self.now() >= trial.ends_at:
            return None
        clean = " ".join(text.split())[: court.LAST_WORD_LIMIT]
        if not clean or not self.repo.set_last_word(trial.id, clean):
            return None
        return self.repo.get_court(trial.id)

    def finish_court(self, court_id: str) -> CourtReport | None:
        trial = self.repo.get_court(court_id)
        if trial is None or trial.status != "active":
            return None
        kill, spare = trial.vote_counts()
        amnesty = self.day_is("amnesty")
        result = "pardoned" if amnesty else court.verdict(kill, spare, appeal=trial.appeal)
        if not self.repo.close_court(court_id, result):
            return None
        now = self.now()
        owner = trial.pic.added_by
        events: dict[int, list[str]] = {}

        def grant(user_id: int | None, code: str) -> None:
            if isinstance(user_id, int):
                events.setdefault(user_id, []).append(code)

        bounty: dict[int, int] = {}
        bail_back = 0
        if result == "executed":
            self.repo.remove_pic(trial.pic.id, "executed", "court", now)
            self.repo.incr_meta("court_executions")
            if isinstance(owner, int) and self.repo.executed_since(owner, now - 86400) >= 3:
                grant(owner, "black_streak")
            bounty = self._pay_bounty(trial.pic.id, [user for user, vote in trial.votes.items() if vote == "kill"])
        else:
            self.repo.set_immunity(trial.pic.id, now + court.IMMUNITY_SECONDS)
            self.repo.incr_meta("court_pardons")
            if trial.last_word:
                grant(owner, "last_word_saved")
            if trial.appeal and trial.bail and isinstance(owner, int):
                bail_back = trial.bail
                self.repo.add_coins(owner, bail_back, "bail_back", now, earn=False)
                grant(owner, "appeal_won")
        for user_id, vote in trial.votes.items():
            self.pay(user_id, economy.COURT_VOTE, "court_vote")
            if vote == "kill" and user_id == owner:
                grant(user_id, "self_executioner")
        if spare == 1 and kill >= 2:
            grant(next(u for u, v in trial.votes.items() if v == "spare"), "devils_advocate")
        users = [owner, *trial.votes.keys()]
        return CourtReport(
            court=self.repo.get_court(court_id) or trial,
            verdict=result,
            granted=self.check_achievements(users, events),
            amnesty=amnesty,
            bounty=bounty,
            bail_back=bail_back,
        )

    def can_appeal(self, trial: Court) -> bool:
        return (
            trial.status == "executed"
            and not trial.appeal
            and self.now() <= trial.ends_at + court.APPEAL_WINDOW
            and not self.repo.meta_str(f"appealed:{trial.id}")
        )

    def appeal(self, court_id: str, user_id: int, title: str = "") -> CourtStart:
        """Second trial for an executed pic, paid by its uploader. Statuses: started, gone,
        not_owner, late, final, broke."""
        trial = self.repo.get_court(court_id)
        if trial is None or trial.status != "executed":
            return CourtStart("gone")
        if trial.appeal:
            return CourtStart("final")
        if trial.pic.added_by != user_id:
            return CourtStart("not_owner")
        if not self.can_appeal(trial) or trial.pic.status != "executed":
            return CourtStart("late")
        if not self.repo.spend(user_id, court.APPEAL_BAIL, "bail", self.now()):
            return CourtStart("broke")
        self.repo.set_meta(f"appealed:{trial.id}", self.now())
        self.repo.revive_pic(trial.pic.id, 0)
        self.repo.incr_meta("court_executions", -1)
        new_id = self.repo.create_court(
            trial.chat_id,
            trial.pic.id,
            trial.reason,
            user_id,
            self.now(),
            court.APPEAL_SECONDS,
            title=title,
            appeal=True,
            bail=court.APPEAL_BAIL,
        )
        return CourtStart("started", self.repo.get_court(new_id))

    def undo_appeal(self, court_id: str) -> None:
        """The appeal card couldn't be sent: put everything back as it was."""
        trial = self.repo.get_court(court_id)
        if trial is None:
            return
        self.repo.drop_court(court_id)
        self.repo.remove_pic(trial.pic.id, "executed", "court", self.now())
        self.repo.incr_meta("court_executions")
        if isinstance(trial.pic.added_by, int) and trial.bail:
            self.repo.add_coins(trial.pic.added_by, trial.bail, "bail_back", self.now(), earn=False)

    def pardon(self, pic_id: str) -> bool:
        revived = self.repo.revive_pic(pic_id, self.now() + court.IMMUNITY_SECONDS)
        pic = self.repo.get_pic(pic_id) if revived else None
        if pic is not None and isinstance(pic.added_by, int):
            self._pending_events.setdefault(pic.added_by, []).append("necromancer")
        return revived

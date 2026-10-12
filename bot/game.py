"""Game service: glues Repo and core rules. Knows nothing about Telegram."""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from bot.core import achievements, arena, court, deck
from bot.db.repo import Battle, Court, Pic, Repo

UPLOAD_LIMIT_PER_HOUR = 1000


@dataclass(frozen=True)
class Granted:
    user_id: int
    codes: list[str]


@dataclass(frozen=True)
class ReactResult:
    pic: Pic
    changed: bool
    court_due: bool
    granted: list[Granted] = field(default_factory=list)


@dataclass(frozen=True)
class StartResult:
    status: str  # 'started' | 'active' | 'shortage' | 'stale'
    battle: Battle | None = None


@dataclass(frozen=True)
class BattleReport:
    battle: Battle
    counted: bool
    winner: int | None
    executed: Pic | None
    rating_before: list[float]
    rating_after: list[float]
    streak: int  # winner's streak after a duel (0 for tournaments / draws without champion)
    milestone: int | None
    granted: list[Granted]


@dataclass(frozen=True)
class CourtStart:
    status: str  # 'started' | 'active' | 'immune' | 'gone'
    court: Court | None = None


@dataclass(frozen=True)
class CourtReport:
    court: Court
    verdict: str  # 'executed' | 'pardoned'
    granted: list[Granted]


class Game:
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
        # Local 00:00–04:59 expressed in UTC hours, for night-upload achievements.
        self.night_hours_utc = [(hour - tz_offset_hours) % 24 for hour in range(0, 5)]

    def now(self) -> int:
        return int(self.clock())

    # ── random ─────────────────────────────────────────────────────────

    def draw_pic(self, chat_id: int) -> tuple[Pic, str] | None:
        return deck.draw_one(self.repo, f"pic:{chat_id}", self.now(), self.rng)

    # ── reactions ──────────────────────────────────────────────────────

    def react(self, pic_id: str, user_id: int, value: int) -> ReactResult | None:
        before = self.repo.get_pic(pic_id)
        if before is None:
            return None
        if before.status != "alive":
            return ReactResult(pic=before, changed=False, court_due=False)
        changed = self.repo.react(pic_id, user_id, value, self.now())
        pic = self.repo.get_pic(pic_id)
        assert pic is not None
        court_due = (
            changed
            and court.dislikes_trigger_court(before.dislikes, pic.dislikes)
            and court.can_be_tried(pic.status, pic.immune_until, self.now())
            and self.repo.active_court_for_pic(pic_id) is None
        )
        granted = self.check_achievements([pic.added_by]) if changed else []
        return ReactResult(pic=pic, changed=changed, court_due=court_due, granted=granted)

    # ── battles ────────────────────────────────────────────────────────

    def start_duel(
        self, chat_id: int, champion_of: str | None = None, title: str = ""
    ) -> StartResult:
        active = self.repo.active_battle(chat_id, "duel")
        if active:
            return StartResult("active", active)

        now = self.now()
        scope = f"arena:{chat_id}"
        streak = 0
        exclude: list[str] = []
        champion: Pic | None = None
        if champion_of is not None:
            previous = self.repo.get_battle(champion_of)
            latest = self.repo.meta_str(f"last_duel:{chat_id}")
            if (
                previous is None
                or previous.winner_slot is None
                or latest != previous.id
                or previous.chat_id != chat_id
            ):
                return StartResult("stale")
            champion = previous.pics[previous.winner_slot]
            champion = self.repo.get_pic(champion.id)
            if champion is None or champion.status != "alive":
                return StartResult("stale")
            streak = previous.result_streak or 0
            exclude = [champion.id]

        needed = 1 if champion else 2
        drawn = deck.draw_many(self.repo, scope, now, needed, exclude=exclude)
        if not drawn:
            return StartResult("shortage")
        pic_ids = ([champion.id] if champion else []) + [pic.id for pic, _ in drawn]
        battle_id = self.repo.create_battle(
            "duel", chat_id, pic_ids, now, arena.DUEL_SECONDS, streak=streak, title=title
        )
        return StartResult("started", self.repo.get_battle(battle_id))

    def start_tournament(self, chat_id: int, title: str = "") -> StartResult:
        active = self.repo.active_battle(chat_id, "tournament")
        if active:
            return StartResult("active", active)
        now = self.now()
        drawn = deck.draw_many(self.repo, f"arena:{chat_id}", now, arena.TOURNAMENT_SIZE)
        if not drawn:
            return StartResult("shortage")
        battle_id = self.repo.create_battle(
            "tournament",
            chat_id,
            [pic.id for pic, _ in drawn],
            now,
            arena.TOURNAMENT_SECONDS,
            title=title,
        )
        return StartResult("started", self.repo.get_battle(battle_id))

    def cancel_battle(self, battle_id: str) -> None:
        self.repo.drop_battle(battle_id)

    def vote_battle(self, battle_id: str, user_id: int, slot: int) -> tuple[str, Battle | None]:
        battle = self.repo.get_battle(battle_id)
        if battle is None:
            return "gone", None
        if battle.status != "active":
            return "closed", battle
        if self.now() >= battle.ends_at:
            return "expired", battle
        if not 0 <= slot < len(battle.pics):
            return "gone", battle
        if not self.repo.vote_battle(battle_id, user_id, slot):
            return "same", battle
        return "ok", self.repo.get_battle(battle_id)

    def finish_battle(self, battle_id: str) -> BattleReport | None:
        if not self.repo.close_battle(battle_id):
            return None
        battle = self.repo.get_battle(battle_id)
        assert battle is not None
        fighters = [
            arena.Fighter(pic.id, pic.rating, pic.games, pic.loss_streak) for pic in battle.pics
        ]
        votes = battle.vote_counts()
        before = [pic.rating for pic in battle.pics]
        now = self.now()

        if battle.kind == "duel":
            outcome = arena.resolve_duel(fighters, votes, battle.streak)
            winner = outcome.winner
            after = list(outcome.ratings)
            outcomes = list(outcome.outcomes)
            counted = outcome.counted
            streak = outcome.streak if winner is not None else battle.streak
            executed_slot = outcome.executed
            self.repo.set_meta(f"last_duel:{battle.chat_id}", battle.id)
            # A champion that drew keeps its streak; otherwise only a winner carries one.
            result_slot = winner if winner is not None else (0 if battle.streak > 0 else None)
            self.repo.set_battle_result(battle_id, result_slot, streak if result_slot is not None else None)
        else:
            outcome_t = arena.resolve_tournament(fighters, votes)
            winner = outcome_t.winner
            after = outcome_t.ratings
            outcomes = outcome_t.outcomes
            counted = outcome_t.counted
            streak = 0
            executed_slot = None
            self.repo.set_battle_result(battle_id, winner, None)

        if counted:
            for slot, pic in enumerate(battle.pics):
                pic_streak = streak if (battle.kind == "duel" and slot == winner) else None
                self.repo.apply_battle_result(pic.id, after[slot], outcomes[slot], pic_streak)
            if battle.kind == "duel" and winner is not None:
                record = self.repo.meta_int(f"streak_record:{battle.chat_id}")
                if streak > record:
                    self.repo.set_meta(f"streak_record:{battle.chat_id}", streak)
            self.repo.incr_meta(f"{battle.kind}s_total")

        executed = None
        if executed_slot is not None:
            loser = battle.pics[executed_slot]
            if self.repo.remove_pic(loser.id, "executed", "duel", now):
                executed = self.repo.get_pic(loser.id)
                self.repo.incr_meta("duel_executions")

        milestone = (
            arena.streak_milestone(streak)
            if battle.kind == "duel" and winner is not None and counted
            else None
        )
        owners = [pic.added_by for pic in battle.pics] if counted else []
        return BattleReport(
            battle=self.repo.get_battle(battle_id) or battle,
            counted=counted,
            winner=winner,
            executed=executed,
            rating_before=before,
            rating_after=after,
            streak=streak if battle.kind == "duel" else 0,
            milestone=milestone,
            granted=self.check_achievements(owners),
        )

    # ── courts ─────────────────────────────────────────────────────────

    def start_court(
        self,
        chat_id: int,
        pic_id: str,
        reason: str,
        started_by: int | None,
        title: str = "",
        pic_message_id: int | None = None,
    ) -> CourtStart:
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
        if not self.repo.vote_court(court_id, user_id, vote):
            return "same", trial
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
        result = court.verdict(kill, spare)
        if not self.repo.close_court(court_id, result):
            return None
        now = self.now()
        if result == "executed":
            self.repo.remove_pic(trial.pic.id, "executed", "court", now)
            self.repo.incr_meta("court_executions")
        else:
            self.repo.set_immunity(trial.pic.id, now + court.IMMUNITY_SECONDS)
            self.repo.incr_meta("court_pardons")
        users = [trial.pic.added_by, *trial.votes.keys()]
        return CourtReport(
            court=self.repo.get_court(court_id) or trial,
            verdict=result,
            granted=self.check_achievements(users),
        )

    def pardon(self, pic_id: str) -> bool:
        return self.repo.revive_pic(pic_id, self.now() + court.IMMUNITY_SECONDS)

    # ── uploads ────────────────────────────────────────────────────────

    def upload_rate_limited(self, user_id: int) -> bool:
        return self.repo.uploads_since(user_id, self.now() - 3600) >= UPLOAD_LIMIT_PER_HOUR

    def add_pic(
        self, file_id: str, file_unique_id: str, user_id: int, visual_hash: str | None
    ) -> tuple[Pic, list[Granted]]:
        pic = self.repo.add_pic(file_id, file_unique_id, user_id, visual_hash, self.now())
        return pic, self.check_achievements([user_id])

    # ── achievements ───────────────────────────────────────────────────

    def backfill_achievements(self) -> int:
        """Silently grant everything already earned (first start after migration)."""
        if self.repo.meta_str("achievements_backfilled"):
            return 0
        granted = self.check_achievements(self.repo.all_user_ids())
        self.repo.set_meta("achievements_backfilled", self.now())
        return sum(len(item.codes) for item in granted)

    def check_achievements(self, user_ids: list[int | None]) -> list[Granted]:
        granted = []
        now = self.now()
        for user_id in dict.fromkeys(uid for uid in user_ids if isinstance(uid, int)):
            stats = self.repo.user_stats(user_id, self.night_hours_utc)
            fresh = [
                code
                for code in achievements.earned(stats, self.repo.achievements_of(user_id))
                if self.repo.grant_achievement(user_id, code, now)
            ]
            if fresh:
                granted.append(Granted(user_id, fresh))
        return granted

"""Game service: glues Repo and core rules. Knows nothing about Telegram."""

import random
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from bot.core import achievements, arena, court, days, deck, economy, games, shop
from bot.db.repo import Battle, Court, Pic, Repo
from bot.services.boss import BossMixin
from bot.services.casino import CasinoMixin
from bot.services.progress import STARTER_BONUS, ProgressMixin
from bot.services.shop import ShopMixin
from bot.services.social import SocialMixin
from bot.services.types import Granted, Note

__all__ = ["Game", "Granted", "Note"]

UPLOAD_LIMIT_PER_HOUR = 1000
# Rewards for taking part: the day events "double coins" and "sniper" multiply these.
ACTIVITY_REASONS = {"vote", "guess", "court_vote", "like", "upload"}


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
    guessers: list[int] = field(default_factory=list)  # voters who picked the winner
    guess_reward: int = 0
    flipped: bool = False  # "upside down" day: the pic with fewer votes won
    bets: dict[int, tuple[int, int]] = field(default_factory=dict)  # user → (staked, paid back)
    bets_burned: int = 0
    bounty: dict[int, int] = field(default_factory=dict)  # hunter → coins
    evolved: list[tuple[int, int, int]] = field(default_factory=list)  # (slot, old stage, new stage)
    challenge: dict | None = None
    champion: int | None = None  # the player who won a challenge
    death_rating: float = arena.DEATH_RATING  # 1000 on a blood-moon day


@dataclass(frozen=True)
class CourtStart:
    status: str  # 'started' | 'active' | 'immune' | 'gone'
    court: Court | None = None


@dataclass(frozen=True)
class CourtReport:
    court: Court
    verdict: str  # 'executed' | 'pardoned'
    granted: list[Granted]
    amnesty: bool = False
    bounty: dict[int, int] = field(default_factory=dict)
    bail_back: int = 0  # bail returned after a won appeal


class Game(ProgressMixin, CasinoMixin, ShopMixin, SocialMixin, BossMixin):
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

    # ── random ─────────────────────────────────────────────────────────

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

    # ── reactions ──────────────────────────────────────────────────────

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
        if battle.mode == "challenge":
            challenge = self.repo.challenge_for_battle(battle_id)
            if challenge and user_id in (challenge["from_user"], challenge["to_user"]):
                return "fighter", battle
        first_vote = user_id not in battle.votes
        if not self.repo.vote_battle(battle_id, user_id, slot):
            return "same", battle
        self._pending_events.setdefault(user_id, []).extend(self.touch_activity(user_id))
        if first_vote:
            self.progress(user_id, "vote")
            self.maybe_random_chest(user_id)
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
        stages_before = [shop.stage(pic.wins).index for pic in battle.pics]
        now = self.now()
        challenge_mode = battle.mode == "challenge"
        # "Upside down" day: the pic with fewer votes wins a regular duel.
        flipped = battle.kind == "duel" and not challenge_mode and self.day_is("upside_down") and sum(votes) > 0
        decisive = list(reversed(votes)) if flipped else votes

        if battle.kind == "duel":
            death = days.BLOOD_MOON_DEATH_RATING if self.day_is("blood_moon") else arena.DEATH_RATING
            outcome = arena.resolve_duel(
                fighters, decisive, battle.streak, death_rating=death, deadly=not challenge_mode
            )
            winner = outcome.winner
            after = list(outcome.ratings)
            outcomes = list(outcome.outcomes)
            counted = outcome.counted
            streak = outcome.streak if winner is not None else battle.streak
            executed_slot = outcome.executed
            if challenge_mode:
                streak = 0
                self.repo.set_battle_result(battle_id, winner, None)
            else:
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
                pic_streak = streak if (battle.kind == "duel" and slot == winner and not challenge_mode) else None
                self.repo.apply_battle_result(pic.id, after[slot], outcomes[slot], pic_streak)
            if battle.kind == "duel" and winner is not None and not challenge_mode:
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
            if battle.kind == "duel" and winner is not None and counted and not challenge_mode
            else None
        )
        guessers, events = self._settle_battle_votes(battle, votes, winner, executed, before, counted)
        bets, burned = self._settle_bets(battle, winner, counted)
        bounty = self._pay_bounty(executed.id, guessers) if executed is not None else {}
        challenge, champion = self._settle_challenge(battle, winner, counted) if challenge_mode else (None, None)

        evolved = []
        if counted:
            for slot, pic in enumerate(battle.pics):
                fresh = self.repo.get_pic(pic.id)
                if fresh is None:
                    continue
                stage = shop.stage(fresh.wins).index
                if stage > stages_before[slot]:
                    evolved.append((slot, stages_before[slot], stage))
                    if isinstance(pic.added_by, int):
                        if stage >= 2:
                            events.setdefault(pic.added_by, []).append("breeder")
                        if stage >= 3:
                            events.setdefault(pic.added_by, []).append("dragon")

        owners = [pic.added_by for pic in battle.pics] if counted else []
        players = [challenge["from_user"], challenge["to_user"]] if challenge else []
        return BattleReport(
            battle=self.repo.get_battle(battle_id) or battle,
            counted=counted,
            winner=winner,
            executed=executed,
            rating_before=before,
            rating_after=after,
            streak=streak if battle.kind == "duel" else 0,
            milestone=milestone,
            granted=self.check_achievements(owners + list(battle.votes) + list(battle.bets) + players, events),
            guessers=guessers,
            guess_reward=self.guess_reward(),
            flipped=flipped,
            bets=bets,
            bets_burned=burned,
            bounty=bounty,
            evolved=evolved,
            challenge=challenge,
            champion=champion,
            death_rating=days.BLOOD_MOON_DEATH_RATING if self.day_is("blood_moon") else arena.DEATH_RATING,
        )

    def _settle_battle_votes(
        self,
        battle: Battle,
        votes: list[int],
        winner: int | None,
        executed: Pic | None,
        before: list[float],
        counted: bool,
    ) -> tuple[list[int], dict[int, list[str]]]:
        """Coins and guess streaks for voters, plus arena event achievements."""
        events: dict[int, list[str]] = {}

        def grant(user_id: int | None, code: str) -> None:
            if isinstance(user_id, int):
                events.setdefault(user_id, []).append(code)

        guessers = []
        for user_id, slot in battle.votes.items():
            self.pay(user_id, economy.VOTE, "vote")
            if winner is None:
                continue
            if slot == winner:
                guessers.append(user_id)
                self.pay(user_id, economy.GUESS, "guess")
                self.progress(user_id, "guess")
                self.repo.incr_counter(user_id, "right_guesses")
                streak = self.repo.incr_counter(user_id, "guess_streak")
                self.repo.raise_counter(user_id, "best_guess_streak", streak)
            else:
                self.repo.set_counter(user_id, "guess_streak", 0)
                self.repo.incr_counter(user_id, "wrong_guesses")
        if not counted:
            return guessers, events

        total = sum(votes)
        if winner is None:
            if max(votes) >= 5:
                for user_id in battle.votes:
                    grant(user_id, "draw_of_century")
            return guessers, events

        winner_pic = battle.pics[winner]
        if total == 1:
            grant(guessers[0] if guessers else None, "lone_warrior")
        if battle.kind != "duel" or battle.mode == "challenge":
            return guessers, events

        loser = 1 - winner
        loser_pic = battle.pics[loser]
        if executed is not None and votes[winner] - votes[loser] == 1:
            for user_id in guessers:
                grant(user_id, "ice_heart")
        if self.repo.lost_before(winner_pic.id, loser_pic.id, battle.id):
            grant(winner_pic.added_by, "revenge")
        if before[winner] < 950 and before[loser] >= 1050:
            grant(winner_pic.added_by, "underdog")
        if winner == 1 and battle.streak >= 3:
            grant(winner_pic.added_by, "regicide")
        potd = self.repo.meta_str(f"potd_day:{winner_pic.id}")
        if potd and int(potd) == self.local_day():
            grant(winner_pic.added_by, "jackpot")
        return guessers, events

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

    # ── uploads ────────────────────────────────────────────────────────

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

    # ── caption contest ────────────────────────────────────────────────

    def start_caption(self, chat_id: int) -> tuple[str, dict | None]:
        """'started' | 'active' | 'shortage'."""
        active = self.repo.active_game(chat_id, "caption")
        if active:
            return "active", active
        drawn = deck.draw_many(self.repo, f"pic:{chat_id}", self.now(), 1)
        if not drawn:
            return "shortage", None
        game_id = self.repo.create_game(
            "caption", chat_id, drawn[0][0].id, self.now(), games.CAPTION_COLLECT_SECONDS
        )
        return "started", self.repo.get_game(game_id)

    def caption_entry(self, chat_id: int, message_id: int, user_id: int, text: str) -> dict | None:
        game = self.repo.game_by_message(chat_id, message_id)
        if game is None or game["phase"] != "collect" or self.now() >= game["phase_ends_at"]:
            return None
        authors = {entry["user_id"] for entry in game["entries"]}
        if user_id not in authors and len(authors) >= games.CAPTION_MAX_ENTRIES:
            return None
        clean = " ".join(text.split())[: games.CAPTION_MAX_LENGTH]
        if not clean:
            return None
        if user_id not in authors:
            self.progress(user_id, "caption")
        self.repo.put_game_entry(game["id"], user_id, clean, self.now())
        self._pending_events.setdefault(user_id, []).extend(self.touch_activity(user_id))
        return self.repo.get_game(game["id"])

    def caption_vote(self, game_id: str, user_id: int, slot: int) -> str:
        """'ok' | 'same' | 'own' | 'closed' | 'gone'."""
        game = self.repo.get_game(game_id)
        if game is None or not 0 <= slot < len(game["entries"]):
            return "gone"
        if game["phase"] != "vote" or self.now() >= game["phase_ends_at"]:
            return "closed"
        author = game["entries"][slot]["user_id"]
        if author == user_id:
            return "own"
        return "ok" if self.repo.put_game_vote(game_id, user_id, author) else "same"

    def advance_caption(self, game_id: str) -> tuple[str, dict | None, list[Granted]]:
        """Move a contest whose phase timer ran out: collect → vote (or cancel), vote → done.
        Returns ('vote' | 'cancelled' | 'done' | 'noop', game, granted)."""
        game = self.repo.get_game(game_id)
        if game is None or game["phase"] == "done":
            return "noop", game, []
        if game["phase"] == "collect":
            if len(game["entries"]) < 2:
                if self.repo.set_game_phase(game_id, "done", self.now(), "collect"):
                    return "cancelled", self.repo.get_game(game_id), []
                return "noop", game, []
            if self.repo.set_game_phase(game_id, "vote", self.now() + games.CAPTION_VOTE_SECONDS, "collect"):
                return "vote", self.repo.get_game(game_id), []
            return "noop", game, []
        if not self.repo.set_game_phase(game_id, "done", self.now(), "vote"):
            return "noop", game, []
        game = self.repo.get_game(game_id)
        winner = games.caption_winner(game["entries"], game["votes"])
        game["winner"] = winner
        users = [entry["user_id"] for entry in game["entries"]] + list(game["votes"])
        if winner is not None:
            self.pay(winner, economy.CAPTION_WIN, "caption_win")
            self.repo.incr_counter(winner, "caption_wins")
        for voter in game["votes"]:
            self.pay(voter, economy.VOTE, "vote")
        return "done", game, self.check_achievements(users)

    # ── golden pic ─────────────────────────────────────────────────────

    def roll_gold(self, chat_id: int) -> bool:
        rush = self.day_is("gold_rush")
        chance = games.GOLD_CHANCE * (days.GOLD_RUSH_CHANCE_FACTOR if rush else 1)
        cooldown = days.GOLD_RUSH_COOLDOWN if rush else games.GOLD_COOLDOWN_SECONDS
        if self.rng.random() >= chance:
            return False
        return self.now() - self.repo.last_gold_at(chat_id) >= cooldown

    def claim_gold(self, token: str, user_id: int) -> tuple[bool, list[Granted]]:
        if not self.repo.claim_gold(token, user_id):
            return False, []
        self.pay(user_id, economy.GOLD, "gold")
        self.repo.incr_counter(user_id, "gold_claims")
        return True, self.check_achievements([user_id])

    # ── wheel of fortune & horoscope ───────────────────────────────────

    def free_spin_available(self, user_id: int) -> bool:
        return self.repo.counter(user_id, "spin_day") != self.local_day()

    def take_free_spin(self, user_id: int) -> bool:
        if not self.free_spin_available(user_id):
            return False
        self.repo.set_counter(user_id, "spin_day", self.local_day())
        return True

    def give_back_free_spin(self, user_id: int) -> None:
        self.repo.set_counter(user_id, "spin_day", 0)

    def resolve_spin(self, user_id: int, dice_value: int) -> tuple[games.Spin, Pic | None, list[Granted]]:
        """The free daily wheel: coins, a curse or a blessing for one of your pics, or a legend."""
        spin = games.spin_outcome(dice_value, self.rng)
        pic = None
        if spin.coins:
            self.pay(user_id, spin.coins, f"spin_{spin.kind}", earn=False)
        if spin.kind in ("curse", "bless"):
            pic = self.repo.random_alive_of(user_id)
            if pic is not None:
                if spin.kind == "curse":
                    self.curse(pic)
                else:
                    self.repo.shift_rating(pic.id, games.BLESS_RATING)
        elif spin.kind == "legend":
            legends = self.repo.top_rated(20)
            pic = legends[self.rng.randrange(len(legends))] if legends else None
        self.repo.incr_counter(user_id, "spins")
        return spin, pic, self.check_achievements([user_id])

    def horoscope(self, user_id: int) -> tuple[Pic | None, bool, list[Granted]]:
        """(pic, already_today, granted). One reading per person per day."""
        if self.repo.counter(user_id, "horoscope_day") == self.local_day():
            return None, True, []
        pics = self.repo.random_alive(1)
        if not pics:
            return None, False, []
        self.repo.set_counter(user_id, "horoscope_day", self.local_day())
        self.repo.incr_counter(user_id, "horoscopes")
        self.progress(user_id, "horoscope")
        return pics[0], False, self.check_achievements([user_id])

    # ── weekly crowns ──────────────────────────────────────────────────

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

    # ── achievements ───────────────────────────────────────────────────

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

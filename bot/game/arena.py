"""Duels, tournaments and player challenges: start, vote, settle."""

from dataclasses import dataclass

from bot.core import arena, days, deck, economy, shop
from bot.db.repo import Battle, Pic
from bot.services.types import BattleReport, StartResult


@dataclass(frozen=True)
class BattleOutcome:
    winner: int | None
    after: list[float]  # ratings after the battle, by slot
    outcomes: list
    counted: bool  # anyone voted
    streak: int  # the duel champion's streak after it
    executed_slot: int | None


class ArenaMixin:
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
        """Settle a battle once: the outcome, ratings, a death, then votes, bets, bounty, a
        challenge's pot and evolutions. None if it was already settled."""
        if not self.repo.close_battle(battle_id):
            return None
        battle = self.repo.get_battle(battle_id)
        assert battle is not None
        votes = battle.vote_counts()
        before = [pic.rating for pic in battle.pics]
        stages_before = [shop.stage(pic.wins).index for pic in battle.pics]
        challenge_mode = battle.mode == "challenge"
        # "Upside down" day: the pic with fewer votes wins a regular duel.
        flipped = battle.kind == "duel" and not challenge_mode and self.day_is("upside_down") and sum(votes) > 0
        death_rating = days.BLOOD_MOON_DEATH_RATING if self.day_is("blood_moon") else arena.DEATH_RATING
        result = self._resolve_battle(battle, list(reversed(votes)) if flipped else votes, death_rating)
        if result.counted:
            self._apply_battle_ratings(battle, result)
        executed = self._execute_loser(battle, result.executed_slot)

        winner, counted, streak = result.winner, result.counted, result.streak
        milestone = (
            arena.streak_milestone(streak)
            if battle.kind == "duel" and winner is not None and counted and not challenge_mode
            else None
        )
        guessers, events = self._settle_battle_votes(battle, votes, winner, executed, before, counted)
        bets, burned = self._settle_bets(battle, winner, counted)
        bounty = self._pay_bounty(executed.id, guessers) if executed is not None else {}
        challenge, champion = self._settle_challenge(battle, winner, counted) if challenge_mode else (None, None)
        evolved = self._evolutions(battle, stages_before, events) if counted else []

        owners = [pic.added_by for pic in battle.pics] if counted else []
        players = [challenge["from_user"], challenge["to_user"]] if challenge else []
        return BattleReport(
            battle=self.repo.get_battle(battle_id) or battle,
            counted=counted,
            winner=winner,
            executed=executed,
            rating_before=before,
            rating_after=result.after,
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
            death_rating=death_rating,
        )

    def _resolve_battle(self, battle: Battle, decisive: list[int], death_rating: float) -> BattleOutcome:
        """Who won, the new ratings and who dies; records the battle's result and the duel streak."""
        fighters = [arena.Fighter(pic.id, pic.rating, pic.games, pic.loss_streak) for pic in battle.pics]
        challenge_mode = battle.mode == "challenge"
        if battle.kind != "duel":
            outcome = arena.resolve_tournament(fighters, decisive)
            self.repo.set_battle_result(battle.id, outcome.winner, None)
            return BattleOutcome(outcome.winner, list(outcome.ratings), list(outcome.outcomes), outcome.counted, 0, None)
        outcome = arena.resolve_duel(
            fighters, decisive, battle.streak, death_rating=death_rating, deadly=not challenge_mode
        )
        winner = outcome.winner
        streak = outcome.streak if winner is not None else battle.streak
        if challenge_mode:
            streak = 0
            self.repo.set_battle_result(battle.id, winner, None)
        else:
            self.repo.set_meta(f"last_duel:{battle.chat_id}", battle.id)
            # A champion that drew keeps its streak; otherwise only a winner carries one.
            result_slot = winner if winner is not None else (0 if battle.streak > 0 else None)
            self.repo.set_battle_result(battle.id, result_slot, streak if result_slot is not None else None)
        return BattleOutcome(winner, list(outcome.ratings), list(outcome.outcomes), outcome.counted, streak, outcome.executed)

    def _apply_battle_ratings(self, battle: Battle, result: BattleOutcome) -> None:
        challenge_mode = battle.mode == "challenge"
        for slot, pic in enumerate(battle.pics):
            pic_streak = result.streak if (battle.kind == "duel" and slot == result.winner and not challenge_mode) else None
            self.repo.apply_battle_result(pic.id, result.after[slot], result.outcomes[slot], pic_streak)
        if battle.kind == "duel" and result.winner is not None and not challenge_mode:
            record = self.repo.meta_int(f"streak_record:{battle.chat_id}")
            if result.streak > record:
                self.repo.set_meta(f"streak_record:{battle.chat_id}", result.streak)
        self.repo.incr_meta(f"{battle.kind}s_total")

    def _execute_loser(self, battle: Battle, slot: int | None) -> Pic | None:
        if slot is None:
            return None
        loser = battle.pics[slot]
        if not self.repo.remove_pic(loser.id, "executed", "duel", self.now()):
            return None
        self.repo.incr_meta("duel_executions")
        return self.repo.get_pic(loser.id)

    def _evolutions(self, battle: Battle, stages_before: list[int], events: dict[int, list[str]]) -> list:
        """(slot, old stage, new stage) for every pic that grew; their owners earn the breeder
        and dragon events."""
        evolved = []
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
        return evolved

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

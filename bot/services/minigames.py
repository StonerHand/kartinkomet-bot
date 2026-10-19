"""Caption contest, golden pic, the free wheel and horoscope."""

from bot.core import days, deck, economy, games
from bot.db.repo import Pic
from bot.services.types import Granted


class MiniGamesMixin:
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

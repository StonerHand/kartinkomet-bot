"""Caption contest, golden pic, the free wheel and horoscope."""

from dataclasses import dataclass, replace

from bot.core import days, deck, economy, games, shop
from bot.db.repo import Pic
from bot.services.types import Granted


@dataclass(frozen=True)
class HigherLower:
    token: str  # answers must carry it: a press on an older round is ignored
    first: Pic
    second: Pic
    streak: int
    record: int


@dataclass(frozen=True)
class HLAnswer:
    status: str  # right | wrong | stale
    first: Pic | None = None
    second: Pic | None = None
    streak: int = 0  # after this answer (the final one when wrong)
    record_before: int = 0
    paid: int = 0


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
        """The free daily wheel: coins, a curse or a blessing for one of your pics, a legend,
        a wooden chest or (rarely) a title. Someone who already has a title gets a chest instead."""
        spin = games.spin_outcome(dice_value, self.rng)
        if spin.kind == "title":
            prize = self.give_prize_title(user_id)
            spin = replace(spin, prize=prize) if prize else replace(spin, kind="chest")
        if spin.kind == "chest":
            self.grant_chest(user_id, "wood", announce=False)
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
        self.track("spin")
        return spin, pic, self.check_achievements([user_id])

    def give_prize_title(self, user_id: int) -> str | None:
        """A rare title for someone without one. None if they already have a title."""
        if self.repo.title_of(user_id):
            return None
        title = shop.PRIZE_TITLES[self.rng.randrange(len(shop.PRIZE_TITLES))]
        self.repo.set_title(user_id, title)
        return title

    def horoscope(self, user_id: int) -> tuple[Pic | None, bool, list[Granted]]:
        """(pic, already_today, granted). One reading per person per day."""
        if self.repo.counter(user_id, "horoscope_day") == self.local_day():
            return None, True, []
        pics = self.repo.random_alive(1)
        if not pics:
            return None, False, []
        self.repo.set_counter(user_id, "horoscope_day", self.local_day())
        self.track("horoscope")
        self.repo.incr_counter(user_id, "horoscopes")
        self.progress(user_id, "horoscope")
        return pics[0], False, self.check_achievements([user_id])

    # ── whose pic? ─────────────────────────────────────────────────────

    def start_whose(self, chat_id: int) -> tuple[str, dict | None]:
        """'started' | 'active' | 'cooldown' | 'shortage'. The game carries `options`: the
        uploaders to choose from, the right one among them."""
        active = self.repo.active_game(chat_id, "whose")
        if active:
            return "active", self.with_options(active)
        if self.now() - self.repo.meta_int(f"whose_at:{chat_id}") < games.WHOSE_COOLDOWN_SECONDS:
            return "cooldown", None
        uploaders = self.repo.uploaders()
        if len(uploaders) < 2:
            return "shortage", None
        author = uploaders[self.rng.randrange(len(uploaders))]
        pic = self.repo.random_alive_of(author)
        if pic is None:
            return "shortage", None
        others = [user for user in uploaders if user != author]
        options = [author, *self.rng.sample(others, min(games.WHOSE_OPTIONS - 1, len(others)))]
        self.rng.shuffle(options)
        game_id = self.repo.create_game("whose", chat_id, pic.id, self.now(), games.WHOSE_SECONDS)
        self.repo.set_game_phase(game_id, "vote", self.now() + games.WHOSE_SECONDS, "collect")
        self.repo.set_meta(f"whose:{game_id}", ",".join(str(user) for user in options))
        self.repo.set_meta(f"whose_at:{chat_id}", self.now())
        return "started", self.with_options(self.repo.get_game(game_id))

    def with_options(self, game: dict) -> dict:
        raw = self.repo.meta_str(f"whose:{game['id']}") or ""
        game["options"] = [int(part) for part in raw.split(",") if part]
        return game

    def guess_whose(self, game_id: str, user_id: int, option: int) -> str:
        """'ok' | 'same' | 'own' | 'closed' | 'gone'. One answer per person, no changing it."""
        game = self.repo.get_game(game_id)
        if game is None or game["kind"] != "whose":
            return "gone"
        options = self.with_options(game)["options"]
        if not 0 <= option < len(options):
            return "gone"
        if game["phase"] != "vote" or self.now() >= game["phase_ends_at"]:
            return "closed"
        pic = self.repo.get_pic(game["pic_id"])
        if pic is not None and pic.added_by == user_id:
            return "own"
        if user_id in game["votes"]:
            return "same"
        self.repo.put_game_vote(game_id, user_id, options[option])
        return "ok"

    def finish_whose(self, game_id: str) -> tuple[dict | None, list[int], list[Granted]]:
        """Close the round: (game, players who guessed right, granted). Only the first call
        settles; later ones get (None, [], [])."""
        if not self.repo.set_game_phase(game_id, "done", self.now(), "vote"):
            return None, [], []
        game = self.with_options(self.repo.get_game(game_id))
        self.repo.forget_meta(f"whose:{game_id}")  # the options are on the game dict now
        pic = self.repo.get_pic(game["pic_id"])
        author = pic.added_by if pic else None
        right = [user for user, guess in game["votes"].items() if guess == author]
        for user_id in right:
            self.pay(user_id, games.WHOSE_REWARD, "whose")
            self.repo.incr_counter(user_id, "whose_right")
        for user_id in game["votes"]:
            self._pending_events.setdefault(user_id, []).extend(self.touch_activity(user_id))
        return game, right, self.check_achievements(list(game["votes"]))

    # ── higher or lower ────────────────────────────────────────────────

    def hl_round(self, user_id: int) -> HigherLower | None:
        """Deal a new pair for this player, keeping the streak. None if the warehouse can't make
        a pair that differs by at least HL_MIN_GAP rating."""
        state = self.hl_state(user_id)
        streak = state[1] if state else 0
        for _ in range(12):
            pair = self.repo.random_alive(2)
            if len(pair) == 2 and abs(pair[0].rating - pair[1].rating) >= games.HL_MIN_GAP:
                token = f"{self.rng.randrange(16**6):06x}"
                self.repo.set_meta(f"hl:{user_id}", f"{token}:{pair[0].id}:{pair[1].id}:{streak}")
                return HigherLower(token, pair[0], pair[1], streak, self.repo.counter(user_id, "hl_best"))
        return None

    def hl_state(self, user_id: int) -> tuple[str, int, str, str] | None:
        """(round token, streak, pic A, pic B) of the player's open round."""
        raw = self.repo.meta_str(f"hl:{user_id}")
        if not raw:
            return None
        token, first, second, streak = raw.split(":")
        return token, int(streak), first, second

    def hl_answer(self, user_id: int, token: str, choice: int) -> HLAnswer:
        """choice: 0 = A is higher, 1 = B is higher. Statuses: right, wrong, stale."""
        state = self.hl_state(user_id)
        if state is None or not state[0] or state[0] != token or choice not in (0, 1):
            return HLAnswer("stale")
        _, streak, first_id, second_id = state
        first, second = self.repo.get_pic(first_id), self.repo.get_pic(second_id)
        if first is None or second is None:
            self.repo.set_meta(f"hl:{user_id}", "")
            return HLAnswer("stale")
        chosen, other = (first, second) if choice == 0 else (second, first)
        self.track("higher")
        record_before = self.repo.counter(user_id, "hl_best")
        if chosen.rating >= other.rating:
            streak += 1
            self.repo.raise_counter(user_id, "hl_best", streak)
            paid = 0
            day_key = f"hl_paid:{self.local_day()}"
            if self.repo.counter(user_id, day_key) < games.HL_PAID_PER_DAY:
                self.repo.incr_counter(user_id, day_key)
                self.pay(user_id, games.HL_REWARD, "hl")
                paid = games.HL_REWARD
            # The token is spent: a second tap on the same round (before the next one is dealt) is stale.
            self.repo.set_meta(f"hl:{user_id}", f":{first_id}:{second_id}:{streak}")
            return HLAnswer("right", first, second, streak, record_before, paid)
        self.repo.set_meta(f"hl:{user_id}", "")
        return HLAnswer("wrong", first, second, streak, record_before)

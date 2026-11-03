"""Guessing games: "whose pic?" and "pic by pieces" in the chat, "higher or lower" in private."""

import json
from dataclasses import dataclass, field

from bot.game.types import Granted
from bot.models.records import Pic
from bot.rules import deck, games


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


@dataclass(frozen=True)
class PieceStep:
    round: dict
    kind: str  # stage (a bigger piece) | done
    pics: tuple[Pic, ...]
    answer: int  # the hidden pic's letter, 0-3
    stage: int
    paid: dict[int, int] = field(default_factory=dict)  # who pressed the right letter → coins
    wrong: int = 0  # how many pressed another
    granted: tuple[Granted, ...] = ()


class QuizMixin:
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
        scope = f"whose:{chat_id}"
        pic = self.repo.random_alive_of(author, unseen_in=scope)
        if pic is None:
            return "shortage", None
        self.repo.mark_shown(scope, [pic.id], self.now())
        others = [user for user in uploaders if user != author]
        options = [author, *self.rng.sample(others, min(games.WHOSE_OPTIONS - 1, len(others)))]
        self.rng.shuffle(options)
        game_id = self.repo.create_game("whose", chat_id, pic.id, self.now(), games.WHOSE_SECONDS)
        self.repo.set_game_phase(game_id, "vote", self.now() + games.WHOSE_SECONDS, "collect")
        self.repo.set_meta(f"whose:{game_id}", ",".join(str(user) for user in options))
        self.repo.set_meta(f"whose_at:{chat_id}", self.now())
        return "started", self.with_options(self.repo.get_game(game_id))

    def whose_cooldown_left(self, chat_id: int) -> int:
        return max(0, games.WHOSE_COOLDOWN_SECONDS - (self.now() - self.repo.meta_int(f"whose_at:{chat_id}")))

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
                paid = self.pay(user_id, games.HL_REWARD, "hl")
            # The token is spent: a second tap on the same round (before the next one is dealt) is stale.
            self.repo.set_meta(f"hl:{user_id}", f":{first_id}:{second_id}:{streak}")
            return HLAnswer("right", first, second, streak, record_before, paid)
        self.repo.set_meta(f"hl:{user_id}", "")
        return HLAnswer("wrong", first, second, streak, record_before)

    # ── pic by pieces ──────────────────────────────────────────────────

    def start_piece(self, chat_id: int) -> tuple[str, dict | None]:
        """'started' | 'active' | 'cooldown' | 'shortage'. Four pics from the chat's deck; a piece
        of one of them, which grows every PIECE_STAGE_SECONDS."""
        active = self.repo.open_rounds(chat_id, "piece")
        if active:
            return "active", active[0]
        if self.piece_cooldown_left(chat_id):
            return "cooldown", None
        drawn = deck.draw_many(self.repo, deck.scope_of(chat_id), self.now(), games.PIECE_OPTIONS)
        if len(drawn) < games.PIECE_OPTIONS:
            return "shortage", None
        state = {"pics": [pic.id for pic, _ in drawn], "answer": self.rng.randrange(games.PIECE_OPTIONS),
                 "stage": 0, "center": games.piece_center(self.rng)}
        round_id = self.repo.create_round(chat_id, "piece", self.now(), self.now() + games.PIECE_STAGE_SECONDS,
                                          text=json.dumps(state))
        return "started", self.repo.get_round(round_id)

    def piece_cooldown_left(self, chat_id: int) -> int:
        return max(0, games.PIECE_COOLDOWN_SECONDS - (self.now() - self.repo.last_round_at(chat_id, "piece")))

    def piece_state(self, found: dict) -> dict:
        return json.loads(found["text"])

    def piece_pics(self, found: dict) -> list[Pic | None]:
        return [self.repo.get_pic(pic_id) for pic_id in self.piece_state(found)["pics"]]

    def guess_piece(self, round_id: str, user_id: int, option: int) -> str:
        """'ok' | 'already' | 'closed' | 'gone'. One letter per person, kept with the stage it
        was pressed in: the earlier, the more it pays."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "piece" or not 0 <= option < games.PIECE_OPTIONS:
            return "gone"
        if found["status"] != "open" or self.now() >= found["ends_at"]:
            return "closed"
        stage = self.piece_state(found)["stage"]
        return "ok" if self.repo.put_round_vote(round_id, user_id, option, stage, replace=False) else "already"

    def advance_piece(self, round_id: str) -> PieceStep | None:
        """When the stage's time is up: a bigger piece, or after the last one the answer — the
        right letters are paid by the stage they were pressed in."""
        found = self.repo.get_round(round_id)
        if found is None or found["status"] != "open" or self.now() < found["ends_at"]:
            return None
        state = self.piece_state(found)
        pics = tuple(self.piece_pics(found))
        if state["stage"] + 1 < len(games.PIECE_ZOOMS) and all(pics):
            state["stage"] += 1
            self.repo.update_round(round_id, self.now() + games.PIECE_STAGE_SECONDS, json.dumps(state))
            return PieceStep(self.repo.get_round(round_id), "stage", pics, state["answer"], state["stage"])
        if not self.repo.close_round(round_id, state["answer"]):
            return None
        paid = {}
        for user_id, (option, stage) in found["votes"].items():
            if option == state["answer"]:
                paid[user_id] = self.pay(user_id, games.PIECE_REWARDS[stage], "piece")
                self.repo.incr_counter(user_id, "pieces_right")
        wrong = len(found["votes"]) - len(paid)
        return PieceStep(self.repo.get_round(round_id), "done", pics, state["answer"], state["stage"], paid, wrong,
                         tuple(self.check_achievements(list(found["votes"]))))

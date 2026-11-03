"""Table games of the chat: the spy among us, the minefield, the safe with a code.

Each is a round (`rounds`) with its state as JSON in `text`; who plays sits in `round_votes`."""

import json
from dataclasses import dataclass, field

from bot.game.types import Granted
from bot.rules import party, table


@dataclass(frozen=True)
class SpyStep:
    round: dict
    kind: str  # talk (the word is out) | vote | cancelled (too few) | caught | escaped
    players: tuple[int, ...] = ()
    spy: int | None = None
    counts: dict[int, int] = field(default_factory=dict)  # player → votes against them
    reward: int = 0  # what each winner got
    granted: tuple[Granted, ...] = ()


@dataclass(frozen=True)
class MinesMove:
    status: str  # safe | boom | cleared | open (pressed an open cell) | closed | gone
    value: int = 0  # base coins the safe cell added to the presser's pot
    result: "MinesResult | None" = None


@dataclass(frozen=True)
class MinesResult:
    round: dict
    kind: str  # boom | cleared | time
    stepper: int | None  # who stepped on the mine
    paid: dict[int, int]  # player → coins paid now
    burned: dict[int, int]  # player → coins their pot would have been worth
    granted: tuple[Granted, ...] = ()


@dataclass(frozen=True)
class SafeGuess:
    status: str  # miss | cracked | invalid | poor | wait | closed | gone
    exact: int = 0
    near: int = 0
    wait: int = 0  # seconds until this player may try again
    result: "SafeResult | None" = None


@dataclass(frozen=True)
class SafeResult:
    round: dict
    code: str
    cracker: int | None  # None: time ran out, the pot waits for the next safe
    pot: int  # coins the tries put in (plus what an unopened safe left)
    seed: int  # what the bot added for the cracker
    granted: tuple[Granted, ...] = ()


def state_of(found: dict) -> dict:
    return json.loads(found["text"] or "{}")


class TableMixin:
    def _table_cooldown_left(self, chat_id: int, kind: str, seconds: int) -> int:
        return max(0, seconds - (self.now() - self.repo.last_round_at(chat_id, kind)))

    def _save(self, found: dict, state: dict, ends_at: int | None = None) -> None:
        self.repo.update_round(found["id"], found["ends_at"] if ends_at is None else ends_at, json.dumps(state))

    # ── the spy ────────────────────────────────────────────────────────

    def start_spy(self, chat_id: int, starter: int, word: str) -> tuple[str, dict | None]:
        """'started' | 'active' | 'cooldown'. Whoever starts it plays; the others join while
        SPY_RECRUIT_SECONDS run."""
        active = self.repo.open_rounds(chat_id, "spy")
        if active:
            return "active", active[0]
        if self.spy_cooldown_left(chat_id):
            return "cooldown", None
        state = {"phase": "recruit", "word": word, "spy": None}
        round_id = self.repo.create_round(
            chat_id, "spy", self.now(), self.now() + table.SPY_RECRUIT_SECONDS, starter, json.dumps(state)
        )
        self.repo.put_round_vote(round_id, starter, -1, 0)
        return "started", self.repo.get_round(round_id)

    def spy_cooldown_left(self, chat_id: int) -> int:
        return self._table_cooldown_left(chat_id, "spy", table.SPY_COOLDOWN_SECONDS)

    def spy_players(self, found: dict) -> list[int]:
        """In the order they joined."""
        return [user for user, _ in sorted(found["votes"].items(), key=lambda item: item[1][1])]

    def join_spy(self, round_id: str, user_id: int) -> str:
        """'ok' | 'already' | 'full' | 'started' | 'gone'."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "spy" or found["status"] != "open":
            return "gone"
        if state_of(found)["phase"] != "recruit" or self.now() >= found["ends_at"]:
            return "started"
        if user_id in found["votes"]:
            return "already"
        if len(found["votes"]) >= table.SPY_MAX:
            return "full"
        if not self.repo.put_round_vote(round_id, user_id, -1, len(found["votes"]), replace=False):
            return "already"
        return "ok"

    def spy_secret(self, round_id: str, user_id: int) -> tuple[str, str | None]:
        """What a player sees behind «My word»: ('word', the word) | ('spy', None) |
        ('waiting', None) before the word is out | ('not_player', None) | ('gone', None)."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "spy" or found["status"] != "open":
            return "gone", None
        if user_id not in found["votes"]:
            return "not_player", None
        state = state_of(found)
        if state["phase"] == "recruit":
            return "waiting", None
        return ("spy", None) if state["spy"] == user_id else ("word", state["word"])

    def vote_spy(self, round_id: str, user_id: int, index: int) -> str:
        """'ok' | 'same' | 'self' | 'not_player' | 'closed' | 'gone'. Only players vote, and
        not for themselves; a vote can be changed."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "spy":
            return "gone"
        players = self.spy_players(found)
        if not 0 <= index < len(players):
            return "gone"
        if found["status"] != "open" or state_of(found)["phase"] != "vote" or self.now() >= found["ends_at"]:
            return "closed"
        if user_id not in found["votes"]:
            return "not_player"
        target = players[index]
        if target == user_id:
            return "self"
        choice, order = found["votes"][user_id]
        if choice == target:
            return "same"
        self.repo.put_round_vote(round_id, user_id, target, order)
        return "ok"

    def spy_counts(self, found: dict) -> dict[int, int]:
        counts = {user: 0 for user in found["votes"]}
        for choice, _ in found["votes"].values():
            if choice in counts:
                counts[choice] += 1
        return counts

    def advance_spy(self, round_id: str) -> SpyStep | None:
        """When the phase's time is up: recruiting ends (too few: called off) and the word goes
        out with a spy among the players; the talk ends and the vote opens; the vote settles."""
        found = self.repo.get_round(round_id)
        if found is None or found["status"] != "open" or self.now() < found["ends_at"]:
            return None
        state = state_of(found)
        players = self.spy_players(found)
        if state["phase"] == "recruit":
            if len(players) < table.SPY_MIN:
                self.repo.close_round(round_id, -1)
                return SpyStep(self.repo.get_round(round_id), "cancelled", tuple(players))
            state["phase"], state["spy"] = "talk", players[self.rng.randrange(len(players))]
            self._save(found, state, self.now() + table.SPY_TALK_SECONDS)
            return SpyStep(self.repo.get_round(round_id), "talk", tuple(players), state["spy"])
        if state["phase"] == "talk":
            state["phase"] = "vote"
            self._save(found, state, self.now() + table.SPY_VOTE_SECONDS)
            return SpyStep(self.repo.get_round(round_id), "vote", tuple(players), state["spy"])
        spy = state["spy"]
        votes = {user: choice for user, (choice, _) in found["votes"].items() if choice in found["votes"]}
        caught = table.spy_caught(votes, spy)
        if not self.repo.close_round(round_id, spy):
            return None
        winners = [user for user in players if user != spy] if caught else [spy]
        reward = 0
        for user_id in winners:
            reward = self.pay(user_id, table.SPY_CATCH_REWARD if caught else table.SPY_ESCAPE_REWARD, "spy")
        self.repo.incr_counter(spy, "spy_caught" if caught else "spy_escaped")
        return SpyStep(self.repo.get_round(round_id), "caught" if caught else "escaped", tuple(players), spy,
                       self.spy_counts(found), reward, tuple(self.check_achievements(players)))

    # ── the minefield ──────────────────────────────────────────────────

    def start_mines(self, chat_id: int) -> tuple[str, dict | None]:
        """'started' | 'active' | 'cooldown'."""
        active = self.repo.open_rounds(chat_id, "mines")
        if active:
            return "active", active[0]
        if self.mines_cooldown_left(chat_id):
            return "cooldown", None
        state = {"mines": table.minefield(self.rng), "open": [], "pots": {}}
        round_id = self.repo.create_round(chat_id, "mines", self.now(), self.now() + table.MINES_SECONDS,
                                          text=json.dumps(state))
        return "started", self.repo.get_round(round_id)

    def mines_cooldown_left(self, chat_id: int) -> int:
        return self._table_cooldown_left(chat_id, "mines", table.MINES_COOLDOWN_SECONDS)

    def mines_pots(self, found: dict) -> dict[int, int]:
        """Player → base coins they opened and haven't taken yet."""
        return {int(user): coins for user, coins in state_of(found)["pots"].items() if coins}

    def open_cell(self, round_id: str, user_id: int, cell: int) -> MinesMove:
        """A safe cell adds its worth to the presser's pot. A mine ends the field: every pot not
        taken burns, and the one who stepped on it wears it for a day. The last safe cell ends it
        too, and then every pot is paid."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "mines" or not 0 <= cell < table.MINES_SIDE ** 2:
            return MinesMove("gone")
        if found["status"] != "open" or self.now() >= found["ends_at"]:
            return MinesMove("closed")
        state = state_of(found)
        if cell in state["open"]:
            return MinesMove("open")
        state["open"].append(cell)
        if cell in state["mines"]:
            self._save(found, state)
            return MinesMove("boom", result=self._settle_mines(round_id, "boom", user_id))
        value = table.cell_value(len(state["open"]) - 1)
        state["pots"][str(user_id)] = state["pots"].get(str(user_id), 0) + value
        self._save(found, state)
        if len(state["open"]) == table.MINES_SIDE ** 2 - table.MINES_COUNT:
            return MinesMove("cleared", value, self._settle_mines(round_id, "cleared"))
        return MinesMove("safe", value)

    def cash_mines(self, round_id: str, user_id: int) -> tuple[str, int]:
        """('ok', coins) | ('empty', 0) | ('closed', 0) | ('gone', 0): take one's pot out of the
        field; opening more cells starts a new one."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "mines":
            return "gone", 0
        if found["status"] != "open" or self.now() >= found["ends_at"]:
            return "closed", 0
        state = state_of(found)
        pot = state["pots"].pop(str(user_id), 0)
        if not pot:
            return "empty", 0
        self._save(found, state)
        return "ok", self.pay(user_id, pot, "mines")

    def finish_mines(self, round_id: str) -> MinesResult | None:
        """Time is up and nobody blew up: every pot is paid."""
        return self._settle_mines(round_id, "time")

    def _settle_mines(self, round_id: str, kind: str, stepper: int | None = None) -> MinesResult | None:
        found = self.repo.get_round(round_id)
        if found is None or not self.repo.close_round(round_id, stepper):
            return None
        pots = self.mines_pots(found)
        paid, burned = {}, {}
        if kind == "boom":
            burned = {user: self.reward(coins) for user, coins in pots.items()}
            self.repo.set_badge(stepper, "mines", "Жертва мины", self.now() + party.BADGE_SECONDS)
            self.repo.incr_counter(stepper, "mines_blown")
        else:
            paid = {user: self.pay(user, coins, "mines") for user, coins in pots.items()}
        people = [*pots, *([stepper] if stepper is not None else [])]
        return MinesResult(self.repo.get_round(round_id), kind, stepper, paid, burned,
                           tuple(self.check_achievements(people)))

    # ── the safe ───────────────────────────────────────────────────────

    def start_safe(self, chat_id: int) -> tuple[str, dict | None]:
        """'started' | 'active' | 'cooldown'. What the last unopened safe held is in this one."""
        active = self.repo.open_rounds(chat_id, "safe")
        if active:
            return "active", active[0]
        if self.safe_cooldown_left(chat_id):
            return "cooldown", None
        carry = self.repo.meta_int(f"safe_carry:{chat_id}")
        self.repo.set_meta(f"safe_carry:{chat_id}", 0)
        state = {"code": table.safe_code(self.rng), "log": [], "pot": carry}
        round_id = self.repo.create_round(chat_id, "safe", self.now(), self.now() + table.SAFE_SECONDS,
                                          text=json.dumps(state))
        return "started", self.repo.get_round(round_id)

    def safe_cooldown_left(self, chat_id: int) -> int:
        return self._table_cooldown_left(chat_id, "safe", table.SAFE_COOLDOWN_SECONDS)

    def safe_in(self, chat_id: int) -> dict | None:
        active = self.repo.open_rounds(chat_id, "safe")
        return active[0] if active and self.now() < active[0]["ends_at"] else None

    def safe_price(self) -> int:
        return self.scaled(table.SAFE_GUESS_PRICE)

    def safe_seed(self) -> int:
        return self.reward(table.SAFE_SEED)

    def guess_safe(self, round_id: str, user_id: int, guess: str) -> SafeGuess:
        """A try costs SAFE_GUESS_PRICE, which goes into the safe. The bot answers how many digits
        stand in their place and how many are in the code elsewhere; all four in place open it."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "safe":
            return SafeGuess("gone")
        if found["status"] != "open" or self.now() >= found["ends_at"]:
            return SafeGuess("closed")
        if not table.valid_guess(guess):
            return SafeGuess("invalid")
        last, tries = found["votes"].get(user_id, (0, 0))
        wait = last + table.SAFE_GUESS_GAP - self.now()
        if wait > 0:
            return SafeGuess("wait", wait=wait)
        price = self.safe_price()
        if not self.repo.spend(user_id, price, "safe_try", self.now()):
            return SafeGuess("poor")
        state = state_of(found)
        exact, near = table.safe_hint(state["code"], guess)
        state["pot"] += price
        state["log"].append([user_id, guess, exact, near])
        self._save(found, state)
        self.repo.put_round_vote(round_id, user_id, self.now(), tries + 1)
        if exact < table.SAFE_DIGITS:
            return SafeGuess("miss", exact, near)
        if not self.repo.close_round(round_id, user_id):
            return SafeGuess("closed")
        self.repo.add_coins(user_id, state["pot"], "safe_pot", self.now(), earn=False)
        seed = self.pay(user_id, table.SAFE_SEED, "safe")
        self.repo.incr_counter(user_id, "safes_cracked")
        result = SafeResult(self.repo.get_round(round_id), state["code"], user_id, state["pot"], seed,
                            tuple(self.check_achievements([user_id])))
        return SafeGuess("cracked", exact, near, result=result)

    def finish_safe(self, round_id: str) -> SafeResult | None:
        """Time is up and the safe held: what the tries put in waits in the chat's next safe."""
        found = self.repo.get_round(round_id)
        if found is None or not self.repo.close_round(round_id, None):
            return None
        state = state_of(found)
        carry = self.repo.meta_int(f"safe_carry:{found['chat_id']}") + state["pot"]
        self.repo.set_meta(f"safe_carry:{found['chat_id']}", carry)
        return SafeResult(self.repo.get_round(round_id), state["code"], None, state["pot"], 0)

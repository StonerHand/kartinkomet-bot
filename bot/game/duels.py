"""Board duels: an accepted /pvp challenge of rock-paper-scissors or tic-tac-toe, played move by
move. The board lives in `meta duel:<challenge>` as JSON, so a restart doesn't end the game."""

import json
from dataclasses import dataclass, field

from bot.game.types import Granted
from bot.rules import duels


@dataclass(frozen=True)
class BoardDuel:
    challenge: dict
    state: dict
    winner: int | None  # None: a draw (or nobody moved), both stakes went back
    pot: int
    score: tuple[int, int]  # head-to-head after it: challenger's wins, opponent's wins
    timed_out: int | None = None  # who let the clock run out
    granted: list[Granted] = field(default_factory=list)


class BoardDuelsMixin:
    def duel_state(self, challenge_id: str) -> dict | None:
        raw = self.repo.meta_str(f"duel:{challenge_id}")
        return json.loads(raw) if raw else None

    def _save_duel(self, challenge_id: str, state: dict) -> None:
        self.repo.set_meta(f"duel:{challenge_id}", json.dumps(state))

    def deal_board(self, challenge: dict) -> dict:
        """The accepted duel's first state: nobody has picked yet, or an empty board with X to move."""
        if challenge["game"] == "rps":
            state = {"picks": {}, "round": 1, "until": self.now() + duels.RPS_SECONDS, "last": None}
        else:
            state = {"board": duels.TTT_EMPTY * 9, "turn": challenge["from_user"],
                     "until": self.now() + duels.TTT_MOVE_SECONDS}
        self._save_duel(challenge["id"], state)
        return state

    def set_duel_message(self, challenge_id: str, message_id: int) -> None:
        state = self.duel_state(challenge_id)
        if state is not None:
            state["message"] = message_id
            self._save_duel(challenge_id, state)

    def mark_duel_widget(self, challenge_id: str) -> None:
        """The board went out as an HTML widget: its redraws edit the widget's data."""
        state = self.duel_state(challenge_id)
        if state is not None:
            state["widget"] = True
            self._save_duel(challenge_id, state)

    def _open_duel(self, challenge_id: str, game: str) -> tuple[dict | None, dict | None]:
        challenge = self.repo.get_challenge(challenge_id)
        state = self.duel_state(challenge_id)
        if challenge is None or challenge["game"] != game or challenge["winner"] is not None or state is None:
            return None, None
        return challenge, state

    def _finish_duel(self, challenge: dict, state: dict, winner: int | None,
                     timed_out: int | None = None) -> BoardDuel:
        state["over"] = True
        self._save_duel(challenge["id"], state)
        pot, score = self._pay_duel(challenge, winner)
        players = [challenge["from_user"], challenge["to_user"]]
        return BoardDuel(self.repo.get_challenge(challenge["id"]), state, winner, pot, score, timed_out,
                         self.check_achievements(players))

    def pick_rps(self, challenge_id: str, user_id: int, pick: int) -> tuple[str, BoardDuel | None]:
        """'ok' (waiting for the other) | 'draw' (same picks, again) | 'done' | 'already' |
        'not_player' | 'gone'. A pick is secret until both are in."""
        challenge, state = self._open_duel(challenge_id, "rps")
        if challenge is None or not 0 <= pick < len(duels.RPS):
            return "gone", None
        players = (challenge["from_user"], challenge["to_user"])
        if user_id not in players:
            return "not_player", None
        if str(user_id) in state["picks"]:
            return "already", None
        state["picks"][str(user_id)] = pick
        if len(state["picks"]) < 2:
            self._save_duel(challenge_id, state)
            return "ok", None
        first, second = (state["picks"][str(player)] for player in players)
        state["last"] = [first, second]
        side = duels.rps_winner(first, second)
        if side is None:
            state.update(picks={}, round=state["round"] + 1, until=self.now() + duels.RPS_SECONDS)
            self._save_duel(challenge_id, state)
            return "draw", None
        return "done", self._finish_duel(challenge, state, players[side])

    def move_ttt(self, challenge_id: str, user_id: int, cell: int) -> tuple[str, BoardDuel | None]:
        """'ok' | 'done' | 'not_turn' | 'taken' | 'not_player' | 'gone'."""
        challenge, state = self._open_duel(challenge_id, "ttt")
        if challenge is None or not 0 <= cell < 9:
            return "gone", None
        players = (challenge["from_user"], challenge["to_user"])
        if user_id not in players:
            return "not_player", None
        if state["turn"] != user_id:
            return "not_turn", None
        board = state["board"]
        if board[cell] != duels.TTT_EMPTY:
            return "taken", None
        mark = duels.TTT_MARKS[players.index(user_id)]
        state["board"] = board[:cell] + mark + board[cell + 1:]
        outcome = duels.ttt_outcome(state["board"])
        if outcome is None:
            state["turn"] = players[1] if user_id == players[0] else players[0]
            state["until"] = self.now() + duels.TTT_MOVE_SECONDS
            self._save_duel(challenge_id, state)
            return "ok", None
        winner = None if outcome == "draw" else players[duels.TTT_MARKS.index(outcome)]
        return "done", self._finish_duel(challenge, state, winner)

    def time_out_duel(self, challenge_id: str) -> BoardDuel | None:
        """The clock ran out. Rock-paper-scissors: whoever picked wins, nobody picked — stakes back.
        Tic-tac-toe: whoever had to move loses."""
        challenge = self.repo.get_challenge(challenge_id)
        state = self.duel_state(challenge_id)
        if challenge is None or challenge["winner"] is not None or state is None or self.now() < state["until"]:
            return None
        players = (challenge["from_user"], challenge["to_user"])
        if challenge["game"] == "rps":
            picked = [player for player in players if str(player) in state["picks"]]
            late = [player for player in players if player not in picked]
            winner = picked[0] if len(picked) == 1 else None
            return self._finish_duel(challenge, state, winner, late[0] if len(late) == 1 else None)
        late = state["turn"]
        return self._finish_duel(challenge, state, players[1] if late == players[0] else players[0], late)

    def open_board_duels(self) -> list[str]:
        return [challenge["id"] for challenge in self.repo.unsettled_game_duels(tuple(duels.BOARD_GAMES))]

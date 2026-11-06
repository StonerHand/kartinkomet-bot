"""Live cards of board duels (rock-paper-scissors, tic-tac-toe): the board, its move clock, the
result. Mixed into timers.Live, which owns the redraw queue and the tasks."""

import asyncio

from bot.rules import duels
from bot.telegram import send
from bot.ui import keyboards, views, widgets


class DuelsLive:
    def duel_names(self, challenge: dict) -> tuple[str, str]:
        label = self.game.repo.user_label
        return label(challenge["from_user"]), label(challenge["to_user"])

    def duel_card(self, challenge_id: str) -> tuple[str, object]:
        challenge = self.game.repo.get_challenge(challenge_id)
        state = self.game.duel_state(challenge_id)
        names = self.duel_names(challenge)
        remaining = state["until"] - self.game.now()
        if challenge["game"] == "rps":
            picked = tuple(str(user) in state["picks"] for user in (challenge["from_user"], challenge["to_user"]))
            text = views.rps_card(names, picked, remaining, state["round"], state.get("last"), challenge_id)
            return text, keyboards.rps(challenge_id)
        turn = 0 if state["turn"] == challenge["from_user"] else 1
        return views.ttt_card(names, turn, remaining, challenge_id), keyboards.ttt(challenge_id, state["board"])

    def duel_widget_data(self, challenge: dict, state: dict, result: dict | None = None) -> str:
        """What a board duel's widget draws; result once it's over (see ui.widgets)."""
        names = self.duel_names(challenge)
        players = (challenge["from_user"], challenge["to_user"])
        if challenge["game"] == "rps":
            picked = tuple(str(user) in state["picks"] for user in players)
            return widgets.rps_data(names, picked, state["round"], state["until"], result)
        turn = 0 if state["turn"] == players[0] else 1
        return widgets.ttt_data(state["board"], names, turn, state["until"], result)

    def watch_duel(self, challenge_id: str) -> None:
        self._spawn(f"du:{challenge_id}", self._duel_loop(challenge_id))

    async def _duel_loop(self, challenge_id: str) -> None:
        """A move or a pick moves the clock; when it runs out, whoever was late loses."""
        first = True
        while True:
            challenge = self.game.repo.get_challenge(challenge_id)
            state = self.game.duel_state(challenge_id)
            if challenge is None or challenge["winner"] is not None:
                return
            if state is None:  # accepted, but the board never went out: nothing was played
                self.game.cancel_dice_duel(challenge)
                return
            remaining = state["until"] - self.game.now()
            if remaining <= 0:
                duel = self.game.time_out_duel(challenge_id)
                if duel is not None:
                    await self.settle_duel(duel)
                return
            if not first:
                self.request_refresh_duel(challenge_id)
            first = False
            await asyncio.sleep(min(self.tick_seconds, remaining))

    def request_refresh_duel(self, challenge_id: str) -> None:
        self._debounce(f"rdu:{challenge_id}", lambda: self.refresh_duel(challenge_id))

    async def refresh_duel(self, challenge_id: str) -> None:
        challenge = self.game.repo.get_challenge(challenge_id)
        state = self.game.duel_state(challenge_id)
        if challenge is None or state is None or challenge["winner"] is not None:
            return

        widget = bool(state.get("widget"))

        def render():
            fresh = self.game.repo.get_challenge(challenge_id)
            if fresh is None or fresh["winner"] is not None:
                return None
            if widget:
                return self.duel_widget_data(fresh, self.game.duel_state(challenge_id)), None
            return self.duel_card(challenge_id)

        await self._redraw(challenge["chat_id"], state.get("message"), False, render, widget)

    async def settle_duel(self, duel) -> None:
        challenge = duel.challenge
        chat_id, state = challenge["chat_id"], duel.state
        names = self.duel_names(challenge)
        label = self.game.repo.user_label
        winner = label(duel.winner) if duel.winner is not None else None
        late = label(duel.timed_out) if duel.timed_out is not None else None
        if challenge["game"] == "rps":
            picks = [state["picks"][str(user)] for user in (challenge["from_user"], challenge["to_user"])] \
                if len(state["picks"]) == 2 else None
            text = views.rps_result(names, picks, winner, duel.pot, late, duel.score, chat_id)
            markup = keyboards.rematch(challenge["id"], challenge["stake"], dice=False)
        else:
            text = views.ttt_result(names, winner, duel.pot, late, duel.score, chat_id)
            markup = keyboards.ttt(challenge["id"], state["board"], over=True, stake=challenge["stake"])
        final = None
        if state.get("widget"):
            ending = {"w": widgets.name(winner) if winner else "", "late": widgets.name(late) if late else ""}
            if challenge["game"] == "rps":
                ending["k"] = picks
            else:
                ending["line"] = list(duels.ttt_line(state["board"]) or ())
            final = self.duel_widget_data(challenge, state, ending)
        message_id = await self._settle_card(chat_id, state.get("message"), text, markup, False, final)
        if duel.winner is not None:
            await send.react(self.bot, chat_id, message_id, "🏆")
        await self.announce(chat_id, duel.granted)


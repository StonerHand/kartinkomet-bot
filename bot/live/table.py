"""Live cards of the table games (the spy, the minefield, the safe), pic by pieces and the auction:
mixed into timers.Live, which owns the redraw queue and the tasks."""

import asyncio

from aiogram.types import BufferedInputFile

from bot.game.table import state_of
from bot.rules import games as game_rules
from bot.rules import table
from bot.telegram import pictures, send
from bot.ui import keyboards, views

TABLE_KINDS = ("spy", "mines", "safe", "piece", "auction")
WATCHED = ("spy", "mines", "safe", "piece")  # the auction's card waits for bids; the schedule settles it
PHASED = ("spy", "piece")  # settled by their own phase loop; the others count down to one deadline


class TableLive:
    # ── cards ──────────────────────────────────────────────────────────

    def table_card(self, found: dict) -> tuple[str, object]:
        game = self.game
        remaining = found["ends_at"] - game.now()
        kind = found["kind"]
        if kind == "spy":
            players = game.spy_players(found)
            labels = [game.repo.user_label(user) for user in players]
            phase = state_of(found)["phase"]
            counts = game.spy_counts(found)
            ready = len(state_of(found).get("ready", []))
            text = views.spy_card(phase, labels, remaining, [counts[user] for user in players], found["id"], ready)
            return text, keyboards.spy(found["id"], phase, labels)
        if kind == "mines":
            state = state_of(found)
            pots = [(game.repo.user_label(user), game.reward(coins)) for user, coins in game.mines_pots(found).items()]
            worth = game.reward(table.cell_value(len(state["open"])))
            text = views.mines_card(pots, len(state["open"]), worth, remaining, found["id"])
            return text, keyboards.mines(found["id"], table.MINES_SIDE, state["open"])
        if kind == "safe":
            return views.safe_card(self.safe_log(found), state_of(found)["pot"], game.safe_price(), game.safe_seed(),
                                   remaining, found["id"]), None
        if kind == "piece":
            rewards = [game.reward(amount) for amount in game_rules.PIECE_REWARDS]
            text = views.piece_card(game.piece_state(found)["stage"], len(found["votes"]), remaining, rewards,
                                    found["id"])
            return text, keyboards.piece(found["id"], views.PIECE_LETTERS)
        bidders = game.auction_bidders(found)
        text = views.auction_card(game.auction_lot(found), bidders, game.auction_raises(), game.auction_min_price(),
                                  found["id"])
        return text, keyboards.auction(found["id"], game.auction_raises())

    def safe_log(self, found: dict) -> list[tuple[str, str, int, int]]:
        return [(self.game.repo.user_label(user), guess, exact, near)
                for user, guess, exact, near in state_of(found)["log"]]

    # ── watching ───────────────────────────────────────────────────────

    def watch_table(self, round_id: str) -> None:
        found = self.game.repo.get_round(round_id)
        if found is None or found["status"] != "open":
            return
        if found["message_id"] is None:
            self.game.repo.drop_round(round_id)  # its card never reached the chat
            return
        if found["kind"] in PHASED:
            self._spawn(f"tb:{round_id}", self._phase_loop(round_id))
            return

        def deadline() -> int | None:
            fresh = self.game.repo.get_round(round_id)
            return fresh["ends_at"] if fresh and fresh["status"] == "open" else None

        self._spawn(f"tb:{round_id}", self._countdown(
            deadline, lambda: self.request_refresh_round(round_id), lambda: self.finish_table(round_id)
        ))

    async def _phase_loop(self, round_id: str) -> None:
        """The spy (recruit → talk → vote) and pic by pieces (a bigger piece each stage): each
        phase ends on its clock and the card moves on."""
        first = True
        while (found := self.game.repo.get_round(round_id)) is not None and found["status"] == "open":
            remaining = found["ends_at"] - self.game.now()
            if remaining <= 0:
                if found["kind"] == "spy":
                    await self.advance_spy(round_id)
                else:
                    await self.advance_piece(round_id)
                first = True
                continue
            if not first:
                self.request_refresh_round(round_id)
            first = False
            await asyncio.sleep(min(self.tick_seconds, remaining))

    async def finish_table(self, round_id: str) -> None:
        found = self.game.repo.get_round(round_id)
        if found is None:
            return
        if found["kind"] == "mines":
            result = self.game.finish_mines(round_id)
            if result is not None:
                await self.settle_mines(result)
        elif found["kind"] == "safe":
            result = self.game.finish_safe(round_id)
            if result is not None:
                await self.settle_safe(result)

    # ── the spy ────────────────────────────────────────────────────────

    async def advance_spy(self, round_id: str) -> None:
        step = self.game.advance_spy(round_id)
        if step is None:
            return
        if step.kind in ("talk", "vote"):
            await self.refresh_round(round_id)
            return
        found = step.round
        labels = self.labels(step.players)
        players = list(step.players)
        text = views.spy_result(step.kind, [labels[user] for user in players], labels.get(step.spy),
                                [step.counts.get(user, 0) for user in players], state_of(found)["word"], step.reward,
                                found["chat_id"])
        markup = keyboards.after_party("spy") if step.kind != "cancelled" else keyboards.more_only()
        message_id = await self._settle_card(found["chat_id"], found["message_id"], text, markup, False)
        if step.kind != "cancelled":
            await send.react(self.bot, found["chat_id"], message_id, "🔥" if step.kind == "caught" else "😱")
        await self.announce(found["chat_id"], list(step.granted))

    # ── the minefield ──────────────────────────────────────────────────

    async def settle_mines(self, result) -> None:
        found = result.round
        state = state_of(found)
        labels = self.labels([*result.paid, *result.burned, result.stepper])
        text = views.mines_result(result.kind, labels.get(result.stepper),
                                  [(labels[user], coins) for user, coins in result.paid.items()],
                                  [(labels[user], coins) for user, coins in result.burned.items()], found["chat_id"])
        markup = keyboards.mines(found["id"], table.MINES_SIDE, state["open"], state["mines"])
        message_id = await self._settle_card(found["chat_id"], found["message_id"], text, markup, False)
        await send.react(self.bot, found["chat_id"], message_id, "🤯" if result.kind == "boom" else "🤑")
        await self.announce(found["chat_id"], list(result.granted))

    # ── the safe ───────────────────────────────────────────────────────

    async def settle_safe(self, result) -> None:
        found = result.round
        cracker = self.game.repo.user_label(result.cracker) if result.cracker is not None else None
        text = views.safe_result(result.code, cracker, result.pot, result.seed, self.safe_log(found), found["chat_id"])
        message_id = await self._settle_card(found["chat_id"], found["message_id"], text,
                                             keyboards.after_party("safe"), False)
        if result.cracker is not None:
            await send.react(self.bot, found["chat_id"], message_id, "🤑", big=True)
        await self.announce(found["chat_id"], list(result.granted))

    # ── pic by pieces ──────────────────────────────────────────────────

    async def advance_piece(self, round_id: str) -> None:
        step = self.game.advance_piece(round_id)
        if step is None:
            return
        found = step.round
        state = self.game.piece_state(found)
        if step.kind == "stage":
            text, markup = self.table_card(found)
            zoom = game_rules.PIECE_ZOOMS[step.stage]
        else:
            labels = self.labels(step.paid)
            text = views.piece_result(step.answer, [(labels[user], coins) for user, coins in step.paid.items()],
                                      step.wrong, found["chat_id"])
            markup, zoom = keyboards.after_party("piece"), 1.0
        board = await pictures.build_pieces(self.bot, step.pics, step.answer, zoom, tuple(state["center"]))
        chat_id, message_id = found["chat_id"], found["message_id"]
        if board is None or not await send.edit_photo(
            self.bot, chat_id, message_id, BufferedInputFile(board, "pieces.jpg"), text, markup
        ):
            await send.edit_caption(self.bot, chat_id, message_id, text, markup)  # the old piece, the new words
        if step.kind == "done":
            await self.announce(chat_id, list(step.granted))


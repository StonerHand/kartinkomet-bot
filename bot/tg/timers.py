"""Live cards: ticking timers, final results, recovery after restart.

Battles, courts and bosses share one countdown loop: refresh the card every TICK_SECONDS,
settle when the deadline passes. Votes and hits ask for a refresh that is debounced, because
Telegram rate-limits edits per chat.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot

from bot.core import boss as boss_rules
from bot.game import Game, Granted
from bot.tg import keyboards, send, views

LOGGER = logging.getLogger(__name__)
TICK_SECONDS = 15
# A battle nobody voted in gets one overtime instead of ending empty.
OVERTIME_SECONDS = 30
REFRESH_DELAY = 1.5
# Notes that put a chest in someone's backpack: kind → tier (None = the note's own code).
CHEST_OF_NOTE = {"chest": None, "quests_all": "wood", "challenge": "rare", "challenges_all": "legend"}


class Live:
    def __init__(self, bot: Bot, game: Game) -> None:
        self.bot = bot
        self.game = game
        self._tasks: dict[str, asyncio.Task] = {}
        self._pending_refresh: set[str] = set()

    # ── tasks ──────────────────────────────────────────────────────────

    def watch_battle(self, battle_id: str) -> None:
        self._spawn(f"b:{battle_id}", self.battle_countdown(battle_id))

    def battle_countdown(self, battle_id: str):
        return self._countdown(
            lambda: self._battle_deadline(battle_id),
            lambda: self.refresh_battle(battle_id),
            lambda: self.finish_battle(battle_id),
        )

    def watch_court(self, court_id: str) -> None:
        def deadline() -> int | None:
            trial = self.game.repo.get_court(court_id)
            return trial.ends_at if trial and trial.status == "active" else None

        self._spawn(f"c:{court_id}", self._countdown(
            deadline, lambda: self.refresh_court(court_id), lambda: self.finish_court(court_id)
        ))

    def watch_boss(self, boss_id: str) -> None:
        def deadline() -> int | None:
            boss = self.game.repo.get_boss(boss_id)
            if boss is None or boss["status"] != "active":
                return None
            return boss["ends_at"] if boss["hp"] > 0 else 0  # killed: settle now

        self._spawn(f"boss:{boss_id}", self._countdown(
            deadline, lambda: self.refresh_boss(boss_id), lambda: self.finish_boss(boss_id)
        ))

    def watch_game(self, game_id: str) -> None:
        self._spawn(f"g:{game_id}", self._game_loop(game_id))

    def watch_challenge(self, challenge_id: str) -> None:
        self._spawn(f"cl:{challenge_id}", self._challenge_loop(challenge_id))

    def request_refresh_battle(self, battle_id: str) -> None:
        self._debounce(f"rb:{battle_id}", lambda: self.refresh_battle(battle_id))

    def request_refresh_court(self, court_id: str) -> None:
        self._debounce(f"rc:{court_id}", lambda: self.refresh_court(court_id))

    def request_refresh_game(self, game_id: str) -> None:
        self._debounce(f"rg:{game_id}", lambda: self.refresh_game(game_id))

    def request_refresh_boss(self, boss_id: str) -> None:
        self._debounce(f"rboss:{boss_id}", lambda: self.refresh_boss(boss_id))

    def restore(self) -> int:
        repo = self.game.repo
        watchers = (
            (repo.active_battle_ids(), self.watch_battle),
            (repo.active_court_ids(), self.watch_court),
            (repo.active_game_ids(), self.watch_game),
            (repo.active_boss_ids(), self.watch_boss),
            (repo.pending_challenge_ids(), self.watch_challenge),
        )
        for ids, watch in watchers:
            for item_id in ids:
                watch(item_id)
        return sum(len(ids) for ids, _ in watchers)

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _countdown(
        self,
        deadline: Callable[[], int | None],
        refresh: Callable[[], Awaitable[None]],
        finish: Callable[[], Awaitable[None]],
    ) -> None:
        """deadline() → unix time, or None when the thing is already settled."""
        while (ends_at := deadline()) is not None:
            remaining = ends_at - self.game.now()
            if remaining <= 0:
                await finish()
                return
            await refresh()
            await asyncio.sleep(min(TICK_SECONDS, remaining))

    def _debounce(self, key: str, refresh: Callable[[], Awaitable[None]]) -> None:
        if key in self._pending_refresh:
            return
        self._pending_refresh.add(key)

        async def run() -> None:
            await asyncio.sleep(REFRESH_DELAY)
            self._pending_refresh.discard(key)
            await refresh()

        self._spawn(f"{key}:{id(run)}", run())

    def _spawn(self, key: str, coroutine) -> None:
        if key in self._tasks and not self._tasks[key].done():
            coroutine.close()
            return
        task = asyncio.create_task(coroutine)
        self._tasks[key] = task
        task.add_done_callback(lambda done, key=key: self._done(key, done))

    def _done(self, key: str, task: asyncio.Task) -> None:
        if self._tasks.get(key) is task:
            del self._tasks[key]
        if not task.cancelled() and task.exception():
            LOGGER.error("Live task %s crashed", key, exc_info=task.exception())

    # ── helpers ────────────────────────────────────────────────────────

    def labels(self, user_ids) -> dict[int, str]:
        return {user_id: self.game.repo.user_label(user_id) for user_id in user_ids if isinstance(user_id, int)}

    async def _settle_card(self, chat_id: int, message_id: int | None, text: str, markup, photo: bool) -> int | None:
        """Put the result into the live card; if Telegram refuses, post it as a new message."""
        edit = send.edit_caption if photo else send.edit_text
        if message_id is not None and await edit(self.bot, chat_id, message_id, text, markup):
            return message_id
        sent = await send.send_text(self.bot, chat_id, text, markup)
        return sent.message_id if sent else None

    async def announce(self, chat_id: int, granted: list[Granted]) -> None:
        """One message per event, however many people got something."""
        if not granted:
            return
        items = [(self.game.repo.user_label(item.user_id), item) for item in granted]
        tiers = [
            CHEST_OF_NOTE[note.kind] or note.code
            for item in granted
            for note in item.notes
            if note.kind in CHEST_OF_NOTE
        ]
        message = await send.send_text(self.bot, chat_id, views.announcement(items), keyboards.open_chests(tiers))
        if message:
            legendary = views.has_legendary(granted)
            await send.react(self.bot, chat_id, message.message_id, "🔥" if legendary else "🎉", big=legendary)

    # ── battles ────────────────────────────────────────────────────────

    def _battle_deadline(self, battle_id: str) -> int | None:
        battle = self.game.repo.get_battle(battle_id)
        if battle is None or battle.status != "active":
            return None
        if battle.ends_at <= self.game.now() and not battle.votes and not battle.extended:
            if self.game.repo.extend_battle(battle_id, OVERTIME_SECONDS):
                return battle.ends_at + OVERTIME_SECONDS
        return battle.ends_at

    def battle_text(self, battle, remaining: int) -> str:
        fighters = None
        if battle.mode == "challenge":
            challenge = self.game.repo.challenge_for_battle(battle.id)
            if challenge:
                fighters = views.challenge_names(challenge, self.labels([challenge["from_user"], challenge["to_user"]]))
        flipped = battle.kind == "duel" and battle.mode == "" and self.game.day_is("upside_down")
        return views.battle_card(battle, remaining, fighters, flipped)

    async def refresh_battle(self, battle_id: str) -> None:
        battle = self.game.repo.get_battle(battle_id)
        if battle is None or battle.status != "active" or battle.message_id is None:
            return
        edit = send.edit_caption if battle.card_is_photo else send.edit_text
        await edit(
            self.bot,
            battle.chat_id,
            battle.message_id,
            self.battle_text(battle, battle.ends_at - self.game.now()),
            keyboards.battle_vote(battle.id, battle.kind, battle.vote_counts()),
        )

    async def finish_battle(self, battle_id: str) -> None:
        report = self.game.finish_battle(battle_id)
        if report is None:
            return
        battle = report.battle
        if battle.mode == "challenge":
            markup = keyboards.more_only()
        elif battle.kind == "duel":
            markup = keyboards.after_duel(battle.id, battle.winner_slot is not None)
        else:
            markup = keyboards.after_tournament()
        people = [*report.bets, *report.bounty, *report.guessers, *(pic.added_by for pic in battle.pics)]
        if report.challenge:
            people += [report.challenge["from_user"], report.challenge["to_user"]]
        text = views.battle_report(report, self.labels(people))
        card_id = await self._settle_card(battle.chat_id, battle.message_id, text, markup, battle.card_is_photo)
        if report.counted and report.winner is not None:
            await send.react(self.bot, battle.chat_id, card_id, "🏆")
        if report.milestone:
            streak = await send.send_text(
                self.bot,
                battle.chat_id,
                views.streak_announcement(report.milestone, report.streak, battle.chat_id),
                reply_to=card_id,
            )
            if streak:
                await send.react(self.bot, battle.chat_id, streak.message_id, "🔥", big=True)
        await self.announce(battle.chat_id, report.granted)

    # ── courts ─────────────────────────────────────────────────────────

    async def refresh_court(self, court_id: str) -> None:
        trial = self.game.repo.get_court(court_id)
        if trial is None or trial.status != "active" or trial.message_id is None:
            return
        kill, spare = trial.vote_counts()
        uploader = self.game.repo.user_label(trial.pic.added_by)
        await send.edit_caption(
            self.bot,
            trial.chat_id,
            trial.message_id,
            views.court_card(trial, trial.ends_at - self.game.now(), uploader),
            keyboards.court_vote(trial.id, kill, spare),
        )

    async def finish_court(self, court_id: str) -> None:
        report = self.game.finish_court(court_id)
        if report is None:
            return
        trial = report.court
        uploader = self.game.repo.user_label(trial.pic.added_by)
        extras = [views.bounty_line(report.bounty, self.labels(report.bounty))]
        markup = None
        if report.verdict == "executed" and self.game.can_appeal(trial) and isinstance(trial.pic.added_by, int):
            extras.append(views.appeal_hint(uploader))
            markup = keyboards.appeal(trial.id)
        text = views.court_result(report, uploader, [extra for extra in extras if extra])
        card_id = await self._settle_card(trial.chat_id, trial.message_id, text, markup, photo=True)
        emoji = "🤡" if report.verdict == "executed" else "🕊"
        await send.react(self.bot, trial.chat_id, card_id, emoji, big=True)
        if trial.pic_message_id is not None:
            pic = self.game.repo.get_pic(trial.pic.id)
            if report.verdict == "executed" or pic is None:
                buttons = keyboards.more_only()
            else:
                buttons = keyboards.pic_actions(pic.id, pic.likes, pic.dislikes)
            await send.edit_markup(self.bot, trial.chat_id, trial.pic_message_id, buttons)
        await self.announce(trial.chat_id, report.granted)

    # ── caption contest ────────────────────────────────────────────────

    async def _game_loop(self, game_id: str) -> None:
        """Two phases (collect → vote), so it advances instead of finishing once."""
        while (game := self.game.repo.get_game(game_id)) is not None and game["phase"] != "done":
            remaining = game["phase_ends_at"] - self.game.now()
            if remaining <= 0:
                await self.advance_game(game_id)
                continue
            await self.refresh_game(game_id)
            await asyncio.sleep(min(TICK_SECONDS, remaining))

    async def refresh_game(self, game_id: str) -> None:
        game = self.game.repo.get_game(game_id)
        if game is None or game["phase"] == "done" or game["message_id"] is None:
            return
        markup = keyboards.caption_vote(game_id, len(game["entries"])) if game["phase"] == "vote" else None
        await send.edit_caption(
            self.bot,
            game["chat_id"],
            game["message_id"],
            views.caption_card(game, game["phase_ends_at"] - self.game.now(), game["chat_id"]),
            markup,
        )

    async def advance_game(self, game_id: str) -> None:
        outcome, game, granted = self.game.advance_caption(game_id)
        if game is None or outcome == "noop" or game["message_id"] is None:
            return
        chat_id, message_id = game["chat_id"], game["message_id"]
        if outcome == "vote":
            await self.refresh_game(game_id)
            return
        if outcome == "cancelled":
            text = views.caption_cancelled(chat_id)
        else:
            text = views.caption_result(game, self.labels(entry["user_id"] for entry in game["entries"]), chat_id)
        await send.edit_caption(self.bot, chat_id, message_id, text, keyboards.after_caption())
        if outcome == "done":
            if game.get("winner") is not None:
                await send.react(self.bot, chat_id, message_id, "🏆")
            await self.announce(chat_id, granted)

    # ── bosses ─────────────────────────────────────────────────────────

    async def refresh_boss(self, boss_id: str) -> None:
        boss = self.game.repo.get_boss(boss_id)
        if boss is None or boss["status"] != "active" or boss["message_id"] is None:
            return
        await send.edit_caption(
            self.bot,
            boss["chat_id"],
            boss["message_id"],
            views.boss_card(boss, self.labels(boss["damage"]), boss["ends_at"] - self.game.now(), boss["chat_id"]),
            keyboards.boss(boss_id, boss_rules.SUPER_PRICE),
        )

    async def finish_boss(self, boss_id: str) -> None:
        report = self.game.finish_boss(boss_id)
        if report is None:
            return
        boss = report.boss
        text = views.boss_result(report, self.labels([*boss["damage"], boss["last_hit_by"]]), boss["chat_id"])
        card_id = await self._settle_card(boss["chat_id"], boss["message_id"], text, keyboards.boss_over(), photo=True)
        await send.react(self.bot, boss["chat_id"], card_id, "🏆" if report.won else "🤡", big=report.won)
        await self.announce(boss["chat_id"], report.granted)

    # ── player challenges ──────────────────────────────────────────────

    async def _challenge_loop(self, challenge_id: str) -> None:
        challenge = self.game.repo.get_challenge(challenge_id)
        if challenge is None or challenge["status"] != "pending":
            return
        await asyncio.sleep(max(0, challenge["expires_at"] - self.game.now()))
        challenge = self.game.repo.get_challenge(challenge_id)
        if challenge is None or not self.game.expire_challenge(challenge) or challenge["message_id"] is None:
            return
        text = views.challenge_closed(challenge, self.labels([challenge["from_user"]]), "expired")
        await send.edit_text(self.bot, challenge["chat_id"], challenge["message_id"], text, None)

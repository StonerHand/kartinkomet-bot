"""Live battle and court cards: ticking timers, final results, recovery after restart."""

import asyncio
import logging

from aiogram import Bot

from bot.game import Game, Granted
from bot.tg import keyboards, send, views

LOGGER = logging.getLogger(__name__)
TICK_SECONDS = 15
# Votes are batched into one card edit per this many seconds: Telegram rate-limits edits per chat.
REFRESH_DELAY = 1.5


class Live:
    def __init__(self, bot: Bot, game: Game) -> None:
        self.bot = bot
        self.game = game
        self._tasks: dict[str, asyncio.Task] = {}
        self._pending_refresh: set[str] = set()

    # ── scheduling ─────────────────────────────────────────────────────

    def watch_battle(self, battle_id: str) -> None:
        self._spawn(f"b:{battle_id}", self._battle_loop(battle_id))

    def watch_court(self, court_id: str) -> None:
        self._spawn(f"c:{court_id}", self._court_loop(court_id))

    def request_refresh_battle(self, battle_id: str) -> None:
        self._debounce(f"rb:{battle_id}", lambda: self.refresh_battle(battle_id))

    def request_refresh_court(self, court_id: str) -> None:
        self._debounce(f"rc:{court_id}", lambda: self.refresh_court(court_id))

    def _debounce(self, key: str, refresh) -> None:
        if key in self._pending_refresh:
            return
        self._pending_refresh.add(key)

        async def run() -> None:
            await asyncio.sleep(REFRESH_DELAY)
            self._pending_refresh.discard(key)
            await refresh()

        self._spawn(f"{key}:{id(run)}", run())

    def restore(self) -> int:
        battle_ids = self.game.repo.active_battle_ids()
        court_ids = self.game.repo.active_court_ids()
        for battle_id in battle_ids:
            self.watch_battle(battle_id)
        for court_id in court_ids:
            self.watch_court(court_id)
        return len(battle_ids) + len(court_ids)

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

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

    # ── battles ────────────────────────────────────────────────────────

    async def _battle_loop(self, battle_id: str) -> None:
        while True:
            battle = self.game.repo.get_battle(battle_id)
            if battle is None or battle.status != "active":
                return
            remaining = battle.ends_at - self.game.now()
            if remaining <= 0:
                break
            await self.refresh_battle(battle_id)
            await asyncio.sleep(min(TICK_SECONDS, remaining))
        await self.finish_battle(battle_id)

    async def refresh_battle(self, battle_id: str) -> None:
        battle = self.game.repo.get_battle(battle_id)
        if battle is None or battle.status != "active" or battle.message_id is None:
            return
        await send.edit_text(
            self.bot,
            battle.chat_id,
            battle.message_id,
            views.battle_card(battle, battle.ends_at - self.game.now()),
            keyboards.battle_vote(battle.id, battle.kind, battle.vote_counts()),
        )

    async def finish_battle(self, battle_id: str) -> None:
        report = self.game.finish_battle(battle_id)
        if report is None:
            return
        battle = report.battle
        if battle.kind == "duel":
            markup = keyboards.after_duel(battle.id, battle.winner_slot is not None)
        else:
            markup = keyboards.after_tournament()
        text = views.battle_result(report, self.uploaders(battle))
        card_id = battle.message_id
        if card_id is None or not await send.edit_text(self.bot, battle.chat_id, card_id, text, markup):
            sent = await send.send_text(self.bot, battle.chat_id, text, markup)
            card_id = sent.message_id if sent else None
        if report.counted and report.winner is not None:
            await send.react(self.bot, battle.chat_id, card_id, "🏆")
        if report.milestone:
            streak_message = await send.send_text(
                self.bot,
                battle.chat_id,
                views.streak_announcement(report.milestone, report.streak, battle.chat_id),
                reply_to=card_id,
            )
            if streak_message:
                await send.react(self.bot, battle.chat_id, streak_message.message_id, "🔥", big=True)
        await self.announce(battle.chat_id, report.granted)

    def uploaders(self, battle) -> list[str]:
        return [self.game.repo.user_label(pic.added_by) for pic in battle.pics]

    # ── courts ─────────────────────────────────────────────────────────

    async def _court_loop(self, court_id: str) -> None:
        while True:
            trial = self.game.repo.get_court(court_id)
            if trial is None or trial.status != "active":
                return
            remaining = trial.ends_at - self.game.now()
            if remaining <= 0:
                break
            await self.refresh_court(court_id)
            await asyncio.sleep(min(TICK_SECONDS, remaining))
        await self.finish_court(court_id)

    async def refresh_court(self, court_id: str) -> None:
        trial = self.game.repo.get_court(court_id)
        if trial is None or trial.status != "active" or trial.message_id is None:
            return
        kill, spare = trial.vote_counts()
        await send.edit_caption(
            self.bot,
            trial.chat_id,
            trial.message_id,
            views.court_card(
                trial,
                trial.ends_at - self.game.now(),
                self.game.repo.user_label(trial.pic.added_by),
            ),
            keyboards.court_vote(trial.id, kill, spare),
        )

    async def finish_court(self, court_id: str) -> None:
        report = self.game.finish_court(court_id)
        if report is None:
            return
        trial = report.court
        uploader = self.game.repo.user_label(trial.pic.added_by)
        text = views.court_result(report, uploader)
        card_id = trial.message_id
        if card_id is None or not await send.edit_caption(self.bot, trial.chat_id, card_id, text, None):
            sent = await send.send_text(self.bot, trial.chat_id, text)
            card_id = sent.message_id if sent else None
        await send.react(
            self.bot, trial.chat_id, card_id, "🤡" if report.verdict == "executed" else "🕊", big=True
        )
        if trial.pic_message_id is not None:
            pic = self.game.repo.get_pic(trial.pic.id)
            if report.verdict == "executed" or pic is None:
                markup = keyboards.more_only()
            else:
                markup = keyboards.pic_actions(pic.id, pic.likes, pic.dislikes)
            await send.edit_markup(self.bot, trial.chat_id, trial.pic_message_id, markup)
        await self.announce(trial.chat_id, report.granted)

    # ── achievements ───────────────────────────────────────────────────

    async def announce(self, chat_id: int, granted: list[Granted]) -> None:
        for item in granted:
            message = await send.send_text(
                self.bot,
                chat_id,
                views.achievements_unlocked(item, self.game.repo.user_label(item.user_id)),
            )
            if message:
                await send.react(self.bot, chat_id, message.message_id, "🎉")

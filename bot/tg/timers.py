"""Live battle and court cards: ticking timers, final results, recovery after restart."""

import asyncio
import logging

from aiogram import Bot

from bot.core import boss as boss_rules
from bot.game import Game, Granted
from bot.tg import keyboards, send, views

LOGGER = logging.getLogger(__name__)
TICK_SECONDS = 15
# A battle nobody voted in gets one overtime instead of ending empty.
OVERTIME_SECONDS = 30
# Votes are batched into one card edit per this many seconds: Telegram rate-limits edits per chat.
REFRESH_DELAY = 1.5


# Notes that put a chest in someone's backpack: kind → tier (None = the note's own code).
CHEST_OF_NOTE = {"chest": None, "quests_all": "wood", "challenge": "rare", "challenges_all": "legend"}


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

    def watch_game(self, game_id: str) -> None:
        self._spawn(f"g:{game_id}", self._game_loop(game_id))

    def watch_boss(self, boss_id: str) -> None:
        self._spawn(f"boss:{boss_id}", self._boss_loop(boss_id))

    def watch_challenge(self, challenge_id: str) -> None:
        self._spawn(f"cl:{challenge_id}", self._challenge_loop(challenge_id))

    def request_refresh_boss(self, boss_id: str) -> None:
        self._debounce(f"rboss:{boss_id}", lambda: self.refresh_boss(boss_id))

    def request_refresh_game(self, game_id: str) -> None:
        self._debounce(f"rg:{game_id}", lambda: self.refresh_game(game_id))

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
        game_ids = self.game.repo.active_game_ids()
        boss_ids = self.game.repo.active_boss_ids()
        challenges = self.game.repo.pending_challenge_ids()
        for boss_id in boss_ids:
            self.watch_boss(boss_id)
        for challenge_id in challenges:
            self.watch_challenge(challenge_id)
        for battle_id in battle_ids:
            self.watch_battle(battle_id)
        for court_id in court_ids:
            self.watch_court(court_id)
        for game_id in game_ids:
            self.watch_game(game_id)
        return len(battle_ids) + len(court_ids) + len(game_ids) + len(boss_ids) + len(challenges)

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
                if not battle.votes and not battle.extended:
                    if self.game.repo.extend_battle(battle_id, OVERTIME_SECONDS):
                        continue
                break
            await self.refresh_battle(battle_id)
            await asyncio.sleep(min(TICK_SECONDS, remaining))
        await self.finish_battle(battle_id)

    def battle_text(self, battle, remaining: int) -> str:
        fighters = None
        if battle.mode == "challenge":
            challenge = self.game.repo.challenge_for_battle(battle.id)
            if challenge:
                labels = self.labels([challenge["from_user"], challenge["to_user"]])
                first, second = (views.who(labels[challenge[key]]) for key in ("from_user", "to_user"))
                fighters = f"🤺 A — <b>{first}</b> · B — <b>{second}</b>\n💰 На кону {views.money(challenge['stake'] * 2)}"
        flipped = battle.kind == "duel" and battle.mode == "" and self.game.day_is("upside_down")
        return views.battle_card(battle, remaining, fighters, flipped)

    def labels(self, user_ids) -> dict[int, str]:
        return {user_id: self.game.repo.user_label(user_id) for user_id in user_ids if isinstance(user_id, int)}

    async def refresh_battle(self, battle_id: str) -> None:
        battle = self.game.repo.get_battle(battle_id)
        if battle is None or battle.status != "active" or battle.message_id is None:
            return
        await self.edit_card(
            battle,
            self.battle_text(battle, battle.ends_at - self.game.now()),
            keyboards.battle_vote(battle.id, battle.kind, battle.vote_counts()),
        )

    async def edit_card(self, battle, text: str, markup) -> bool:
        edit = send.edit_caption if battle.card_is_photo else send.edit_text
        return await edit(self.bot, battle.chat_id, battle.message_id, text, markup)

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
        guessers = [self.game.repo.user_label(user_id) for user_id in report.guessers]
        people = [*report.bets, *report.bounty]
        if report.challenge:
            people += [report.challenge["from_user"], report.challenge["to_user"]]
        labels = self.labels(people)
        extras = []
        if report.challenge:
            extras.append("\n".join([views.challenge_names(report, labels), *views.challenge_result(report, labels, battle.chat_id)]))
        extras.append("\n".join(views.evolution_lines(report)))
        extras.append("\n".join(views.bets_result(report, labels)))
        extras.append(views.bounty_line(report.bounty, labels) or "")
        text = views.battle_result(report, self.uploaders(battle), guessers, [block for block in extras if block])
        card_id = battle.message_id
        if card_id is None or not await self.edit_card(battle, text, markup):
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
        extras = []
        bounty = views.bounty_line(report.bounty, self.labels(report.bounty))
        if bounty:
            extras.append(bounty)
        markup = None
        if report.verdict == "executed" and self.game.can_appeal(trial) and isinstance(trial.pic.added_by, int):
            extras.append(views.appeal_hint(uploader))
            markup = keyboards.appeal(trial.id)
        text = views.court_result(report, uploader, extras)
        card_id = trial.message_id
        if card_id is None or not await send.edit_caption(self.bot, trial.chat_id, card_id, text, markup):
            sent = await send.send_text(self.bot, trial.chat_id, text, markup)
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

    # ── caption contest ────────────────────────────────────────────────

    async def _game_loop(self, game_id: str) -> None:
        while True:
            game = self.game.repo.get_game(game_id)
            if game is None or game["phase"] == "done":
                return
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
        elif outcome == "cancelled":
            await send.edit_caption(
                self.bot, chat_id, message_id, views.caption_cancelled(chat_id), keyboards.after_caption()
            )
        elif outcome == "done":
            labels = {
                user_id: self.game.repo.user_label(user_id)
                for user_id in [entry["user_id"] for entry in game["entries"]]
            }
            await send.edit_caption(
                self.bot,
                chat_id,
                message_id,
                views.caption_result(game, labels, chat_id),
                keyboards.after_caption(),
            )
            if game.get("winner") is not None:
                await send.react(self.bot, chat_id, message_id, "🏆")
            await self.announce(chat_id, granted)

    # ── achievements ───────────────────────────────────────────────────

    async def announce(self, chat_id: int, granted: list[Granted]) -> None:
        """One message per event, however many people got something."""
        if not granted:
            return
        items = [(self.game.repo.user_label(item.user_id), item) for item in granted]
        tiers = [CHEST_OF_NOTE[note.kind] or note.code for item in granted for note in item.notes if note.kind in CHEST_OF_NOTE]
        message = await send.send_text(self.bot, chat_id, views.announcement(items), keyboards.open_chests(tiers))
        if message:
            legendary = views.has_legendary(granted)
            await send.react(self.bot, chat_id, message.message_id, "🔥" if legendary else "🎉", big=legendary)

    # ── bosses ─────────────────────────────────────────────────────────

    async def _boss_loop(self, boss_id: str) -> None:
        while True:
            boss = self.game.repo.get_boss(boss_id)
            if boss is None or boss["status"] != "active":
                return
            remaining = boss["ends_at"] - self.game.now()
            if remaining <= 0 or boss["hp"] <= 0:
                break
            await self.refresh_boss(boss_id)
            await asyncio.sleep(min(TICK_SECONDS, remaining))
        await self.finish_boss(boss_id)

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
        labels = self.labels([*boss["damage"], boss["last_hit_by"]])
        text = views.boss_result(report, labels, boss["chat_id"])
        card_id = boss["message_id"]
        if card_id is None or not await send.edit_caption(self.bot, boss["chat_id"], card_id, text, keyboards.boss_over()):
            sent = await send.send_text(self.bot, boss["chat_id"], text, keyboards.boss_over())
            card_id = sent.message_id if sent else None
        await send.react(self.bot, boss["chat_id"], card_id, "🏆" if report.won else "🤡", big=report.won)
        await self.announce(boss["chat_id"], report.granted)

    # ── player challenges ──────────────────────────────────────────────

    async def _challenge_loop(self, challenge_id: str) -> None:
        challenge = self.game.repo.get_challenge(challenge_id)
        if challenge is None or challenge["status"] != "pending":
            return
        await asyncio.sleep(max(0, challenge["expires_at"] - self.game.now()))
        challenge = self.game.repo.get_challenge(challenge_id)
        if challenge is None or not self.game.expire_challenge(challenge):
            return
        if challenge["message_id"] is not None:
            labels = self.labels([challenge["from_user"]])
            await send.edit_text(
                self.bot,
                challenge["chat_id"],
                challenge["message_id"],
                views.challenge_closed(challenge, labels, "expired"),
                None,
            )

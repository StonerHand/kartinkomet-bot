"""Scheduled events: event of the day, pic of the day, the daily boss, evening auto-court,
weekly digest, daily backup, plus a one-time v4 release note.

A loop wakes every minute, works in the chats' local time (BOT_TZ_OFFSET) and marks each
job done in `meta`, so a restart never repeats or skips a day. A job only fires within
WINDOW_HOURS after its time: a bot that was down all day doesn't post a stale digest at night.
"""

import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from bot.core import days, economy
from bot.game import Game
from bot.texts import events as texts
from bot.texts.pick import pick
from bot.texts import ui
from bot.tg import cards, keyboards, send, views
from bot.tg.boss import summon
from bot.tg.court import open_court
from bot.tg.timers import Live

LOGGER = logging.getLogger(__name__)
TICK_SECONDS = 60
WINDOW_HOURS = 3
ACTIVE_CHAT_DAYS = 14


@dataclass(frozen=True)
class Job:
    name: str
    hour: int
    weekday: int | None  # 0 = Monday … 6 = Sunday; None = every day
    per_chat: bool


JOBS = (
    Job("backup", 4, None, per_chat=False),
    Job("day_event", days.START_HOUR, None, per_chat=True),
    Job("pic_of_the_day", 12, None, per_chat=True),
    Job("boss", 16, None, per_chat=True),
    Job("auto_court", 19, None, per_chat=True),
    Job("weekly", 18, 6, per_chat=True),
)
RELEASE_KEY = "release_note_v4"


class Events:
    def __init__(self, bot: Bot, game: Game, live: Live, admins: frozenset[int], tz_offset_hours: int) -> None:
        self.bot = bot
        self.game = game
        self.live = live
        self.admins = admins
        self.offset = timedelta(hours=tz_offset_hours)
        self._task: asyncio.Task | None = None
        self.handlers: dict[str, Callable[..., Awaitable[bool]]] = {
            "backup": self.backup,
            "pic_of_the_day": self.pic_of_the_day,
            "auto_court": self.auto_court,
            "weekly": self.weekly,
            "day_event": self.day_event,
            "boss": self.daily_boss,
        }

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # one bad tick must not kill the scheduler
                LOGGER.exception("Scheduled events tick failed")
            await asyncio.sleep(TICK_SECONDS)

    def local_now(self) -> datetime:
        return datetime.fromtimestamp(self.game.now(), UTC) + self.offset

    async def tick(self) -> None:
        await self.release_note()
        local = self.local_now()
        for job in JOBS:
            if job.weekday is not None and local.weekday() != job.weekday:
                continue
            if not job.hour <= local.hour < job.hour + WINDOW_HOURS:
                continue
            period = local.strftime("%G-W%V") if job.weekday is not None else local.date().isoformat()
            targets = self.chats() if job.per_chat else [None]
            for chat_id in targets:
                key = f"event:{job.name}:{chat_id or 'global'}:{period}"
                if self.game.repo.meta_str(key):
                    continue
                # Mark first: a job that keeps failing must not retry every minute.
                self.game.repo.set_meta(key, self.game.now())
                handler = self.handlers[job.name]
                done = await (handler(chat_id) if job.per_chat else handler())
                LOGGER.info("Event %s for %s: %s", job.name, chat_id, "sent" if done else "skipped")

    def chats(self) -> list[int]:
        return self.game.repo.event_chats(self.game.now() - ACTIVE_CHAT_DAYS * 86400)

    # ── jobs ───────────────────────────────────────────────────────────

    async def release_note(self) -> None:
        """Once per chat after the v4 deploy: what's new and the starter coins."""
        if self.game.repo.meta_str(RELEASE_KEY):
            return
        self.game.repo.set_meta(RELEASE_KEY, self.game.now())
        for chat_id in self.chats():
            await send.send_text(self.bot, chat_id, ui.RELEASE_V4, keyboards.release_v4())

    async def day_event(self, chat_id: int) -> bool:
        code, _ = self.game.roll_day_event()
        text = cards.day_event(code, chat_id, self.game.tax_report())
        message = await send.send_text(self.bot, chat_id, text)
        if message is None:
            return False
        await send.react(self.bot, chat_id, message.message_id, "⚡")
        if code == "invasion":
            await summon(self.bot, self.game, self.live, chat_id, double=True, forced=True)
        return True

    async def daily_boss(self, chat_id: int) -> bool:
        return await summon(self.bot, self.game, self.live, chat_id, forced=True) == "started"

    async def pic_of_the_day(self, chat_id: int) -> bool:
        repo = self.game.repo
        yesterday = repo.meta_str(f"potd_last:{chat_id}")
        exclude = [yesterday] if yesterday else []
        pic = repo.most_liked_since(self.game.now() - 86400, exclude=exclude)
        phrase_pool = texts.PIC_OF_THE_DAY
        if pic is None:
            legends = [candidate for candidate in repo.top_rated(20) if candidate.id not in exclude]
            if not legends:
                return False
            pic = legends[self.game.rng.randrange(len(legends))]
            phrase_pool = texts.PIC_OF_THE_DAY_FALLBACK
        uploader = repo.user_label(pic.added_by) if pic.added_by else None
        caption = views.card("🌅 <b>ПИКЧА ДНЯ</b>", pick(phrase_pool, chat_id), views.pic_footer(pic, uploader))
        message = await send.send_photo(
            self.bot, chat_id, pic.file_id, caption, keyboards.pic_actions(pic.id, pic.likes, pic.dislikes)
        )
        if message is None:
            return False
        repo.set_meta(f"potd_last:{chat_id}", pic.id)
        repo.set_meta(f"potd_day:{pic.id}", self.game.local_day())  # for the "jackpot" achievement
        await send.react(self.bot, chat_id, message.message_id, "❤", big=True)
        return True

    async def auto_court(self, chat_id: int) -> bool:
        pic = self.game.repo.worst_triable(self.game.now())
        if pic is None:
            return False
        await send.send_text(self.bot, chat_id, f"<b>{escape(pick(texts.AUTO_COURT, chat_id))}</b>")
        status = await open_court(self.bot, self.game, self.live, chat_id, pic.id, "bottom", None)
        return status == "started"

    async def weekly(self, chat_id: int) -> bool:
        repo = self.game.repo
        summary = repo.week_summary(chat_id, self.game.now() - 7 * 86400)
        crowns = self.game.crown_week()
        if not summary["battles"] and not summary["likes"] and not summary["uploads"] and not crowns:
            return False
        numbers = [
            f"⚔️ Боёв: <b>{summary['battles']}</b> · ⚰️ казнено: <b>{summary['executed']}</b>",
            f"🤙🏻 <b>{summary['likes']}</b> · 🖕🏻 <b>{summary['dislikes']}</b> за неделю",
            f"🔥 Лучшая серия недели: <b>{summary['best_streak']}</b>" if summary["best_streak"] > 1 else "",
        ]
        uploaders = ["<b>📥 Грузили больше всех</b>"] + [
            f"{views.MEDALS[index]} {views.who(repo.user_label(user_id))} — <b>{count}</b>"
            for index, (user_id, count) in enumerate(summary["uploads"])
        ] if summary["uploads"] else []
        crown_lines = ["<b>👑 Короны недели</b> <i>(висят у имени до следующего воскресенья)</i>"] + [
            f"{economy.CROWNS[kind][0]} {escape(economy.CROWNS[kind][1])} — <b>{views.who(repo.user_label(user_id))}</b>"
            for kind, (user_id, _) in crowns.items()
        ] if crowns else []
        top_pic = summary["top_pic"]
        photo_note = "🏅 <i>На фото — самая залайканная пикча недели</i>" if top_pic is not None else None
        text = views.card(
            "📅 <b>ИТОГИ НЕДЕЛИ</b>", pick(texts.WEEKLY, chat_id), numbers, uploaders, crown_lines, photo_note
        )
        if top_pic is not None:
            message = await send.send_photo(self.bot, chat_id, top_pic.file_id, text)
        else:
            message = await send.send_text(self.bot, chat_id, text)
        return message is not None

    async def backup(self) -> bool:
        if not self.admins:
            return False
        stamp = self.local_now().strftime("%Y-%m-%d")
        sent = False
        with tempfile.TemporaryDirectory(prefix="kartinkomet-") as temp_dir:
            path = Path(temp_dir) / f"kartinkomet-{stamp}.sqlite"
            self.game.repo.export_backup(path)
            for admin_id in self.admins:
                try:
                    await self.bot.send_document(
                        admin_id,
                        FSInputFile(path, filename=path.name),
                        caption=texts.BACKUP_CAPTION,
                        disable_notification=True,
                    )
                    sent = True
                except TelegramAPIError:
                    LOGGER.warning("Backup not delivered to admin %s (did they /start the bot?)", admin_id)
        return sent

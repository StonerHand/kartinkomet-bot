"""Uploading pics in a private chat, with exact and visual duplicate checks."""

import logging
from dataclasses import dataclass, field
from io import BytesIO
from time import monotonic

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.game import Game
from bot.texts import ui
from bot.texts.pick import pick
from bot.tg import keyboards, send, views
from bot.tg.timers import Live
from bot.visual_hash import image_dhash

LOGGER = logging.getLogger(__name__)
router = Router(name="upload")

VISUAL_DUPLICATE_DISTANCE = 4
BURST_LIMIT = 120
BURST_WINDOW = 60.0
MAX_HASH_DOWNLOAD = 10 * 1024 * 1024
PANEL_EVERY = 5


@dataclass
class Session:
    intro: str
    panel_message_id: int | None = None
    added: int = 0
    duplicates: int = 0
    failed: int = 0
    events: list[float] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return self.added + self.duplicates + self.failed


sessions: dict[int, Session] = {}
_visual_hashes: list[int] | None = None


def known_hashes(game: Game) -> list[int]:
    global _visual_hashes
    if _visual_hashes is None:
        _visual_hashes = []
        for value in game.repo.visual_hashes():
            try:
                _visual_hashes.append(int(value, 16))
            except ValueError:
                continue
    return _visual_hashes


def is_visual_duplicate(game: Game, visual_hash: str | None) -> bool:
    if not visual_hash:
        return False
    value = int(visual_hash, 16)
    return any((value ^ known).bit_count() <= VISUAL_DUPLICATE_DISTANCE for known in known_hashes(game))


def image_of(message: Message) -> tuple[str, str, int | None] | None:
    if message.photo:
        photo = message.photo[-1]
        return photo.file_id, photo.file_unique_id, photo.file_size
    document = message.document
    if document and (document.mime_type or "").startswith("image/"):
        return document.file_id, document.file_unique_id, document.file_size
    return None


async def visual_hash_of(bot: Bot, file_id: str, size: int | None) -> str | None:
    if size is not None and size > MAX_HASH_DOWNLOAD:
        return None
    try:
        telegram_file = await send.retry(lambda: bot.get_file(file_id), "get_file")
        if not telegram_file.file_path:
            return None
        buffer = BytesIO()
        await send.retry(
            lambda: bot.download_file(telegram_file.file_path, destination=buffer), "download"
        )
        return image_dhash(buffer.getvalue())
    except TelegramAPIError:
        LOGGER.warning("Visual hash failed", exc_info=True)
        return None


async def redraw(bot: Bot, chat_id: int, session: Session, force: bool = False) -> None:
    if session.panel_message_id is None:
        return
    if not force and session.processed > 3 and session.processed % PANEL_EVERY:
        return
    await send.edit_text(
        bot,
        chat_id,
        session.panel_message_id,
        views.upload_progress(session.intro, session.added, session.duplicates, session.failed),
        keyboards.uploading(),
    )


async def begin(bot: Bot, message: Message, user_id: int) -> None:
    if message.chat.type != "private":
        await message.answer(ui.UPLOAD_PRIVATE_ONLY, parse_mode="HTML")
        return
    session = sessions.get(user_id)
    if session is None:
        session = Session(intro=pick(ui.UPLOAD_START, user_id))
        sessions[user_id] = session
    panel = await send.send_text(
        bot,
        message.chat.id,
        views.upload_progress(session.intro, session.added, session.duplicates, session.failed),
        keyboards.uploading(),
    )
    if panel is not None:
        if session.panel_message_id is not None:
            await send.delete(bot, message.chat.id, session.panel_message_id)
        session.panel_message_id = panel.message_id


async def end(bot: Bot, chat_id: int, user_id: int, cancelled: bool) -> None:
    session = sessions.pop(user_id, None)
    if session is None:
        await send.send_text(bot, chat_id, ui.UPLOAD_NOT_ACTIVE)
        return
    closing = pick(ui.UPLOAD_CANCELLED if cancelled else ui.UPLOAD_FINISH, user_id)
    text = views.upload_progress(closing, session.added, session.duplicates, session.failed)
    if session.panel_message_id is None or not await send.edit_text(
        bot, chat_id, session.panel_message_id, text, None
    ):
        await send.send_text(bot, chat_id, text)
    if not cancelled and session.added:
        await send.send_with_effect(
            bot,
            chat_id,
            f"🎉 <b>+{session.added}</b> на склад. Они уже в рандоме",
            send.EFFECT_PARTY,
        )


@router.message(Command("upload", "upload_pidor"))
async def upload_command(message: Message, bot: Bot) -> None:
    if message.from_user:
        await begin(bot, message, message.from_user.id)


@router.message(Command("done"))
async def done_command(message: Message, bot: Bot) -> None:
    if message.from_user:
        await end(bot, message.chat.id, message.from_user.id, cancelled=False)


@router.message(Command("cancel"))
async def cancel_command(message: Message, bot: Bot) -> None:
    if message.from_user:
        await end(bot, message.chat.id, message.from_user.id, cancelled=True)


@router.callback_query(F.data.startswith("up:"))
async def upload_buttons(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    if callback.message is None:
        return
    action = callback.data.split(":", 1)[1]
    if action == "start":
        await begin(bot, callback.message, callback.from_user.id)
    else:
        await end(bot, callback.message.chat.id, callback.from_user.id, cancelled=action == "cancel")


@router.message(F.chat.type == "private", F.photo | F.document)
async def receive(message: Message, bot: Bot, game: Game, live: Live) -> None:
    if message.from_user is None:
        return
    user_id = message.from_user.id
    session = sessions.get(user_id)
    if session is None:
        if image_of(message):
            await message.answer("Хочешь закинуть на склад? Сначала /upload")
        return

    image = image_of(message)
    now = monotonic()
    session.events = [event for event in session.events if event >= now - BURST_WINDOW]
    session.events.append(now)
    if image is None or len(session.events) > BURST_LIMIT or game.upload_rate_limited(user_id):
        session.failed += 1
        await redraw(bot, message.chat.id, session, force=True)
        return

    file_id, file_unique_id, size = image
    if game.repo.pic_known(file_unique_id):
        session.duplicates += 1
        game.note_duplicate(user_id)
        await redraw(bot, message.chat.id, session)
        return

    visual_hash = await visual_hash_of(bot, file_id, size)
    if is_visual_duplicate(game, visual_hash) or game.repo.pic_known(file_unique_id):
        session.duplicates += 1
        game.note_duplicate(user_id)
        await redraw(bot, message.chat.id, session)
        return

    added = game.add_pic(file_id, file_unique_id, user_id, visual_hash)
    if added is None:
        session.duplicates += 1
        game.note_duplicate(user_id)
        await redraw(bot, message.chat.id, session)
        return
    _, granted = added
    if visual_hash:
        known_hashes(game).append(int(visual_hash, 16))
    session.added += 1
    await redraw(bot, message.chat.id, session)
    await live.announce(message.chat.id, granted)

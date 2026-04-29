import asyncio
import logging
import random
from datetime import date
from html import escape
from typing import Literal, TypedDict
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InputMediaPhoto, Message, ReplyKeyboardRemove

from bot.image_pool import UPLOAD_LIMIT_PER_HOUR, ImagePool
from bot.keyboards import duel_vote, main_menu, new_duel, picture_actions, picture_actions_with_counts, upload_menu
from bot.texts import (
    ACHIEVEMENTS,
    AUTO_DELETE_DISLIKES,
    BOT_MOODS,
    DUEL_START_PHRASES,
    DUEL_STATUS_PHRASES,
    DUEL_TIE_PHRASES,
    DUEL_WIN_PHRASES,
    EMPTY_POOL_PHRASES,
    JURY_THRESHOLDS,
    PICTURE_CAPTIONS,
    UPLOAD_FINISH_PHRASES,
    UPLOAD_START_PHRASES,
)

UPLOAD_COMMAND = "upload_pidor"
DUEL_SECONDS = 60
RANDOM = random.SystemRandom()
LOGGER = logging.getLogger(__name__)


class UploadSession(TypedDict):
    added: int
    failed: int
    duplicates: int
    ack_sent: bool


DuelStartResult = Literal["started", "active", "failed"]


active_uploads: dict[int, UploadSession] = {}
duel_sessions: dict[str, dict] = {}
active_duels_by_chat: dict[int, str] = {}
duel_locks: dict[int, asyncio.Lock] = {}


class AddPicture(StatesGroup):
    uploading = State()


def build_router(
    image_pool: ImagePool,
    target_channel_id: str | None = None,
    admin_user_ids: frozenset[int] = frozenset(),
) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await message.answer(
            format_start(),
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        await show_menu(message)

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await message.answer(format_help(), parse_mode="HTML")

    @router.message(Command("menu"))
    async def menu_command(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await message.answer("Пульт обновлён", reply_markup=ReplyKeyboardRemove())
        await show_menu(message)

    @router.message(Command("pic"))
    @router.channel_post(Command("pic"))
    async def send_random_picture(message: Message, bot: Bot) -> None:
        image_pool.remember_user(message.from_user)
        await send_picture(
            bot=bot,
            chat_id=message.chat.id,
            image_pool=image_pool,
            target_channel_id=target_channel_id,
            answer_message=message,
        )

    @router.message(Command("count"))
    @router.channel_post(Command("count"))
    async def count_pictures(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await message.answer(format_count(image_pool), parse_mode="HTML")

    @router.message(Command("stats"))
    @router.channel_post(Command("stats"))
    async def stats_command(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await message.answer(format_stats(image_pool), parse_mode="HTML")

    @router.message(Command("me"))
    async def my_uploads_command(message: Message) -> None:
        if message.from_user is None:
            return

        image_pool.remember_user(message.from_user)
        await message.answer(
            format_user_progress(message.from_user.id, image_pool),
            parse_mode="HTML",
        )

    @router.message(Command("top"))
    async def top_uploaders_command(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await message.answer(format_top_uploaders(image_pool), parse_mode="HTML")

    @router.message(Command("duel"))
    async def duel_command(message: Message, bot: Bot) -> None:
        image_pool.remember_user(message.from_user)
        await send_duel(bot=bot, message=message, image_pool=image_pool)

    @router.message(Command("reset_stats"))
    @router.channel_post(Command("reset_stats"))
    async def reset_stats_command(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        if not is_admin(message, admin_user_ids):
            await message.answer(format_admin_only("Сброс статистики"))
            return

        image_pool.reset_stats()
        await message.answer(format_reset_stats_done(), parse_mode="HTML")

    @router.message(Command("dedupe_user"))
    async def dedupe_user_command(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        if not is_admin(message, admin_user_ids):
            await message.answer(format_admin_only("Чистка дублей"))
            return

        target_user_id = parse_user_id_argument(message)
        if target_user_id is None:
            await message.answer(format_dedupe_usage(), parse_mode="HTML")
            return

        result = image_pool.dedupe_user(target_user_id)
        await message.answer(format_dedupe_result(result), parse_mode="HTML")

    @router.message(Command("mood"))
    @router.channel_post(Command("mood"))
    async def mood_command(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await message.answer(format_mood(), parse_mode="HTML")

    @router.message(Command("id"))
    async def user_id(message: Message) -> None:
        if message.from_user is None:
            await message.answer("Не смог определить user ID")
            return

        image_pool.remember_user(message.from_user)
        await message.answer(format_user_id(message.from_user.id), parse_mode="HTML")

    @router.message(Command(UPLOAD_COMMAND))
    @router.channel_post(Command(UPLOAD_COMMAND))
    async def start_upload(message: Message, state: FSMContext) -> None:
        image_pool.remember_user(message.from_user)
        await activate_upload(message, state)

    @router.message(Command("done"))
    @router.channel_post(Command("done"))
    async def done_upload(message: Message, state: FSMContext) -> None:
        image_pool.remember_user(message.from_user)
        await finish_upload_or_warn(message, state)

    @router.message(Command("cancel"))
    @router.channel_post(Command("cancel"))
    async def cancel_upload_command(message: Message, state: FSMContext) -> None:
        image_pool.remember_user(message.from_user)
        await cancel_upload(message, state)

    @router.message(F.photo | F.document)
    @router.channel_post(F.photo | F.document)
    async def save_picture(message: Message, state: FSMContext) -> None:
        image_pool.remember_user(message.from_user)
        if not is_upload_active(message):
            return

        data = upload_data(message)
        added = int(data.get("added", 0))
        failed = int(data.get("failed", 0))
        duplicates = int(data.get("duplicates", 0))
        ack_sent = bool(data.get("ack_sent", False))

        result = image_pool.add_from_message(message)
        if result.added:
            data.update(
                {
                    "added": added + 1,
                    "failed": failed,
                    "duplicates": duplicates,
                    "ack_sent": True,
                }
            )
            if not ack_sent:
                await message.answer(
                    "<b>✅ Пикчи принимаю</b>\n\n"
                    "Когда всё закинули — нажми <code>✅ Закончить</code>\n"
                    "Если передумали — <code>❌ Отмена</code>",
                    parse_mode="HTML",
                    reply_markup=upload_menu(),
                )
            achievement = achievement_for(message, image_pool)
            if achievement:
                await message.answer(achievement, parse_mode="HTML")
            return

        if result.duplicate:
            data.update({"added": added, "failed": failed, "duplicates": duplicates + 1})
            await message.answer(format_duplicate_skipped())
            return

        if result.rate_limited:
            await message.answer(format_upload_limit(), parse_mode="HTML")
            return

        data.update({"added": added, "failed": failed + 1, "duplicates": duplicates})
        await message.answer(format_invalid_file())

    @router.callback_query(F.data == "pic")
    async def pic_callback(callback: CallbackQuery, bot: Bot) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message is None:
            await callback.answer()
            return

        await send_picture(
            bot=bot,
            chat_id=callback.message.chat.id,
            image_pool=image_pool,
            target_channel_id=target_channel_id,
        )
        await callback.answer()

    @router.callback_query(F.data == "count")
    async def count_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        await callback.answer(f"📦 В пуле пикч: {image_pool.count()}", show_alert=True)

    @router.callback_query(F.data == "stats")
    async def stats_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message:
            await callback.message.answer(format_stats(image_pool), parse_mode="HTML")
        await callback.answer()

    @router.callback_query(F.data == "me")
    async def me_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message:
            await callback.message.answer(
                format_user_progress(callback.from_user.id, image_pool),
                parse_mode="HTML",
            )
        await callback.answer()

    @router.callback_query(F.data == "top")
    async def top_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message:
            await callback.message.answer(format_top_uploaders(image_pool), parse_mode="HTML")
        await callback.answer()

    @router.callback_query(F.data == "upload")
    async def upload_callback(callback: CallbackQuery, state: FSMContext) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message is None:
            await callback.answer()
            return

        activated = await activate_upload(callback.message, state)
        await callback.answer("Загрузка открыта" if activated else "Открой личку с ботом")

    @router.callback_query(F.data == "done")
    async def done_callback(callback: CallbackQuery, state: FSMContext) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message is None:
            await callback.answer()
            return

        current_state = await state.get_state()
        if current_state != AddPicture.uploading.state and not is_upload_active(callback.message):
            await callback.answer("Загрузка уже закрыта", show_alert=False)
            return

        await finish_upload_or_warn(callback.message, state)
        await callback.answer()

    @router.callback_query(F.data == "cancel_upload")
    async def cancel_upload_callback(callback: CallbackQuery, state: FSMContext) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message is None:
            await callback.answer()
            return

        current_state = await state.get_state()
        if current_state != AddPicture.uploading.state and not is_upload_active(callback.message):
            await callback.answer("Загрузка уже закрыта", show_alert=False)
            return

        await cancel_upload(callback.message, state)
        await callback.answer()

    @router.callback_query(F.data.startswith("react:"))
    async def react_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.data is None:
            await callback.answer()
            return

        _, reaction, image_id = callback.data.split(":", 2)
        reaction_update = image_pool.react(image_id, reaction, callback.from_user.id)
        if reaction_update is None:
            await callback.answer("Не нашёл эту пикчу", show_alert=True)
            return

        image = reaction_update.image
        if callback.message:
            if (
                reaction_update.changed
                and reaction == "dislike"
                and image.dislikes >= AUTO_DELETE_DISLIKES
            ):
                image_pool.delete(image.id)
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                    await callback.message.reply("Два средних пальца. Пикча удалена из пула")
                except TelegramAPIError:
                    LOGGER.warning("Failed to mark auto-deleted image message", exc_info=True)
                await callback.answer("Народный суд сработал")
                return

            try:
                await callback.message.edit_reply_markup(
                    reply_markup=picture_actions_with_counts(
                        image_id=image.id,
                        likes=image.likes,
                        fires=image.fires,
                        dislikes=image.dislikes,
                    )
                )
            except TelegramAPIError:
                LOGGER.warning("Failed to update reaction buttons", exc_info=True)
            jury_message = jury_verdict(image.dislikes)
            if reaction_update.changed and reaction == "dislike" and jury_message:
                try:
                    await callback.message.reply(jury_message)
                except TelegramAPIError:
                    LOGGER.warning("Failed to send jury warning", exc_info=True)

        await callback.answer("Засчитано" if reaction_update.changed else "Уже стоит")

    @router.callback_query(F.data.startswith("duel:"))
    async def duel_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.data is None:
            await callback.answer()
            return

        _, duel_id, side = callback.data.split(":", 2)
        duel = duel_sessions.get(duel_id)
        if duel is None:
            await callback.answer("Дуэль уже растворилась в истории", show_alert=True)
            return
        if not duel.get("active", False):
            await callback.answer("Дуэль уже закончилась", show_alert=True)
            return

        votes = duel["votes"]
        votes[str(callback.from_user.id)] = side
        left_votes = sum(1 for vote in votes.values() if vote == "left")
        right_votes = sum(1 for vote in votes.values() if vote == "right")
        if callback.message:
            try:
                await callback.message.edit_text(
                    format_duel_score(
                        left_votes,
                        right_votes,
                        title=str(duel.get("title") or random_duel_start_phrase()),
                        status=str(duel.get("status") or random_duel_status_phrase()),
                    ),
                    parse_mode="HTML",
                    reply_markup=duel_vote(duel_id, left_votes, right_votes),
                )
            except TelegramAPIError:
                LOGGER.warning("Failed to update duel vote message", exc_info=True)
        await callback.answer("Голос принят")

    @router.callback_query(F.data == "duel_new")
    async def new_duel_callback(callback: CallbackQuery, bot: Bot) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message is None:
            await callback.answer()
            return

        duel_result = await send_duel(
            bot=bot,
            message=callback.message,
            image_pool=image_pool,
            silent_if_active=True,
        )
        if duel_result == "started":
            await callback.answer("Запускаю новую дуэль")
        elif duel_result == "active":
            await callback.answer("Дуэль уже идёт")
        else:
            await callback.answer("Дуэль не запустилась")

    @router.message(F.text == "Помощь")
    async def help_button(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await help_command(message)

    @router.message()
    @router.channel_post()
    async def fallback(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        if is_upload_active(message):
            data = upload_data(message)
            failed = int(data.get("failed", 0))
            data["failed"] = failed + 1
            await message.answer(format_invalid_file())

    return router


async def send_picture(
    bot: Bot,
    chat_id: int,
    image_pool: ImagePool,
    target_channel_id: str | None = None,
    answer_message: Message | None = None,
    avoid_recent: bool = True,
) -> None:
    destination_chat_id = target_channel_id or chat_id
    image = image_pool.random_image(
        avoid_recent=avoid_recent,
        chat_id=destination_chat_id,
    )
    if image is None:
        if answer_message:
            await answer_message.answer(RANDOM.choice(EMPTY_POOL_PHRASES))
        else:
            await bot.send_message(chat_id=chat_id, text=RANDOM.choice(EMPTY_POOL_PHRASES))
        return

    await bot.send_photo(
        chat_id=destination_chat_id,
        photo=image.file_id,
        caption=random_picture_caption(),
        reply_markup=picture_actions(image.id),
    )

    if (
        target_channel_id
        and answer_message
        and str(answer_message.chat.id) != str(target_channel_id)
    ):
        await answer_message.answer("Пикча улетела в канал")


async def send_duel(
    bot: Bot,
    message: Message,
    image_pool: ImagePool,
    silent_if_active: bool = False,
) -> DuelStartResult:
    chat_id = message.chat.id
    async with duel_lock_for(chat_id):
        if active_duel_id_for_chat(chat_id):
            if not silent_if_active:
                await message.answer(format_duel_already_active(), parse_mode="HTML")
            return "active"

        if image_pool.count() < 2:
            await message.answer("⚔️ Для дуэли нужно хотя бы две пикчи в пуле")
            return "failed"

        left = image_pool.random_image(chat_id=f"duel:{chat_id}:left")
        right = image_pool.random_image(chat_id=f"duel:{chat_id}:right")
        if left is None or right is None:
            await message.answer("⚔️ Дуэль сорвалась. Пул пустоват")
            return "failed"

        attempts = 0
        while right.id == left.id and attempts < 5:
            right = image_pool.random_image(chat_id=f"duel:{chat_id}:right:{attempts}")
            attempts += 1
            if right is None:
                break

        if right is None or right.id == left.id:
            await message.answer("⚔️ Дуэль не собралась. Рандом принёс одну и ту же пикчу")
            return "failed"

        try:
            await bot.send_media_group(
                chat_id=chat_id,
                media=[
                    InputMediaPhoto(media=left.file_id),
                    InputMediaPhoto(media=right.file_id),
                ],
            )
        except TelegramAPIError:
            LOGGER.warning("Failed to send duel media group, falling back to separate photos", exc_info=True)
            await bot.send_photo(
                chat_id=chat_id,
                photo=left.file_id,
            )
            await bot.send_photo(
                chat_id=chat_id,
                photo=right.file_id,
            )

        duel_id = uuid4().hex
        title = random_duel_start_phrase()
        status = random_duel_status_phrase()
        duel_sessions[duel_id] = {
            "chat_id": chat_id,
            "left": left.id,
            "right": right.id,
            "votes": {},
            "active": True,
            "title": title,
            "status": status,
        }
        try:
            score_message = await message.answer(
                format_duel_score(0, 0, title=title, status=status),
                parse_mode="HTML",
                reply_markup=duel_vote(duel_id),
            )
        except TelegramAPIError:
            duel_sessions.pop(duel_id, None)
            LOGGER.warning("Failed to send duel vote message", exc_info=True)
            return "failed"

        register_active_duel(chat_id, duel_id)
        asyncio.create_task(finalize_duel(duel_id, bot, image_pool, chat_id, score_message.message_id))
        return "started"


async def finalize_duel(
    duel_id: str,
    bot: Bot,
    image_pool: ImagePool,
    chat_id: int,
    message_id: int,
) -> None:
    await asyncio.sleep(DUEL_SECONDS)
    duel = duel_sessions.get(duel_id)
    if duel is None or not duel.get("active", False):
        return

    duel["active"] = False
    votes = duel["votes"]
    left_votes = sum(1 for vote in votes.values() if vote == "left")
    right_votes = sum(1 for vote in votes.values() if vote == "right")

    if left_votes == right_votes:
        image_pool.record_duel_result(tied=True)
        result_text = format_duel_result(left_votes, right_votes, winner=None)
    elif left_votes > right_votes:
        image_pool.delete(duel["right"])
        image_pool.record_duel_result(tied=False)
        result_text = format_duel_result(left_votes, right_votes, winner="left")
    else:
        image_pool.delete(duel["left"])
        image_pool.record_duel_result(tied=False)
        result_text = format_duel_result(left_votes, right_votes, winner="right")

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=result_text,
            parse_mode="HTML",
            reply_markup=new_duel(),
        )
    except TelegramAPIError:
        LOGGER.warning("Failed to edit completed duel message", exc_info=True)
    finally:
        clear_active_duel(chat_id, duel_id)
        duel_sessions.pop(duel_id, None)


def duel_lock_for(chat_id: int) -> asyncio.Lock:
    lock = duel_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        duel_locks[chat_id] = lock
    return lock


def active_duel_id_for_chat(chat_id: int) -> str | None:
    duel_id = active_duels_by_chat.get(chat_id)
    if duel_id is None:
        return None

    duel = duel_sessions.get(duel_id)
    if duel and duel.get("active", False):
        return duel_id

    active_duels_by_chat.pop(chat_id, None)
    return None


def register_active_duel(chat_id: int, duel_id: str) -> None:
    active_duels_by_chat[chat_id] = duel_id


def clear_active_duel(chat_id: int, duel_id: str) -> None:
    if active_duels_by_chat.get(chat_id) == duel_id:
        active_duels_by_chat.pop(chat_id, None)


async def activate_upload(message: Message, state: FSMContext) -> bool:
    if not is_private_chat(message):
        await message.answer(format_upload_private_only(), parse_mode="HTML")
        return False

    await state.set_state(AddPicture.uploading)
    active_uploads[message.chat.id] = new_upload_session()
    upload_text = (
        f"📥 <b>{escape(RANDOM.choice(UPLOAD_START_PHRASES))}</b>\n\n"
        "🖼 Кидайте одну пикчу, пачку, альбом или пересланные изображения"
    )
    await message.answer(
        upload_text,
        parse_mode="HTML",
    )
    return True


async def finish_upload_or_warn(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state != AddPicture.uploading.state and not is_upload_active(message):
        await message.answer("⚠️ Загрузка уже закрыта")
        return

    await finish_upload(message, state)


async def cancel_upload(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state != AddPicture.uploading.state and not is_upload_active(message):
        await message.answer("⚠️ Загрузка уже закрыта")
        return

    await state.clear()
    active_uploads.pop(message.chat.id, None)
    await message.answer(format_upload_cancelled(), parse_mode="HTML")


async def finish_upload(message: Message, state: FSMContext) -> None:
    data = upload_data(message)
    added = int(data.get("added", 0))
    failed = int(data.get("failed", 0))
    duplicates = int(data.get("duplicates", 0))
    await state.clear()
    active_uploads.pop(message.chat.id, None)

    lines = [
        f"<b>✅ {escape(RANDOM.choice(UPLOAD_FINISH_PHRASES))}</b>",
        "",
        "<b>📦 Итог загрузки</b>",
        f"Добавлено пикч: <b>{added}</b>",
    ]
    if failed:
        lines.append(f"Не зашло: <b>{failed}</b>")
    if duplicates:
        lines.append(f"Дубликатов пропущено: <b>{duplicates}</b>")

    await message.answer("\n".join(lines), parse_mode="HTML")


def is_upload_active(message: Message) -> bool:
    return is_private_chat(message) and message.chat.id in active_uploads


def is_private_chat(message: Message) -> bool:
    return message.chat.type == "private"


def new_upload_session() -> UploadSession:
    return {"added": 0, "failed": 0, "duplicates": 0, "ack_sent": False}


def upload_data(message: Message) -> UploadSession:
    return active_uploads.setdefault(
        message.chat.id,
        new_upload_session(),
    )


def is_admin(message: Message, admin_user_ids: frozenset[int]) -> bool:
    if not admin_user_ids or message.from_user is None:
        return False

    return message.from_user.id in admin_user_ids


def parse_user_id_argument(message: Message) -> int | None:
    text = message.text or message.caption or ""
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return None

    raw_user_id = parts[1].strip()
    if not raw_user_id.isdigit():
        return None

    return int(raw_user_id)


async def show_menu(message: Message) -> None:
    await message.answer(
        "<b>Пульт от ядерки 🚨</b>",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


def format_stats(image_pool: ImagePool) -> str:
    stats = image_pool.stats()
    return (
        "<b>📊 Сводка kartinkomet</b>\n\n"
        "<b>📦 Пул</b>\n"
        f"Пикч внутри: <b>{stats.total_images}</b>\n\n"
        "<b>🎲 Рандом</b>\n"
        f"Выстрелов: <b>{stats.total_shows}</b>\n\n"
        "<b>⚔️ Дуэли</b>\n"
        f"Боев: <b>{stats.total_duels}</b>\n"
        f"Казней: <b>{stats.duel_executions}</b>\n"
        f"Мирных исходов: <b>{stats.duel_ties}</b>\n\n"
        "<b>🧪 Реакции</b>\n"
        f"👍 Одобрений: <b>{stats.total_likes}</b>\n"
        f"💩 Какашек: <b>{stats.total_fires}</b>\n"
        f"🖕 Пальцев: <b>{stats.total_dislikes}</b>"
    )


def format_start() -> str:
    return (
        "<b>Я @kartinkomet_bot</b>\n\n"
        "Раздаю случайные пикчи из общего пула, принимаю новые пачками, "
        "устраиваю мемные дуэли и считаю вклад каждого поставщика хаоса\n\n"
        f"<b>🧠 Режим дня:</b> {daily_mood()}\n\n"
        "Жмите <code>🎲 Рандом</code>, запускайте <code>⚔️ Дуэль</code> "
        "или закидывайте пикчи в личке через <code>⬆️ Загрузка</code>"
    )


def format_help() -> str:
    return (
        "<b>Пульт управления хаосом</b>\n\n"
        "<b>🎲 Картинки</b>\n"
        "<code>/pic</code> — выстрелить рандомной пикчей\n"
        "<code>/count</code> — размер общего пула\n"
        "<code>/menu</code> — открыть пульт от ядерки\n\n"
        "<b>⬆️ Загрузка</b>\n"
        "<code>/upload_pidor</code> — открыть загрузку пикч в личке\n"
        "<code>/done</code> — закрыть загрузку в личке\n"
        "<code>/cancel</code> — отменить загрузку в личке\n\n"
        "<b>📊 Статистика</b>\n"
        "<code>/stats</code> — общие реакции и показы\n"
        "<code>/me</code> — ваш вклад, титулы и комбо\n"
        "<code>/top</code> — топ загрузчиков\n\n"
        "<b>⚔️ Игры</b>\n"
        "<code>/duel</code> — битва двух случайных пикч\n"
        "<code>/mood</code> — режим бота на сегодня\n\n"
        "<b>🧹 Народный суд</b>\n"
        "2 средних пальца удаляют пикчу из пула"
    )


def format_count(image_pool: ImagePool) -> str:
    return (
        "<b>📦 Общий пул</b>\n\n"
        f"Сейчас внутри: <b>{image_pool.count()}</b> пикч"
    )


def format_mood() -> str:
    return (
        "<b>🧠 Режим дня</b>\n\n"
        f"{daily_mood()}"
    )


def format_upload_private_only() -> str:
    return (
        "<b>📬 Загрузка теперь в личке</b>\n\n"
        "В группе бот только раздаёт пикчи, показывает статы и запускает дуэли\n\n"
        "Чтобы пополнить общий пул, откройте "
        '<a href="https://t.me/kartinkomet_bot">@kartinkomet_bot</a>, '
        f"отправьте <code>/{UPLOAD_COMMAND}</code> и кидайте картинки туда"
    )


def format_duel_already_active() -> str:
    return (
        "<b>⚔️ Дуэль уже идёт</b>\n\n"
        "Дождитесь финального свистка, потом запускайте новую"
    )


def format_user_id(user_id: int) -> str:
    return (
        "<b>🪪 Telegram user ID</b>\n\n"
        f"<code>{user_id}</code>"
    )


def format_upload_limit() -> str:
    return (
        "<b>🧯 Стоп-кран сработал</b>\n\n"
        f"Можно <b>{UPLOAD_LIMIT_PER_HOUR}</b> новых пикч в час\n"
        "Пауза, склад перегрелся"
    )


def format_duplicate_skipped() -> str:
    return "♻️ Дубликат пропущен"


def format_invalid_file() -> str:
    return "⚠️ Файл не зашёл. Отправьте изображение"


def format_upload_cancelled() -> str:
    return "<b>❌ Загрузка отменена</b>"


def format_admin_only(action: str) -> str:
    return f"🔒 {action} доступна только админам"


def format_reset_stats_done() -> str:
    return (
        "<b>♻️ Статистика сброшена</b>\n\n"
        "Реакции, показы, дуэли и память рандома обнулены"
    )


def format_dedupe_usage() -> str:
    return (
        "<b>🧹 Формат чистки дублей</b>\n\n"
        "<code>/dedupe_user 1045485205</code>"
    )


def format_dedupe_result(result) -> str:
    return (
        "<b>🧹 Чистка дублей завершена</b>\n\n"
        f"👤 Пользователь: <code>{result.user_id}</code>\n"
        f"🔎 Проверено его пикч: <b>{result.scanned}</b>\n"
        f"🧹 Убрано дублей: <b>{result.removed}</b>\n"
        f"📦 Осталось его пикч: <b>{result.remaining}</b>"
    )


def format_user_progress(user_id: int, image_pool: ImagePool) -> str:
    uploaded_count = image_pool.count_by_user(user_id)
    reaction_stats = image_pool.reaction_stats_by_user(user_id)
    current_achievement = current_achievement_for(uploaded_count)
    next_achievement = next_achievement_for(uploaded_count)
    combo_achievements = combo_achievements_for(reaction_stats)
    lines = [
        "<b>Ваш вклад в общий хаос</b>",
        "",
        "<b>📦 Загрузка</b>",
        f"Загружено пикч: <b>{uploaded_count}</b>",
        f"Текущее достижение: <b>{current_achievement}</b>",
        "",
        "<b>📊 Реакции на ваши пикчи</b>",
        f"👍 Одобрений: <b>{reaction_stats.likes}</b>",
        f"💩 Какашек: <b>{reaction_stats.fires}</b>",
        f"🖕 Пальцев: <b>{reaction_stats.dislikes}</b>",
        f"🎲 Показов: <b>{reaction_stats.shown}</b>",
        "",
        "<b>🎖 Статус</b>",
        f"Титул качества: <b>{quality_title(reaction_stats)}</b>",
    ]
    if combo_achievements:
        lines.append("Комбо:")
        lines.extend(f"• <b>{item}</b>" for item in combo_achievements)

    lines.append("")
    lines.append("<b>🎯 Следующий рубеж</b>")

    if next_achievement is None:
        lines.append("Лимиты здравого смысла закончились")
        return "\n".join(lines)

    threshold, achievement = next_achievement
    remaining = threshold - uploaded_count
    lines.append(f"До следующего: <b>{remaining}</b>")
    lines.append(f"Следующее достижение: <b>{achievement}</b> на {threshold} пикч")
    return "\n".join(lines)


def format_top_uploaders(image_pool: ImagePool, limit: int = 10) -> str:
    top_uploaders = image_pool.top_uploaders(limit=limit)
    if not top_uploaders:
        return (
            "<b>🏆 Топ загрузчиков пикч</b>\n\n"
            "Пьедестал пуст. Пока никто не занёс пикчи в общий котёл"
        )

    lines = ["<b>🏆 Топ загрузчиков пикч</b>", ""]
    medals = ["🥇", "🥈", "🥉"]
    for position, (user_id, count) in enumerate(top_uploaders, start=1):
        if position == 1:
            lines.append("<b>👑 Пьедестал</b>")
        if position == 4:
            lines.append("")
            lines.append("<b>📦 Остальные поставщики</b>")

        prefix = medals[position - 1] if position <= len(medals) else f"{position}."
        achievement = current_achievement_for(count)
        user_label = escape(image_pool.user_label(user_id))
        lines.append(
            f"{prefix} <b>{user_label}</b> — <b>{count}</b> пикч · {achievement}"
        )

    return "\n".join(lines)


def current_achievement_for(uploaded_count: int) -> str:
    current = "пока без медали, но путь начат"
    for threshold, achievement in ACHIEVEMENTS:
        if uploaded_count >= threshold:
            current = achievement
        else:
            break

    return current


def next_achievement_for(uploaded_count: int) -> tuple[int, str] | None:
    for threshold, achievement in ACHIEVEMENTS:
        if uploaded_count < threshold:
            return threshold, achievement

    return None


def daily_mood() -> str:
    today = date.today().toordinal()
    return BOT_MOODS[today % len(BOT_MOODS)]


def random_picture_caption() -> str:
    return RANDOM.choice(PICTURE_CAPTIONS)


def quality_title(stats) -> str:
    if stats.uploaded == 0:
        return "кандидат в поставщики хаоса"
    if stats.likes >= 50 and stats.likes >= stats.fires + stats.dislikes:
        return "поставщик годноты"
    if stats.fires >= 50 and stats.fires > stats.likes:
        return "магистр спорного контента"
    if stats.dislikes >= 10:
        return "любимец народного суда"
    if stats.uploaded >= 100 and stats.likes == 0:
        return "архитектор тишины"
    return "стабильный участник беспорядка"


def combo_achievements_for(stats) -> list[str]:
    combos = []
    if stats.uploaded >= UPLOAD_LIMIT_PER_HOUR:
        combos.append("заливочный марафонец")
    if stats.likes >= 10:
        combos.append("пикчи собирают одобрение")
    if stats.fires >= 10:
        combos.append("контент вызывает вопросы")
    if stats.dislikes >= 5:
        combos.append("народный суд заметил")
    if stats.shown >= 50:
        combos.append("частый гость рандома")
    return combos[:4]


def format_duel_score(
    left_votes: int,
    right_votes: int,
    title: str | None = None,
    status: str | None = None,
) -> str:
    if left_votes == right_votes:
        verdict = "⚖️ Пока ничья"
    elif left_votes > right_votes:
        verdict = "🔥 Лидирует: 🅰️ Первая"
    else:
        verdict = "🔥 Лидирует: 🅱️ Вторая"

    return (
        f"<b>⚔️ {escape(title or random_duel_start_phrase())}</b>\n"
        f"{escape(status or random_duel_status_phrase())}\n\n"
        f"🅰️ Первая: <b>{left_votes}</b>\n"
        f"🅱️ Вторая: <b>{right_votes}</b>\n\n"
        f"⏱ <b>{DUEL_SECONDS} секунд</b>\n"
        f"{verdict}"
    )


def format_duel_result(left_votes: int, right_votes: int, winner: str | None) -> str:
    if winner is None:
        phrase = random_duel_tie_phrase()
        verdict = "⚖️ Ничья. Обе пикчи выжили"
    elif winner == "left":
        phrase = random_duel_win_phrase()
        verdict = "👑 Победила: <b>🅰️ Первая</b>\n🗑 Удалена: <b>🅱️ Вторая</b>"
    else:
        phrase = random_duel_win_phrase()
        verdict = "👑 Победила: <b>🅱️ Вторая</b>\n🗑 Удалена: <b>🅰️ Первая</b>"

    return (
        "<b>🏁 Дуэль окончена</b>\n"
        f"{escape(phrase)}\n\n"
        f"🅰️ Первая: <b>{left_votes}</b>\n"
        f"🅱️ Вторая: <b>{right_votes}</b>\n\n"
        f"{verdict}"
    )


def random_duel_start_phrase() -> str:
    return RANDOM.choice(DUEL_START_PHRASES)


def random_duel_status_phrase() -> str:
    return RANDOM.choice(DUEL_STATUS_PHRASES)


def random_duel_win_phrase() -> str:
    return RANDOM.choice(DUEL_WIN_PHRASES)


def random_duel_tie_phrase() -> str:
    return RANDOM.choice(DUEL_TIE_PHRASES)


def achievement_for(message: Message, image_pool: ImagePool) -> str | None:
    if message.from_user is None:
        return None

    uploaded_count = image_pool.count_by_user(message.from_user.id)
    uploader = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else (message.from_user.first_name or "кто-то")
    )
    for threshold, achievement in ACHIEVEMENTS:
        if uploaded_count == threshold:
            return f"<b>🏅 Достижение:</b> {achievement}\n{uploader} загрузил пикч: {uploaded_count}"

    return None


def jury_verdict(dislikes: int) -> str | None:
    return JURY_THRESHOLDS.get(dislikes)

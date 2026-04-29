import asyncio
import logging
import random
from datetime import date
from html import escape
from time import monotonic
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
from bot.weather import format_weather_error, format_weather_report, get_mala_tokmachka_weather

UPLOAD_COMMAND = "upload_pidor"
DUEL_SECONDS = 60
DUEL_TICK_SECONDS = 15
DUEL_STALE_GRACE_SECONDS = 20
RANDOM = random.SystemRandom()
LOGGER = logging.getLogger(__name__)


class UploadSession(TypedDict):
    added: int
    failed: int
    duplicates: int
    ack_sent: bool
    announced_achievements: set[int]


DuelStartResult = Literal["started", "active", "failed"]


active_uploads: dict[int, UploadSession] = {}
duel_sessions: dict[str, dict] = {}
active_duels_by_chat: dict[int, str] = {}
duel_locks: dict[int, asyncio.Lock] = {}
duel_tasks: dict[str, asyncio.Task] = {}


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

    @router.message(Command("weather"))
    @router.channel_post(Command("weather"))
    async def weather_command(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await send_weather(message)

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
                    "Когда всё закинули — нажмите <code>✅ Закончить</code>\n"
                    "Если передумали — нажмите <code>❌ Отмена</code>",
                    parse_mode="HTML",
                    reply_markup=upload_menu(),
                )
            achievement = achievement_for(message, image_pool, data["announced_achievements"])
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

    @router.callback_query(F.data == "weather")
    async def weather_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message:
            await send_weather(callback.message)
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
            await callback.answer("Загрузка не открыта", show_alert=False)
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
            await callback.answer("Загрузка не открыта", show_alert=False)
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
        user_key = str(callback.from_user.id)
        if votes.get(user_key) == side:
            await callback.answer("Уже стоит")
            return

        votes[user_key] = side
        left_votes, right_votes = duel_vote_counts(duel)
        if callback.message:
            try:
                await callback.message.edit_text(
                    format_duel_score(
                        left_votes,
                        right_votes,
                        title=str(duel.get("title") or random_duel_start_phrase()),
                        status=str(duel.get("status") or random_duel_status_phrase()),
                        remaining_seconds=duel_remaining_seconds(duel),
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
            "expires_at": monotonic() + DUEL_SECONDS,
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
        schedule_duel_finalizer(duel_id, bot, image_pool, chat_id, score_message.message_id)
        return "started"


async def finalize_duel(
    duel_id: str,
    bot: Bot,
    image_pool: ImagePool,
    chat_id: int,
    message_id: int,
) -> None:
    try:
        while True:
            duel = duel_sessions.get(duel_id)
            if duel is None or not duel.get("active", False):
                return

            remaining_seconds = duel_remaining_seconds(duel)
            if remaining_seconds <= 0:
                break

            await asyncio.sleep(min(DUEL_TICK_SECONDS, remaining_seconds))
            duel = duel_sessions.get(duel_id)
            if duel is None or not duel.get("active", False):
                return

            remaining_seconds = duel_remaining_seconds(duel)
            if remaining_seconds > 0:
                await update_duel_score_message(
                    bot=bot,
                    chat_id=chat_id,
                    message_id=message_id,
                    duel_id=duel_id,
                    duel=duel,
                    remaining_seconds=remaining_seconds,
                )

        duel = duel_sessions.get(duel_id)
        if duel is None or not duel.get("active", False):
            return

        duel["active"] = False
        left_votes, right_votes = duel_vote_counts(duel)

        if left_votes == right_votes:
            image_pool.finish_duel(loser_id=None)
            result_text = format_duel_result(left_votes, right_votes, winner=None)
        elif left_votes > right_votes:
            image_pool.finish_duel(loser_id=duel["right"])
            result_text = format_duel_result(left_votes, right_votes, winner="left")
        else:
            image_pool.finish_duel(loser_id=duel["left"])
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
    except Exception:
        LOGGER.exception("Duel finalizer crashed")
    finally:
        clear_active_duel(chat_id, duel_id)
        duel_sessions.pop(duel_id, None)
        duel_tasks.pop(duel_id, None)


def schedule_duel_finalizer(
    duel_id: str,
    bot: Bot,
    image_pool: ImagePool,
    chat_id: int,
    message_id: int,
) -> None:
    task = asyncio.create_task(finalize_duel(duel_id, bot, image_pool, chat_id, message_id))
    duel_tasks[duel_id] = task
    task.add_done_callback(log_duel_task_exception)


def log_duel_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return

    error = task.exception()
    if error is not None:
        LOGGER.error(
            "Duel task finished with an error",
            exc_info=(type(error), error, error.__traceback__),
        )


async def update_duel_score_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    duel_id: str,
    duel: dict,
    remaining_seconds: int,
) -> None:
    left_votes, right_votes = duel_vote_counts(duel)
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=format_duel_score(
                left_votes,
                right_votes,
                title=str(duel.get("title") or random_duel_start_phrase()),
                status=str(duel.get("status") or random_duel_status_phrase()),
                remaining_seconds=remaining_seconds,
            ),
            parse_mode="HTML",
            reply_markup=duel_vote(duel_id, left_votes, right_votes),
        )
    except TelegramAPIError:
        LOGGER.warning("Failed to update duel timer message", exc_info=True)


def duel_vote_counts(duel: dict) -> tuple[int, int]:
    votes = duel.get("votes", {})
    return (
        sum(1 for vote in votes.values() if vote == "left"),
        sum(1 for vote in votes.values() if vote == "right"),
    )


def duel_remaining_seconds(duel: dict) -> int:
    try:
        expires_at = float(duel.get("expires_at") or 0)
    except (TypeError, ValueError):
        return 0

    return max(0, round(expires_at - monotonic()))


def duel_is_stale(duel: dict) -> bool:
    try:
        expires_at = float(duel.get("expires_at") or 0)
    except (TypeError, ValueError):
        return True

    return monotonic() > expires_at + DUEL_STALE_GRACE_SECONDS


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
        if duel_is_stale(duel):
            duel["active"] = False
            active_duels_by_chat.pop(chat_id, None)
            duel_sessions.pop(duel_id, None)
            duel_tasks.pop(duel_id, None)
            LOGGER.warning("Cleared stale duel %s in chat %s", duel_id, chat_id)
            return None
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
        f"<b>📥 {escape(RANDOM.choice(UPLOAD_START_PHRASES))}</b>\n\n"
        "🖼 Кидайте одну пикчу, пачку, альбом или пересланные изображения\n\n"
        "После первой принятой пикчи появятся кнопки завершения"
    )
    await message.answer(
        upload_text,
        parse_mode="HTML",
    )
    return True


async def finish_upload_or_warn(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state != AddPicture.uploading.state and not is_upload_active(message):
        await message.answer(format_upload_not_active(), parse_mode="HTML")
        return

    await finish_upload(message, state)


async def cancel_upload(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state != AddPicture.uploading.state and not is_upload_active(message):
        await message.answer(format_upload_not_active(), parse_mode="HTML")
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
        "<b>✅ Загрузка завершена</b>",
        escape(RANDOM.choice(UPLOAD_FINISH_PHRASES)),
        "",
        "<b>📦 Итог</b>",
        format_metric("Добавлено пикч", added),
    ]
    if failed:
        lines.append(format_metric("Не зашло", failed))
    if duplicates:
        lines.append(format_metric("Дубликатов пропущено", duplicates))

    await message.answer("\n".join(lines), parse_mode="HTML")


def is_upload_active(message: Message) -> bool:
    return is_private_chat(message) and message.chat.id in active_uploads


def is_private_chat(message: Message) -> bool:
    return message.chat.type == "private"


def new_upload_session() -> UploadSession:
    return {
        "added": 0,
        "failed": 0,
        "duplicates": 0,
        "ack_sent": False,
        "announced_achievements": set(),
    }


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
        "<b>🚨 Пульт от ядерки</b>\n\n"
        "<b>🎮 Быстрые кнопки</b>\n"
        "🎲 рандом · ⚔️ дуэль\n\n"
        "<b>📊 Склад и люди</b>\n"
        "📊 сводка · 👤 мой вклад · 🏆 топ\n\n"
        "⬆️ загрузка работает в личке с ботом",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


def format_metric(label: str, value: int | str) -> str:
    return f"• {label}: <b>{value}</b>"


def format_section(title: str, *lines: str) -> str:
    return "\n".join([f"<b>{title}</b>", *lines])


def format_stats(image_pool: ImagePool) -> str:
    stats = image_pool.stats()
    sections = [
        "<b>📊 Сводка kartinkomet</b>",
        format_section("📦 Пул", format_metric("Пикч внутри", stats.total_images)),
        format_section("🎲 Рандом", format_metric("Выдано пикч", stats.total_shows)),
        format_section(
            "⚔️ Дуэли",
            format_metric("Боев", stats.total_duels),
            format_metric("Удалений после боя", stats.duel_executions),
            format_metric("Ничьих без удаления", stats.duel_ties),
        ),
        format_section(
            "🧪 Реакции",
            format_metric("🤙🏻 Одобрений", stats.total_likes),
            format_metric("🖕🏻 Пальцев", stats.total_dislikes),
        ),
    ]
    return "\n\n".join(sections)


def format_start() -> str:
    return (
        "<b>👋 Я @kartinkomet_bot</b>\n"
        "Общий склад пикч, рандом, дуэли и статистика без лишней бюрократии\n\n"
        f"<b>🧠 Режим дня</b>\n{daily_mood()}\n\n"
        "<b>🚀 Быстрый старт</b>\n"
        "• <code>🎲 Рандом</code> — получить пикчу\n"
        "• <code>⚔️ Дуэль</code> — устроить бой двух пикч\n"
        "• <code>⬆️ Загрузить пикчи</code> — пополнить пул в личке\n"
        "• <code>🌦 Погода</code> — узнать, что там в Малой Токмачке"
    )


def format_help() -> str:
    sections = [
        "<b>🧭 Пульт управления хаосом</b>",
        format_section(
            "🎲 Картинки",
            "<code>/pic</code> — выстрелить рандомной пикчей",
            "<code>/count</code> — размер общего пула",
            "<code>/menu</code> — открыть пульт от ядерки",
        ),
        format_section(
            "⚔️ Дуэли",
            "<code>/duel</code> — битва двух случайных пикч",
            "<code>/mood</code> — режим бота на сегодня",
            "<code>/weather</code> — погода в Малой Токмачке",
        ),
        format_section(
            "⬆️ Загрузка",
            "<code>/upload_pidor</code> — открыть загрузку в личке",
            "<code>/done</code> — закрыть загрузку",
            "<code>/cancel</code> — отменить загрузку",
        ),
        format_section(
            "📊 Статистика",
            "<code>/stats</code> — общая сводка",
            "<code>/me</code> — ваш вклад, титулы и комбо",
            "<code>/top</code> — топ загрузчиков",
        ),
        format_section(
            "🧹 Народный суд",
            "2 средних пальца удаляют пикчу из пула",
        ),
    ]
    return "\n\n".join(sections)


def format_count(image_pool: ImagePool) -> str:
    return (
        "<b>📦 Общий пул</b>\n\n"
        f"{format_metric('Пикч на складе', image_pool.count())}"
    )


def format_mood() -> str:
    return (
        "<b>🧠 Режим дня</b>\n\n"
        f"{daily_mood()}"
    )


async def send_weather(message: Message) -> None:
    try:
        report = await get_mala_tokmachka_weather()
    except Exception:
        LOGGER.warning("Failed to fetch weather", exc_info=True)
        await message.answer(format_weather_error(), parse_mode="HTML")
        return

    await message.answer(format_weather_report(report), parse_mode="HTML")


def format_upload_private_only() -> str:
    return (
        "<b>📬 Загрузка уехала в личку</b>\n\n"
        "В группе бот не ловит файлы стабильно из-за Telegram Privacy Mode\n\n"
        "<b>Как пополнить пул</b>\n"
        "1. Откройте <a href=\"https://t.me/kartinkomet_bot\">@kartinkomet_bot</a>\n"
        f"2. Отправьте <code>/{UPLOAD_COMMAND}</code>\n"
        "3. Кидайте пикчи туда"
    )


def format_duel_already_active() -> str:
    return (
        "<b>⚔️ Дуэль уже идёт</b>\n\n"
        "Дождитесь финального свистка\n"
        "После итогов можно запускать новую"
    )


def format_user_id(user_id: int) -> str:
    return (
        "<b>🪪 Telegram user ID</b>\n\n"
        f"<code>{user_id}</code>"
    )


def format_upload_limit() -> str:
    return (
        "<b>🧯 Стоп-кран сработал</b>\n\n"
        f"{format_metric('Лимит', f'{UPLOAD_LIMIT_PER_HOUR} новых пикч в час')}\n"
        "Пауза, склад перегрелся"
    )


def format_duplicate_skipped() -> str:
    return "♻️ Дубликат пропущен"


def format_invalid_file() -> str:
    return "⚠️ Файл не зашёл. Отправьте изображение"


def format_upload_cancelled() -> str:
    return (
        "<b>❌ Загрузка отменена</b>\n\n"
        "Пакет закрыт без итоговой сводки"
    )


def format_upload_not_active() -> str:
    return (
        "<b>⚠️ Загрузка не открыта</b>\n\n"
        f"Откройте её в личке через <code>/{UPLOAD_COMMAND}</code>"
    )


def format_admin_only(action: str) -> str:
    return f"🔒 {action} доступна только админам"


def format_reset_stats_done() -> str:
    return (
        "<b>♻️ Статистика сброшена</b>\n\n"
        "• реакции обнулены\n"
        "• показы обнулены\n"
        "• дуэли обнулены\n"
        "• память рандома очищена"
    )


def format_dedupe_usage() -> str:
    return (
        "<b>🧹 Формат чистки дублей</b>\n\n"
        "<code>/dedupe_user 1045485205</code>"
    )


def format_dedupe_result(result) -> str:
    return (
        "<b>🧹 Чистка дублей завершена</b>\n\n"
        f"{format_metric('👤 Пользователь', f'<code>{result.user_id}</code>')}\n"
        f"{format_metric('🔎 Проверено его пикч', result.scanned)}\n"
        f"{format_metric('🧹 Убрано дублей', result.removed)}\n"
        f"{format_metric('📦 Осталось его пикч', result.remaining)}"
    )


def format_user_progress(user_id: int, image_pool: ImagePool) -> str:
    uploaded_count = image_pool.count_by_user(user_id)
    reaction_stats = image_pool.reaction_stats_by_user(user_id)
    current_achievement = current_achievement_for(uploaded_count)
    next_achievement = next_achievement_for(uploaded_count)
    combo_achievements = combo_achievements_for(reaction_stats)
    lines = [
        "<b>👤 Ваш вклад в общий склад</b>",
        "",
        "<b>📦 Загрузка</b>",
        format_metric("Загружено пикч", uploaded_count),
        format_metric("Достижение", current_achievement),
        "",
        "<b>📊 Реакции на ваши пикчи</b>",
        format_metric("🤙🏻 Одобрений", reaction_stats.likes),
        format_metric("🖕🏻 Пальцев", reaction_stats.dislikes),
        format_metric("🎲 Выдано рандомом", reaction_stats.shown),
        "",
        "<b>🎖 Статус</b>",
        format_metric("Титул качества", quality_title(reaction_stats)),
    ]
    if combo_achievements:
        lines.append("")
        lines.append("<b>🧩 Комбо</b>")
        lines.extend(f"• <b>{item}</b>" for item in combo_achievements)

    lines.append("")
    lines.append("<b>🎯 Следующий рубеж</b>")

    if next_achievement is None:
        lines.append("• Лимиты здравого смысла закончились")
        return "\n".join(lines)

    threshold, achievement = next_achievement
    remaining = threshold - uploaded_count
    lines.append(format_metric("До следующего", remaining))
    lines.append(format_metric("Следующее", f"{achievement} на {threshold} пикч"))
    return "\n".join(lines)


def format_top_entry(prefix: str, user_label: str, count: int, achievement: str) -> str:
    return f"{prefix} <b>{escape(user_label)}</b> — <b>{count}</b> пикч · {escape(achievement)}"


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
            lines.append("<b>👑 Пьедестал:</b>")
            lines.append("")
        if position == 4:
            lines.append("")
            lines.append("<b>📦 Остальные поставщики</b>")
            lines.append("")

        prefix = medals[position - 1] if position <= len(medals) else f"{position}."
        achievement = current_achievement_for(count)
        user_label = image_pool.user_label(user_id)
        lines.append(format_top_entry(prefix, user_label, count, achievement))

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
    if stats.likes >= 50 and stats.likes >= stats.dislikes:
        return "поставщик годноты"
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
    remaining_seconds: int | None = None,
) -> str:
    if left_votes == right_votes:
        verdict = "⚖️ пока ничья"
    elif left_votes > right_votes:
        verdict = "🔥 🅰️ ведёт"
    else:
        verdict = "🔥 🅱️ ведёт"

    seconds_left = DUEL_SECONDS if remaining_seconds is None else max(0, remaining_seconds)
    return (
        f"<b>⚔️ {escape(title or random_duel_start_phrase())}</b>\n"
        f"{escape(status or random_duel_status_phrase())}\n\n"
        f"🅰️ слева: <b>{left_votes}</b> · 🅱️ справа: <b>{right_votes}</b>\n\n"
        f"⏱ <b>{seconds_left} секунд</b> · "
        f"{verdict}"
    )


def format_duel_result(left_votes: int, right_votes: int, winner: str | None) -> str:
    if winner is None:
        phrase = random_duel_tie_phrase()
        verdict = "⚖️ Ничья. Обе пикчи остаются в пуле"
    elif winner == "left":
        phrase = random_duel_win_phrase()
        verdict = "👑 Выжила: <b>🅰️ слева</b>\n🗑 Улетела из пула: <b>🅱️ справа</b>"
    else:
        phrase = random_duel_win_phrase()
        verdict = "👑 Выжила: <b>🅱️ справа</b>\n🗑 Улетела из пула: <b>🅰️ слева</b>"

    return (
        "<b>🏁 Дуэль завершена</b>\n"
        f"{escape(phrase)}\n\n"
        f"🅰️ слева: <b>{left_votes}</b> · 🅱️ справа: <b>{right_votes}</b>\n\n"
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


def achievement_for(
    message: Message,
    image_pool: ImagePool,
    announced_achievements: set[int] | None = None,
) -> str | None:
    if message.from_user is None:
        return None

    uploaded_count = image_pool.count_by_user(message.from_user.id)
    uploader = (
        message.from_user.username
        if message.from_user.username
        else (message.from_user.first_name or "кто-то")
    )
    for threshold, achievement in ACHIEVEMENTS:
        if uploaded_count == threshold:
            if announced_achievements is not None:
                if threshold in announced_achievements:
                    return None
                announced_achievements.add(threshold)
            return (
                f"<b>🏅 Достижение:</b> {achievement}\n"
                f"{escape(uploader)} загрузил пикч: {uploaded_count}"
            )

    return None


def jury_verdict(dislikes: int) -> str | None:
    return JURY_THRESHOLDS.get(dislikes)

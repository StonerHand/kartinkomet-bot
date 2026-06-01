import asyncio
import logging
import random
import tempfile
from collections.abc import Awaitable, Callable
from html import escape
from pathlib import Path
from time import monotonic
from typing import Literal, TypeVar, TypedDict
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message, ReplyKeyboardRemove

from bot.image_pool import UPLOAD_LIMIT_PER_HOUR, ImagePool
from bot.keyboards import (
    arena_menu,
    duel_vote,
    empty_picture_pool_actions,
    main_menu,
    new_duel,
    new_tournament,
    picture_actions_with_counts,
    random_menu,
    storage_menu,
    tournament_vote,
    upload_hub,
    upload_menu,
)
from bot.texts import (
    ACHIEVEMENTS,
    AUTO_DELETE_DISLIKES,
    DUEL_START_PHRASES,
    DUEL_STATUS_PHRASES,
    DUEL_TIE_PHRASES,
    DUEL_WIN_PHRASES,
    EMPTY_POOL_PHRASES,
    JURY_THRESHOLDS,
    PICTURE_CAPTIONS,
    UPLOAD_START_PHRASES,
)

UPLOAD_COMMAND = "upload_pidor"
DUEL_SECONDS = 60
TOURNAMENT_SECONDS = 90
TOURNAMENT_SIZE = 4
DUEL_TICK_SECONDS = 15
DUEL_STALE_GRACE_SECONDS = 20
UPLOAD_MARATHON_THRESHOLD = 100
TELEGRAM_SEND_RETRIES = 3
TELEGRAM_RETRY_BASE_DELAY = 0.45
RANDOM = random.SystemRandom()
LOGGER = logging.getLogger(__name__)
T = TypeVar("T")

TOURNAMENT_START_PHRASES = (
    "Открыт короткий чемпионат подозрительных пикч",
    "Четыре кандидата вышли на витрину",
    "Мини-олимпиада общего склада стартовала",
    "Пикчи построились в сетку без лишних речей",
    "Чат получил четыре повода нажать не туда",
    "Склад выставил квартет на народный просмотр",
    "Начался турнир без судьи и тормозов",
    "Четвёрка визуального шума готова к проверке",
    "Пикчевый плей-офф включён",
    "Контент вышел на короткую дистанцию",
)
TOURNAMENT_STATUS_PHRASES = (
    "Выбираем чемпиона, никого не удаляем",
    "Тут не казнь, тут корона",
    "Голосуйте за ту, которую не стыдно вынести вперёд",
    "Победитель получит славу, остальные просто переживут",
    "Кнопки собирают народный рейтинг",
    "Смотрим, кто сегодня тащит визуальный цех",
    "Чат решает, какая пикча громче",
    "Турнир идёт мягче дуэли, но с понтами",
    "Каждый голос двигает корону",
    "Склад ждёт нового чемпиона",
)
TOURNAMENT_WIN_PHRASES = (
    "Корона нашла голову",
    "Чемпион определён, склад хлопает папками",
    "Победитель вышел из сетки сухим",
    "Народ выбрал витринный экземпляр",
    "Рейтинг сказал своё",
    "Турнир закрылся без жертв, но с фаворитом",
    "Кнопочная демократия выдала чемпиона",
    "Победитель забрал свет софитов",
    "Пикча дня получила микрокорону",
    "Общий склад записал нового чемпиона",
)
TOURNAMENT_TIE_PHRASES = (
    "Ничья. Чат красиво ушёл от ответственности",
    "Корону не выдали, кандидаты разошлись молча",
    "Голоса слиплись в ничью",
    "Турнир завис на дипломатии",
    "Победитель не найден, склад делает вид, что так и надо",
    "Сетка закончилась без чемпиона",
    "Кнопки не смогли договориться",
    "Ничья, зато никто не обиделся",
    "Чат посмотрел и промолчал достаточно громко",
    "Корона осталась на зарядке",
)


def _runtime_phrase_grid(starts: list[str], endings: list[str]) -> tuple[str, ...]:
    return tuple(f"{start} {ending}" for start in starts for ending in endings)


def _extend_runtime_phrases(
    base: tuple[str, ...],
    additions: tuple[str, ...],
    target_count: int,
) -> tuple[str, ...]:
    phrases = list(dict.fromkeys(base))
    for phrase in additions:
        if phrase not in phrases:
            phrases.append(phrase)
        if len(phrases) == target_count:
            return tuple(phrases)
    raise RuntimeError(f"Not enough runtime phrases to build a pool of {target_count}.")


TOURNAMENT_START_PHRASES = _extend_runtime_phrases(
    TOURNAMENT_START_PHRASES,
    _runtime_phrase_grid(
        [
            "Турнирная витрина",
            "Квартет пикч",
            "Складской плей-офф",
            "Четыре пикчи",
            "Мини-чемпионат",
            "Пикчевой подиум",
            "Мемная сетка",
            "Контентная четверка",
            "Визуальный кубок",
            "Случайный чемпионат",
        ],
        [
            "выходит на старт",
            "просит чемпиона",
            "открывает голосование",
            "запускает витрину",
            "собирает народный рейтинг",
            "поднимает корону",
            "выкатывает претендентов",
        ],
    ),
    80,
)
TOURNAMENT_STATUS_PHRASES = _extend_runtime_phrases(
    TOURNAMENT_STATUS_PHRASES,
    _runtime_phrase_grid(
        [
            "Чат",
            "Турнир",
            "Кнопки",
            "Витрина",
            "Склад",
            "Пул",
            "Публика",
            "Рандом",
            "Мемная сетка",
            "Контентный совет",
        ],
        [
            "выбирает чемпиона",
            "раздаёт корону",
            "считает голоса",
            "ищет фаворита",
            "делает вид, что тут спорт",
            "держит витрину открытой",
            "проверяет силу кнопок",
        ],
    ),
    80,
)
TOURNAMENT_WIN_PHRASES = _extend_runtime_phrases(
    TOURNAMENT_WIN_PHRASES,
    _runtime_phrase_grid(
        [
            "Чемпион",
            "Победитель витрины",
            "Король сетки",
            "Фаворит чата",
            "Главная пикча",
            "Витринный чемпион",
            "Народный выбор",
            "Турнирный герой",
            "Пикча с короной",
            "Складской чемпион",
        ],
        [
            "получает корону",
            "забирает свет",
            "выходит из сетки",
            "становится главным",
            "уходит в историю склада",
            "берёт витрину",
            "получает складской титул",
        ],
    ),
    80,
)
TOURNAMENT_TIE_PHRASES = _extend_runtime_phrases(
    TOURNAMENT_TIE_PHRASES,
    _runtime_phrase_grid(
        [
            "Турнир",
            "Кнопки",
            "Чат",
            "Сетка",
            "Корона",
            "Витрина",
            "Пул",
            "Публика",
            "Четвёрка",
            "Контентный совет",
        ],
        [
            "ушёл в ничью",
            "не выбрал чемпиона",
            "завис на дипломатии",
            "оставил всех без короны",
            "сохранил интригу",
            "закрылся без победителя",
            "не отдал никому витрину",
            "оставил табло в тумане",
        ],
    ),
    80,
)


class UploadSession(TypedDict):
    added: int
    failed: int
    duplicates: int
    announced_achievements: set[int]
    achievement_names: list[str]


DuelStartResult = Literal["started", "active", "failed"]
DuelKind = Literal["image"]


active_uploads: dict[int, UploadSession] = {}
duel_sessions: dict[str, dict] = {}
active_duels_by_chat: dict[int, dict[DuelKind, str]] = {}
duel_locks: dict[int, asyncio.Lock] = {}
duel_tasks: dict[str, asyncio.Task] = {}
tournament_sessions: dict[str, dict] = {}
active_tournaments_by_chat: dict[int, str] = {}
tournament_locks: dict[int, asyncio.Lock] = {}
tournament_tasks: dict[str, asyncio.Task] = {}


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
        await show_menu(message, image_pool)

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await message.answer(format_help(), parse_mode="HTML")

    @router.message(Command("menu"))
    async def menu_command(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await show_menu(message, image_pool)

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
        await message.answer(
            format_stats(image_pool, chat_id=message.chat.id),
            parse_mode="HTML",
        )

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

    @router.message(Command("tournament"))
    async def tournament_command(message: Message, bot: Bot) -> None:
        image_pool.remember_user(message.from_user)
        await send_tournament(bot=bot, message=message, image_pool=image_pool)

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

    @router.message(Command("backup"))
    async def backup_command(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        if not is_admin(message, admin_user_ids):
            await message.answer(format_admin_only("Бэкап"))
            return

        await send_backup(message, image_pool)

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

        result = image_pool.add_from_message(message)
        if result.added:
            data.update(
                {
                    "added": added + 1,
                    "failed": failed,
                    "duplicates": duplicates,
                }
            )
            achievement = achievement_for(message, image_pool, data["announced_achievements"])
            if achievement:
                if message.from_user is not None:
                    data["achievement_names"].append(
                        current_achievement_for(image_pool.count_by_user(message.from_user.id))
                    )
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
        await callback.answer(
            format_count_alert(image_pool),
            show_alert=True,
        )

    @router.callback_query(F.data == "stats")
    async def stats_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message:
            await callback.message.answer(
                format_stats(image_pool, chat_id=callback.message.chat.id),
                parse_mode="HTML",
            )
        await callback.answer()

    @router.callback_query(F.data == "menu")
    async def menu_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message:
            await show_menu(callback.message, image_pool, edit_existing=True)
        await callback.answer()

    @router.callback_query(F.data == "menu_random")
    async def menu_random_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message:
            await answer_or_edit_panel(
                callback.message,
                format_random_menu(),
                random_menu(),
                "random menu",
            )
        await callback.answer()

    @router.callback_query(F.data == "menu_arena")
    async def menu_arena_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message:
            chat_id = callback.message.chat.id
            arena_state = active_arena_snapshot(chat_id)
            await answer_or_edit_panel(
                callback.message,
                format_arena_menu(chat_id),
                arena_menu(
                    image_duel_active=arena_state["image_seconds"] is not None,
                    tournament_active=arena_state["tournament_seconds"] is not None,
                    image_duel_seconds=arena_state["image_seconds"],
                    tournament_seconds=arena_state["tournament_seconds"],
                ),
                "arena menu",
            )
        await callback.answer()

    @router.callback_query(F.data == "menu_storage")
    async def menu_storage_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message:
            await answer_or_edit_panel(
                callback.message,
                format_storage_menu(image_pool),
                storage_menu(is_private=is_private_chat(callback.message)),
                "storage menu",
            )
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

    @router.callback_query(F.data == "upload_hub")
    async def upload_hub_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message:
            await answer_or_edit_panel(
                callback.message,
                format_upload_hub(is_private_chat(callback.message)),
                upload_hub(is_private=is_private_chat(callback.message)),
                "upload hub",
            )
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
        if not is_any_upload_active(callback.message, current_state):
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
        if not is_any_upload_active(callback.message, current_state):
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
                    await callback.message.reply(
                        "<b>⚖️ Народный суд</b>\n\n"
                        "🖕🏻 <b>2</b> голоса\n"
                        "🗑 Пикча удалена со склада",
                        parse_mode="HTML",
                    )
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
    async def duel_callback(callback: CallbackQuery, bot: Bot) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.data is None:
            await callback.answer()
            return

        _, duel_id, side = callback.data.split(":", 2)
        duel = duel_sessions.get(duel_id)
        if duel is None or duel.get("kind", "image") != "image":
            await callback.answer("Дуэль уже растворилась в истории", show_alert=True)
            return
        if not duel.get("active", False):
            await callback.answer("Дуэль уже закончилась", show_alert=True)
            return
        if duel_remaining_seconds(duel) <= 0:
            await close_expired_image_duel_from_callback(
                callback=callback,
                bot=bot,
                image_pool=image_pool,
                duel_id=duel_id,
                duel=duel,
            )
            await callback.answer("Финальный свисток уже был")
            return

        votes = duel["votes"]
        user_key = str(callback.from_user.id)
        if votes.get(user_key) == side:
            await callback.answer("Уже стоит")
            return

        votes[user_key] = side
        left_votes, right_votes = duel_vote_counts(duel)
        if callback.message:
            await edit_callback_text_if_changed(
                callback.message,
                duel,
                format_duel_score(
                    left_votes,
                    right_votes,
                    title=str(duel.get("title") or random_duel_start_phrase()),
                    status=str(duel.get("status") or random_duel_status_phrase()),
                    remaining_seconds=duel_remaining_seconds(duel),
                ),
                duel_vote(duel_id, left_votes, right_votes),
                "duel vote message",
            )
        await callback.answer("Голос принят")

    @router.callback_query(F.data.startswith("tournament:"))
    async def tournament_callback(callback: CallbackQuery, bot: Bot) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.data is None:
            await callback.answer()
            return

        _, tournament_id, raw_option = callback.data.split(":", 2)
        tournament = tournament_sessions.get(tournament_id)
        if tournament is None:
            await callback.answer("Турнир уже уехал в архив", show_alert=True)
            return
        if not tournament.get("active", False):
            await callback.answer("Турнир уже закончился", show_alert=True)
            return
        if tournament_remaining_seconds(tournament) <= 0:
            await close_expired_tournament_from_callback(
                callback=callback,
                bot=bot,
                image_pool=image_pool,
                tournament_id=tournament_id,
                tournament=tournament,
            )
            await callback.answer("Финальный свисток уже был")
            return

        try:
            option = int(raw_option)
        except ValueError:
            await callback.answer()
            return

        if option not in range(TOURNAMENT_SIZE):
            await callback.answer()
            return

        votes = tournament["votes"]
        user_key = str(callback.from_user.id)
        if votes.get(user_key) == option:
            await callback.answer("Уже стоит")
            return

        votes[user_key] = option
        vote_counts = tournament_vote_counts(tournament)
        if callback.message:
            await edit_callback_text_if_changed(
                callback.message,
                tournament,
                format_tournament_score(
                    vote_counts,
                    title=str(tournament.get("title") or random_tournament_start_phrase()),
                    status=str(tournament.get("status") or random_tournament_status_phrase()),
                    remaining_seconds=tournament_remaining_seconds(tournament),
                ),
                tournament_vote(tournament_id, vote_counts),
                "tournament vote message",
            )
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

    @router.callback_query(F.data.startswith("duel_champion:"))
    async def champion_duel_callback(callback: CallbackQuery, bot: Bot) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message is None or callback.data is None:
            await callback.answer()
            return

        _, champion_id = callback.data.split(":", 1)
        duel_result = await send_duel(
            bot=bot,
            message=callback.message,
            image_pool=image_pool,
            silent_if_active=True,
            champion_id=champion_id,
        )
        if duel_result == "started":
            await callback.answer("Чемпион вышел на дуэль")
        elif duel_result == "active":
            await callback.answer("Дуэль уже идёт")
        else:
            await callback.answer("Чемпион не нашёл соперника")

    @router.callback_query(F.data == "tournament_new")
    async def new_tournament_callback(callback: CallbackQuery, bot: Bot) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message is None:
            await callback.answer()
            return

        tournament_result = await send_tournament(
            bot=bot,
            message=callback.message,
            image_pool=image_pool,
            silent_if_active=True,
        )
        if tournament_result == "started":
            await callback.answer("Запускаю турнир")
        elif tournament_result == "active":
            await callback.answer("Турнир уже идёт")
        else:
            await callback.answer("Турнир не запустился")

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
        is_private = is_private_chat(answer_message) if answer_message else False
        text = format_empty_picture_pool(RANDOM.choice(EMPTY_POOL_PHRASES), is_private=is_private)
        reply_markup = empty_picture_pool_actions(is_private=is_private)
        if answer_message:
            await answer_message.answer(text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        return

    try:
        await telegram_request_with_retry(
            lambda: bot.send_photo(
                chat_id=destination_chat_id,
                photo=image.file_id,
                caption=format_picture_caption(image),
                parse_mode="HTML",
                reply_markup=picture_actions_with_counts(
                    image_id=image.id,
                    likes=image.likes,
                    dislikes=image.dislikes,
                ),
            ),
            "random picture",
        )
    except TelegramAPIError:
        LOGGER.warning("Failed to send random picture", exc_info=True)
        if answer_message:
            await answer_message.answer("Telegram не отдал пикчу. Попробуйте ещё раз")
        return

    if (
        target_channel_id
        and answer_message
        and str(answer_message.chat.id) != str(target_channel_id)
    ):
        await answer_message.answer("Пикча улетела в канал")


def telegram_message_not_modified(error: TelegramAPIError) -> bool:
    return "message is not modified" in str(error).casefold()


async def telegram_request_with_retry(
    operation: Callable[[], Awaitable[T]],
    description: str,
) -> T:
    for attempt in range(1, TELEGRAM_SEND_RETRIES + 1):
        try:
            return await operation()
        except TelegramNetworkError:
            if attempt == TELEGRAM_SEND_RETRIES:
                raise
            LOGGER.warning(
                "Telegram network error during %s, retrying %s/%s",
                description,
                attempt,
                TELEGRAM_SEND_RETRIES,
                exc_info=True,
            )
            await asyncio.sleep(TELEGRAM_RETRY_BASE_DELAY * attempt)

    raise RuntimeError(f"Telegram request retry loop ended unexpectedly: {description}")


async def send_photo_album_with_fallback(
    bot: Bot,
    chat_id: int,
    file_ids: list[str],
    description: str,
) -> bool:
    try:
        await telegram_request_with_retry(
            lambda: bot.send_media_group(
                chat_id=chat_id,
                media=[InputMediaPhoto(media=file_id) for file_id in file_ids],
            ),
            f"{description} media group",
        )
        return True
    except TelegramAPIError:
        LOGGER.warning(
            "Failed to send %s media group, falling back to separate photos",
            description,
            exc_info=True,
        )

    try:
        for index, file_id in enumerate(file_ids, start=1):
            await telegram_request_with_retry(
                lambda file_id=file_id: bot.send_photo(chat_id=chat_id, photo=file_id),
                f"{description} fallback photo {index}",
            )
    except TelegramAPIError:
        LOGGER.warning("Failed to send %s fallback photos", description, exc_info=True)
        return False

    return True


async def edit_callback_text_if_changed(
    message: Message,
    state: dict,
    text: str,
    reply_markup,
    log_context: str,
) -> None:
    if state.get("score_text") == text:
        return

    try:
        await message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        state["score_text"] = text
    except TelegramAPIError as error:
        if telegram_message_not_modified(error):
            state["score_text"] = text
            return
        LOGGER.warning("Failed to update %s", log_context, exc_info=True)


async def edit_bot_text_if_changed(
    bot: Bot,
    chat_id: int,
    message_id: int,
    state: dict,
    text: str,
    reply_markup,
    log_context: str,
) -> None:
    if state.get("score_text") == text:
        return

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        state["score_text"] = text
    except TelegramAPIError as error:
        if telegram_message_not_modified(error):
            state["score_text"] = text
            return
        LOGGER.warning("Failed to update %s", log_context, exc_info=True)


async def edit_or_send_final_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup,
    log_context: str,
) -> None:
    try:
        await telegram_request_with_retry(
            lambda: bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            ),
            f"{log_context} edit",
        )
        return
    except TelegramAPIError as error:
        if telegram_message_not_modified(error):
            return
        LOGGER.warning("Failed to edit %s, sending fallback", log_context, exc_info=True)

    try:
        await telegram_request_with_retry(
            lambda: bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            ),
            f"{log_context} fallback",
        )
    except TelegramAPIError:
        LOGGER.warning("Failed to send fallback %s", log_context, exc_info=True)


async def send_duel(
    bot: Bot,
    message: Message,
    image_pool: ImagePool,
    silent_if_active: bool = False,
    champion_id: str | None = None,
) -> DuelStartResult:
    chat_id = message.chat.id
    async with duel_lock_for(chat_id):
        if active_duel_id_for_chat(chat_id, "image"):
            if not silent_if_active:
                await message.answer(format_duel_already_active("image"), parse_mode="HTML")
            return "active"

        if image_pool.count() < 2:
            await message.answer("⚔️ Для дуэли нужно хотя бы две пикчи в пуле")
            return "failed"

        duel_pair = (
            image_pool.random_duel_pair_with(champion_id, chat_id=chat_id)
            if champion_id
            else image_pool.random_duel_pair(chat_id=chat_id)
        )
        if duel_pair is None:
            await message.answer("⚔️ Дуэль сорвалась. Пул пустоват")
            return "failed"
        left, right = duel_pair

        media_sent = await send_photo_album_with_fallback(
            bot,
            chat_id,
            [left.file_id, right.file_id],
            "image duel",
        )
        if not media_sent:
            await message.answer("⚔️ Дуэль сорвалась. Telegram не отдал картинки")
            return "failed"

        duel_id = uuid4().hex
        title = random_duel_start_phrase()
        status = random_duel_status_phrase()
        score_text = format_duel_score(0, 0, title=title, status=status)
        duel_sessions[duel_id] = {
            "kind": "image",
            "chat_id": chat_id,
            "left": left.id,
            "right": right.id,
            "votes": {},
            "active": True,
            "title": title,
            "status": status,
            "expires_at": monotonic() + DUEL_SECONDS,
            "score_text": score_text,
        }
        try:
            score_message = await telegram_request_with_retry(
                lambda: message.answer(
                    score_text,
                    parse_mode="HTML",
                    reply_markup=duel_vote(duel_id),
                ),
                "image duel vote message",
            )
        except TelegramAPIError:
            duel_sessions.pop(duel_id, None)
            LOGGER.warning("Failed to send duel vote message", exc_info=True)
            return "failed"

        register_active_duel(chat_id, "image", duel_id)
        schedule_duel_finalizer(duel_id, bot, image_pool, chat_id, score_message.message_id)
        return "started"


async def send_tournament(
    bot: Bot,
    message: Message,
    image_pool: ImagePool,
    silent_if_active: bool = False,
) -> DuelStartResult:
    chat_id = message.chat.id
    async with tournament_lock_for(chat_id):
        if active_tournament_id_for_chat(chat_id):
            if not silent_if_active:
                await message.answer(format_tournament_already_active(), parse_mode="HTML")
            return "active"

        if image_pool.count() < TOURNAMENT_SIZE:
            await message.answer(
                f"🏟 Для турнира нужно хотя бы {TOURNAMENT_SIZE} пикчи в пуле",
            )
            return "failed"

        candidates = image_pool.random_tournament_candidates(
            chat_id=chat_id,
            size=TOURNAMENT_SIZE,
        )
        if candidates is None:
            await message.answer("🏟 Турнир сорвался. Пул не набрал состав")
            return "failed"

        media_sent = await send_photo_album_with_fallback(
            bot,
            chat_id,
            [record.file_id for record in candidates],
            "image tournament",
        )
        if not media_sent:
            await message.answer("🏟 Турнир сорвался. Telegram не отдал картинки")
            return "failed"

        tournament_id = uuid4().hex
        title = random_tournament_start_phrase()
        status = random_tournament_status_phrase()
        score_text = format_tournament_score([0, 0, 0, 0], title=title, status=status)
        tournament_sessions[tournament_id] = {
            "chat_id": chat_id,
            "records": [record.id for record in candidates],
            "votes": {},
            "active": True,
            "title": title,
            "status": status,
            "expires_at": monotonic() + TOURNAMENT_SECONDS,
            "score_text": score_text,
        }
        try:
            score_message = await telegram_request_with_retry(
                lambda: message.answer(
                    score_text,
                    parse_mode="HTML",
                    reply_markup=tournament_vote(tournament_id),
                ),
                "tournament vote message",
            )
        except TelegramAPIError:
            tournament_sessions.pop(tournament_id, None)
            LOGGER.warning("Failed to send tournament vote message", exc_info=True)
            return "failed"

        register_active_tournament(chat_id, tournament_id)
        schedule_tournament_finalizer(
            tournament_id,
            bot,
            image_pool,
            chat_id,
            score_message.message_id,
        )
        return "started"


def resolve_image_duel_result(duel: dict, image_pool: ImagePool) -> str:
    final_text = duel.get("final_text")
    if isinstance(final_text, str):
        duel["active"] = False
        return final_text

    duel["active"] = False
    left_votes, right_votes = duel_vote_counts(duel)

    if left_votes == right_votes:
        image_pool.finish_duel(loser_id=None)
        final_text = format_duel_result(left_votes, right_votes, winner=None)
    elif left_votes > right_votes:
        image_pool.finish_duel(loser_id=duel["right"])
        final_text = format_duel_result(left_votes, right_votes, winner="left")
    else:
        image_pool.finish_duel(loser_id=duel["left"])
        final_text = format_duel_result(left_votes, right_votes, winner="right")

    duel["final_text"] = final_text
    return final_text


def resolve_tournament_result(tournament: dict, image_pool: ImagePool) -> str:
    final_text = tournament.get("final_text")
    if isinstance(final_text, str):
        tournament["active"] = False
        return final_text

    tournament["active"] = False
    vote_counts = tournament_vote_counts(tournament)
    winner = tournament_winner(vote_counts)
    image_pool.record_tournament_result(tied=winner is None)
    final_text = format_tournament_result(vote_counts, winner=winner)
    tournament["final_text"] = final_text
    return final_text


def callback_chat_id(callback: CallbackQuery, session: dict) -> int | None:
    raw_chat_id = session.get("chat_id")
    if raw_chat_id is not None:
        try:
            return int(raw_chat_id)
        except (TypeError, ValueError):
            LOGGER.warning("Interactive session has invalid chat_id: %r", raw_chat_id)

    message = callback.message
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    if chat_id is None:
        return None

    try:
        return int(chat_id)
    except (TypeError, ValueError):
        LOGGER.warning("Callback message has invalid chat_id: %r", chat_id)
        return None


async def close_expired_image_duel_from_callback(
    callback: CallbackQuery,
    bot: Bot,
    image_pool: ImagePool,
    duel_id: str,
    duel: dict,
) -> None:
    chat_id = callback_chat_id(callback, duel)
    if chat_id is None:
        LOGGER.warning("Cannot close expired image duel %s without chat_id", duel_id)
        duel["active"] = False
        duel_sessions.pop(duel_id, None)
        duel_tasks.pop(duel_id, None)
        return

    result_text = resolve_image_duel_result(duel, image_pool)
    if callback.message:
        await edit_or_send_final_message(
            bot=bot,
            chat_id=chat_id,
            message_id=callback.message.message_id,
            text=result_text,
            reply_markup=new_duel(),
            log_context="expired image duel message",
        )
    clear_active_duel(chat_id, "image", duel_id)
    duel_sessions.pop(duel_id, None)
    duel_tasks.pop(duel_id, None)


async def close_expired_tournament_from_callback(
    callback: CallbackQuery,
    bot: Bot,
    image_pool: ImagePool,
    tournament_id: str,
    tournament: dict,
) -> None:
    chat_id = callback_chat_id(callback, tournament)
    if chat_id is None:
        LOGGER.warning("Cannot close expired tournament %s without chat_id", tournament_id)
        tournament["active"] = False
        tournament_sessions.pop(tournament_id, None)
        tournament_tasks.pop(tournament_id, None)
        return

    result_text = resolve_tournament_result(tournament, image_pool)
    if callback.message:
        await edit_or_send_final_message(
            bot=bot,
            chat_id=chat_id,
            message_id=callback.message.message_id,
            text=result_text,
            reply_markup=new_tournament(tournament_winner_record_id(tournament)),
            log_context="expired tournament message",
        )
    clear_active_tournament(chat_id, tournament_id)
    tournament_sessions.pop(tournament_id, None)
    tournament_tasks.pop(tournament_id, None)


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

        result_text = resolve_image_duel_result(duel, image_pool)
        await edit_or_send_final_message(
            bot=bot,
            chat_id=chat_id,
            message_id=message_id,
            text=result_text,
            reply_markup=new_duel(),
            log_context="completed image duel message",
        )
    except Exception:
        LOGGER.exception("Duel finalizer crashed")
    finally:
        clear_active_duel(chat_id, "image", duel_id)
        duel_sessions.pop(duel_id, None)
        duel_tasks.pop(duel_id, None)


async def finalize_tournament(
    tournament_id: str,
    bot: Bot,
    image_pool: ImagePool,
    chat_id: int,
    message_id: int,
) -> None:
    try:
        while True:
            tournament = tournament_sessions.get(tournament_id)
            if tournament is None or not tournament.get("active", False):
                return

            remaining_seconds = tournament_remaining_seconds(tournament)
            if remaining_seconds <= 0:
                break

            await asyncio.sleep(min(DUEL_TICK_SECONDS, remaining_seconds))
            tournament = tournament_sessions.get(tournament_id)
            if tournament is None or not tournament.get("active", False):
                return

            remaining_seconds = tournament_remaining_seconds(tournament)
            if remaining_seconds > 0:
                await update_tournament_score_message(
                    bot=bot,
                    chat_id=chat_id,
                    message_id=message_id,
                    tournament_id=tournament_id,
                    tournament=tournament,
                    remaining_seconds=remaining_seconds,
                )

        tournament = tournament_sessions.get(tournament_id)
        if tournament is None or not tournament.get("active", False):
            return

        result_text = resolve_tournament_result(tournament, image_pool)

        await edit_or_send_final_message(
            bot=bot,
            chat_id=chat_id,
            message_id=message_id,
            text=result_text,
            reply_markup=new_tournament(tournament_winner_record_id(tournament)),
            log_context="completed tournament message",
        )
    except Exception:
        LOGGER.exception("Tournament finalizer crashed")
    finally:
        clear_active_tournament(chat_id, tournament_id)
        tournament_sessions.pop(tournament_id, None)
        tournament_tasks.pop(tournament_id, None)


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


def schedule_tournament_finalizer(
    tournament_id: str,
    bot: Bot,
    image_pool: ImagePool,
    chat_id: int,
    message_id: int,
) -> None:
    task = asyncio.create_task(
        finalize_tournament(tournament_id, bot, image_pool, chat_id, message_id)
    )
    tournament_tasks[tournament_id] = task
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
    await edit_bot_text_if_changed(
        bot,
        chat_id,
        message_id,
        duel,
        format_duel_score(
            left_votes,
            right_votes,
            title=str(duel.get("title") or random_duel_start_phrase()),
            status=str(duel.get("status") or random_duel_status_phrase()),
            remaining_seconds=remaining_seconds,
        ),
        duel_vote(duel_id, left_votes, right_votes),
        "duel timer message",
    )


async def update_tournament_score_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    tournament_id: str,
    tournament: dict,
    remaining_seconds: int,
) -> None:
    vote_counts = tournament_vote_counts(tournament)
    await edit_bot_text_if_changed(
        bot,
        chat_id,
        message_id,
        tournament,
        format_tournament_score(
            vote_counts,
            title=str(tournament.get("title") or random_tournament_start_phrase()),
            status=str(tournament.get("status") or random_tournament_status_phrase()),
            remaining_seconds=remaining_seconds,
        ),
        tournament_vote(tournament_id, vote_counts),
        "tournament timer message",
    )


def duel_vote_counts(duel: dict) -> tuple[int, int]:
    votes = duel.get("votes", {})
    return (
        sum(1 for vote in votes.values() if vote == "left"),
        sum(1 for vote in votes.values() if vote == "right"),
    )


def tournament_vote_counts(tournament: dict) -> list[int]:
    votes = tournament.get("votes", {})
    counts = [0, 0, 0, 0]
    for vote in votes.values():
        if isinstance(vote, int) and vote in range(TOURNAMENT_SIZE):
            counts[vote] += 1
    return counts


def tournament_winner(votes: list[int]) -> int | None:
    if not votes:
        return None

    best_score = max(votes)
    if best_score <= 0 or votes.count(best_score) != 1:
        return None
    return votes.index(best_score)


def tournament_winner_record_id(tournament: dict) -> str | None:
    winner = tournament_winner(tournament_vote_counts(tournament))
    if winner is None:
        return None

    records = tournament.get("records")
    if not isinstance(records, list) or winner >= len(records):
        return None

    record_id = records[winner]
    return str(record_id) if record_id else None


def duel_remaining_seconds(duel: dict) -> int:
    try:
        expires_at = float(duel.get("expires_at") or 0)
    except (TypeError, ValueError):
        return 0

    return max(0, round(expires_at - monotonic()))


def tournament_remaining_seconds(tournament: dict) -> int:
    return duel_remaining_seconds(tournament)


def duel_is_stale(duel: dict) -> bool:
    try:
        expires_at = float(duel.get("expires_at") or 0)
    except (TypeError, ValueError):
        return True

    return monotonic() > expires_at + DUEL_STALE_GRACE_SECONDS


def tournament_is_stale(tournament: dict) -> bool:
    return duel_is_stale(tournament)


def duel_lock_for(chat_id: int) -> asyncio.Lock:
    lock = duel_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        duel_locks[chat_id] = lock
    return lock


def tournament_lock_for(chat_id: int) -> asyncio.Lock:
    lock = tournament_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        tournament_locks[chat_id] = lock
    return lock


def active_duel_id_for_chat(chat_id: int, kind: DuelKind) -> str | None:
    chat_duels = active_duels_by_chat.get(chat_id)
    if not chat_duels:
        return None

    duel_id = chat_duels.get(kind)
    if duel_id is None:
        return None

    duel = duel_sessions.get(duel_id)
    duel_kind = duel.get("kind", "image") if duel else None
    if duel and duel_kind == kind and duel.get("active", False):
        if duel_is_stale(duel):
            duel["active"] = False
            chat_duels.pop(kind, None)
            if not chat_duels:
                active_duels_by_chat.pop(chat_id, None)
            duel_sessions.pop(duel_id, None)
            duel_tasks.pop(duel_id, None)
            LOGGER.warning("Cleared stale %s duel %s in chat %s", kind, duel_id, chat_id)
            return None
        return duel_id

    chat_duels.pop(kind, None)
    if not chat_duels:
        active_duels_by_chat.pop(chat_id, None)
    return None


def register_active_duel(chat_id: int, kind: DuelKind, duel_id: str) -> None:
    active_duels_by_chat.setdefault(chat_id, {})[kind] = duel_id


def clear_active_duel(chat_id: int, kind: DuelKind, duel_id: str) -> None:
    chat_duels = active_duels_by_chat.get(chat_id)
    if not chat_duels:
        return

    if chat_duels.get(kind) == duel_id:
        chat_duels.pop(kind, None)

    if not chat_duels:
        active_duels_by_chat.pop(chat_id, None)


def active_tournament_id_for_chat(chat_id: int) -> str | None:
    tournament_id = active_tournaments_by_chat.get(chat_id)
    if tournament_id is None:
        return None

    tournament = tournament_sessions.get(tournament_id)
    if tournament and tournament.get("active", False):
        if tournament_is_stale(tournament):
            tournament["active"] = False
            active_tournaments_by_chat.pop(chat_id, None)
            tournament_sessions.pop(tournament_id, None)
            tournament_tasks.pop(tournament_id, None)
            LOGGER.warning("Cleared stale tournament %s in chat %s", tournament_id, chat_id)
            return None
        return tournament_id

    active_tournaments_by_chat.pop(chat_id, None)
    return None


def register_active_tournament(chat_id: int, tournament_id: str) -> None:
    active_tournaments_by_chat[chat_id] = tournament_id


def clear_active_tournament(chat_id: int, tournament_id: str) -> None:
    if active_tournaments_by_chat.get(chat_id) == tournament_id:
        active_tournaments_by_chat.pop(chat_id, None)


async def activate_upload(message: Message, state: FSMContext) -> bool:
    if not is_private_chat(message):
        await message.answer(format_upload_private_only(), parse_mode="HTML")
        return False

    await state.set_state(AddPicture.uploading)
    active_uploads[message.chat.id] = new_upload_session()
    upload_text = format_upload_opened(RANDOM.choice(UPLOAD_START_PHRASES))
    await message.answer(
        upload_text,
        parse_mode="HTML",
        reply_markup=upload_menu(),
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
    achievement_names = list(data.get("achievement_names", []))
    await state.clear()
    active_uploads.pop(message.chat.id, None)

    lines = [
        "<b>✅ Загрузка закрыта</b>",
        "Пакет разобран и припаркован на складе",
        "",
        "<b>📦 Итог пакета</b>",
        format_metric("✅ Добавлено", added),
        format_metric("♻️ Дублей", duplicates),
        format_metric("🚫 Не принято", failed),
    ]
    if achievement_names:
        lines.append(format_metric("🏅 Новый ранг", achievement_names[-1]))
    easter_egg = rare_easter_egg()
    if easter_egg:
        lines.extend(["", easter_egg])

    await message.answer("\n".join(lines), parse_mode="HTML")


def is_upload_active(message: Message) -> bool:
    return is_private_chat(message) and message.chat.id in active_uploads


def is_any_upload_active(message: Message, current_state: str | None) -> bool:
    return (
        current_state == AddPicture.uploading.state
        or is_upload_active(message)
    )


def is_private_chat(message: Message) -> bool:
    return message.chat.type == "private"


def new_upload_session() -> UploadSession:
    return {
        "added": 0,
        "failed": 0,
        "duplicates": 0,
        "announced_achievements": set(),
        "achievement_names": [],
    }


def upload_data(message: Message) -> UploadSession:
    return active_uploads.setdefault(
        message.chat.id,
        new_upload_session(),
    )


async def show_menu(
    message: Message,
    image_pool: ImagePool,
    edit_existing: bool = False,
) -> None:
    is_private = is_private_chat(message)
    chat_id = message.chat.id
    arena_state = active_arena_snapshot(chat_id)
    reply_markup = main_menu(
        is_private=is_private,
        image_duel_active=arena_state["image_seconds"] is not None,
        tournament_active=arena_state["tournament_seconds"] is not None,
        image_duel_seconds=arena_state["image_seconds"],
        tournament_seconds=arena_state["tournament_seconds"],
    )
    text = format_main_menu(image_pool, chat_id, is_private=is_private)
    if edit_existing:
        await answer_or_edit_panel(message, text, reply_markup, "main menu")
        return

    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


async def send_backup(message: Message, image_pool: ImagePool) -> None:
    await message.answer(format_backup_started(), parse_mode="HTML")

    sent_files = 0
    with tempfile.TemporaryDirectory(prefix="kartinkomet-backup-") as raw_temp_dir:
        temp_dir = Path(raw_temp_dir)
        database_backup_path = temp_dir / "kartinkomet.sqlite"
        if image_pool.export_database_backup(database_backup_path):
            await message.answer_document(
                FSInputFile(database_backup_path, filename="kartinkomet.sqlite"),
                caption="SQLite-снимок всей базы",
            )
            sent_files += 1

        for source_path, caption in backup_json_sources(image_pool):
            if not source_path.exists() or source_path.stat().st_size == 0:
                continue

            await message.answer_document(
                FSInputFile(source_path, filename=source_path.name),
                caption=caption,
            )
            sent_files += 1

    await message.answer(format_backup_done(sent_files), parse_mode="HTML")


def backup_json_sources(image_pool: ImagePool) -> tuple[tuple[Path, str], ...]:
    return ((image_pool.storage_path, "JSON-страховка пикч"),)


async def answer_or_edit_panel(
    message: Message,
    text: str,
    reply_markup,
    log_context: str,
) -> None:
    try:
        await message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
        return
    except TelegramAPIError as error:
        if telegram_message_not_modified(error):
            return
        LOGGER.debug("Cannot edit %s, sending a new panel", log_context, exc_info=True)

    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


def format_main_menu(
    image_pool: ImagePool,
    chat_id: int,
    is_private: bool,
) -> str:
    upload_note = (
        "личка открыта, можно заносить контент"
        if is_private
        else "из группы покажу маршрут в личку"
    )
    return (
        "<b>🎛 Пульт kartinkomet</b>\n"
        "<i>один экран, все рычаги</i>\n\n"
        "<b>📦 Склад</b>\n"
        f"Пикчи <b>{image_pool.count()}</b>\n\n"
        "<b>⚔️ Арены</b>\n"
        f"Пикч-бой <b>{active_duel_status(chat_id, 'image')}</b> · "
        f"Турнир <b>{active_tournament_status(chat_id)}</b>\n\n"
        "<b>📥 Загрузка</b>\n"
        f"{upload_note}"
    )


def format_random_menu() -> str:
    return (
        "<b>🎲 Выдача</b>\n\n"
        "Контент-подача без лишних церемоний\n\n"
        "<b>Доступно</b>\n"
        "<code>🎲 Пикча</code> — случайный визуальный выстрел"
    )


def format_arena_menu(chat_id: int) -> str:
    return (
        "<b>⚔️ Арены</b>\n\n"
        "Народный стресс-тест для пикч\n\n"
        "<b>Сейчас</b>\n"
        f"Пикч-бой: <b>{active_duel_status(chat_id, 'image')}</b>\n"
        f"Турнир: <b>{active_tournament_status(chat_id)}</b>\n\n"
        "<b>Правило</b>\n"
        "Дуэль удаляет проигравшую пикчу, турнир никого не трогает"
    )


def format_storage_menu(image_pool: ImagePool) -> str:
    return (
        "<b>📦 Склад</b>\n\n"
        "Инвентарь, вклад и вход в загрузку\n\n"
        "<b>Внутри</b>\n"
        f"Пикчи: <b>{image_pool.count()}</b>\n"
        "<b>Навигация</b>\n"
        "Счётчик, топ, личная карточка и загрузочный отсек"
    )


def format_metric(label: str, value: int | str) -> str:
    return f"{label}: <b>{value}</b>"


def format_section(title: str, *lines: str) -> str:
    return "\n".join([f"<b>{title}</b>", *lines])


def format_stats(
    image_pool: ImagePool,
    chat_id: int | None = None,
) -> str:
    stats = image_pool.stats()
    pool_lines = [format_metric("Пикчи", stats.total_images)]
    random_lines = [format_metric("Пикчи", stats.total_shows)]
    reaction_lines = [
        f"Пикчи: 🤙🏻 <b>{stats.total_likes}</b> · 🖕🏻 <b>{stats.total_dislikes}</b>",
    ]
    sections = [
        "<b>📊 Сводка склада</b>",
        format_section("📦 Контент", *pool_lines),
        format_section("🎲 Выдача", *random_lines),
        format_section(
            "⚔️ Арены",
            format_metric("Дуэли", stats.total_duels),
            format_metric("Казней", stats.duel_executions),
            format_metric("Мирных исходов", stats.duel_ties),
            format_metric("Турниры", stats.total_tournaments),
            format_metric("Без чемпиона", stats.tournament_ties),
        ),
        format_section("⚖️ Реакции", *reaction_lines),
    ]
    if chat_id is not None:
        sections.append(format_section("🟢 Сейчас", *format_active_duel_lines(chat_id)))
    return "\n\n".join(sections)


def format_active_duel_lines(chat_id: int) -> list[str]:
    return [
        format_metric("Дуэль пикч", active_duel_status(chat_id, "image")),
        format_metric("Турнир", active_tournament_status(chat_id)),
    ]


def format_timer(seconds: int) -> str:
    safe_seconds = max(0, seconds)
    minutes, seconds_left = divmod(safe_seconds, 60)
    return f"{minutes:02d}:{seconds_left:02d}"


def active_arena_snapshot(chat_id: int) -> dict[str, int | None]:
    return {
        "image_seconds": active_duel_seconds(chat_id, "image"),
        "tournament_seconds": active_tournament_seconds(chat_id),
    }


def active_duel_seconds(chat_id: int, kind: DuelKind) -> int | None:
    duel_id = active_duel_id_for_chat(chat_id, kind)
    if duel_id is None:
        return None

    duel = duel_sessions.get(duel_id)
    if not duel:
        return None

    return duel_remaining_seconds(duel)


def active_tournament_seconds(chat_id: int) -> int | None:
    tournament_id = active_tournament_id_for_chat(chat_id)
    if tournament_id is None:
        return None

    tournament = tournament_sessions.get(tournament_id)
    if not tournament:
        return None

    return tournament_remaining_seconds(tournament)


def active_duel_status(chat_id: int, kind: DuelKind) -> str:
    seconds = active_duel_seconds(chat_id, kind)
    if seconds is None:
        return "свободно"

    return f"идёт {format_timer(seconds)}"


def active_tournament_status(chat_id: int) -> str:
    seconds = active_tournament_seconds(chat_id)
    if seconds is None:
        return "свободно"

    return f"идёт {format_timer(seconds)}"


def format_start() -> str:
    return (
        "<b>👋 @kartinkomet_bot на связи</b>\n\n"
        "Склад пикч, арены для голосований и народный суд без лишней мишуры\n\n"
        "<b>🎛 Быстрый старт</b>\n"
        "<code>🎲 Пикча</code> — случайная выдача\n"
        "<code>⚔️ Пикч-бой</code> — дуэль двух пикч\n"
        "<code>🏟 Турнир</code> - четыре пикчи, один чемпион\n\n"
        "<b>📥 Загрузка</b>\n"
        "<code>📥 Загрузка</code> в личке принимает контент\n"
        "<code>📬 В личку</code> в группе показывает маршрут"
    )


def format_help() -> str:
    sections = [
        "<b>🧭 Карта команд kartinkomet</b>",
        format_section(
            "🎛 Навигация",
            "<code>/start</code> — запустить картинный реактор",
            "<code>/menu</code> — открыть главный пульт",
            "<code>/help</code> — показать карту команд",
        ),
        format_section(
            "🎲 Выдача",
            "<code>/pic</code> — случайная пикча со склада",
        ),
        format_section(
            "⚔️ Арены",
            "<code>/duel</code> — дуэль двух случайных пикч",
            "<code>/tournament</code> — турнир четырёх пикч",
            "Дуэль удаляет проигравшую пикчу, турнир никого не удаляет",
        ),
        format_section(
            "📥 Загрузка",
            "<code>/upload_pidor</code> — принять пикчи в личке",
            "Внутри загрузки: <code>/done</code> завершает, <code>/cancel</code> отменяет",
        ),
        format_section(
            "📊 Склад",
            "<code>/stats</code> — сводка склада и арен",
            "<code>/count</code> — быстрый счётчик склада",
            "<code>/me</code> — личная карточка игрока",
            "<code>/top</code> — топ поставщиков пикч",
        ),
        format_section(
            "🧹 Народный суд",
            "2 средних пальца удаляют пикчу из пула",
        ),
    ]
    return "\n\n".join(sections)


def format_count(image_pool: ImagePool) -> str:
    return (
        "<b>📦 Склад</b>\n\n"
        "<b>Контент</b>\n"
        f"{format_metric('Пикчи', image_pool.count())}"
    )


def format_count_alert(image_pool: ImagePool) -> str:
    stats = image_pool.stats()
    return (
        "📦 Склад\n"
        f"Пикч: {image_pool.count()}\n"
        f"Пикч-дуэлей: {stats.total_duels}\n"
        f"Турниров: {stats.total_tournaments}"
    )


def format_upload_hub(is_private: bool = False) -> str:
    if is_private:
        return (
            "<b>📬 Загрузочный отсек</b>\n\n"
            "Выберите, что заносим в общий склад\n\n"
            "<code>📥 Пикчи</code> — фото, пачки, альбомы\n"
        )

    return (
        "<b>📬 Загрузка живёт в личке</b>\n\n"
        "В группе оставляем выдачу и арены, а склад пополняем один на один с ботом\n\n"
        "Нажмите кнопку ниже, бот подскажет маршрут"
    )


def format_upload_private_only() -> str:
    return (
        "<b>📬 Пикчи принимаются в личке</b>\n\n"
        "В группе остаются выдача, арены и сводка. Пикчи принимаю один на один, так стабильнее\n\n"
        "<b>Маршрут</b>\n"
        "Откройте <a href=\"https://t.me/kartinkomet_bot\">@kartinkomet_bot</a>\n"
        f"Отправьте <code>/{UPLOAD_COMMAND}</code>\n"
        "Кидайте пикчи туда"
    )


def format_upload_opened(intro: str) -> str:
    return (
        "<b>📥 Приём пикч открыт</b>\n\n"
        f"{escape(intro)}\n\n"
        "<b>Что кидать</b>\n"
        "Фото, пачку, альбом или пересланные изображения\n\n"
        "<b>Управление</b>\n"
        "<code>✅ Закончить</code> — сохранить пакет\n"
        "<code>❌ Отмена</code> — закрыть без отчёта"
    )


def format_duel_already_active(kind: DuelKind = "image") -> str:
    busy_line = "Сейчас занята пикчевая арена"
    free_line = "Дождитесь финала или запустите турнир"

    return (
        "<b>⚔️ Дуэль уже идёт</b>\n\n"
        f"{busy_line}\n"
        f"{free_line}\n\n"
        "Дубль внутри одного раздела не запускаю, чтобы чат не поехал"
    )


def format_tournament_already_active() -> str:
    return (
        "<b>🏟 Турнир уже идёт</b>\n\n"
        "Дождитесь финального свистка, потом запускайте новый"
    )


def format_user_id(user_id: int) -> str:
    return (
        "<b>🪪 Telegram user ID</b>\n\n"
        f"<code>{user_id}</code>"
    )


def parse_user_id_argument(message: Message) -> int | None:
    raw_text = (message.text or message.caption or "").strip()
    parts = raw_text.split(maxsplit=1)
    if len(parts) != 2:
        return None

    try:
        return int(parts[1].strip())
    except ValueError:
        return None


def format_upload_limit() -> str:
    return (
        "<b>🧯 Стоп-кран сработал</b>\n\n"
        f"{format_metric('Лимит', f'{UPLOAD_LIMIT_PER_HOUR} новых пикч в час')}\n"
        "Пауза, склад перегрелся"
    )


def format_duplicate_skipped() -> str:
    return "♻️ Дубликат. Уже лежит на складе"


def format_invalid_file() -> str:
    return (
        "⚠️ Файл не принят\n\n"
        "Отправьте фото или изображение как документ: JPG, PNG, WEBP"
    )


def format_empty_picture_pool(phrase: str, is_private: bool = False) -> str:
    action = (
        "Нажмите <code>📥 Пикчи</code> и кидайте пакет сюда"
        if is_private
        else "Нажмите <code>📬 Как загрузить пикчи</code> и бот покажет маршрут в личку"
    )
    return (
        "<b>📭 Склад пикч пуст</b>\n\n"
        f"{escape(phrase)}\n"
        "На полках пока только пыль и ожидание\n\n"
        "<b>Маршрут</b>\n"
        f"{action}"
    )


def format_upload_cancelled() -> str:
    return (
        "<b>❌ Загрузка отменена</b>\n\n"
        "Пакет закрыт без итоговой сводки"
    )


def format_upload_not_active() -> str:
    return (
        "<b>⚠️ Загрузка не открыта</b>\n\n"
        "<b>Открыть</b>\n"
        f"Пикчи: <code>/{UPLOAD_COMMAND}</code>\n"
        "Загружать лучше в личке с ботом"
    )


def format_admin_only(action: str) -> str:
    return f"🔒 {action} доступна только админам"


def format_backup_started() -> str:
    return (
        "<b>📦 Собираю бэкап</b>\n\n"
        "Сейчас отправлю файлы базы в личку"
    )


def format_backup_done(sent_files: int) -> str:
    return (
        "<b>✅ Бэкап отправлен</b>\n\n"
        f"Файлов: <b>{sent_files}</b>\n"
        "Главный файл: <code>kartinkomet.sqlite</code>"
    )


def format_reset_stats_done() -> str:
    return (
        "<b>♻️ Статистика сброшена</b>\n\n"
        "• реакции обнулены\n"
        "• показы обнулены\n"
        "• дуэли обнулены\n"
        "• память рандома очищена\n"
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
        "<b>👤 Карточка игрока</b>",
        "Ваш след на складе",
        "",
        "<b>📦 Вклад</b>",
        format_metric("Пикчи", uploaded_count),
        format_metric("Ранг", current_achievement),
        "",
        "<b>⚖️ Реакции</b>",
        f"🤙🏻 <b>{reaction_stats.likes}</b> · 🖕🏻 <b>{reaction_stats.dislikes}</b>",
        format_metric("Показы", reaction_stats.shown),
        "",
        "<b>🎖 Титул</b>",
        format_metric("Качество", quality_title(reaction_stats)),
    ]
    if combo_achievements:
        lines.append("")
        lines.append("<b>🧩 Комбо</b>")
        lines.extend(f"• <b>{item}</b>" for item in combo_achievements)

    lines.append("")
    lines.append("<b>🎯 Следующий ранг</b>")

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
            "<b>🏆 Топ поставщиков</b>\n\n"
            "Пьедестал пока пустует. Кто-то должен занести первую пикчу"
        )

    lines = ["<b>🏆 Топ поставщиков</b>", ""]
    medals = ["🥇", "🥈", "🥉"]
    for position, (user_id, count) in enumerate(top_uploaders, start=1):
        if position == 1:
            lines.append("<b>👑 Элита</b>")
            lines.append("")
        if position == 4:
            lines.append("")
            lines.append("<b>📦 Складская смена</b>")
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


def random_picture_caption() -> str:
    return RANDOM.choice(PICTURE_CAPTIONS)


def format_picture_caption(image) -> str:
    return (
        f"{escape(random_picture_caption())}\n\n"
        f"{format_reaction_hint()}"
    )


def format_reaction_hint() -> str:
    return "<b>Глас народа</b>\n🤙🏻 оставить · 🖕🏻 убрать"


def rare_easter_egg() -> str | None:
    if RANDOM.randrange(20) != 0:
        return None

    return escape(
        RANDOM.choice(
            (
                "Склад тихо хлопнул дверью холодильника",
                "Рандом сделал вид, что всё под контролем",
                "Кнопки переглянулись и промолчали",
                "Архив пополнился и немного осмелел",
                "Где-то в логах стало уютнее",
            )
        )
    )


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
    if stats.uploaded >= UPLOAD_MARATHON_THRESHOLD:
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
        verdict = "⚖️ Пока ничья"
    elif left_votes > right_votes:
        verdict = "🔥 Ведёт 🅰️"
    else:
        verdict = "🔥 Ведёт 🅱️"

    seconds_left = DUEL_SECONDS if remaining_seconds is None else max(0, remaining_seconds)
    return (
        "<b>⚔️ Арена пикч</b>\n\n"
        f"{escape(title or random_duel_start_phrase())}\n"
        f"{escape(status or random_duel_status_phrase())}\n\n"
        "<b>Счёт</b>\n"
        f"🅰️ Первый: <b>{left_votes}</b>\n"
        f"🅱️ Второй: <b>{right_votes}</b>\n\n"
        "<b>Статус</b>\n"
        f"⏱ <b>{format_timer(seconds_left)}</b> · {verdict}"
    )


def format_duel_result(left_votes: int, right_votes: int, winner: str | None) -> str:
    if winner is None:
        phrase = random_duel_tie_phrase()
        verdict = "⚖️ Ничья\n📦 Обе пикчи остаются на складе"
    elif winner == "left":
        phrase = random_duel_win_phrase()
        verdict = "🏆 Победитель: <b>🅰️ первая</b>\n🗑 Удалена: <b>🅱️ вторая</b>"
    else:
        phrase = random_duel_win_phrase()
        verdict = "🏆 Победитель: <b>🅱️ вторая</b>\n🗑 Удалена: <b>🅰️ первая</b>"

    return (
        "<b>⚖️ Приговор арены</b>\n\n"
        f"{escape(phrase)}\n\n"
        "<b>Счёт</b>\n"
        f"🅰️ Первый: <b>{left_votes}</b>\n"
        f"🅱️ Второй: <b>{right_votes}</b>\n\n"
        "<b>История боя</b>\n"
        f"{format_battle_history(left_votes, right_votes, winner, item_label='мем')}\n\n"
        "<b>Вердикт</b>\n"
        f"{verdict}"
    )


def format_battle_history(
    left_votes: int,
    right_votes: int,
    winner: str | None,
    item_label: str,
) -> str:
    total_votes = left_votes + right_votes
    if winner is None:
        if total_votes == 0:
            return f"Кнопки молчали. Ни один {item_label} не пострадал"
        return f"Голоса разошлись поровну: {total_votes} {plural_votes(total_votes)}"

    margin = abs(left_votes - right_votes)
    winner_label = "🅰️ первый" if winner == "left" else "🅱️ второй"
    loser_label = "🅱️ второй" if winner == "left" else "🅰️ первый"
    return (
        f"{winner_label} забрал бой с отрывом "
        f"{margin} {plural_votes(margin)}. {loser_label} покидает пул"
    )


def plural_votes(value: int) -> str:
    value = abs(value)
    if value % 10 == 1 and value % 100 != 11:
        return "голос"
    if value % 10 in (2, 3, 4) and value % 100 not in (12, 13, 14):
        return "голоса"
    return "голосов"


def format_tournament_score(
    votes: list[int],
    title: str | None = None,
    status: str | None = None,
    remaining_seconds: int | None = None,
) -> str:
    winner = tournament_winner(votes)
    if winner is None:
        verdict = "⚖️ Лидера нет"
    else:
        verdict = f"👑 Ведёт: <b>{tournament_option_label(winner)}</b>"

    seconds_left = TOURNAMENT_SECONDS if remaining_seconds is None else max(0, remaining_seconds)
    return (
        "<b>🏟 Турнир пикч</b>\n\n"
        f"{escape(title or random_tournament_start_phrase())}\n"
        f"{escape(status or random_tournament_status_phrase())}\n\n"
        "<b>Счёт</b>\n"
        f"1️⃣ Первая: <b>{votes[0]}</b> · 2️⃣ Вторая: <b>{votes[1]}</b>\n"
        f"3️⃣ Третья: <b>{votes[2]}</b> · 4️⃣ Четвёртая: <b>{votes[3]}</b>\n\n"
        "<b>Статус</b>\n"
        f"⏱ <b>{format_timer(seconds_left)}</b> · {verdict}"
    )


def format_tournament_result(votes: list[int], winner: int | None) -> str:
    if winner is None:
        phrase = random_tournament_tie_phrase()
        verdict = "⚖️ Чемпион не выбран\n📦 Все пикчи остаются на складе"
    else:
        phrase = random_tournament_win_phrase()
        verdict = f"👑 Чемпион: <b>{tournament_option_label(winner)}</b>\n📦 Остальные остаются на складе"

    return (
        "<b>🏁 Финал витрины</b>\n\n"
        f"{escape(phrase)}\n\n"
        "<b>Счёт</b>\n"
        f"1️⃣ Первая: <b>{votes[0]}</b> · 2️⃣ Вторая: <b>{votes[1]}</b>\n"
        f"3️⃣ Третья: <b>{votes[2]}</b> · 4️⃣ Четвёртая: <b>{votes[3]}</b>\n\n"
        "<b>Итог</b>\n"
        f"{verdict}"
    )


def tournament_option_label(index: int) -> str:
    labels = ["1️⃣ Первая", "2️⃣ Вторая", "3️⃣ Третья", "4️⃣ Четвёртая"]
    return labels[index]


def random_duel_start_phrase() -> str:
    return RANDOM.choice(DUEL_START_PHRASES)


def random_duel_status_phrase() -> str:
    return RANDOM.choice(DUEL_STATUS_PHRASES)


def random_duel_win_phrase() -> str:
    return RANDOM.choice(DUEL_WIN_PHRASES)


def random_duel_tie_phrase() -> str:
    return RANDOM.choice(DUEL_TIE_PHRASES)


def random_tournament_start_phrase() -> str:
    return RANDOM.choice(TOURNAMENT_START_PHRASES)


def random_tournament_status_phrase() -> str:
    return RANDOM.choice(TOURNAMENT_STATUS_PHRASES)


def random_tournament_win_phrase() -> str:
    return RANDOM.choice(TOURNAMENT_WIN_PHRASES)


def random_tournament_tie_phrase() -> str:
    return RANDOM.choice(TOURNAMENT_TIE_PHRASES)


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

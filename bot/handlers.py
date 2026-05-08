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
from bot.joke_pool import JokePool
from bot.keyboards import (
    duel_vote,
    joke_actions,
    joke_actions_with_counts,
    joke_duel_vote,
    main_menu,
    new_duel,
    new_joke_duel,
    new_tournament,
    picture_actions,
    picture_actions_with_counts,
    tournament_vote,
    upload_menu,
)
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
JOKE_UPLOAD_COMMAND = "upload_joke"
DUEL_SECONDS = 60
JOKE_DUEL_SECONDS = 120
TOURNAMENT_SECONDS = 90
TOURNAMENT_SIZE = 4
DUEL_TICK_SECONDS = 15
DUEL_STALE_GRACE_SECONDS = 20
TELEGRAM_TEXT_CHUNK_SIZE = 3500
UPLOAD_MARATHON_THRESHOLD = 100
RANDOM = random.SystemRandom()
LOGGER = logging.getLogger(__name__)

JOKE_DUEL_START_PHRASES = (
    "Анекдотная заруба в эфире",
    "Стендап без лицензии стартовал",
    "Два текста вошли в чат",
    "Словесная драка началась",
    "Комиссия по смешному собралась",
    "Блокнот вывел бойцов",
    "Пульт юмора дал искру",
    "Суд баянов открыт",
    "Ринг анекдотов готов",
    "Народный разбор шуток начался",
)
JOKE_DUEL_STATUS_PHRASES = (
    "Чат решает, кто достоин жить в блокноте",
    "Кнопки принимают показания",
    "Смеховая комиссия смотрит строго",
    "Один текст выйдет сухим, второй уйдёт в архив",
    "Голосование идёт без права на скуку",
    "Блокнот нервно перелистывает страницы",
    "Публика выбирает меньшее зло",
    "Юмор проходит народную проверку",
    "Присяжные держат палец на кнопке",
    "Таймер тащит драму за шиворот",
)
JOKE_DUEL_WIN_PHRASES = (
    "Чат вынес приговор. Победитель остаётся в блокноте",
    "Смеховая комиссия определилась. Слабый текст удалён",
    "Народ сказал своё. Проигравший анекдот покинул пул",
    "Кнопки всё решили. Победитель получил прописку",
    "Блокнот пережил чистку. Один анекдот не вывез",
    "Юмор прошёл фильтр. Проигравший отправлен за дверь",
    "Финальный смешок прозвучал. Победитель остаётся",
    "Суд баянов закрыл заседание. Лишний текст удалён",
    "Чат выбрал живого. Второй анекдот ушёл в туман",
    "Вердикт принят. Победитель продолжит гастроли",
)
JOKE_DUEL_TIE_PHRASES = (
    "Чат не определился. Оба анекдота остаются",
    "Ничья. Блокнот решил не устраивать казнь",
    "Присяжные зависли. Оба текста выжили",
    "Суд смешного ушёл на обед. Удалений нет",
    "Голоса разошлись поровну. Все остаются при своих",
    "Кнопки не договорились. Блокнот никого не трогает",
    "Народный суд моргнул. Оба анекдота живы",
    "Таймер сгорел без жертвы. Ничья",
    "Арена сохранила обоих. Видимо, так надо",
    "Вердикт размазался. Казни не будет",
)

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


class UploadSession(TypedDict):
    added: int
    failed: int
    duplicates: int
    announced_achievements: set[int]


class JokeUploadSession(TypedDict):
    added: int
    failed: int
    duplicates: int


DuelStartResult = Literal["started", "active", "failed"]
DuelKind = Literal["image", "joke"]


active_uploads: dict[int, UploadSession] = {}
active_joke_uploads: dict[int, JokeUploadSession] = {}
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


class AddJoke(StatesGroup):
    uploading = State()


def build_router(
    image_pool: ImagePool,
    joke_pool: JokePool,
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

    @router.message(Command("joke"))
    @router.channel_post(Command("joke"))
    async def send_random_joke(message: Message, bot: Bot) -> None:
        image_pool.remember_user(message.from_user)
        await send_joke(
            bot=bot,
            chat_id=message.chat.id,
            joke_pool=joke_pool,
            answer_message=message,
        )

    @router.message(Command("count"))
    @router.channel_post(Command("count"))
    async def count_pictures(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await message.answer(format_count(image_pool, joke_pool), parse_mode="HTML")

    @router.message(Command("stats"))
    @router.channel_post(Command("stats"))
    async def stats_command(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        await message.answer(
            format_stats(image_pool, joke_pool, chat_id=message.chat.id),
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

    @router.message(Command("jokeduel"))
    async def joke_duel_command(message: Message, bot: Bot) -> None:
        image_pool.remember_user(message.from_user)
        await send_joke_duel(bot=bot, message=message, joke_pool=joke_pool)

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
        joke_pool.reset_stats()
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

    @router.message(Command(JOKE_UPLOAD_COMMAND))
    @router.channel_post(Command(JOKE_UPLOAD_COMMAND))
    async def start_joke_upload(message: Message, state: FSMContext) -> None:
        image_pool.remember_user(message.from_user)
        await activate_joke_upload(message, state)

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
            if is_joke_upload_active(message):
                data = joke_upload_data(message)
                failed = int(data.get("failed", 0))
                data["failed"] = failed + 1
                await message.answer(format_invalid_joke())
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
            f"📦 Пикч: {image_pool.count()} · 😂 Анекдотов: {joke_pool.count()}",
            show_alert=True,
        )

    @router.callback_query(F.data == "stats")
    async def stats_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message:
            await callback.message.answer(
                format_stats(image_pool, joke_pool, chat_id=callback.message.chat.id),
                parse_mode="HTML",
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

    @router.callback_query(F.data == "weather")
    async def weather_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message:
            await send_weather(callback.message)
        await callback.answer()

    @router.callback_query(F.data == "joke")
    async def joke_callback(callback: CallbackQuery, bot: Bot) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message is None:
            await callback.answer()
            return

        await send_joke(
            bot=bot,
            chat_id=callback.message.chat.id,
            joke_pool=joke_pool,
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

    @router.callback_query(F.data == "upload_joke")
    async def upload_joke_callback(callback: CallbackQuery, state: FSMContext) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message is None:
            await callback.answer()
            return

        activated = await activate_joke_upload(callback.message, state)
        await callback.answer(
            "Загрузка анекдотов открыта" if activated else "Открой личку с ботом"
        )

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

    @router.callback_query(F.data.startswith("joke_react:"))
    async def joke_react_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.data is None:
            await callback.answer()
            return

        _, reaction, joke_id = callback.data.split(":", 2)
        reaction_update = joke_pool.react(joke_id, reaction, callback.from_user.id)
        if reaction_update is None:
            await callback.answer("Не нашёл этот анекдот", show_alert=True)
            return

        joke = reaction_update.joke
        if callback.message:
            if (
                reaction_update.changed
                and reaction == "dislike"
                and joke.dislikes >= AUTO_DELETE_DISLIKES
            ):
                joke_pool.delete(joke.id)
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                    await callback.message.reply("Два средних пальца. Анекдот удалён из пула")
                except TelegramAPIError:
                    LOGGER.warning("Failed to mark auto-deleted joke message", exc_info=True)
                await callback.answer("Народный суд сработал")
                return

            try:
                await callback.message.edit_reply_markup(
                    reply_markup=joke_actions_with_counts(
                        joke_id=joke.id,
                        likes=joke.likes,
                        dislikes=joke.dislikes,
                    )
                )
            except TelegramAPIError:
                LOGGER.warning("Failed to update joke reaction buttons", exc_info=True)

        await callback.answer("Засчитано" if reaction_update.changed else "Уже стоит")

    @router.callback_query(F.data.startswith("duel:"))
    async def duel_callback(callback: CallbackQuery) -> None:
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

    @router.callback_query(F.data.startswith("joke_duel:"))
    async def joke_duel_callback(callback: CallbackQuery) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.data is None:
            await callback.answer()
            return

        _, duel_id, side = callback.data.split(":", 2)
        duel = duel_sessions.get(duel_id)
        if duel is None or duel.get("kind") != "joke":
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
                    format_joke_duel_score(
                        left_votes,
                        right_votes,
                        title=str(duel.get("title") or random_joke_duel_start_phrase()),
                        status=str(duel.get("status") or random_joke_duel_status_phrase()),
                        remaining_seconds=duel_remaining_seconds(duel),
                    ),
                    parse_mode="HTML",
                    reply_markup=joke_duel_vote(duel_id, left_votes, right_votes),
                )
            except TelegramAPIError:
                LOGGER.warning("Failed to update joke duel vote message", exc_info=True)
        await callback.answer("Голос принят")

    @router.callback_query(F.data.startswith("tournament:"))
    async def tournament_callback(callback: CallbackQuery) -> None:
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
            try:
                await callback.message.edit_text(
                    format_tournament_score(
                        vote_counts,
                        title=str(tournament.get("title") or random_tournament_start_phrase()),
                        status=str(tournament.get("status") or random_tournament_status_phrase()),
                        remaining_seconds=tournament_remaining_seconds(tournament),
                    ),
                    parse_mode="HTML",
                    reply_markup=tournament_vote(tournament_id, vote_counts),
                )
            except TelegramAPIError:
                LOGGER.warning("Failed to update tournament vote message", exc_info=True)
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

    @router.callback_query(F.data == "joke_duel_new")
    async def new_joke_duel_callback(callback: CallbackQuery, bot: Bot) -> None:
        image_pool.remember_user(callback.from_user)
        if callback.message is None:
            await callback.answer()
            return

        duel_result = await send_joke_duel(
            bot=bot,
            message=callback.message,
            joke_pool=joke_pool,
            silent_if_active=True,
        )
        if duel_result == "started":
            await callback.answer("Запускаю дуэль анекдотов")
        elif duel_result == "active":
            await callback.answer("Дуэль уже идёт")
        else:
            await callback.answer("Дуэль не запустилась")

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

    @router.message(F.text)
    async def save_joke(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        if is_upload_active(message):
            data = upload_data(message)
            failed = int(data.get("failed", 0))
            data["failed"] = failed + 1
            await message.answer(format_invalid_file())
            return

        if not is_joke_upload_active(message):
            return

        if (message.text or "").strip().startswith("/"):
            data = joke_upload_data(message)
            failed = int(data.get("failed", 0))
            data["failed"] = failed + 1
            await message.answer(format_invalid_joke_command(), parse_mode="HTML")
            return

        data = joke_upload_data(message)
        added = int(data.get("added", 0))
        failed = int(data.get("failed", 0))
        duplicates = int(data.get("duplicates", 0))

        result = joke_pool.add_from_message(message)
        if result.added:
            data.update(
                {
                    "added": added + 1,
                    "failed": failed,
                    "duplicates": duplicates,
                }
            )
            return

        if result.duplicate:
            data.update({"added": added, "failed": failed, "duplicates": duplicates + 1})
            await message.answer(format_duplicate_joke_skipped())
            return

        data.update({"added": added, "failed": failed + 1, "duplicates": duplicates})
        await message.answer(format_invalid_joke())

    @router.message()
    @router.channel_post()
    async def fallback(message: Message) -> None:
        image_pool.remember_user(message.from_user)
        if is_upload_active(message):
            data = upload_data(message)
            failed = int(data.get("failed", 0))
            data["failed"] = failed + 1
            await message.answer(format_invalid_file())
        elif is_joke_upload_active(message):
            data = joke_upload_data(message)
            failed = int(data.get("failed", 0))
            data["failed"] = failed + 1
            await message.answer(format_invalid_joke())

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


async def send_joke(
    bot: Bot,
    chat_id: int,
    joke_pool: JokePool,
    answer_message: Message | None = None,
    avoid_recent: bool = True,
) -> None:
    joke = joke_pool.random_joke(
        avoid_recent=avoid_recent,
        chat_id=chat_id,
    )
    if joke is None:
        text = format_empty_joke_pool()
        if answer_message:
            await answer_message.answer(text, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        return

    await bot.send_message(
        chat_id=chat_id,
        text=format_joke(joke.text),
        parse_mode="HTML",
        reply_markup=joke_actions(joke.id),
    )


async def send_joke_duel_entry(message: Message, title: str, text: str) -> None:
    chunks = split_text_for_telegram(text.strip())
    total_chunks = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        chunk_title = title
        if total_chunks > 1:
            chunk_title = f"{title} · часть {index}/{total_chunks}"

        await message.answer(format_joke_duel_entry(chunk_title, chunk), parse_mode="HTML")


async def send_duel(
    bot: Bot,
    message: Message,
    image_pool: ImagePool,
    silent_if_active: bool = False,
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

        duel_pair = image_pool.random_duel_pair(chat_id=chat_id)
        if duel_pair is None:
            await message.answer("⚔️ Дуэль сорвалась. Пул пустоват")
            return "failed"
        left, right = duel_pair

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
            "kind": "image",
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

        register_active_duel(chat_id, "image", duel_id)
        schedule_duel_finalizer(duel_id, bot, image_pool, chat_id, score_message.message_id)
        return "started"


async def send_joke_duel(
    bot: Bot,
    message: Message,
    joke_pool: JokePool,
    silent_if_active: bool = False,
) -> DuelStartResult:
    chat_id = message.chat.id
    async with duel_lock_for(chat_id):
        if active_duel_id_for_chat(chat_id, "joke"):
            if not silent_if_active:
                await message.answer(format_duel_already_active("joke"), parse_mode="HTML")
            return "active"

        if joke_pool.count() < 2:
            await message.answer("😂 Для дуэли нужно хотя бы два анекдота в блокноте")
            return "failed"

        duel_pair = joke_pool.random_duel_pair(chat_id=chat_id)
        if duel_pair is None:
            await message.answer("😂 Дуэль сорвалась. Блокнот пустоват")
            return "failed"
        left, right = duel_pair

        try:
            await send_joke_duel_entry(message, "🅰️ Первый анекдот", left.text)
            await send_joke_duel_entry(message, "🅱️ Второй анекдот", right.text)
        except TelegramAPIError:
            LOGGER.warning("Failed to send joke duel text messages", exc_info=True)
            return "failed"

        duel_id = uuid4().hex
        title = random_joke_duel_start_phrase()
        status = random_joke_duel_status_phrase()
        duel_sessions[duel_id] = {
            "kind": "joke",
            "chat_id": chat_id,
            "left": left.id,
            "right": right.id,
            "votes": {},
            "active": True,
            "title": title,
            "status": status,
            "expires_at": monotonic() + JOKE_DUEL_SECONDS,
        }
        try:
            score_message = await message.answer(
                format_joke_duel_score(0, 0, title=title, status=status),
                parse_mode="HTML",
                reply_markup=joke_duel_vote(duel_id),
            )
        except TelegramAPIError:
            duel_sessions.pop(duel_id, None)
            LOGGER.warning("Failed to send joke duel vote message", exc_info=True)
            return "failed"

        register_active_duel(chat_id, "joke", duel_id)
        schedule_joke_duel_finalizer(duel_id, bot, joke_pool, chat_id, score_message.message_id)
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

        try:
            await bot.send_media_group(
                chat_id=chat_id,
                media=[InputMediaPhoto(media=record.file_id) for record in candidates],
            )
        except TelegramAPIError:
            LOGGER.warning(
                "Failed to send tournament media group, falling back to separate photos",
                exc_info=True,
            )
            for record in candidates:
                await bot.send_photo(chat_id=chat_id, photo=record.file_id)

        tournament_id = uuid4().hex
        title = random_tournament_start_phrase()
        status = random_tournament_status_phrase()
        tournament_sessions[tournament_id] = {
            "chat_id": chat_id,
            "records": [record.id for record in candidates],
            "votes": {},
            "active": True,
            "title": title,
            "status": status,
            "expires_at": monotonic() + TOURNAMENT_SECONDS,
        }
        try:
            score_message = await message.answer(
                format_tournament_score([0, 0, 0, 0], title=title, status=status),
                parse_mode="HTML",
                reply_markup=tournament_vote(tournament_id),
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
        clear_active_duel(chat_id, "image", duel_id)
        duel_sessions.pop(duel_id, None)
        duel_tasks.pop(duel_id, None)


async def finalize_joke_duel(
    duel_id: str,
    bot: Bot,
    joke_pool: JokePool,
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
                await update_joke_duel_score_message(
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
            result_text = format_joke_duel_result(
                left_votes,
                right_votes,
                winner=None,
            )
        elif left_votes > right_votes:
            joke_pool.delete(str(duel["right"]))
            result_text = format_joke_duel_result(
                left_votes,
                right_votes,
                winner="left",
            )
        else:
            joke_pool.delete(str(duel["left"]))
            result_text = format_joke_duel_result(
                left_votes,
                right_votes,
                winner="right",
            )

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=result_text,
                parse_mode="HTML",
                reply_markup=new_joke_duel(),
            )
        except TelegramAPIError:
            LOGGER.warning("Failed to edit completed joke duel message", exc_info=True)
    except Exception:
        LOGGER.exception("Joke duel finalizer crashed")
    finally:
        clear_active_duel(chat_id, "joke", duel_id)
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

        tournament["active"] = False
        vote_counts = tournament_vote_counts(tournament)
        winner = tournament_winner(vote_counts)
        image_pool.record_tournament_result(tied=winner is None)
        result_text = format_tournament_result(vote_counts, winner=winner)

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=result_text,
                parse_mode="HTML",
                reply_markup=new_tournament(),
            )
        except TelegramAPIError:
            LOGGER.warning("Failed to edit completed tournament message", exc_info=True)
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


def schedule_joke_duel_finalizer(
    duel_id: str,
    bot: Bot,
    joke_pool: JokePool,
    chat_id: int,
    message_id: int,
) -> None:
    task = asyncio.create_task(
        finalize_joke_duel(duel_id, bot, joke_pool, chat_id, message_id)
    )
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


async def update_joke_duel_score_message(
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
            text=format_joke_duel_score(
                left_votes,
                right_votes,
                title=str(duel.get("title") or random_joke_duel_start_phrase()),
                status=str(duel.get("status") or random_joke_duel_status_phrase()),
                remaining_seconds=remaining_seconds,
            ),
            parse_mode="HTML",
            reply_markup=joke_duel_vote(duel_id, left_votes, right_votes),
        )
    except TelegramAPIError:
        LOGGER.warning("Failed to update joke duel timer message", exc_info=True)


async def update_tournament_score_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    tournament_id: str,
    tournament: dict,
    remaining_seconds: int,
) -> None:
    vote_counts = tournament_vote_counts(tournament)
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=format_tournament_score(
                vote_counts,
                title=str(tournament.get("title") or random_tournament_start_phrase()),
                status=str(tournament.get("status") or random_tournament_status_phrase()),
                remaining_seconds=remaining_seconds,
            ),
            parse_mode="HTML",
            reply_markup=tournament_vote(tournament_id, vote_counts),
        )
    except TelegramAPIError:
        LOGGER.warning("Failed to update tournament timer message", exc_info=True)


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
    active_joke_uploads.pop(message.chat.id, None)
    active_uploads[message.chat.id] = new_upload_session()
    upload_text = format_upload_opened(RANDOM.choice(UPLOAD_START_PHRASES))
    await message.answer(
        upload_text,
        parse_mode="HTML",
        reply_markup=upload_menu(),
    )
    return True


async def activate_joke_upload(message: Message, state: FSMContext) -> bool:
    if not is_private_chat(message):
        await message.answer(format_joke_upload_private_only(), parse_mode="HTML")
        return False

    await state.set_state(AddJoke.uploading)
    active_uploads.pop(message.chat.id, None)
    active_joke_uploads[message.chat.id] = new_joke_upload_session()
    await message.answer(
        format_joke_upload_opened(),
        parse_mode="HTML",
        reply_markup=upload_menu(),
    )
    return True


async def finish_upload_or_warn(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state == AddJoke.uploading.state or is_joke_upload_active(message):
        await finish_joke_upload(message, state)
        return

    if current_state != AddPicture.uploading.state and not is_upload_active(message):
        await message.answer(format_upload_not_active(), parse_mode="HTML")
        return

    await finish_upload(message, state)


async def cancel_upload(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state == AddJoke.uploading.state or is_joke_upload_active(message):
        await state.clear()
        active_joke_uploads.pop(message.chat.id, None)
        await message.answer(format_joke_upload_cancelled(), parse_mode="HTML")
        return

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


async def finish_joke_upload(message: Message, state: FSMContext) -> None:
    data = joke_upload_data(message)
    added = int(data.get("added", 0))
    failed = int(data.get("failed", 0))
    duplicates = int(data.get("duplicates", 0))
    await state.clear()
    active_joke_uploads.pop(message.chat.id, None)

    lines = [
        "<b>✅ Загрузка анекдотов завершена</b>",
        "Устный фонд пополнен, тамада нервно уважает",
        "",
        "<b>😂 Итог</b>",
        format_metric("Добавлено анекдотов", added),
    ]
    if failed:
        lines.append(format_metric("Не зашло", failed))
    if duplicates:
        lines.append(format_metric("Баянов пропущено", duplicates))

    await message.answer("\n".join(lines), parse_mode="HTML")


def is_upload_active(message: Message) -> bool:
    return is_private_chat(message) and message.chat.id in active_uploads


def is_joke_upload_active(message: Message) -> bool:
    return is_private_chat(message) and message.chat.id in active_joke_uploads


def is_any_upload_active(message: Message, current_state: str | None) -> bool:
    return (
        current_state in {AddPicture.uploading.state, AddJoke.uploading.state}
        or is_upload_active(message)
        or is_joke_upload_active(message)
    )


def is_private_chat(message: Message) -> bool:
    return message.chat.type == "private"


def new_upload_session() -> UploadSession:
    return {
        "added": 0,
        "failed": 0,
        "duplicates": 0,
        "announced_achievements": set(),
    }


def new_joke_upload_session() -> JokeUploadSession:
    return {
        "added": 0,
        "failed": 0,
        "duplicates": 0,
    }


def upload_data(message: Message) -> UploadSession:
    return active_uploads.setdefault(
        message.chat.id,
        new_upload_session(),
    )


def joke_upload_data(message: Message) -> JokeUploadSession:
    return active_joke_uploads.setdefault(
        message.chat.id,
        new_joke_upload_session(),
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
    is_private = is_private_chat(message)
    upload_note = "загрузка доступна здесь" if is_private else "загрузка уедет в личку"
    await message.answer(
        "<b>🚨 Пульт от ядерки</b>\n\n"
        "<b>🎲 Рандом</b>\n"
        "Пикча или анекдот из общего пула\n\n"
        "<b>⚔️ Игры</b>\n"
        "Дуэли удаляют проигравших, турнир выбирает чемпиона\n\n"
        "<b>📊 Склад</b>\n"
        "Сводка, топ, профиль и погода\n\n"
        f"<b>📥 Загрузка</b>\n{upload_note}",
        parse_mode="HTML",
        reply_markup=main_menu(is_private=is_private),
    )


def format_metric(label: str, value: int | str) -> str:
    return f"{label}: <b>{value}</b>"


def format_section(title: str, *lines: str) -> str:
    return "\n".join([f"<b>{title}</b>", *lines])


def format_stats(
    image_pool: ImagePool,
    joke_pool: JokePool | None = None,
    chat_id: int | None = None,
) -> str:
    stats = image_pool.stats()
    joke_stats = joke_pool.stats() if joke_pool else None
    pool_lines = [format_metric("Пикчи", stats.total_images)]
    random_lines = [format_metric("Пикчи выданы", stats.total_shows)]
    reaction_lines = [
        f"Пикчи: <b>{stats.total_likes}</b> 🤙🏻 · <b>{stats.total_dislikes}</b> 🖕🏻",
    ]
    if joke_stats is not None:
        pool_lines.append(format_metric("Анекдоты", joke_stats.total_jokes))
        random_lines.append(format_metric("Анекдоты выданы", joke_stats.total_shows))
        reaction_lines.append(
            f"Анекдоты: <b>{joke_stats.total_likes}</b> 🤙🏻 · <b>{joke_stats.total_dislikes}</b> 🖕🏻"
        )

    sections = [
        "<b>📊 Сводка</b>",
        format_section("📦 Пул", *pool_lines),
        format_section("🎲 Рандом", *random_lines),
        format_section(
            "⚔️ Игры",
            format_metric("Дуэли", stats.total_duels),
            format_metric("Удалений после дуэлей", stats.duel_executions),
            format_metric("Мирных дуэлей", stats.duel_ties),
            format_metric("Турниры", stats.total_tournaments),
            format_metric("Турниры без чемпиона", stats.tournament_ties),
        ),
        format_section("🤙🏻 Реакции", *reaction_lines),
    ]
    if chat_id is not None:
        sections.append(format_section("🟢 Активные игры", *format_active_duel_lines(chat_id)))
    return "\n\n".join(sections)


def format_active_duel_lines(chat_id: int) -> list[str]:
    return [
        format_metric("Дуэль пикч", active_duel_status(chat_id, "image")),
        format_metric("Дуэль шуток", active_duel_status(chat_id, "joke")),
        format_metric("Турнир", active_tournament_status(chat_id)),
    ]


def active_duel_status(chat_id: int, kind: DuelKind) -> str:
    duel_id = active_duel_id_for_chat(chat_id, kind)
    if duel_id is None:
        return "свободно"

    duel = duel_sessions.get(duel_id)
    if not duel:
        return "свободно"

    return f"идёт, {duel_remaining_seconds(duel)} сек"


def active_tournament_status(chat_id: int) -> str:
    tournament_id = active_tournament_id_for_chat(chat_id)
    if tournament_id is None:
        return "свободно"

    tournament = tournament_sessions.get(tournament_id)
    if not tournament:
        return "свободно"

    return f"идёт, {tournament_remaining_seconds(tournament)} сек"


def format_start() -> str:
    return (
        "<b>👋 Я @kartinkomet_bot</b>\n\n"
        "Общий склад пикч и анекдотов. Выдаю рандом, запускаю дуэли, выбираю чемпионов "
        "и веду бухгалтерию хаоса\n\n"
        f"<b>🧠 Режим дня</b>\n{daily_mood()}\n\n"
        "<b>🎛 Главное</b>\n"
        "<code>🎲 Пикча</code> — случайная картинка\n"
        "<code>😂 Анекдот</code> — случайная шутка\n"
        "<code>⚔️ Пикчи</code> и <code>😂 Шутки</code> — дуэли\n"
        "<code>🏟 Турнир</code> — четыре пикчи, один чемпион\n\n"
        "<b>📥 Загрузка</b>\n"
        "<code>📥 Пикчи</code> и <code>📝 Шутки</code> работают в личке"
    )


def format_help() -> str:
    sections = [
        "<b>🧭 Команды kartinkomet</b>",
        format_section(
            "🎲 Картинки",
            "<code>/pic</code> — рандомная пикча",
            "<code>/count</code> — размер пула",
            "<code>/menu</code> — открыть пульт",
        ),
        format_section(
            "😂 Анекдоты",
            "<code>/joke</code> — случайный анекдот",
            "<code>/upload_joke</code> — загрузка анекдотов в личке",
        ),
        format_section(
            "⚔️ Дуэли",
            "<code>/duel</code> — битва двух случайных пикч",
            "<code>/jokeduel</code> — битва двух случайных анекдотов",
            "<code>/tournament</code> — турнир четырёх пикч без удаления",
            "Пикчевая и анекдотная арены могут идти параллельно",
            "<code>/mood</code> — режим бота на сегодня",
            "<code>/weather</code> — погода в Малой Токмачке",
        ),
        format_section(
            "📥 Загрузка",
            "<code>/upload_pidor</code> — открыть загрузку в личке",
            "<code>/done</code> — завершить загрузку",
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
            "2 средних пальца удаляют пикчу или анекдот из пула",
        ),
    ]
    return "\n\n".join(sections)


def format_count(image_pool: ImagePool, joke_pool: JokePool | None = None) -> str:
    joke_line = (
        f"\n{format_metric('Анекдоты', joke_pool.count())}"
        if joke_pool
        else ""
    )
    return (
        "<b>📦 Общий пул</b>\n\n"
        f"{format_metric('Пикчи', image_pool.count())}"
        f"{joke_line}"
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
        "<b>📬 Пикчи принимаю только в личке</b>\n\n"
        "В группе оставляем рандом, дуэли и сводку. Так загрузка не шумит и Telegram "
        "точнее отдаёт файлы боту\n\n"
        "<b>Что делать</b>\n"
        "Откройте <a href=\"https://t.me/kartinkomet_bot\">@kartinkomet_bot</a>\n"
        f"Отправьте <code>/{UPLOAD_COMMAND}</code>\n"
        "Кидайте пикчи туда"
    )


def format_upload_opened(intro: str) -> str:
    return (
        "<b>📥 Загрузка пикч</b>\n\n"
        f"{escape(intro)}\n\n"
        "<b>Что кидать</b>\n"
        "Одна пикча, пачка, альбом или пересланные изображения\n\n"
        "<b>Управление</b>\n"
        "Когда всё закинули — <code>✅ Закончить</code>\n"
        "Передумали — <code>❌ Отмена</code>"
    )


def format_joke_upload_opened() -> str:
    return (
        "<b>📝 Загрузка анекдотов</b>\n\n"
        "Отправляйте шутки обычным текстом. Один анекдот — одно сообщение\n\n"
        "<b>Управление</b>\n"
        "Когда всё закинули — <code>✅ Закончить</code>\n"
        "Передумали — <code>❌ Отмена</code>"
    )


def format_duel_already_active(kind: DuelKind = "image") -> str:
    if kind == "joke":
        busy_line = "Сейчас занята анекдотная арена"
        free_line = "Пикчевую дуэль можно запускать отдельно"
    else:
        busy_line = "Сейчас занята пикчевая арена"
        free_line = "Анекдотную дуэль можно запускать отдельно"

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


def format_empty_joke_pool() -> str:
    return (
        "<b>😂 Анекдотов пока нет</b>\n\n"
        f"Откройте личку с ботом и отправьте <code>/{JOKE_UPLOAD_COMMAND}</code>"
    )


def format_joke(text: str) -> str:
    return (
        "<b>😂 Анекдот из общего блокнота</b>\n\n"
        f"<blockquote>{escape(text)}</blockquote>"
    )


def format_joke_duel_entry(title: str, text: str) -> str:
    return (
        f"<b>{escape(title)}</b>\n\n"
        f"<blockquote>{escape(text)}</blockquote>"
    )


def format_duplicate_joke_skipped() -> str:
    return "♻️ Баян уже в блокноте"


def format_invalid_joke() -> str:
    return (
        "⚠️ Не похоже на анекдот\n\n"
        "Отправьте обычный текст одним сообщением"
    )


def format_invalid_joke_command() -> str:
    return (
        "<b>⚠️ Это команда, а не анекдот</b>\n\n"
        f"Для завершения используйте <code>/done</code>, для отмены — <code>/cancel</code>"
    )


def format_joke_upload_private_only() -> str:
    return (
        "<b>📬 Шутки принимаю только в личке</b>\n\n"
        "В группе оставляем выдачу, сводку и дуэли. Блокнот пополняется один на один\n\n"
        "<b>Что делать</b>\n"
        "Откройте <a href=\"https://t.me/kartinkomet_bot\">@kartinkomet_bot</a>\n"
        f"Отправьте <code>/{JOKE_UPLOAD_COMMAND}</code>\n"
        "Кидайте анекдоты текстом"
    )


def format_joke_upload_cancelled() -> str:
    return (
        "<b>❌ Загрузка анекдотов отменена</b>\n\n"
        "Блокнот закрыт без итоговой сводки"
    )


def format_upload_cancelled() -> str:
    return (
        "<b>❌ Загрузка отменена</b>\n\n"
        "Пакет закрыт без итоговой сводки"
    )


def format_upload_not_active() -> str:
    return (
        "<b>⚠️ Сейчас нет открытой загрузки</b>\n\n"
        "<b>Как открыть</b>\n"
        f"Пикчи: <code>/{UPLOAD_COMMAND}</code>\n"
        f"Шутки: <code>/{JOKE_UPLOAD_COMMAND}</code>\n\n"
        "Загружать лучше в личке с ботом"
    )


def format_admin_only(action: str) -> str:
    return f"🔒 {action} доступна только админам"


def format_reset_stats_done() -> str:
    return (
        "<b>♻️ Статистика сброшена</b>\n\n"
        "• реакции обнулены\n"
        "• показы обнулены\n"
        "• дуэли обнулены\n"
        "• память рандома очищена\n"
        "• анекдоты оставлены, но их реакции и показы обнулены"
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
        "<b>👤 Личный профиль</b>",
        "",
        "<b>📥 Поставки</b>",
        format_metric("Загружено пикч", uploaded_count),
        format_metric("Текущее достижение", current_achievement),
        "",
        "<b>📊 Реакции на ваши пикчи</b>",
        format_metric("🤙🏻 Одобрений", reaction_stats.likes),
        format_metric("🖕🏻 Пальцев", reaction_stats.dislikes),
        format_metric("🎲 Выдано рандомом", reaction_stats.shown),
        "",
        "<b>🎖 Качество</b>",
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
            lines.append("<b>👑 Пьедестал</b>")
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
        verdict = "🔥 🅰️ Ведёт"
    else:
        verdict = "🔥 🅱️ Ведёт"

    seconds_left = DUEL_SECONDS if remaining_seconds is None else max(0, remaining_seconds)
    return (
        "<b>⚔️ Арена пикч</b>\n\n"
        f"{escape(title or random_duel_start_phrase())}\n"
        f"{escape(status or random_duel_status_phrase())}\n\n"
        f"🅰️ Слева: <b>{left_votes}</b> · 🅱️ Справа: <b>{right_votes}</b>\n\n"
        f"⏱ Осталось: <b>{seconds_left} секунд</b>\n"
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
        "<b>🏁 Дуэль завершена</b>\n\n"
        f"{escape(phrase)}\n\n"
        "<b>Счёт</b>\n"
        f"🅰️ Слева: <b>{left_votes}</b>\n"
        f"🅱️ Справа: <b>{right_votes}</b>\n\n"
        "<b>Вердикт</b>\n"
        f"{verdict}"
    )


def format_joke_duel_score(
    left_votes: int,
    right_votes: int,
    title: str | None = None,
    status: str | None = None,
    remaining_seconds: int | None = None,
) -> str:
    if left_votes == right_votes:
        verdict = "⚖️ Пока ничья"
    elif left_votes > right_votes:
        verdict = "🔥 🅰️ Ведёт"
    else:
        verdict = "🔥 🅱️ Ведёт"

    seconds_left = JOKE_DUEL_SECONDS if remaining_seconds is None else max(0, remaining_seconds)
    return (
        "<b>😂⚔️ Арена анекдотов</b>\n\n"
        f"{escape(title or random_joke_duel_start_phrase())}\n"
        f"{escape(status or random_joke_duel_status_phrase())}\n\n"
        f"🅰️ Первый: <b>{left_votes}</b> · 🅱️ Второй: <b>{right_votes}</b>\n\n"
        f"⏱ Осталось: <b>{seconds_left} секунд</b>\n"
        f"{verdict}"
    )


def format_joke_duel_result(
    left_votes: int,
    right_votes: int,
    winner: str | None,
) -> str:
    if winner is None:
        phrase = random_joke_duel_tie_phrase()
        verdict = "⚖️ Ничья. Оба анекдота остаются в блокноте"
    elif winner == "left":
        phrase = random_joke_duel_win_phrase()
        verdict = "👑 Выжил: <b>🅰️ первый</b>\n🗑 Улетел из блокнота: <b>🅱️ второй</b>"
    else:
        phrase = random_joke_duel_win_phrase()
        verdict = "👑 Выжил: <b>🅱️ второй</b>\n🗑 Улетел из блокнота: <b>🅰️ первый</b>"

    return (
        "<b>🏁 Дуэль анекдотов завершена</b>\n\n"
        f"{escape(phrase)}\n\n"
        "<b>Счёт</b>\n"
        f"🅰️ Первый: <b>{left_votes}</b>\n"
        f"🅱️ Второй: <b>{right_votes}</b>\n\n"
        "<b>Вердикт</b>\n"
        f"{verdict}"
    )


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
        f"⏱ Осталось: <b>{seconds_left} секунд</b>\n"
        f"{verdict}"
    )


def format_tournament_result(votes: list[int], winner: int | None) -> str:
    if winner is None:
        phrase = random_tournament_tie_phrase()
        verdict = "⚖️ Чемпион не выбран. Все пикчи остаются в пуле"
    else:
        phrase = random_tournament_win_phrase()
        verdict = f"👑 Чемпион: <b>{tournament_option_label(winner)}</b>\n📦 Остальные остаются в пуле"

    return (
        "<b>🏁 Турнир завершён</b>\n\n"
        f"{escape(phrase)}\n\n"
        "<b>Счёт</b>\n"
        f"1️⃣ Первая: <b>{votes[0]}</b> · 2️⃣ Вторая: <b>{votes[1]}</b>\n"
        f"3️⃣ Третья: <b>{votes[2]}</b> · 4️⃣ Четвёртая: <b>{votes[3]}</b>\n\n"
        "<b>Вердикт</b>\n"
        f"{verdict}"
    )


def tournament_option_label(index: int) -> str:
    labels = ["1️⃣ первая", "2️⃣ вторая", "3️⃣ третья", "4️⃣ четвёртая"]
    return labels[index]


def split_text_for_telegram(
    text: str,
    chunk_size: int = TELEGRAM_TEXT_CHUNK_SIZE,
) -> list[str]:
    if not text:
        return [""]

    chunks = []
    current = []
    current_size = 0
    for char in text:
        escaped_size = len(escape(char))
        if current and current_size + escaped_size > chunk_size:
            chunks.append("".join(current))
            current = []
            current_size = 0

        current.append(char)
        current_size += escaped_size

    if current:
        chunks.append("".join(current))

    return chunks


def random_duel_start_phrase() -> str:
    return RANDOM.choice(DUEL_START_PHRASES)


def random_duel_status_phrase() -> str:
    return RANDOM.choice(DUEL_STATUS_PHRASES)


def random_duel_win_phrase() -> str:
    return RANDOM.choice(DUEL_WIN_PHRASES)


def random_duel_tie_phrase() -> str:
    return RANDOM.choice(DUEL_TIE_PHRASES)


def random_joke_duel_start_phrase() -> str:
    return RANDOM.choice(JOKE_DUEL_START_PHRASES)


def random_joke_duel_status_phrase() -> str:
    return RANDOM.choice(JOKE_DUEL_STATUS_PHRASES)


def random_joke_duel_win_phrase() -> str:
    return RANDOM.choice(JOKE_DUEL_WIN_PHRASES)


def random_joke_duel_tie_phrase() -> str:
    return RANDOM.choice(JOKE_DUEL_TIE_PHRASES)


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

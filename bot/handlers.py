import random
from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ForceReply, Message, ReplyKeyboardRemove

from bot.image_pool import ImagePool
from bot.keyboards import main_menu, picture_actions, picture_actions_with_counts, upload_menu
from bot.texts import (
    ACHIEVEMENTS,
    AUTO_DELETE_DISLIKES,
    BOT_MOODS,
    EMPTY_POOL_PHRASES,
    JURY_THRESHOLDS,
    PICTURE_CAPTIONS,
    UPLOAD_FINISH_PHRASES,
    UPLOAD_START_PHRASES,
)

UPLOAD_COMMANDS = ("upload", "upload_pidor")
active_uploads: dict[int, dict[str, int | bool]] = {}


class AddPicture(StatesGroup):
    uploading = State()


def build_router(
    image_pool: ImagePool,
    target_channel_id: str | None = None,
) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(
            "Я @kartinkomet_bot. Отправляю случайные изображения из общего пула\n\n"
            f"Сегодня бот в режиме: <b>{daily_mood()}</b>\n\n"
            "Жмите кнопку <code>🎲 Рандом</code> или используйте <code>/pic</code>",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        await show_menu(message)

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        text = (
            "<b>Пульт управления хаосом:</b>\n\n"
            "🎲 <code>/pic</code> — выстрелить рандомной пикчей\n"
            "📦 <code>/count</code> — проверить, сколько пикч в реакторе\n"
            "📊 <code>/stats</code> — посмотреть лайки, какашки и средние пальцы\n"
            "🧠 <code>/mood</code> — узнать, в каком режиме бот сегодня\n"
            "🚨 <code>/menu</code> — открыть пульт от ядерки\n"
            "⬆️ <code>/upload</code> — открыть загрузку пикч\n"
            "✅ <code>/done</code> — закрыть загрузку\n"
            "❌ <code>/cancel</code> — отменить загрузку\n"
            "🖕 5 средних пальцев — народный суд удаляет пикчу из пула"
        )

        await message.answer(text, parse_mode="HTML")

    @router.message(Command("menu"))
    async def menu_command(message: Message) -> None:
        await message.answer("Убираю лишние кнопки", reply_markup=ReplyKeyboardRemove())
        await show_menu(message)

    @router.message(Command("pic"))
    @router.channel_post(Command("pic"))
    async def send_random_picture(message: Message, bot: Bot) -> None:
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
        await message.answer(f"В пуле пикч: {image_pool.count()}")

    @router.message(Command("stats"))
    @router.channel_post(Command("stats"))
    async def stats_command(message: Message) -> None:
        await message.answer(format_stats(image_pool), parse_mode="HTML")

    @router.message(Command("reset_stats"))
    @router.channel_post(Command("reset_stats"))
    async def reset_stats_command(message: Message) -> None:
        image_pool.reset_stats()
        await message.answer("Статистика сброшена. Реакции, показы и история рандома обнулены")

    @router.message(Command("mood"))
    @router.channel_post(Command("mood"))
    async def mood_command(message: Message) -> None:
        await message.answer(
            f"Сегодня бот в режиме: <b>{daily_mood()}</b>\n"
            "Caption под пикчами остаётся чистым, без лишних приставок",
            parse_mode="HTML",
        )

    @router.message(Command("id"))
    async def user_id(message: Message) -> None:
        if message.from_user is None:
            await message.answer("Не смог определить user ID")
            return

        await message.answer(f"Ваш user ID: {message.from_user.id}")

    @router.message(Command(*UPLOAD_COMMANDS))
    @router.channel_post(Command(*UPLOAD_COMMANDS))
    async def start_upload(message: Message, state: FSMContext) -> None:
        await activate_upload(message, state)

    @router.message(Command("done"))
    @router.channel_post(Command("done"))
    async def done_upload(message: Message, state: FSMContext) -> None:
        await finish_upload_or_warn(message, state)

    @router.message(Command("cancel"))
    @router.channel_post(Command("cancel"))
    async def cancel_upload_command(message: Message, state: FSMContext) -> None:
        await cancel_upload(message, state)

    @router.message(F.photo | F.document)
    @router.channel_post(F.photo | F.document)
    async def save_picture(message: Message, state: FSMContext) -> None:
        if not is_upload_active(message):
            return

        data = upload_data(message)
        added = int(data.get("added", 0))
        failed = int(data.get("failed", 0))
        duplicates = int(data.get("duplicates", 0))
        ack_sent = bool(data.get("ack_sent", False))

        result = image_pool.add_from_message(message)
        if result.added:
            data.update({"added": added + 1, "failed": failed, "duplicates": duplicates, "ack_sent": True})
            if not ack_sent:
                await message.answer("Пикчи принимаю. Когда хватит, жми кнопку", reply_markup=upload_menu())
            achievement = achievement_for(message, image_pool)
            if achievement:
                await message.answer(achievement, parse_mode="HTML")
            return

        if result.duplicate:
            data.update({"added": added, "failed": failed, "duplicates": duplicates + 1})
            await message.answer("Дубликат пропущен")
            return

        data.update({"added": added, "failed": failed + 1, "duplicates": duplicates})
        await message.answer("Файл не зашёл. Отправьте изображение")

    @router.callback_query(F.data == "pic")
    async def pic_callback(callback: CallbackQuery, bot: Bot) -> None:
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
        await callback.answer(f"В пуле пикч: {image_pool.count()}", show_alert=True)

    @router.callback_query(F.data == "stats")
    async def stats_callback(callback: CallbackQuery) -> None:
        if callback.message:
            await callback.message.answer(format_stats(image_pool), parse_mode="HTML")
        await callback.answer()

    @router.callback_query(F.data == "upload")
    async def upload_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if callback.message is None:
            await callback.answer()
            return

        await activate_upload(callback.message, state)
        await callback.answer()

    @router.callback_query(F.data == "done")
    async def done_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if callback.message is None:
            await callback.answer()
            return

        await finish_upload_or_warn(callback.message, state)
        await callback.answer()

    @router.callback_query(F.data == "cancel_upload")
    async def cancel_upload_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if callback.message is None:
            await callback.answer()
            return

        await cancel_upload(callback.message, state)
        await callback.answer()

    @router.callback_query(F.data.startswith("react:"))
    async def react_callback(callback: CallbackQuery) -> None:
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
                await callback.message.edit_reply_markup(reply_markup=None)
                await callback.message.answer("Пять средних пальцев. Пикча удалена из пула")
                await callback.answer("Народный суд сработал")
                return

            await callback.message.edit_reply_markup(
                reply_markup=picture_actions_with_counts(
                    image_id=image.id,
                    likes=image.likes,
                    fires=image.fires,
                    dislikes=image.dislikes,
                )
            )
            jury_message = jury_verdict(image.dislikes)
            if reaction_update.changed and reaction == "dislike" and jury_message:
                await callback.message.answer(jury_message)

        await callback.answer("Засчитано" if reaction_update.changed else "Уже стоит")

    @router.message(F.text == "Помощь")
    async def help_button(message: Message) -> None:
        await help_command(message)

    @router.message()
    @router.channel_post()
    async def fallback(message: Message) -> None:
        if is_upload_active(message):
            data = upload_data(message)
            failed = int(data.get("failed", 0))
            data["failed"] = failed + 1
            await message.answer("Файл не зашёл. Отправьте изображение")
            return

        await message.answer(
            "Жми <code>/pic</code> или открой <code>/menu</code>",
            parse_mode="HTML",
        )

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
            await answer_message.answer(random.choice(EMPTY_POOL_PHRASES))
        else:
            await bot.send_message(chat_id=chat_id, text=random.choice(EMPTY_POOL_PHRASES))
        return

    await bot.send_photo(
        chat_id=destination_chat_id,
        photo=image.file_id,
        caption=random_picture_caption(),
        reply_markup=picture_actions(image.id),
    )

    if target_channel_id and answer_message and str(answer_message.chat.id) != str(target_channel_id):
        await answer_message.answer("Пикча улетела в канал")


async def activate_upload(message: Message, state: FSMContext) -> None:
    await state.set_state(AddPicture.uploading)
    active_uploads[message.chat.id] = {"added": 0, "failed": 0, "duplicates": 0, "ack_sent": False}
    await state.update_data(added=0, failed=0, duplicates=0, ack_sent=False)
    upload_text = (
        f"{random.choice(UPLOAD_START_PHRASES)}. Кидайте одну пикчу, пачку или пересланные изображения. "
        "Когда хватит, отправьте <code>/done</code> или нажми <code>✅ Закончить</code>"
    )
    await message.answer(
        upload_text,
        parse_mode="HTML",
        reply_markup=upload_menu(),
    )
    if message.chat.type in {"group", "supergroup"}:
        await message.answer(
            "В группе прикрепляйте пикчи ответом на это сообщение, чтобы Telegram точно отдал их боту",
            reply_markup=ForceReply(
                selective=True,
                input_field_placeholder="Прикрепите пикчи сюда",
            ),
        )


async def finish_upload_or_warn(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state != AddPicture.uploading.state and not is_upload_active(message):
        await message.answer("Загрузка сейчас не открыта")
        return

    await finish_upload(message, state)


async def cancel_upload(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state != AddPicture.uploading.state and not is_upload_active(message):
        await message.answer("Отменять нечего. Загрузка сейчас не открыта")
        return

    data = upload_data(message)
    added = int(data.get("added", 0))
    await state.clear()
    active_uploads.pop(message.chat.id, None)
    await message.answer(f"Загрузка отменена. Уже добавлено пикч: {added}")


async def finish_upload(message: Message, state: FSMContext) -> None:
    data = upload_data(message)
    added = int(data.get("added", 0))
    failed = int(data.get("failed", 0))
    duplicates = int(data.get("duplicates", 0))
    await state.clear()
    active_uploads.pop(message.chat.id, None)

    text = f"{random.choice(UPLOAD_FINISH_PHRASES)}. Добавлено пикч: {added}"
    if failed:
        text += f". Не зашло: {failed}"
    if duplicates:
        text += f". Дубликатов пропущено: {duplicates}"

    await message.answer(text)


def is_upload_active(message: Message) -> bool:
    return message.chat.id in active_uploads


def upload_data(message: Message) -> dict[str, int | bool]:
    return active_uploads.setdefault(
        message.chat.id,
        {"added": 0, "failed": 0, "duplicates": 0, "ack_sent": False},
    )


async def show_menu(message: Message) -> None:
    await message.answer(
        "<b>Пульт от ядерки 🚨</b>",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


def format_stats(image_pool: ImagePool) -> str:
    stats = image_pool.stats()
    return (
        "<b>Сводка по реактору kartinkomet:</b>\n\n"
        f"📦 Пикч в пуле: <b>{stats.total_images}</b>\n"
        f"🎲 Выстрелов рандома: <b>{stats.total_shows}</b>\n"
        f"👍 Одобрений: <b>{stats.total_likes}</b>\n"
        f"💩 Какашек прилетело: <b>{stats.total_fires}</b>\n"
        f"🖕 Средних пальцев: <b>{stats.total_dislikes}</b>"
    )


def daily_mood() -> str:
    today = date.today().toordinal()
    return BOT_MOODS[today % len(BOT_MOODS)]


def random_picture_caption() -> str:
    return random.choice(PICTURE_CAPTIONS)


def achievement_for(message: Message, image_pool: ImagePool) -> str | None:
    if message.from_user is None:
        return None

    uploaded_count = image_pool.count_by_user(message.from_user.id)
    uploader = f"@{message.from_user.username}" if message.from_user.username else (message.from_user.first_name or "кто-то")
    for threshold, achievement in ACHIEVEMENTS:
        if uploaded_count == threshold:
            return f"<b>🏅 Достижение:</b> {achievement}\n{uploader} загрузил пикч: {uploaded_count}"

    return None


def jury_verdict(dislikes: int) -> str | None:
    return JURY_THRESHOLDS.get(dislikes)

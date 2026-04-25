import random

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from bot.image_pool import ImagePool
from bot.keyboards import main_menu, picture_actions, picture_actions_with_counts, upload_menu

UPLOAD_COMMAND = "upload_pidor"
UPLOAD_FINISH_PHRASES = [
    "Залив закрыт",
    "Пикчепровод перекрыт",
    "Приём мемного топлива завершён",
    "Контейнер с пикчами опечатан",
    "Загрузка ушла в закат",
    "Пикчи приняты, сервер задумался",
    "Мемный трюм закрыт",
    "Папка с хаосом пополнена",
    "Картинкомёт перезаряжен",
    "Пакет пикч приземлился",
    "Операция «закинуть приколы» завершена",
    "Рандом получил новую пищу",
    "Пикчи легли в пул как родные",
    "Залив окончен, расходимся красиво",
    "Мемный склад обновлён",
    "Пикчи загружены в пушку",
    "Картинки ушли в общий котёл",
    "Пул пополнен, тревога отменяется",
    "Священный архив пикч обновлён",
    "Загрузка завершена без лишней драмы",
    "Пикчи припаркованы",
    "Контент залетел на базу",
    "Картинкомёт довольно урчит",
    "Пакет принят, мемы под охраной",
    "Залив закрыт, пикчи в домике",
    "Пикчевой десант высажен",
    "Мемная смена окончена",
    "Пул сказал спасибо",
    "Пикчи успешно спрятаны в рукаве",
    "Кнопка загрузки остывает",
]
UPLOAD_START_PHRASES = [
    "Да как ты заебал",
    "Ну давай, раз уж начал",
    "Открываю пасть Картинкомёта",
    "Ладно, неси свои пикчи",
    "Сейчас будем кормить рандом",
    "Залив открыт, погнали без истерик",
    "Ну что, контентный курьер прибыл",
    "Кидай, пока сервер не передумал",
    "Мемный шлюз открыт",
    "Пикчеприёмник включён",
    "Давай сюда этот визуальный шум",
    "Окей, загружаем вашу странную коллекцию",
    "Приём пикч начался, держимся",
    "Склад мемов распахнул ворота",
    "Картинкомёт готов жрать картинки",
    "Ну всё, пошла загрузочная движуха",
    "Контентная воронка открыта",
    "Давай, удиви этот JSON",
    "Пакуй пикчи в общий котёл",
    "Залив активирован, отступать поздно",
    "Мемная таможня ждёт груз",
    "Скидывай, пока кнопка горячая",
    "Рандом просит добавки",
    "Пикчевой док открыт",
    "Ворота хаоса открыты",
    "Картинки на стол, разговоры потом",
    "Загружаем приколы промышленными объёмами",
    "Система морально готова",
    "Пул открыл рот",
    "Ну понеслась",
]


class AddPicture(StatesGroup):
    uploading = State()


def build_router(
    image_pool: ImagePool,
    target_channel_id: str | None = None,
    admin_ids: set[int] | None = None,
) -> Router:
    router = Router()
    admin_ids = admin_ids or set()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(
            "Я @kartinkomet_bot. Отправляю случайные изображения из общего пула\n\n"
            "Жмите кнопку <b>\"🎲 Рандом\"</b> или используйте /pic",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        await show_menu(message, is_user_admin(message.from_user.id if message.from_user else None, admin_ids))

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        text = (
            "Командный пульт:\n"
            "/pic - рандомная пикча\n"
            "/count - размер пула\n"
            "/stats - статистика\n"
            "/menu - открыть пульт\n"
            "/id - показать ваш Telegram user ID\n"
            "/done - закончить загрузку"
        )
        if is_user_admin(message.from_user.id if message.from_user else None, admin_ids):
            text += f"\n/{UPLOAD_COMMAND} - включить режим загрузки"

        await message.answer(text)

    @router.message(Command("menu"))
    async def menu_command(message: Message) -> None:
        await message.answer("Убираю лишние кнопки", reply_markup=ReplyKeyboardRemove())
        await show_menu(message, is_user_admin(message.from_user.id if message.from_user else None, admin_ids))

    @router.message(Command("pic"))
    async def send_random_picture(message: Message, bot: Bot) -> None:
        await send_picture(
            bot=bot,
            chat_id=message.chat.id,
            image_pool=image_pool,
            is_admin=is_user_admin(message.from_user.id if message.from_user else None, admin_ids),
            target_channel_id=target_channel_id,
            answer_message=message,
        )

    @router.message(Command("count"))
    async def count_pictures(message: Message) -> None:
        await message.answer(f"В пуле пикч: {image_pool.count()}")

    @router.message(Command("stats"))
    async def stats_command(message: Message) -> None:
        await message.answer(format_stats(image_pool))

    @router.message(Command("id"))
    async def user_id(message: Message) -> None:
        if message.from_user is None:
            await message.answer("Не смог определить user ID")
            return

        await message.answer(f"Ваш user ID: {message.from_user.id}")

    @router.message(Command(UPLOAD_COMMAND))
    async def start_upload(message: Message, state: FSMContext) -> None:
        if not is_user_admin(message.from_user.id if message.from_user else None, admin_ids):
            await message.answer("Залив доступен только администратору")
            return

        await activate_upload(message, state)

    @router.message(Command("done"))
    async def done_upload(message: Message, state: FSMContext) -> None:
        await finish_upload_or_warn(message, state)

    @router.message(AddPicture.uploading)
    async def save_picture(message: Message, state: FSMContext) -> None:
        if not is_user_admin(message.from_user.id if message.from_user else None, admin_ids):
            await state.clear()
            await message.answer("Залив доступен только администратору")
            return

        data = await state.get_data()
        added = int(data.get("added", 0))
        failed = int(data.get("failed", 0))
        duplicates = int(data.get("duplicates", 0))

        result = image_pool.add_from_message(message)
        if result.added:
            await state.update_data(added=added + 1, failed=failed, duplicates=duplicates)
            await message.answer("Пикча добавлена", reply_markup=upload_menu())
            return

        if result.duplicate:
            await state.update_data(added=added, failed=failed, duplicates=duplicates + 1)
            await message.answer("Дубликат пропущен")
            return

        await state.update_data(added=added, failed=failed + 1, duplicates=duplicates)
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
            is_admin=is_user_admin(callback.from_user.id, admin_ids),
            target_channel_id=target_channel_id,
        )
        await callback.answer()

    @router.callback_query(F.data == "count")
    async def count_callback(callback: CallbackQuery) -> None:
        await callback.answer(f"В пуле пикч: {image_pool.count()}", show_alert=True)

    @router.callback_query(F.data == "stats")
    async def stats_callback(callback: CallbackQuery) -> None:
        await callback.answer(format_stats(image_pool), show_alert=True)

    @router.callback_query(F.data == "upload")
    async def upload_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if callback.message is None:
            await callback.answer()
            return

        if not is_user_admin(callback.from_user.id, admin_ids):
            await callback.answer("Только для админа", show_alert=True)
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

    @router.callback_query(F.data.startswith("delete:"))
    async def delete_callback(callback: CallbackQuery) -> None:
        if not is_user_admin(callback.from_user.id, admin_ids):
            await callback.answer("Только для админа", show_alert=True)
            return

        image_id = callback.data.split(":", 1)[1] if callback.data else ""
        if image_pool.delete(image_id):
            await callback.answer("Выкинули из пула", show_alert=True)
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
            return

        await callback.answer("Этой пикчи уже нет в пуле", show_alert=True)

    @router.callback_query(F.data.startswith("react:"))
    async def react_callback(callback: CallbackQuery) -> None:
        if callback.data is None:
            await callback.answer()
            return

        _, reaction, image_id = callback.data.split(":", 2)
        image = image_pool.react(image_id, reaction)
        if image is None:
            await callback.answer("Не нашёл эту пикчу", show_alert=True)
            return

        if callback.message:
            await callback.message.edit_reply_markup(
                reply_markup=picture_actions_with_counts(
                    image_id=image.id,
                    is_admin=has_delete_button(callback.message) or is_user_admin(callback.from_user.id, admin_ids),
                    likes=image.likes,
                    fires=image.fires,
                    dislikes=image.dislikes,
                )
            )

        await callback.answer("Засчитано")

    @router.message(F.text == "Помощь")
    async def help_button(message: Message) -> None:
        await help_command(message)

    @router.message()
    async def fallback(message: Message) -> None:
        await message.answer("Жми /pic или открой /menu")

    return router


async def send_picture(
    bot: Bot,
    chat_id: int,
    image_pool: ImagePool,
    is_admin: bool,
    target_channel_id: str | None = None,
    answer_message: Message | None = None,
    avoid_recent: bool = False,
) -> None:
    image = image_pool.random_image(avoid_recent=avoid_recent)
    if image is None:
        if answer_message:
            await answer_message.answer("Пул пуст. Сначала залейте пикчи")
        else:
            await bot.send_message(chat_id=chat_id, text="Пул пуст. Сначала залейте пикчи")
        return

    destination_chat_id = target_channel_id or chat_id
    await bot.send_photo(
        chat_id=destination_chat_id,
        photo=image.file_id,
        reply_markup=picture_actions(image.id, is_admin and target_channel_id is None),
    )

    if target_channel_id and answer_message and str(answer_message.chat.id) != str(target_channel_id):
        await answer_message.answer("Пикча улетела в канал")


async def activate_upload(message: Message, state: FSMContext) -> None:
    await state.set_state(AddPicture.uploading)
    await state.update_data(added=0, failed=0, duplicates=0)
    await message.answer(
        f"{random.choice(UPLOAD_START_PHRASES)}. Кидайте одну пикчу, пачку или пересланные изображения. "
        "Когда хватит, нажмите кнопку или отправьте /done",
        reply_markup=upload_menu(),
    )


async def finish_upload_or_warn(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state != AddPicture.uploading.state:
        await message.answer("Залив сейчас не открыт")
        return

    await finish_upload(message, state)


async def finish_upload(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    added = int(data.get("added", 0))
    failed = int(data.get("failed", 0))
    duplicates = int(data.get("duplicates", 0))
    await state.clear()

    text = f"{random.choice(UPLOAD_FINISH_PHRASES)}. Добавлено пикч: {added}"
    if failed:
        text += f". Не зашло: {failed}"
    if duplicates:
        text += f". Дубликатов пропущено: {duplicates}"

    await message.answer(text)


async def show_menu(message: Message, is_admin: bool) -> None:
    await message.answer(
        "<b>Пульт от ядерки 🚨</b>",
        parse_mode="HTML",
        reply_markup=main_menu(is_admin=is_admin),
    )


def format_stats(image_pool: ImagePool) -> str:
    stats = image_pool.stats()
    return (
        "Статы kartinkomet:\n"
        f"Пикч в пуле: {stats.total_images}\n"
        f"Выдано картинок: {stats.total_shows}\n"
        f"Лайков: {stats.total_likes}\n"
        f"Какашек: {stats.total_fires}\n"
        f"Средних пальцев: {stats.total_dislikes}"
    )


def is_user_admin(user_id: int | None, admin_ids: set[int]) -> bool:
    if not admin_ids:
        return True

    return user_id in admin_ids


def has_delete_button(message: Message) -> bool:
    if message.reply_markup is None:
        return False

    for row in message.reply_markup.inline_keyboard:
        for button in row:
            if button.callback_data and button.callback_data.startswith("delete:"):
                return True

    return False

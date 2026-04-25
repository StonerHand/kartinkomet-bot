from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.image_pool import ImagePool
from bot.keyboards import main_menu, picture_actions, reply_menu

UPLOAD_COMMAND = "upload_pidor"


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
            "Я Картинкомет 3000. Отправляю случайные изображения из общего пула.\n\n"
            "Жмите кнопку или используйте /pic",
            reply_markup=reply_menu(),
        )
        await show_menu(message, is_user_admin(message.from_user.id if message.from_user else None, admin_ids))

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        text = (
            "Доступные команды:\n"
            "/pic - отправить случайное изображение\n"
            "/count - показать количество изображений в пуле\n"
            "/menu - открыть меню\n"
            "/id - показать ваш Telegram user ID\n"
            "/done - завершить режим загрузки"
        )
        if is_user_admin(message.from_user.id if message.from_user else None, admin_ids):
            text += f"\n/{UPLOAD_COMMAND} - включить режим загрузки"

        await message.answer(text)

    @router.message(Command("menu"))
    async def menu_command(message: Message) -> None:
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
        await message.answer(f"Изображений в пуле: {image_pool.count()}")

    @router.message(Command("id"))
    async def user_id(message: Message) -> None:
        if message.from_user is None:
            await message.answer("Не удалось определить user ID")
            return

        await message.answer(f"Ваш user ID: {message.from_user.id}")

    @router.message(Command(UPLOAD_COMMAND))
    async def start_upload(message: Message, state: FSMContext) -> None:
        if not is_user_admin(message.from_user.id if message.from_user else None, admin_ids):
            await message.answer("Загрузка доступна только администратору")
            return

        await activate_upload(message, state)

    @router.message(Command("done"))
    async def done_upload(message: Message, state: FSMContext) -> None:
        await finish_upload_or_warn(message, state)

    @router.message(AddPicture.uploading)
    async def save_picture(message: Message, state: FSMContext) -> None:
        if not is_user_admin(message.from_user.id if message.from_user else None, admin_ids):
            await state.clear()
            await message.answer("Загрузка доступна только администратору")
            return

        data = await state.get_data()
        added = int(data.get("added", 0))
        failed = int(data.get("failed", 0))
        duplicates = int(data.get("duplicates", 0))

        result = image_pool.add_from_message(message)
        if result.added:
            await state.update_data(added=added + 1, failed=failed, duplicates=duplicates)
            return

        if result.duplicate:
            await state.update_data(added=added, failed=failed, duplicates=duplicates + 1)
            await message.answer("Дубликат не добавлен")
            return

        await state.update_data(added=added, failed=failed + 1, duplicates=duplicates)
        await message.answer("Файл не добавлен. Отправьте изображение")

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
        await callback.answer(f"Изображений в пуле: {image_pool.count()}", show_alert=True)

    @router.callback_query(F.data == "upload")
    async def upload_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if callback.message is None:
            await callback.answer()
            return

        if not is_user_admin(callback.from_user.id, admin_ids):
            await callback.answer("Только для администратора", show_alert=True)
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
            await callback.answer("Только для администратора", show_alert=True)
            return

        image_id = callback.data.split(":", 1)[1] if callback.data else ""
        if image_pool.delete(image_id):
            await callback.answer("Удалено из пула", show_alert=True)
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
            return

        await callback.answer("Картинка уже удалена", show_alert=True)

    @router.message(F.text == "Меню")
    async def menu_button(message: Message) -> None:
        await show_menu(message, is_user_admin(message.from_user.id if message.from_user else None, admin_ids))

    @router.message(F.text == "Помощь")
    async def help_button(message: Message) -> None:
        await help_command(message)

    @router.message()
    async def fallback(message: Message) -> None:
        await message.answer("Используйте /pic или откройте /menu")

    return router


async def send_picture(
    bot: Bot,
    chat_id: int,
    image_pool: ImagePool,
    is_admin: bool,
    target_channel_id: str | None = None,
    answer_message: Message | None = None,
) -> None:
    image = image_pool.random_image()
    if image is None:
        if answer_message:
            await answer_message.answer("Пул изображений пуст. Сначала добавьте изображения")
        else:
            await bot.send_message(chat_id=chat_id, text="Пул изображений пуст. Сначала добавьте изображения")
        return

    destination_chat_id = target_channel_id or chat_id
    await bot.send_photo(
        chat_id=destination_chat_id,
        photo=image.file_id,
        reply_markup=picture_actions(image.id, is_admin and target_channel_id is None),
    )

    if target_channel_id and answer_message and str(answer_message.chat.id) != str(target_channel_id):
        await answer_message.answer("Изображение отправлено в канал")


async def activate_upload(message: Message, state: FSMContext) -> None:
    await state.set_state(AddPicture.uploading)
    await state.update_data(added=0, failed=0, duplicates=0)
    await message.answer(
        "Режим загрузки изображений активирован. Отправьте одно или несколько изображений. "
        "После завершения отправьте /done"
    )


async def finish_upload_or_warn(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state != AddPicture.uploading.state:
        await message.answer("Режим загрузки не активирован")
        return

    await finish_upload(message, state)


async def finish_upload(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    added = int(data.get("added", 0))
    failed = int(data.get("failed", 0))
    duplicates = int(data.get("duplicates", 0))
    await state.clear()

    text = f"Загрузка завершена. Добавлено изображений: {added}"
    if failed:
        text += f". Не удалось добавить: {failed}"
    if duplicates:
        text += f". Дубликатов пропущено: {duplicates}"

    await message.answer(text)


async def show_menu(message: Message, is_admin: bool) -> None:
    await message.answer("Меню", reply_markup=main_menu(is_admin=is_admin))


def is_user_admin(user_id: int | None, admin_ids: set[int]) -> bool:
    if not admin_ids:
        return True

    return user_id in admin_ids

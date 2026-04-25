from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.image_pool import ImagePool
from bot.keyboards import main_menu

UPLOAD_COMMAND = "upload_pidor"


class AddPicture(StatesGroup):
    uploading = State()


def build_router(image_pool: ImagePool, target_channel_id: str | None = None) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(
            "Я Картинкомет 3000. Отправляю случайные изображения из общего пула.\n\n"
            "Команда /pic отправит случайную картинку.\n"
            "Для загрузки изображений используйте секретную команду",
            reply_markup=main_menu(),
        )

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(
            "Доступные команды:\n"
            "/pic - отправить случайное изображение\n"
            "/count - показать количество изображений в пуле\n"
            "/done - завершить режим загрузки\n"
            "/help - показать эту справку"
        )

    @router.message(Command("pic"))
    async def send_random_picture(message: Message, bot: Bot) -> None:
        file_id = image_pool.random_file_id()
        if file_id is None:
            await message.answer("Пул изображений пуст. Сначала добавьте изображения")
            return

        chat_id = target_channel_id or message.chat.id
        await bot.send_photo(chat_id=chat_id, photo=file_id)

        if target_channel_id and str(message.chat.id) != str(target_channel_id):
            await message.answer("Изображение отправлено в канал")

    @router.message(Command("count"))
    async def count_pictures(message: Message) -> None:
        await message.answer(f"Изображений в пуле: {image_pool.count()}")

    @router.message(Command(UPLOAD_COMMAND))
    async def start_upload(message: Message, state: FSMContext) -> None:
        await state.set_state(AddPicture.uploading)
        await state.update_data(added=0, failed=0)
        await message.answer(
            "Режим загрузки изображений активирован. Отправьте одно или несколько изображений. "
            "После завершения отправьте /done"
        )

    @router.message(Command("done"))
    async def done_without_upload(message: Message, state: FSMContext) -> None:
        current_state = await state.get_state()
        if current_state != AddPicture.uploading.state:
            await message.answer("Режим загрузки не активирован")
            return

        await finish_upload(message, state)

    @router.message(AddPicture.uploading)
    async def save_picture(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        added = int(data.get("added", 0))
        failed = int(data.get("failed", 0))

        if image_pool.add_from_message(message):
            await state.update_data(added=added + 1, failed=failed)
            return

        await state.update_data(added=added, failed=failed + 1)
        await message.answer("Файл не добавлен. Отправьте изображение")

    @router.message(F.text == "Помощь")
    async def help_button(message: Message) -> None:
        await help_command(message)

    @router.message()
    async def fallback(message: Message) -> None:
        await message.answer("Используйте /pic, чтобы получить случайное изображение")

    return router


async def finish_upload(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    added = int(data.get("added", 0))
    failed = int(data.get("failed", 0))
    await state.clear()

    if failed:
        await message.answer(
            f"Загрузка завершена. Добавлено изображений: {added}. Не удалось добавить: {failed}"
        )
        return

    await message.answer(f"Загрузка завершена. Добавлено изображений: {added}")

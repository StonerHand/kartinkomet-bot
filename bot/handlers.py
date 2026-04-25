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
    "Загрузка закрыта",
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
    "Загрузка окончена, расходимся красиво",
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
    "Загрузка закрыта, пикчи в домике",
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
    "Загрузка открыта, погнали без истерик",
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
    "Загрузка активирована, отступать поздно",
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
PICTURE_CAPTIONS = [
    "Сейчас будет искусство",
    "Держи визуальный удар",
    "Рандом выкатывает базу",
    "Экспонат из дурки",
    "Архивный материал",
    "Это нельзя развидеть",
    "Пикча прибыла без предупреждения",
    "Контент сомнительной свежести",
    "Вот это поворот",
    "Рандом сказал «держи»",
    "Картинкомёт выстрелил",
    "Ничего не объясняю",
    "Материал для внутреннего расследования",
    "Пикча с характером",
    "Случайность уровня бог",
    "Это было в пуле, я не виноват",
    "Глазами смотреть осторожно",
    "Вот тебе кусок хаоса",
    "Пикча вышла из тени",
    "Рандом снова творит странное",
    "Визуальный прикол доставлен",
    "Склад выдал вот это",
    "Проверка на моральную устойчивость",
    "Картинка нашла своего зрителя",
    "Лови артефакт",
    "Это не баг, это контент",
    "Пул решил так",
    "Без контекста, зато честно",
    "Сервер достал из кармана",
    "Мемная единица доставлена",
]
EMPTY_POOL_PHRASES = [
    "Пул пуст. Сначала загрузите пикчи",
    "Тут пусто. Даже рандом ушёл курить",
    "Пикч нет. Картинкомёт щёлкает вхолостую",
    "Пул пустой, как обещания после созвона",
    "Нечего выдавать. Несите картинки",
    "Рандом голодный. Загрузите пикчи",
    "Архив пуст. Мемы не подвезли",
    "Пикчевой склад пустует",
    "Контента ноль. Срочно кормить",
    "Пул сухой. Нужны пикчи",
    "Картинкомёт без патронов",
    "Пустота смотрит в ответ",
    "JSON грустит без file_id",
    "Ни одной пикчи. Позор, но поправимый",
    "Рандом готов, но выбирать нечего",
    "Пикчи закончились ещё до начала",
    "Склад открылся, а там воздух",
    "Мемная полка пуста",
    "Сначала загрузите контент, потом требуйте чудес",
    "Пул пуст, зато честно",
    "Кнопка нажалась, пикчи не нашлись",
    "Тут пока вакуум и лёгкое осуждение",
    "Картинкомёт просит боеприпасы",
    "Нужны картинки. Рандом не маг",
    "Пока выдавать нечего",
    "Пул на нуле. Загрузка спасёт ситуацию",
    "Пикч нет, но вы держитесь",
    "Ноль картинок. Абсолютный дзен",
    "Случайность не случилась",
    "Пустой пул. Загрузите хоть что-нибудь",
]


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
            "Жмите кнопку <b>\"🎲 Рандом\"</b> или используйте /pic",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        await show_menu(message)

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        text = (
            "<b>Командный пульт:</b>\n"
            "🎲 /pic — рандомная пикча\n"
            "📦 /count — сколько пикч в реакторе\n"
            "📊 /stats — статы по реакциям\n"
            "🚨 /menu — открыть пульт от ядерки\n"
            "🪪 /id — показать ваш Telegram user ID\n"
            "✅ /done — закончить загрузку\n"
            "❌ /cancel — отменить загрузку"
        )
        text += f"\n/{UPLOAD_COMMAND} - включить режим загрузки"

        await message.answer(text, parse_mode="HTML")

    @router.message(Command("menu"))
    async def menu_command(message: Message) -> None:
        await message.answer("Убираю лишние кнопки", reply_markup=ReplyKeyboardRemove())
        await show_menu(message)

    @router.message(Command("pic"))
    async def send_random_picture(message: Message, bot: Bot) -> None:
        await send_picture(
            bot=bot,
            chat_id=message.chat.id,
            image_pool=image_pool,
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
        await activate_upload(message, state)

    @router.message(Command("done"))
    async def done_upload(message: Message, state: FSMContext) -> None:
        await finish_upload_or_warn(message, state)

    @router.message(Command("cancel"))
    async def cancel_upload_command(message: Message, state: FSMContext) -> None:
        await cancel_upload(message, state)

    @router.message(AddPicture.uploading)
    async def save_picture(message: Message, state: FSMContext) -> None:
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
        image = image_pool.react(image_id, reaction)
        if image is None:
            await callback.answer("Не нашёл эту пикчу", show_alert=True)
            return

        if callback.message:
            await callback.message.edit_reply_markup(
                reply_markup=picture_actions_with_counts(
                    image_id=image.id,
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
    target_channel_id: str | None = None,
    answer_message: Message | None = None,
    avoid_recent: bool = False,
) -> None:
    image = image_pool.random_image(avoid_recent=avoid_recent)
    if image is None:
        if answer_message:
            await answer_message.answer(random.choice(EMPTY_POOL_PHRASES))
        else:
            await bot.send_message(chat_id=chat_id, text=random.choice(EMPTY_POOL_PHRASES))
        return

    destination_chat_id = target_channel_id or chat_id
    await bot.send_photo(
        chat_id=destination_chat_id,
        photo=image.file_id,
        caption=random.choice(PICTURE_CAPTIONS),
        reply_markup=picture_actions(image.id),
    )

    if target_channel_id and answer_message and str(answer_message.chat.id) != str(target_channel_id):
        await answer_message.answer("Пикча улетела в канал")


async def activate_upload(message: Message, state: FSMContext) -> None:
    await state.set_state(AddPicture.uploading)
    await state.update_data(added=0, failed=0, duplicates=0)
    await message.answer(
        f"{random.choice(UPLOAD_START_PHRASES)}. Кидайте одну пикчу, пачку или пересланные изображения. "
        "Когда хватит, отправьте /done или нажми \"✅ Закончить\"",
        reply_markup=upload_menu(),
    )


async def finish_upload_or_warn(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state != AddPicture.uploading.state:
        await message.answer("Загрузка сейчас не открыта")
        return

    await finish_upload(message, state)


async def cancel_upload(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state != AddPicture.uploading.state:
        await message.answer("Отменять нечего. Загрузка сейчас не открыта")
        return

    data = await state.get_data()
    added = int(data.get("added", 0))
    await state.clear()
    await message.answer(f"Загрузка отменена. Уже добавлено пикч: {added}")


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


async def show_menu(message: Message) -> None:
    await message.answer(
        "<b>Пульт от ядерки 🚨</b>",
        parse_mode="HTML",
        reply_markup=main_menu(),
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

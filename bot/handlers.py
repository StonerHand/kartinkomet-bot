import random
from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ForceReply, Message, ReplyKeyboardRemove

from bot.image_pool import ImagePool
from bot.keyboards import main_menu, picture_actions, picture_actions_with_counts, upload_menu

UPLOAD_COMMAND = "upload_pidor"
active_uploads: dict[int, dict[str, int | bool]] = {}
UPLOAD_FINISH_PHRASES = [
    "Загрузка закрыта",
    "Пикчепровод перекрыт",
    "Приём мемного топлива завершён",
    "Контейнер с пикчами опечатан",
    "Загрузка ушла в закат",
    "Пикчи приняты, сервер задумался",
    "Мемный трюм закрыт",
    "Папка с хаосом пополнена",
    "Бот перезаряжен",
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
    "Бот довольно урчит",
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
    "Открываю пасть бота",
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
    "Бот готов жрать картинки",
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
    "Бот выстрелил",
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
    "Пикча прошла без досмотра",
    "Визуальный объект неопознан",
    "Рандом открыл портал",
    "Это уже не лечится",
    "Содержимое вызывает вопросы",
    "Смотреть можно, понимать необязательно",
    "Кадр из параллельной реальности",
    "Пул выдал странное",
    "Бот нашёл это под диваном",
    "Немного хаоса в ленту",
    "Проверка связи с безумием",
    "Пикча с запахом приключений",
    "Такое мог выбрать только рандом",
    "Визуальная пощёчина",
    "Доказательство, что интернет устал",
    "Случайность без тормозов",
    "Пикча попросила выйти",
    "Научно не объяснено",
    "Архив открылся сам",
    "Контент с мутной биографией",
    "Пикча пришла без приглашения",
    "Случайный экспонат общего котла",
    "Это не сон, это пул",
    "Бот не комментирует, но осуждает",
    "Рандом хлопнул дверью",
    "На экране что-то происходит",
    "Слишком поздно отворачиваться",
    "Пикча уже здесь",
    "Реактор выплюнул результат",
    "Визуальный шум уровня мастер",
    "Склад странностей пополнился вами",
    "Картинка из зоны турбулентности",
    "С этим живём дальше",
    "Пул сказал: держи крепче",
    "Очередной аргумент против порядка",
    "Визуальная улика",
    "Это было неизбежно",
    "Пикча для смелых",
    "Без гарантии психической стабильности",
    "Рандом не ошибается, он издевается",
    "Контент вышел из-под контроля",
    "Файл с настроением понедельника",
    "Пикча, которую не просили",
    "Зато не скучно",
    "Случайность с тяжёлым взглядом",
    "Пул сделал выбор за вас",
    "Нормально же общались",
    "Бот достал из тёмного угла",
    "Культурный слой интернета",
    "Шедевр сомнительного периода",
    "Пикча из отдела находок",
    "Рандомный артефакт получен",
    "Смотреть под ответственность зрителя",
    "Содержимое может вызвать мемы",
    "Пикча без тормозов и документов",
    "Пул сегодня в ударе",
    "Визуальная авария без пострадавших",
    "Это уже история",
    "Кандидат в музей странного",
    "Бот принёс добычу",
    "Файл решил стать событием",
    "Рандом включил драму",
    "Немного цифрового абсурда",
    "Пикча с сомнительной репутацией",
    "Случайность на максималках",
    "Уровень контента: да",
    "Бот сделал вид, что так и надо",
    "Это не картинка, это заявление",
    "Пул подкинул сюрприз",
    "Визуальный материал без лицензии на адекватность",
    "Картинка, которая смотрит в ответ",
    "Рандом устроил показ",
    "Сервер выдохнул и отправил это",
    "Пикча из категории «ну ладно»",
    "Проверка вкуса провалена успешно",
    "Контент прибыл на своих ногах",
    "Это точно было загружено человеком",
    "Пул не несёт ответственности",
    "Картинка с характером и проблемами",
    "Рандомная находка из подвала",
    "Визуальная граната без чеки",
    "Бот выдал нечто",
    "Мемная археология в действии",
    "Пикча посмотрела на правила и ушла",
    "Случайность сегодня дерзкая",
    "Контент, который невозможно развидеть",
    "Пул выбрал насилие",
    "Картинка для сильных духом",
    "Бот достал козырь из рукава",
    "Интернет оставил это нам",
    "Визуальный фейерверк сомнений",
    "Пикча уровня «что происходит»",
    "Рандом включил режим дурки",
    "Это попало в архив не случайно",
    "Картинка пришла решать вопросы",
    "Бот передаёт привет из бездны",
    "Пул раскрыл тайну",
    "Содержимое требует аплодисментов или полиции",
    "Визуальный объект повышенной странности",
    "Пикча, которой не нужен контекст",
    "Рандом отсыпал щедро",
    "Это не фильтр, это судьба",
    "Контент вышел на связь",
    "Пул снова делает вид, что всё нормально",
    "Бот нашёл прекрасное в ужасном",
    "Картинка с внутренним конфликтом",
    "Визуальное доказательство хаоса",
    "Пикча прошла кастинг",
    "Рандом достал тяжёлую артиллерию",
    "Сервер выбрал путь мемов",
    "Это можно показывать только друзьям",
    "Картинка пришла портить продуктивность",
    "Пул не подвёл, но напугал",
    "Бот отправил то, что было",
    "Визуальный беспорядок доставлен",
    "Пикча уровня «мама, я в интернете»",
    "Рандом попросил не благодарить",
    "Контент с повышенным содержанием вопросов",
    "Пул выкатил классику безумия",
    "Это нельзя назвать случайностью",
]
EMPTY_POOL_PHRASES = [
    "Пул пуст. Сначала загрузите пикчи",
    "Тут пусто. Даже рандом ушёл курить",
    "Пикч нет. Бот щёлкает вхолостую",
    "Пул пустой, как обещания после созвона",
    "Нечего выдавать. Несите картинки",
    "Рандом голодный. Загрузите пикчи",
    "Архив пуст. Мемы не подвезли",
    "Пикчевой склад пустует",
    "Контента ноль. Срочно кормить",
    "Пул сухой. Нужны пикчи",
    "Бот без патронов",
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
    "Бот просит боеприпасы",
    "Нужны картинки. Рандом не маг",
    "Пока выдавать нечего",
    "Пул на нуле. Загрузка спасёт ситуацию",
    "Пикч нет, но вы держитесь",
    "Ноль картинок. Абсолютный дзен",
    "Случайность не случилась",
    "Пустой пул. Загрузите хоть что-нибудь",
]
BOT_MOODS = [
    "злой архивариус",
    "сонный оператор мемного реактора",
    "вахтёр визуального хаоса",
    "молчаливый коллекционер странного",
    "радостный мусоросортировщик",
    "уставший хранитель пикч",
    "дерзкий раздатчик рандома",
    "подозрительно бодрый бот",
    "мемный диспетчер",
    "цифровой кладовщик",
    "режим: всё видел, ничего не понял",
    "реактор на минималках",
    "бот после третьего кофе",
    "дежурный по странным картинкам",
    "официально не осуждает, но запоминает",
]
ACHIEVEMENTS = [
    (1, "🏅 Достижение: первый вброс"),
    (5, "🏅 Достижение: поставщик визуального шума"),
    (10, "🏅 Достижение: мемный логист"),
    (25, "🏅 Достижение: оператор пикчепровода"),
    (50, "🏅 Достижение: контентный промышленник"),
    (100, "🏅 Достижение: легенда общего пула"),
]
JURY_THRESHOLDS = {
    3: "Суд присяжных напрягся",
    10: "Пикча получила народный вотум недоверия",
}
AUTO_DELETE_DISLIKES = 5


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
            "Жмите кнопку <b>\"🎲 Рандом\"</b> или используйте /pic",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        await show_menu(message)

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        text = (
            "<b>Пульт управления хаосом:</b>\n\n"
            "🎲 /pic — выстрелить рандомной пикчей\n"
            "📦 /count — проверить, сколько пикч в реакторе\n"
            "📊 /stats — посмотреть лайки, какашки и средние пальцы\n"
            "🧠 /mood — узнать, в каком режиме бот сегодня\n"
            "🚨 /menu — открыть пульт от ядерки\n"
            "⬆️ /upload_pidor — открыть загрузку пикч\n"
            "✅ /done — закрыть загрузку\n"
            "❌ /cancel — отменить загрузку"
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
        await message.answer(f"Сегодня бот в режиме: {daily_mood()}")

    @router.message(Command("id"))
    async def user_id(message: Message) -> None:
        if message.from_user is None:
            await message.answer("Не смог определить user ID")
            return

        await message.answer(f"Ваш user ID: {message.from_user.id}")

    @router.message(Command(UPLOAD_COMMAND))
    @router.channel_post(Command(UPLOAD_COMMAND))
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
                await message.answer(achievement)
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

        await message.answer("Жми /pic или открой /menu")

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
        caption=random.choice(PICTURE_CAPTIONS),
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
        "Когда хватит, отправьте /done или нажми <b>\"✅ Закончить\"</b>"
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


def achievement_for(message: Message, image_pool: ImagePool) -> str | None:
    if message.from_user is None:
        return None

    uploaded_count = image_pool.count_by_user(message.from_user.id)
    uploader = f"@{message.from_user.username}" if message.from_user.username else (message.from_user.first_name or "кто-то")
    for threshold, achievement in ACHIEVEMENTS:
        if uploaded_count == threshold:
            return f"{achievement}\n{uploader} загрузил пикч: {uploaded_count}"

    return None


def jury_verdict(dislikes: int) -> str | None:
    return JURY_THRESHOLDS.get(dislikes)

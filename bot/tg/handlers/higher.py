"""Higher or lower: which of two pics has the higher rating. A personal game, so it lives in the
private chat with the bot; one message is redrawn round after round."""

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.core import games as games_rules
from bot.game import Game
from bot.texts import games as game_texts
from bot.tg.runtime import send
from bot.tg.runtime.pictures import build_collage
from bot.tg.runtime.timers import Live
from bot.tg.ui import keyboards, views

router = Router(name="higher")
DEFAULT_USERNAME = "kartinkomet_bot"


async def username(bot: Bot) -> str:
    me = await bot.me()
    return me.username or DEFAULT_USERNAME


async def deal(bot: Bot, game: Game, chat_id: int, user_id: int, message_id: int | None = None, last=None) -> bool:
    """Show the next round: in place of `message_id` when given, else as a new message."""
    round_ = game.hl_round(user_id)
    if round_ is None:
        await send.send_text(bot, chat_id, "🎯 На складе мало пикч с разным рейтингом. Устройте пару дуэлей")
        return False
    image = await build_collage(bot, [round_.first, round_.second])
    if image is None:
        await send.send_text(bot, chat_id, "🎯 Не получилось собрать пикчи. Попробуй ещё раз: /higher")
        return False
    photo = BufferedInputFile(image, filename="higher.jpg")
    caption = views.hl_card(round_.streak, round_.record, last)
    markup = keyboards.higher_lower(round_.token)
    if message_id is not None and await send.edit_photo(bot, chat_id, message_id, photo, caption, markup):
        return True
    return await send.send_photo(bot, chat_id, photo, caption, markup) is not None


@router.message(Command("higher"))
async def higher_command(message: Message, bot: Bot, game: Game) -> None:
    if message.from_user is None:
        return
    if message.chat.type != "private":
        await message.reply(game_texts.HL_INVITE, reply_markup=keyboards.higher_lower_link(await username(bot)))
        return
    await deal(bot, game, message.chat.id, message.from_user.id)


@router.callback_query(F.data == "gm:hl", F.message)
async def higher_button(callback: CallbackQuery, bot: Bot, game: Game) -> None:
    if callback.message.chat.type == "private":
        await send.answer_quietly(callback, "🎯 Раздаю пикчи…")
        await deal(bot, game, callback.message.chat.id, callback.from_user.id)
        return
    await callback.answer()
    await send.send_text(bot, callback.message.chat.id, game_texts.HL_INVITE, keyboards.higher_lower_link(await username(bot)))


@router.callback_query(F.data.startswith("hl:"), F.message)
async def answer(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    parts = callback.data.split(":")
    chat_id, message_id, user_id = callback.message.chat.id, callback.message.message_id, callback.from_user.id
    if parts[1] == "new":
        await send.answer_quietly(callback, "🎯 Новая серия")
        await deal(bot, game, chat_id, user_id, message_id)
        return
    result = game.hl_answer(user_id, parts[2] if len(parts) > 2 else "", int(parts[1]) if parts[1].isdigit() else -1)
    if result.status == "stale":
        await callback.answer("Этот раунд уже сыгран", show_alert=True)
        return
    if result.status == "right":
        await send.answer_quietly(callback, f"✅ Верно! Серия {result.streak}")
        await deal(bot, game, chat_id, user_id, message_id, result)
        return
    await send.answer_quietly(callback, "❌ Мимо")
    await send.edit_caption(bot, chat_id, message_id, views.hl_over(result, chat_id, game.reward(games_rules.HL_REWARD)), keyboards.higher_lower_over())
    await live.announce(chat_id, game.check_achievements([user_id]))

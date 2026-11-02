"""Random pics, reactions, showing a specific pic."""

from time import monotonic

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.game import Game
from bot.texts import events as event_texts
from bot.texts import toasts, ui
from bot.texts.pick import pick
from bot.tg.handlers.court import open_court
from bot.tg.runtime import send
from bot.tg.runtime.timers import Live
from bot.tg.ui import keyboards, views

router = Router(name="pics")


def pic_markup(game: Game, pic_id: str, likes: int, dislikes: int):
    if game.repo.active_court_for_pic(pic_id):
        return keyboards.on_trial()
    return keyboards.pic_actions(pic_id, likes, dislikes)


# Telegram allows ~20 messages a minute in a group; mashing "🎲 Ещё" would get the whole chat muted.
COOLDOWN_SECONDS = 1.5
_last_drop: dict[int, float] = {}


def cooling_down(chat_id: int) -> bool:
    now = monotonic()
    if now - _last_drop.get(chat_id, 0.0) < COOLDOWN_SECONDS:
        return True
    _last_drop[chat_id] = now
    return False


async def drop_pic(bot: Bot, game: Game, live: Live, chat_id: int, user_id: int | None) -> None:
    drawn = game.draw_for(chat_id, user_id)
    if drawn is None:
        await send.send_text(bot, chat_id, f"<b>📦 {pick(ui.EMPTY_POOL, chat_id)}</b>")
        return
    pic, bucket, granted = drawn
    if game.roll_gold(chat_id):
        from bot.tg.handlers.games import drop_gold  # local: games imports arena → avoid an import cycle

        if await drop_gold(bot, game, chat_id, pic):
            await live.announce(chat_id, granted)
            return
    uploader = game.repo.user_label(pic.added_by) if pic.added_by else None
    message = await send.send_photo(
        bot,
        chat_id,
        pic.file_id,
        views.pic_caption(pic, bucket, chat_id, uploader, game.repo.bounty_on(pic.id)),
        pic_markup(game, pic.id, pic.likes, pic.dislikes),
    )
    if message is None:
        await send.send_text(bot, chat_id, pick(ui.ERRORS), keyboards.more_only())
        return
    await live.announce(chat_id, granted)


@router.message(Command("pic"))
async def pic_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    if not cooling_down(message.chat.id):
        await drop_pic(bot, game, live, message.chat.id, message.from_user.id if message.from_user else None)


@router.callback_query(F.data == "pic", F.message)
async def pic_button(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    if cooling_down(callback.message.chat.id):
        await callback.answer(pick(event_texts.COOLDOWN))
        return
    await callback.answer()
    await drop_pic(bot, game, live, callback.message.chat.id, callback.from_user.id)


@router.callback_query(F.data.startswith("show:"), F.message)
async def show_pic(callback: CallbackQuery, bot: Bot, game: Game) -> None:
    pic = game.repo.get_pic(callback.data.split(":", 1)[1])
    if pic is None or pic.status != "alive":
        await callback.answer("Её уже нет в живых", show_alert=True)
        return
    await callback.answer()
    chat_id = callback.message.chat.id
    uploader = game.repo.user_label(pic.added_by) if pic.added_by else None
    await send.send_photo(
        bot,
        chat_id,
        pic.file_id,
        views.pic_caption(pic, "legend", chat_id, uploader, game.repo.bounty_on(pic.id)),
        pic_markup(game, pic.id, pic.likes, pic.dislikes),
    )


@router.callback_query(F.data.startswith("r:"))
async def react(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    _, sign, pic_id = callback.data.split(":", 2)
    result = game.react(pic_id, callback.from_user.id, 1 if sign == "+" else -1)
    if result is None:
        await callback.answer("Не нашёл эту пикчу", show_alert=True)
        return
    message = callback.message
    if result.pic.status != "alive":
        await callback.answer("Её уже нет в живых. Помянем", show_alert=True)
        if message is not None:
            await send.edit_markup(bot, message.chat.id, message.message_id, keyboards.more_only())
        return
    if not result.changed:
        await callback.answer(pick(toasts.ALREADY))
        return

    await callback.answer(pick(toasts.LIKE if sign == "+" else toasts.DISLIKE))
    if message is None:
        return
    chat_id = message.chat.id
    if result.court_due:
        await open_court(
            bot,
            game,
            live,
            chat_id,
            pic_id,
            "dislikes",
            callback.from_user.id,
            pic_message_id=message.message_id,
        )
    else:
        await send.edit_markup(
            bot,
            chat_id,
            message.message_id,
            pic_markup(game, pic_id, result.pic.likes, result.pic.dislikes),
        )
    await live.announce(chat_id, result.granted)

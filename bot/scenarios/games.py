"""Mini-games: caption contest, golden pic, wheel of fortune, horoscope."""

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.core import economy
from bot.core import games as game_rules
from bot.game import Game
from bot.media import collage
from bot.texts import games as game_texts
from bot.texts import toasts, ui
from bot.texts.pick import pick
from bot.tg.runtime import send
from bot.tg.runtime.pictures import download
from bot.tg.runtime.timers import Live
from bot.tg.ui import keyboards, views

LOGGER = logging.getLogger(__name__)
router = Router(name="games")
DICE_ANIMATION_SECONDS = 2.8  # Telegram's 🎰 needs ~2.5 s to stop before revealing the prize


# ── caption contest ────────────────────────────────────────────────────


async def start_caption(bot: Bot, game: Game, live: Live, chat_id: int) -> str:
    status, contest = game.start_caption(chat_id)
    if status == "active" and contest is not None:
        if contest["phase_ends_at"] <= game.now():
            await live.advance_game(contest["id"])
            status, contest = game.start_caption(chat_id)
        else:
            return "active"
    if status == "shortage" or contest is None:
        await send.send_text(bot, chat_id, f"<b>📦 {pick(ui.EMPTY_POOL, chat_id)}</b>")
        return "shortage"
    pic = game.repo.get_pic(contest["pic_id"])
    message = await send.send_photo(
        bot,
        chat_id,
        pic.file_id,
        views.caption_card(contest, contest["phase_ends_at"] - game.now()),
    )
    if message is None:
        game.repo.drop_game(contest["id"])
        return "failed"
    game.repo.set_game_message(contest["id"], message.message_id)
    live.watch_game(contest["id"])
    return "started"


@router.message(Command("caption"))
async def caption_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    if await start_caption(bot, game, live, message.chat.id) == "active":
        await send.reply_personal(bot, message, "🖋 Конкурс подписей уже идёт — ответь на пикчу выше")


@router.callback_query(F.data.startswith("cv:"))
async def caption_vote(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, game_id, raw_slot = callback.data.split(":", 2)
    status = game.caption_vote(game_id, callback.from_user.id, int(raw_slot) if raw_slot.isdigit() else -1)
    answers = {
        "ok": pick(toasts.DUEL_VOTE),
        "same": pick(toasts.ALREADY),
        "own": "За свою подпись голосовать нельзя, нарцисс",
        "closed": "Голосование уже закрыто",
        "gone": "Этого конкурса уже нет",
    }
    await callback.answer(answers[status], show_alert=status in ("own", "gone"))
    if status == "ok":
        live.request_refresh_game(game_id)


async def caption_reply(message: Message, bot: Bot, game: Game, live: Live) -> bool:
    """A reply to a caption-contest pic. Returns True if it was taken as a caption."""
    if message.from_user is None or message.reply_to_message is None:
        return False
    contest = game.caption_entry(
        message.chat.id, message.reply_to_message.message_id, message.from_user.id, message.text or ""
    )
    if contest is None:
        return False
    await send.react(bot, message.chat.id, message.message_id, "✍")
    live.request_refresh_game(contest["id"])
    return True


# ── whose pic? ─────────────────────────────────────────────────────────


async def start_whose(bot: Bot, game: Game, live: Live, chat_id: int) -> str:
    """'started' | 'active' | 'cooldown' | 'shortage' | 'failed'."""
    status, round_ = game.start_whose(chat_id)
    if status == "active" and round_ is not None and round_["phase_ends_at"] <= game.now():
        await live.advance_game(round_["id"])
        status, round_ = game.start_whose(chat_id)
    if status != "started" or round_ is None:
        return status
    pic = game.repo.get_pic(round_["pic_id"])
    labels = [game.repo.user_label(user) for user in round_["options"]]
    message = await send.send_photo(
        bot,
        chat_id,
        pic.file_id,
        views.whose_card(round_, round_["phase_ends_at"] - game.now(), game.reward(game_rules.WHOSE_REWARD)),
        keyboards.whose(round_["id"], labels),
    )
    if message is None:
        game.repo.drop_game(round_["id"])
        return "failed"
    game.repo.set_game_message(round_["id"], message.message_id)
    live.watch_game(round_["id"])
    return "started"


WHOSE_REFUSALS = {
    "active": "🕵️ Раунд уже идёт — отвечай на пикчу выше",
    "cooldown": "🕵️ Детектив курит. Следующий раунд через {wait}",
    "shortage": "🕵️ Нужны пикчи хотя бы от двух человек",
    "failed": "🕵️ Telegram не дал показать пикчу. Попробуй ещё раз",
}


def whose_refusal(game: Game, chat_id: int, status: str) -> str:
    return WHOSE_REFUSALS[status].format(wait=views.duration(game.whose_cooldown_left(chat_id)))


@router.message(Command("whose"))
async def whose_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    status = await start_whose(bot, game, live, message.chat.id)
    if status != "started":
        await send.reply_personal(bot, message, whose_refusal(game, message.chat.id, status))


@router.callback_query(F.data.startswith("wh:"))
async def whose_guess(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, game_id, raw = callback.data.split(":", 2)
    status = game.guess_whose(game_id, callback.from_user.id, int(raw) if raw.isdigit() else -1)
    answers = {
        "ok": "🕵️ Ответ записан. Узнаешь через полминуты",
        "same": "Ответ уже принят. Переобуваться нельзя",
        "own": "Это твоя пикча. Не подсказывай",
        "closed": "Раунд уже закончился",
        "gone": "Этого раунда уже нет",
    }
    await callback.answer(answers[status], show_alert=status in ("own", "gone"))
    if status == "ok":
        live.request_refresh_game(game_id)


# ── golden pic ─────────────────────────────────────────────────────────


async def drop_gold(bot: Bot, game: Game, chat_id: int, pic) -> bool:
    """Send a pic as a golden one. False if the frame couldn't be built (caller sends it plainly)."""
    try:
        image = await download(bot, pic.file_id)
        if image is None:
            return False
        framed = await asyncio.to_thread(collage.golden_frame, image)
    except Exception:  # a failed frame just means a normal pic
        LOGGER.warning("Golden frame failed", exc_info=True)
        return False
    token = game.repo.create_gold(chat_id, pic.id, game.now())
    message = await send.send_photo(
        bot, chat_id, BufferedInputFile(framed, filename="gold.jpg"), views.gold_caption(game.reward(economy.GOLD)), keyboards.gold(token)
    )
    return message is not None


@router.callback_query(F.data.startswith("gold:"))
async def grab_gold(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    token = callback.data.split(":", 1)[1]
    if token == "taken":
        await callback.answer(pick(game_texts.GOLD_CLAIMED))
        return
    won, granted = game.claim_gold(token, callback.from_user.id)
    if not won:
        await callback.answer(pick(game_texts.GOLD_CLAIMED), show_alert=True)
        return
    await callback.answer(f"⚡ Твоё! +{views.num(game.reward(economy.GOLD))} 🪙", show_alert=True)
    if callback.message is not None:
        label = game.repo.user_label(callback.from_user.id)
        chat_id = callback.message.chat.id
        await send.edit_markup(bot, chat_id, callback.message.message_id, keyboards.gold_taken(label))
        await live.announce(chat_id, granted)


# ── wheel of fortune (free, once a day) ────────────────────────────────


async def spin(bot: Bot, game: Game, live: Live, chat_id: int, user_id: int) -> str | None:
    """Returns a toast for refusals, None when the wheel actually spun."""
    if not game.take_free_spin(user_id):
        return views.marked(pick(game_texts.WHEEL_USED), "🎡")
    try:
        dice = await bot.send_dice(chat_id, emoji="🎰")
    except TelegramAPIError:
        LOGGER.warning("Could not send the slot machine in %s", chat_id, exc_info=True)
        game.give_back_free_spin(user_id)
        return pick(ui.ERRORS)
    await asyncio.sleep(DICE_ANIMATION_SECONDS)
    result, pic, granted = game.resolve_spin(user_id, dice.dice.value)
    balance = game.repo.player(user_id)[0]
    text = views.spin_result(game.repo.user_label(user_id), result, pic, balance, chat_id)
    markup = keyboards.after_wheel()
    if result.kind == "legend" and pic is not None:
        await send.send_photo(bot, chat_id, pic.file_id, text, markup, reply_to=dice.message_id)
    else:
        await send.send_text(bot, chat_id, text, markup, reply_to=dice.message_id)
    await live.announce(chat_id, granted)
    return None


@router.message(Command("wheel"))
async def wheel_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    if message.from_user is None:
        return
    refusal = await spin(bot, game, live, message.chat.id, message.from_user.id)
    if refusal:
        await send.reply_personal(bot, message, refusal)


# ── horoscope ──────────────────────────────────────────────────────────


async def horoscope(bot: Bot, game: Game, live: Live, chat_id: int, user_id: int) -> str | None:
    pic, already, granted = game.horoscope(user_id)
    if already:
        return views.marked(pick(game_texts.HOROSCOPE_AGAIN), "🔮")
    if pic is None:
        return pick(ui.EMPTY_POOL)
    await send.send_photo(bot, chat_id, pic.file_id, views.horoscope(game.repo.user_label(user_id), chat_id))
    await live.announce(chat_id, granted)
    return None


@router.message(Command("horoscope"))
async def horoscope_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    if message.from_user is None:
        return
    refusal = await horoscope(bot, game, live, message.chat.id, message.from_user.id)
    if refusal:
        await send.reply_personal(bot, message, refusal)


# ── panel buttons ──────────────────────────────────────────────────────


@router.callback_query(F.data.in_({"gm:caption", "gm:spin", "gm:horo", "gm:whose"}), F.message)
async def game_buttons(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    chat_id = callback.message.chat.id
    # Refusals from buttons are pop-ups for the one who pressed, not messages in the chat.
    if callback.data == "gm:whose":
        status = await start_whose(bot, game, live, chat_id)
        if status == "started":
            await send.answer_quietly(callback, "🕵️ Раунд начался")
        else:
            await send.answer_quietly_alert(callback, whose_refusal(game, chat_id, status))
        return
    if callback.data == "gm:caption":
        if await start_caption(bot, game, live, chat_id) == "active":
            await send.answer_quietly_alert(callback, "🖋 Конкурс подписей уже идёт — ответь на пикчу выше")
        else:
            await send.answer_quietly(callback, "🖋 Конкурс начался")
        return
    if callback.data == "gm:spin":
        if not game.free_spin_available(callback.from_user.id):
            await callback.answer(views.marked(pick(game_texts.WHEEL_USED), "🎡"), show_alert=True)
            return
        await send.answer_quietly(callback, "🎡 Крутим!")
        refusal = await spin(bot, game, live, chat_id, callback.from_user.id)
    else:
        if not game.horoscope_available(callback.from_user.id):
            await callback.answer(views.marked(pick(game_texts.HOROSCOPE_AGAIN), "🔮"), show_alert=True)
            return
        await send.answer_quietly(callback, "🔮 Спрашиваю звёзды…")
        refusal = await horoscope(bot, game, live, chat_id, callback.from_user.id)
    if refusal:
        await send.personal(bot, chat_id, callback.from_user.id, refusal, callback_query_id=callback.id)

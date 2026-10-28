"""Casino on Telegram's animated dice: slots, dice vs the bot, darts, basketball, football, bowling."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import monotonic

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.core import casino
from bot.game import Game
from bot.texts import casino as texts
from bot.texts import ui
from bot.texts.pick import pick
from bot.tg import keyboards, send, views
from bot.tg.timers import Live

LOGGER = logging.getLogger(__name__)
router = Router(name="casino")
ANIMATION_SCALE = 1.0  # tests set 0
_last_play: dict[int, float] = {}


def cooling_down(user_id: int) -> bool:
    now = monotonic()
    if now - _last_play.get(user_id, 0.0) < casino.COOLDOWN_SECONDS:
        return True
    _last_play[user_id] = now
    return False


async def play(
    bot: Bot,
    game: Game,
    live: Live,
    chat_id: int,
    user_id: int,
    code: str,
    stake: int,
    on_started: Callable[[], Awaitable[None]] | None = None,
) -> str | None:
    """Roll one casino game. Returns a refusal to show the player, None when it was played.
    on_started runs once the stake is taken, so a button press is answered before the animation."""
    if code not in casino.GAMES:
        return views.marked(pick(ui.ERRORS), "⚠️")
    if cooling_down(user_id):
        return views.marked(pick(texts.COOLDOWN), "🎰")
    status = game.place_casino_bet(user_id, stake)
    if status == "small":
        return views.marked(pick(texts.SMALL), "🎰")
    if status == "broke":
        return views.marked(pick(texts.BROKE), "💸")
    info = casino.GAMES[code]
    if on_started is not None:
        await on_started()
    try:
        first = await bot.send_dice(chat_id, emoji=info.emoji)
        values = (first.dice.value,)
        if code == "dice":
            house = await bot.send_dice(chat_id, emoji=info.emoji, reply_to_message_id=first.message_id)
            values = (first.dice.value, house.dice.value)
    except TelegramAPIError:
        LOGGER.warning("Casino dice failed in %s", chat_id, exc_info=True)
        game.refund_casino_bet(user_id, stake)
        return pick(ui.ERRORS)
    await asyncio.sleep(info.animation * ANIMATION_SCALE)
    result = game.settle_casino(user_id, code, stake, values)
    label = game.repo.user_label(user_id)
    sent = await send.send_text(
        bot,
        chat_id,
        views.casino_result(label, result, values, chat_id),
        keyboards.casino_again(code, max(casino.STAKE_MIN, min(stake, max(result.balance, casino.STAKE_MIN)))),
        reply_to=first.message_id,
    )
    if result.profit >= result.stake * 5 and sent is not None:  # a big win deserves fireworks
        await send.react(bot, chat_id, sent.message_id, "🔥", big=True)
    await live.announce(chat_id, result.granted)
    return None


async def play_command(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live, code: str) -> None:
    if message.from_user is None:
        return
    user_id = message.from_user.id
    balance = game.repo.player(user_id)[0]
    stake = casino.parse_stake(command.args or "", balance, game.stake_for_play(user_id))
    if stake is None:
        await send.reply_personal(bot, message, f"Ставка — число: /{casino.GAMES[code].command} 100, или «все»")
        return
    if command.args:  # an explicit stake becomes the default for the buttons too
        game.set_stake(user_id, None if stake == balance and not command.args.strip().isdigit() else stake)
    refusal = await play(bot, game, live, message.chat.id, user_id, code, stake)
    if refusal:
        await send.reply_personal(bot, message, refusal)


@router.message(Command("casino"))
async def casino_command(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    from bot.tg.panel import open_screen  # local: panel imports this package, keep imports one-way

    await open_screen(message, bot, game, admins, "casino")  # it shows the asker's coins and stake


@router.message(Command("spin", "slots"))
async def spin_command(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    await play_command(message, command, bot, game, live, "slots")


@router.message(Command("dice"))
async def dice_command(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    await play_command(message, command, bot, game, live, "dice")


@router.message(Command("darts"))
async def darts_command(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    await play_command(message, command, bot, game, live, "darts")


@router.message(Command("basket"))
async def basket_command(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    await play_command(message, command, bot, game, live, "basket")


@router.message(Command("football"))
async def football_command(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    await play_command(message, command, bot, game, live, "football")


@router.message(Command("bowling"))
async def bowling_command(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    await play_command(message, command, bot, game, live, "bowling")


async def show_stake(bot: Bot, game: Game, callback: CallbackQuery) -> None:
    """On someone's own casino screen (personal copy or private chat), move the ✅ to the new stake.
    The chat's shared panel isn't redrawn: it would show one person's stake to everyone."""
    message = callback.message
    if isinstance(message, Message) and (message.ephemeral_message_id or message.chat.type == "private"):
        from bot.tg.screens import Ctx, render  # local: screens imports the views this module shares

        text, markup = render("casino", Ctx(game, message.chat.id, callback.from_user.id))
        await send.redraw(bot, message, callback.from_user.id, text, markup)


@router.callback_query(F.data.startswith("cs:"))
async def set_stake(callback: CallbackQuery, bot: Bot, game: Game) -> None:
    raw = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    balance = game.repo.player(user_id)[0]
    if raw == "all":
        game.set_stake(user_id, None)
        await callback.answer(f"🃏 Ва-банк: ставишь всё, сейчас это {views.num(balance)} 🪙. {pick(texts.STAKE_SET)}")
        await show_stake(bot, game, callback)
        return
    if raw.startswith("p") and raw[1:].isdigit():
        share = int(raw[1:])
        game.set_stake_share(user_id, share)
        stake = casino.share_stake(balance, share)
        await callback.answer(f"🎟 Ставка {share}% баланса, сейчас это {views.num(stake)} 🪙. {pick(texts.STAKE_SET)}")
        await show_stake(bot, game, callback)
        return
    amount = int(raw) if raw.isdigit() else casino.DEFAULT_STAKE  # buttons of older messages
    game.set_stake(user_id, amount)
    await callback.answer(f"🎟 Ставка {views.num(amount)} 🪙. {pick(texts.STAKE_SET)}")
    await show_stake(bot, game, callback)


async def play_button(callback: CallbackQuery, bot: Bot, game: Game, live: Live, code: str, stake: int) -> None:
    if callback.message is None:
        await callback.answer()
        return
    info = casino.GAMES.get(code)

    async def answer_now() -> None:
        await send.answer_quietly(callback, f"{info.emoji} Ставка {stake} 🪙. Крутим!")

    refusal = await play(bot, game, live, callback.message.chat.id, callback.from_user.id, code, stake, answer_now)
    if refusal:
        await send.answer_quietly_alert(callback, refusal)


@router.callback_query(F.data.startswith("cg:"))
async def game_button(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    code = callback.data.split(":", 1)[1]
    await play_button(callback, bot, game, live, code, game.stake_for_play(callback.from_user.id))


@router.callback_query(F.data.startswith("cp:"))
async def again_button(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    _, code, raw = callback.data.split(":", 2)
    stake = int(raw) if raw.isdigit() else casino.DEFAULT_STAKE
    await play_button(callback, bot, game, live, code, stake)

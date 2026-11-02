"""The live control panel: one message per chat, redrawn in place. Screens live in screens.py."""

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from bot.game import Game
from bot.texts import ui
from bot.tg.runtime import send
from bot.tg.ui import screens
from bot.tg.ui.screens import Ctx

router = Router(name="panel")
HELP_SECONDS = 600  # the rules are long: if the chat had to see them, give time to read


@router.my_chat_member()
async def bot_status_changed(update: ChatMemberUpdated) -> None:
    """Made an admin, the bot may write personal messages any time: stop assuming it can't."""
    send.ephemeral_allowed_again(update.chat.id)


def message_ctx(message: Message, game: Game, admins: frozenset[int], arg: str | None = None) -> Ctx:
    user_id = message.from_user.id if message.from_user else 0
    return Ctx(game, message.chat.id, user_id, user_id in admins, message.chat.type == "private", arg)


async def open_panel(
    message: Message, bot: Bot, game: Game, admins: frozenset[int], name: str = "home", arg: str | None = None
) -> None:
    """Post a fresh panel and delete the previous one, so a chat never has two."""
    ctx = message_ctx(message, game, admins, arg)
    text, markup = screens.render(name, ctx)
    previous = game.repo.panel_message(ctx.chat_id)
    sent = await send.send_text(bot, ctx.chat_id, text, markup)
    if sent is None:
        return
    game.repo.set_panel_message(ctx.chat_id, sent.message_id)
    if previous is not None:
        await send.delete(bot, ctx.chat_id, previous)


async def show_personal(bot: Bot, ctx: Ctx, name: str, callback_id: str | None = None) -> bool:
    """A personal screen only its owner sees. False if Telegram refused the ephemeral message."""
    text, markup = screens.render(name, ctx)
    if name == "quests":
        markup = screens.quests_markup(ctx.game, ctx.user_id, ctx.chat_id)
    return await send.ephemeral(bot, ctx.chat_id, ctx.user_id, text, callback_id, markup) is not None


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    if command.args == "hl" and message.from_user is not None:  # the "play in private" link
        from bot.tg.handlers.higher import deal  # local: higher imports arena, which imports this package

        await deal(bot, game, message.chat.id, message.from_user.id)
        return
    await message.answer(ui.START, parse_mode="HTML")
    await open_panel(message, bot, game, admins)


@router.message(Command("menu"))
async def menu(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    await open_panel(message, bot, game, admins)


@router.message(Command("top"))
async def top(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    await open_panel(message, bot, game, admins, "top", "uploads")


async def open_screen(message: Message, bot: Bot, game: Game, admins: frozenset[int], name: str) -> None:
    """A screen about the one who asked (their profile, coins, stake): in a group only they see
    it; if Telegram refuses, it becomes the panel."""
    ctx = message_ctx(message, game, admins)
    if ctx.is_private or message.from_user is None or not await show_personal(bot, ctx, name):
        await open_panel(message, bot, game, admins, name)


@router.message(Command("me", "quests", "chest"))
async def personal(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    command = (message.text or "").split()[0].lstrip("/").split("@")[0]
    await open_screen(message, bot, game, admins, "me" if command == "me" else "quests")


@router.message(Command("help"))
async def help_command(message: Message, bot: Bot) -> None:
    await send.reply_personal(bot, message, ui.HELP, seconds=HELP_SECONDS)


@router.message(Command("id"))
async def my_id(message: Message, bot: Bot) -> None:
    if message.from_user:
        await send.reply_personal(bot, message, f"🆔 Твой ID: <code>{message.from_user.id}</code>")


@router.callback_query(F.data.startswith("m:"))
async def navigate(callback: CallbackQuery, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    """In a group the chat's panel stays on its home screen for everyone: a section pressed on it
    opens for the presser only, in the panel's place, and further presses redraw that personal
    copy. So one person browsing the shop never loses it to someone else pressing «Slots»."""
    message = callback.message
    if not isinstance(message, Message):
        await send.answer_quietly(callback, "Открой /menu ещё раз")
        return
    parts = callback.data.split(":")
    name = parts[1] if len(parts) > 1 else "home"
    arg = ":".join(parts[2:]) or None  # "m:top:uploads:w" → "uploads:w"
    user_id = callback.from_user.id
    ctx = Ctx(game, message.chat.id, user_id, user_id in admins, message.chat.type == "private", arg)
    if name == "adm" and not ctx.is_admin:
        await callback.answer(ui.ADMIN_ONLY, show_alert=True)
        return
    text, markup = screens.render(name, ctx)
    if name == "quests" and not ctx.is_private:  # its buttons carry the chat, for personal copies
        markup = screens.quests_markup(game, user_id, ctx.chat_id) or markup
    own = bool(message.ephemeral_message_id)
    if own and await send.edit_ephemeral(bot, ctx.chat_id, user_id, message.ephemeral_message_id, text, markup):
        await send.answer_quietly(callback)  # the presser's own copy, redrawn in place
        return
    if not ctx.is_private and (own or name != "home"):
        # In the panel's place if Telegram allows, else just below it; from another card (a
        # result's «👥 Люди») always below, so the card stays. A copy that vanished (Telegram
        # drops them on app restarts) is replaced by a fresh one.
        panel = game.repo.panel_message(ctx.chat_id) == message.message_id
        for replace in (True, False) if panel and not own else (False,):
            if await send.ephemeral(bot, ctx.chat_id, user_id, text, callback.id, markup, replace=replace):
                await send.answer_quietly(callback, None if own else "👀 Видно только тебе")
                return
    await callback.answer("🔄 Обновлено" if name == "home" and arg == "refresh" else None)
    if not own:
        await send.edit_text(bot, ctx.chat_id, message.message_id, text, markup)

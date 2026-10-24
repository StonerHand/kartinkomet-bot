"""The live control panel: one message per chat, redrawn in place. Screens live in screens.py."""

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from bot.game import Game
from bot.texts import ui
from bot.tg import screens, send
from bot.tg.screens import PERSONAL, Ctx

router = Router(name="panel")


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
    text, _ = screens.render(name, ctx)
    markup = screens.quests_markup(ctx.game, ctx.user_id, ctx.chat_id) if name == "quests" else None
    return await send.send_ephemeral(bot, ctx.chat_id, ctx.user_id, text, callback_id, markup)


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    if command.args == "hl" and message.from_user is not None:  # the "play in private" link
        from bot.tg.higher import deal  # local: higher imports arena, which imports this package

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


@router.message(Command("me", "quests", "chest"))
async def personal(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    """In a group only the author sees these; if Telegram refuses, they become the panel."""
    command = (message.text or "").split()[0].lstrip("/").split("@")[0]
    name = "me" if command == "me" else "quests"
    ctx = message_ctx(message, game, admins)
    if ctx.is_private or message.from_user is None or not await show_personal(bot, ctx, name):
        await open_panel(message, bot, game, admins, name)


@router.message(Command("help"))
async def help_command(message: Message, bot: Bot) -> None:
    await send.reply_personal(bot, message, ui.HELP)


@router.message(Command("id"))
async def my_id(message: Message, bot: Bot) -> None:
    if message.from_user:
        await send.reply_personal(bot, message, f"Твой ID: <code>{message.from_user.id}</code>")


@router.callback_query(F.data.startswith("m:"))
async def navigate(callback: CallbackQuery, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    message = callback.message
    if message is None:
        await callback.answer()
        return
    parts = callback.data.split(":")
    name = parts[1] if len(parts) > 1 else "home"
    arg = ":".join(parts[2:]) or None  # "m:top:uploads:w" → "uploads:w"
    ctx = Ctx(game, message.chat.id, callback.from_user.id, callback.from_user.id in admins,
              message.chat.type == "private", arg)
    if name == "adm" and not ctx.is_admin:
        await callback.answer(ui.ADMIN_ONLY, show_alert=True)
        return
    if name in PERSONAL and not ctx.is_private and await show_personal(bot, ctx, name, callback.id):
        await send.answer_quietly(callback, "👀 Показал только тебе")
        return
    text, markup = screens.render(name, ctx)
    await callback.answer("🔄 Обновлено" if name == "home" and arg == "refresh" else None)
    await send.edit_text(bot, message.chat.id, message.message_id, text, markup)

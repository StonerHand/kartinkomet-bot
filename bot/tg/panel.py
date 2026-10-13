"""The live control panel: one message per chat, redrawn in place."""

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.game import Game
from bot.texts import ui
from bot.tg import keyboards, send, views

router = Router(name="panel")

BOARDS = {"uploads", "loved", "killers", "streaks"}


def screen(
    game: Game,
    name: str,
    arg: str | None,
    chat_id: int,
    user_id: int,
    is_admin: bool,
    is_private: bool,
) -> tuple[str, InlineKeyboardMarkup]:
    repo = game.repo
    if name == "hall":
        pics = repo.top_rated(10)
        labels = [repo.user_label(pic.added_by) for pic in pics]
        record = repo.meta_int(f"streak_record:{chat_id}")
        return views.hall(pics, labels, record), keyboards.hall([pic.id for pic in pics])
    if name == "bottom":
        pics = repo.bottom_rated(10)
        labels = [repo.user_label(pic.added_by) for pic in pics]
        return views.bottom(pics, labels), keyboards.bottom([pic.id for pic in pics])
    if name == "grave":
        pics = repo.graveyard(5)
        labels = [repo.user_label(pic.added_by) for pic in pics]
        text = views.graveyard(repo.count_pics("executed"), pics, labels, game.now())
        return text, keyboards.graveyard([pic.id for pic in pics], is_admin)
    if name == "top":
        board = arg if arg in BOARDS else "uploads"
        rows = [(repo.user_label(user), value) for user, value in repo.top_users(board)]
        return views.top(board, rows), keyboards.tops(board)
    if name == "me":
        stats = repo.user_stats(user_id, game.night_hours_utc)
        ranking = [uid for uid, _ in repo.top_users("uploads", limit=1000)]
        place = ranking.index(user_id) + 1 if user_id in ranking else None
        text = views.profile(repo.user_label(user_id), stats, repo.achievements_of(user_id), place)
        return text, keyboards.markup(keyboards.back())
    if name == "help":
        return ui.HELP, keyboards.markup(keyboards.back())
    if name == "up":
        return views.upload_hub(is_private), keyboards.upload_hub(is_private)
    if name == "adm" and is_admin:
        text = views.admin(repo.totals(), repo.count_users(), str(repo.database_path))
        events_on = None if is_private else repo.chat_events_on(chat_id)
        return text, keyboards.admin(events_on)
    return views.home(repo.totals(), chat_id, live_now(game, chat_id)), keyboards.home(is_admin)


def live_now(game: Game, chat_id: int) -> list[str]:
    now = game.now()
    lines = []
    for kind, label in (("duel", "⚔️ Дуэль"), ("tournament", "🏟 Турнир")):
        battle = game.repo.active_battle(chat_id, kind)
        if battle and battle.ends_at > now:
            lines.append(f"{label} · ⏳ {views.timer(battle.ends_at - now)}")
    courts = game.repo.active_courts_in_chat(chat_id, now)
    if courts:
        extra = f" · и ещё {len(courts) - 1}" if len(courts) > 1 else ""
        lines.append(f"⚖️ Суд · ⏳ {views.timer(min(courts) - now)}{extra}")
    return lines


async def open_panel(
    message: Message, bot: Bot, game: Game, admins: frozenset[int], name: str = "home", arg: str | None = None
) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    text, markup = screen(
        game, name, arg, chat_id, user_id, user_id in admins, message.chat.type == "private"
    )
    previous = game.repo.panel_message(chat_id)
    sent = await send.send_text(bot, chat_id, text, markup)
    if sent is None:
        return
    game.repo.set_panel_message(chat_id, sent.message_id)
    if previous is not None:
        await send.delete(bot, chat_id, previous)


@router.message(CommandStart())
async def start(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    await message.answer(ui.START, parse_mode="HTML")
    await open_panel(message, bot, game, admins)


@router.message(Command("menu"))
async def menu(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    await open_panel(message, bot, game, admins)


@router.message(Command("top"))
async def top(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    await open_panel(message, bot, game, admins, "top", "uploads")


@router.message(Command("me"))
async def me(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    await open_panel(message, bot, game, admins, "me")


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(ui.HELP, parse_mode="HTML")


@router.message(Command("id"))
async def my_id(message: Message) -> None:
    if message.from_user:
        await message.answer(f"Твой ID: <code>{message.from_user.id}</code>", parse_mode="HTML")


@router.callback_query(F.data.startswith("m:"))
async def navigate(callback: CallbackQuery, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    message = callback.message
    if message is None:
        await callback.answer()
        return
    parts = callback.data.split(":")
    name = parts[1] if len(parts) > 1 else "home"
    arg = parts[2] if len(parts) > 2 else None
    is_admin = callback.from_user.id in admins
    if name == "adm" and not is_admin:
        await callback.answer(ui.ADMIN_ONLY, show_alert=True)
        return
    is_private = message.chat.type == "private"
    text, markup = screen(game, name, arg, message.chat.id, callback.from_user.id, is_admin, is_private)
    if name == "me" and not is_private:
        # The profile is personal: in a group show it only to the person who asked.
        if await send.send_ephemeral(bot, message.chat.id, callback.from_user.id, text, callback.id):
            await send.answer_quietly(callback, "👤 Показал только тебе")
            return
    await callback.answer("🔄 Обновлено" if name == "home" and arg == "refresh" else None)
    await send.edit_text(bot, message.chat.id, message.message_id, text, markup)

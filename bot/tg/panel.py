"""The live control panel: one message per chat, redrawn in place."""

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.core import casino
from bot.game import Game
from bot.texts import ui
from bot.tg import cards, keyboards, send, views

router = Router(name="panel")

BOARDS = {"uploads", "loved", "killers", "streaks", "rich"}
PERSONAL = {"me", "quests"}  # shown only to the person who asked, in groups


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
        if pics:
            text += f"\n\n<i>Кнопка с номером — воскресить за {views.num(game.price('resurrect'))} монет, нажать дважды</i>"
        return text, keyboards.graveyard([pic.id for pic in pics], is_admin)
    if name == "top":
        board = arg if arg in BOARDS else "uploads"
        rows = [(repo.user_label(user), value) for user, value in repo.top_users(board)]
        return views.top(board, rows), keyboards.tops(board)
    if name == "me":
        stats = repo.user_stats(user_id, game.night_hours_utc, game.tz_offset_hours, game.now())
        ranking = [uid for uid, _ in repo.top_users("uploads", limit=1000)]
        place = ranking.index(user_id) + 1 if user_id in ranking else None
        coins, earned, _ = repo.player(user_id)
        spouse = repo.spouse_of(user_id)
        jail = repo.counter(user_id, "jail_until") - game.now()
        streak = repo.counter(user_id, "active_streak")
        if repo.counter(user_id, "last_active_day") < game.local_day() - 1:
            streak = 0  # the streak burnt out
        text = views.profile(
            repo.user_label(user_id),
            stats,
            repo.achievements_of(user_id),
            place,
            views.Wallet(
                coins=coins,
                earned=earned,
                streak=streak,
                right_guesses=repo.counter(user_id, "right_guesses"),
                wrong_guesses=repo.counter(user_id, "wrong_guesses"),
                nemesis=(repo.user_label(nemesis[0]), nemesis[1]) if (nemesis := repo.nemesis(user_id)) else None,
                crowns=tuple(game.crowns_of(user_id)),
                spouse=(repo.user_label(spouse[0]), (game.now() - spouse[1]) // 86400) if spouse else None,
                title=repo.title_of(user_id),
                chests=game.chests_of(user_id),
                jailed=max(0, jail),
            ),
            repo.achievement_owners(),
            max(1, repo.count_users()),
        )
        return text, keyboards.markup(keyboards.back())
    if name == "games":
        return views.GAMES_SCREEN, keyboards.games_menu()
    if name == "casino":
        balance = repo.player(user_id)[0]
        text = cards.casino_screen(
            repo.user_label(user_id), balance, game.stake_for_play(user_id), chat_id, game.day_is("lucky_day")
        )
        return text, keyboards.casino_menu(casino.STAKE_PRESETS)
    if name == "shop":
        prices = {item: game.price(item) for item in ("shield", "boost", "court", "uncurse", "resurrect", "title")}
        text = cards.shop_screen(repo.user_label(user_id), repo.player(user_id)[0], prices, chat_id, game.day_event())
        return text, keyboards.shop_menu()
    if name == "quests":
        daily, weekly = game.quests_of(user_id)
        chests = game.chests_of(user_id)
        ready = repo.counter(user_id, "daily_day") != game.local_day()
        text = cards.quests_screen(
            repo.user_label(user_id), daily, weekly, chests, ready, repo.counter(user_id, "daily_streak"), chat_id
        )
        return text, keyboards.quests_menu(ready, chests)
    if name == "help":
        return ui.HELP, keyboards.markup(keyboards.back())
    if name == "up":
        return views.upload_hub(is_private), keyboards.upload_hub(is_private)
    if name == "adm" and is_admin:
        text = views.admin(repo.totals(), repo.count_users(), str(repo.database_path))
        events_on = None if is_private else repo.chat_events_on(chat_id)
        return text, keyboards.admin(events_on)
    today = cards.day_event_line(game.day_event())
    return views.home(repo.totals(), chat_id, live_now(game, chat_id), today), keyboards.home(is_admin)


def live_now(game: Game, chat_id: int) -> list[str]:
    now = game.now()
    lines = []
    for kind, label in (("duel", "⚔️ Дуэль"), ("tournament", "🏟 Турнир")):
        battle = game.repo.active_battle(chat_id, kind)
        if battle and battle.ends_at > now:
            lines.append(f"{label} · ещё {views.timer(battle.ends_at - now)}")
    courts = game.repo.active_courts_in_chat(chat_id, now)
    if courts:
        extra = f" · и ещё {len(courts) - 1}" if len(courts) > 1 else ""
        lines.append(f"⚖️ Суд · ещё {views.timer(min(courts) - now)}{extra}")
    boss = game.repo.active_boss(chat_id)
    if boss and boss["ends_at"] > now:
        lines.append(f"👹 Босс · здоровье {boss['hp']}/{boss['max_hp']} · ещё {views.timer(boss['ends_at'] - now)}")
    if game.repo.active_challenge_battle(chat_id):
        lines.append("🤺 Идёт вызов")
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


async def personal(message: Message, bot: Bot, game: Game, admins: frozenset[int], name: str) -> None:
    """Personal screens by command: in a group only the author sees them; if Telegram refuses an
    ephemeral message, the screen becomes the panel as before."""
    if message.chat.type != "private" and message.from_user is not None:
        user_id = message.from_user.id
        text, _ = screen(game, name, None, message.chat.id, user_id, user_id in admins, False)
        markup = None
        if name == "quests":
            ready = game.repo.counter(user_id, "daily_day") != game.local_day()
            markup = keyboards.quests_menu(ready, game.chests_of(user_id), message.chat.id)
            markup = markup if markup.inline_keyboard else None
        if await send.send_ephemeral(bot, message.chat.id, user_id, text, None, markup):
            return
    await open_panel(message, bot, game, admins, name)


@router.message(Command("me"))
async def me(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    await personal(message, bot, game, admins, "me")


@router.message(Command("quests", "chest"))
async def quests(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    await personal(message, bot, game, admins, "quests")


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
    if name in PERSONAL and not is_private:
        # Personal screens: in a group show them only to the person who asked.
        ephemeral_markup = None
        if name == "quests":  # no "back" (it can't edit an ephemeral message), chat id in buttons
            user_id = callback.from_user.id
            ready = game.repo.counter(user_id, "daily_day") != game.local_day()
            ephemeral_markup = keyboards.quests_menu(ready, game.chests_of(user_id), message.chat.id)
            ephemeral_markup = ephemeral_markup if ephemeral_markup.inline_keyboard else None
        if await send.send_ephemeral(bot, message.chat.id, callback.from_user.id, text, callback.id, ephemeral_markup):
            await send.answer_quietly(callback, "👀 Показал только тебе")
            return
    await callback.answer("🔄 Обновлено" if name == "home" and arg == "refresh" else None)
    await send.edit_text(bot, message.chat.id, message.message_id, text, markup)

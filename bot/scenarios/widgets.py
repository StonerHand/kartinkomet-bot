"""HTML widgets in the chat (Bot API 10.4): the table games, board duels, the slot machine and the
live board as small pages inside messages. Off until an admin switches them on for the chat
(admin panel): until Telegram opens the API to bots, and for chats with clients that can't draw
widgets, every game keeps its ordinary card. A widget that Telegram refuses falls back to it too.

Each widget message is registered in `meta wmsg:<chat>:<message>` → "<kind>:<what>"; a tap
arrives as a `widget_query` update (app/middleware.WidgetQueries) and is routed here by it."""

import json
import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.game.engine import Game
from bot.live.timers import Live
from bot.rules import casino as casino_rules
from bot.scenarios import casino as casino_scenario
from bot.telegram import send
from bot.telegram import widgets as widget_api
from bot.telegram.widgets import WidgetQuery
from bot.ui import views, widgets

LOGGER = logging.getLogger(__name__)
router = Router(name="widgets")
BOARD_SIZE = 5  # season places the board shows
BOARD_CACHE_SECONDS = 60  # how often clients ask for the board's fresh data
FEED_SIZE = 5
BIG_WIN = 5  # a slot win this many times the stake goes to the machine's feed


def enabled(game: Game, chat_id: int) -> bool:
    return chat_id < 0 and game.repo.meta_int(f"widgets:{chat_id}") == 1


def toggle(game: Game, chat_id: int) -> bool:
    on = not enabled(game, chat_id)
    game.repo.set_meta(f"widgets:{chat_id}", int(on))
    return on


async def post(
    bot: Bot, game: Game, chat_id: int, kind: str, what: str, data: str,
    shared: bool = False, reply_to: int | None = None,
) -> Message | None:
    """Send a widget and register it; None (and the reason noted for the admin) when Telegram
    refuses: the caller sends the ordinary card instead."""
    message = await widget_api.send_widget(
        bot, chat_id, widgets.page(kind), widgets.CAPTIONS[kind],
        chat_data=None if shared else data, public_data=data if shared else None, shared=shared, reply_to=reply_to,
    )
    if message is None:
        game.repo.set_meta("widgets_refused", game.now())
        return None
    game.repo.set_meta(f"wmsg:{chat_id}:{message.message_id}", f"{kind}:{what}")
    return message


# ── taps ──────────────────────────────────────────────────────────────

Handler = Callable[[Bot, Game, Live, WidgetQuery, str], Awaitable[dict | str]]


async def handle(bot: Bot, game: Game, live: Live, query: WidgetQuery) -> None:
    """A tap inside a widget: do what it asks, answer with what the widget shows the tapper."""
    user = query.user
    if not user.is_bot:
        game.repo.remember_user(user.id, user.username, user.first_name, user.last_name, game.now())
    ref = game.repo.meta_str(f"wmsg:{query.chat_id}:{query.message_id}") if query.chat_id else ""
    kind, _, what = (ref or "").partition(":")
    handler = HANDLERS.get(kind)
    result: dict | str = {"s": "gone"}
    if handler is not None:
        result = await handler(bot, game, live, query, what)
    await widget_api.answer(bot, query.id, result if isinstance(result, str) else widget_api.pack(result))


async def tap_mines(bot: Bot, game: Game, live: Live, query: WidgetQuery, round_id: str) -> dict:
    if query.data == "c":
        status, paid = game.cash_mines(round_id, query.user.id)
        if status == "ok":
            live.request_refresh_round(round_id)
        return {"s": status, "v": paid}
    raw = query.data[1:]
    move = game.open_cell(round_id, query.user.id, int(raw) if query.data.startswith("o") and raw.isdigit() else -1)
    if move.result is not None:
        await live.settle_mines(move.result)
    elif move.status == "safe":
        live.request_refresh_round(round_id)
    return {"s": move.status, "v": game.reward(move.value)}


async def tap_safe(bot: Bot, game: Game, live: Live, query: WidgetQuery, round_id: str) -> dict:
    code = query.data[1:] if query.data.startswith("t") else ""
    attempt = game.guess_safe(round_id, query.user.id, code)
    if attempt.result is not None:
        await live.settle_safe(attempt.result)
    elif attempt.status == "miss":
        live.request_refresh_round(round_id)
    return {"s": attempt.status, "e": attempt.exact, "n": attempt.near, "w": attempt.wait}


async def tap_spy(bot: Bot, game: Game, live: Live, query: WidgetQuery, round_id: str) -> dict:
    user, data = query.user.id, query.data
    if data == "w":
        status, word = game.spy_secret(round_id, user)
        return {"spy": 1} if status == "spy" else {"w": word} if status == "word" else {"s": status}
    if data == "j":
        status = game.join_spy(round_id, user)
    elif data == "s":
        status = game.start_spy_now(round_id, user)
        if status == "ok":
            await live.hurry(round_id)
            return {"s": status}
    elif data == "r":
        status = game.spy_ready(round_id, user)
    else:
        index = data[1:]
        status = game.vote_spy(round_id, user, int(index) if data.startswith("v") and index.isdigit() else -1)
    if status == "ok":
        await live.spy_moved(round_id)
    return {"s": status}


async def tap_rps(bot: Bot, game: Game, live: Live, query: WidgetQuery, challenge_id: str) -> dict:
    raw = query.data[1:]
    status, duel = game.pick_rps(challenge_id, query.user.id, int(raw) if query.data.startswith("p") and raw.isdigit() else -1)
    if duel is not None:
        await live.settle_duel(duel)
    elif status in ("ok", "draw"):
        live.request_refresh_duel(challenge_id)
    return {"s": status}


async def tap_ttt(bot: Bot, game: Game, live: Live, query: WidgetQuery, challenge_id: str) -> dict:
    raw = query.data[1:]
    status, duel = game.move_ttt(challenge_id, query.user.id, int(raw) if query.data.startswith("m") and raw.isdigit() else -1)
    if duel is not None:
        await live.settle_duel(duel)
    elif status == "ok":
        await live.refresh_duel(challenge_id)
    return {"s": status}


async def tap_slots(bot: Bot, game: Game, live: Live, query: WidgetQuery, chat: str) -> dict:
    """One spin of the shared machine: only the spinner sees the reels stop; big wins go to the
    machine's feed, which everyone sees. The bot draws the reels, as Telegram's 🎰 would (1..64)."""
    user_id = query.user.id
    if casino_scenario.cooling_down(user_id):
        return {"e": "cool"}
    stake = game.stake_for_play(user_id)
    status = game.place_casino_bet(user_id, stake)
    if status != "ok":
        return {"e": status}
    value = game.rng.randint(1, 64)
    result = game.settle_casino(user_id, "slots", stake, (value,))
    if result.payout >= stake * BIG_WIN and query.chat_id is not None and query.message_id is not None:
        await feed(bot, game, query.chat_id, query.message_id, game.repo.user_label(user_id), result.payout - stake)
    if query.chat_id is not None:
        await live.announce(query.chat_id, result.granted)
    return {"v": value, "w": result.payout, "k": stake, "b": result.balance}


async def feed(bot: Bot, game: Game, chat_id: int, message_id: int, who: str, won: int) -> None:
    key = f"slots_feed:{chat_id}:{message_id}"
    entries = json.loads(game.repo.meta_str(key) or "[]")
    entries = [[who, won], *entries][:FEED_SIZE]
    game.repo.set_meta(key, json.dumps(entries, ensure_ascii=False))
    await widget_api.edit_data(bot, chat_id, message_id, widgets.slots_data([tuple(item) for item in entries]))


async def tap_board(bot: Bot, game: Game, live: Live, query: WidgetQuery, chat: str) -> str:
    return board_data(game, int(chat))


HANDLERS: dict[str, Handler] = {
    "mines": tap_mines, "safe": tap_safe, "spy": tap_spy, "rps": tap_rps, "ttt": tap_ttt, "slots": tap_slots,
    "board": tap_board,
}


# ── the slot machine and the live board ───────────────────────────────

WIDGETS_OFF = ("🧩 Это виджет, а виджеты в этом чате выключены. Админ включает их в /admin, "
               "когда Telegram откроет их ботам")


@router.message(Command("machine"))
async def machine_command(message: Message, bot: Bot, game: Game) -> None:
    """/machine: one slot machine for the whole chat (a widget)."""
    if not enabled(game, message.chat.id):
        await send.reply_personal(bot, message, WIDGETS_OFF)
        return
    if await post(bot, game, message.chat.id, "slots", "machine", widgets.slots_data([])) is None:
        await send.reply_personal(bot, message, views.marked(
            f"Telegram не принял виджет. Казино на кубиках — /spin {casino_rules.DEFAULT_STAKE}", "🎰"))


def board_snapshot(game: Game, chat_id: int) -> tuple[list[tuple[str, int]], tuple[int, int] | None]:
    """(the season's top with points, the team week's red and blue) as the board shows them."""
    start, end = game.season_bounds()
    season = [(game.repo.user_label(user), points) for user, points in game.repo.season_scores(start, end, BOARD_SIZE)]
    week = game.team_week(chat_id)
    return season, (week.scores.get("red", 0), week.scores.get("blue", 0)) if week else None


def board_data(game: Game, chat_id: int) -> str:
    season, teams = board_snapshot(game, chat_id)
    hour = (game.now() // 3600 + game.tz_offset_hours) % 24
    return widgets.board_data(season, teams, f"{hour}:{game.now() % 3600 // 60:02d}")


@router.message(Command("board"))
async def board_command(message: Message, bot: Bot, game: Game) -> None:
    """/board: the season's race and the team week, live: a shared widget the schedule refreshes;
    with widgets off, a snapshot card."""
    chat_id = message.chat.id
    if enabled(game, chat_id):
        sent = await post(bot, game, chat_id, "board", str(chat_id), board_data(game, chat_id), shared=True)
        if sent is not None:
            shared_id = widget_api.widget_id(sent)
            if shared_id:  # without it the board still answers «Обновить», it just won't refresh by itself
                game.repo.set_meta(f"board:{chat_id}", shared_id)
            return
    await send.send_text(bot, chat_id, board_card(game, chat_id))


def board_card(game: Game, chat_id: int) -> str:
    season, teams = board_snapshot(game, chat_id)
    return views.board_card(season, teams, game.season())


_boards: dict[int, tuple] = {}  # what each chat's board shows now


async def refresh_boards(bot: Bot, game: Game, chat_ids: list[int]) -> int:
    """Every schedule tick: each chat's live board gets fresh data when it changed."""
    sent = 0
    for chat_id in chat_ids:
        shared_id = game.repo.meta_str(f"board:{chat_id}")
        if not shared_id or not enabled(game, chat_id):
            continue
        snapshot = board_snapshot(game, chat_id)
        if _boards.get(chat_id) == snapshot:
            continue
        if await widget_api.edit_shared(bot, shared_id, board_data(game, chat_id), BOARD_CACHE_SECONDS):
            _boards[chat_id] = snapshot
            sent += 1
    return sent

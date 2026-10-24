"""Panel screens: data from the game, text from views, buttons from keyboards.

Each screen is a function of a Ctx; `render(name, ctx)` picks one. The panel router, admin
tools and personal (ephemeral) screens all go through here.
"""

from collections.abc import Callable
from dataclasses import dataclass

from aiogram.types import InlineKeyboardMarkup

from bot.core import casino
from bot.game import Game
from bot.texts import ui
from bot.tg import keyboards, views

BOARDS = {"uploads", "loved", "killers", "streaks", "rich", "season", "hl"}
SHOP_ITEMS = ("shield", "boost", "court", "uncurse", "resurrect", "title")
Screen = tuple[str, InlineKeyboardMarkup]


@dataclass(frozen=True)
class Ctx:
    game: Game
    chat_id: int
    user_id: int
    is_admin: bool = False
    is_private: bool = False
    arg: str | None = None

    @property
    def repo(self):
        return self.game.repo

    def labels(self, pics) -> list[str]:
        return [self.repo.user_label(pic.added_by) for pic in pics]


def home(ctx: Ctx) -> Screen:
    game = ctx.game
    today = views.day_event_line(game.day_event())
    days_left = max(1, -(-(game.season_bounds()[1] - game.now()) // 86400))
    season = views.season_line(game.season(), days_left)
    text = views.home(ctx.repo.totals(), ctx.chat_id, live_now(game, ctx.chat_id), today, season)
    return text, keyboards.home(ctx.is_admin)


def hall(ctx: Ctx) -> Screen:
    pics = ctx.repo.top_rated(10)
    record = ctx.repo.meta_int(f"streak_record:{ctx.chat_id}")
    return views.hall(pics, ctx.labels(pics), record), keyboards.hall([pic.id for pic in pics])


def bottom(ctx: Ctx) -> Screen:
    pics = ctx.repo.bottom_rated(10)
    return views.bottom(pics, ctx.labels(pics)), keyboards.bottom([pic.id for pic in pics])


def grave(ctx: Ctx) -> Screen:
    pics = ctx.repo.graveyard(5)
    text = views.graveyard(ctx.repo.count_pics("executed"), pics, ctx.labels(pics), ctx.game.now())
    if pics:
        price = views.num(ctx.game.price("resurrect"))
        text += f"\n\n<i>Кнопка с номером — воскресить за {price} монет, нажать дважды</i>"
    return text, keyboards.graveyard([pic.id for pic in pics], ctx.is_admin)


def top(ctx: Ctx) -> Screen:
    board, _, period = (ctx.arg or "").partition(":")
    board = board if board in BOARDS else "uploads"
    week = period == "w" and board in keyboards.WEEKLY_BOARDS
    if board == "season":
        raw = ctx.game.season_top(10)
    else:
        raw = ctx.repo.top_users(board, since=ctx.game.now() - 7 * 86400 if week else None)
    rows = [(ctx.repo.user_label(user), value) for user, value in raw]
    return views.top(board, rows, week), keyboards.tops(board, week)


def seasons_screen(ctx: Ctx) -> Screen:
    game = ctx.game
    live = [(ctx.repo.user_label(user), score) for user, score in game.season_top(3)]
    past = [
        (season, [(ctx.repo.user_label(user), score) for user, score in podium])
        for season, podium in ctx.repo.podiums(6)
    ]
    return views.seasons_hall(game.season(), live, past), keyboards.markup(keyboards.back("m:top:season"))


def me(ctx: Ctx) -> Screen:
    game, repo, user_id = ctx.game, ctx.repo, ctx.user_id
    now = game.now()
    stats = repo.user_stats(user_id, game.night_hours_utc, game.tz_offset_hours, now)
    ranking = [uid for uid, _ in repo.top_users("uploads", limit=1000)]
    coins, earned, _ = repo.player(user_id)
    spouse = repo.spouse_of(user_id)
    nemesis = repo.nemesis(user_id)
    streak = repo.counter(user_id, "active_streak")
    if repo.counter(user_id, "last_active_day") < game.local_day() - 1:
        streak = 0  # the streak burnt out
    wallet = views.Wallet(
        coins=coins,
        earned=earned,
        streak=streak,
        right_guesses=repo.counter(user_id, "right_guesses"),
        wrong_guesses=repo.counter(user_id, "wrong_guesses"),
        nemesis=(repo.user_label(nemesis[0]), nemesis[1]) if nemesis else None,
        crowns=tuple(game.crowns_of(user_id)),
        spouse=(repo.user_label(spouse[0]), (now - spouse[1]) // 86400) if spouse else None,
        title=repo.title_of(user_id),
        chests=game.chests_of(user_id),
        jailed=max(0, repo.counter(user_id, "jail_until") - now),
        season=(game.season(), *game.season_standing(user_id)),
        podiums=tuple(repo.podiums_of(user_id)),
        casino=repo.casino_stats(user_id),
        best_pic=best_pic(repo, user_id),
        records=records(repo, user_id),
    )
    text = views.profile(
        repo.user_label(user_id),
        stats,
        repo.achievements_of(user_id),
        ranking.index(user_id) + 1 if user_id in ranking else None,
        wallet,
        repo.achievement_owners(),
        max(1, repo.count_users()),
    )
    best = best_pic(repo, user_id)
    return text, keyboards.profile(best[0] if best else None)


RECORDS = (
    ("best_daily_streak", "Бонус дня подряд"),
    ("best_active_streak", "Дней подряд на складе"),
    ("hl_best", "Серия в «Выше-ниже»"),
    ("caption_wins", "Побед в «Подпиши пикчу»"),
    ("whose_right", "Угадано в «Чья пикча?»"),
)


def records(repo, user_id: int) -> tuple[tuple[str, int], ...]:
    counters = repo.counters_of(user_id)
    return tuple((what, counters[key]) for key, what in RECORDS if counters.get(key, 0) > 1)


def best_pic(repo, user_id: int) -> tuple[str, float, int, int] | None:
    pics = repo.pics_of(user_id, limit=1)
    if not pics or pics[0] is None:
        return None
    return pics[0].id, pics[0].rating, pics[0].wins, pics[0].losses


def games(ctx: Ctx) -> Screen:
    return views.GAMES_SCREEN, keyboards.games_menu()


def people(ctx: Ctx) -> Screen:
    return views.PEOPLE_SCREEN, keyboards.people_menu()


def casino_screen(ctx: Ctx) -> Screen:
    game = ctx.game
    mode, value = game.stake_mode(ctx.user_id)
    text = views.casino_screen(
        ctx.repo.user_label(ctx.user_id),
        ctx.repo.player(ctx.user_id)[0],
        game.stake_for_play(ctx.user_id),
        ctx.chat_id,
        game.day_is("lucky_day"),
        mode,
        value,
    )
    current = {"all": "all", "share": f"p{value}"}.get(mode, "")
    return text, keyboards.casino_menu(casino.STAKE_SHARES, current)


def shop(ctx: Ctx) -> Screen:
    prices = {item: ctx.game.price(item) for item in SHOP_ITEMS}
    prices["bounty"] = ctx.game.bounty_amounts()[0]
    balance = ctx.repo.player(ctx.user_id)[0]
    text = views.shop_screen(
        ctx.repo.user_label(ctx.user_id), balance, prices, ctx.chat_id, ctx.game.day_event(), ctx.game.wealth()
    )
    return text, keyboards.shop_menu()


def daily_ready(game: Game, user_id: int) -> bool:
    return game.repo.counter(user_id, "daily_day") != game.local_day()


def quests_markup(game: Game, user_id: int, chat_id: int | None = None) -> InlineKeyboardMarkup | None:
    """chat_id for the ephemeral version: its buttons carry the chat and it has no "back"."""
    markup = keyboards.quests_menu(daily_ready(game, user_id), game.chests_of(user_id), chat_id)
    return markup if markup.inline_keyboard else None


def quests(ctx: Ctx) -> Screen:
    game, user_id = ctx.game, ctx.user_id
    daily, weekly = game.quests_of(user_id)
    text = views.quests_screen(
        ctx.repo.user_label(user_id),
        daily,
        weekly,
        game.chests_of(user_id),
        daily_ready(game, user_id),
        ctx.repo.counter(user_id, "daily_streak"),
        ctx.chat_id,
    )
    return text, quests_markup(game, user_id) or keyboards.markup(keyboards.back())


def help_screen(ctx: Ctx) -> Screen:
    return ui.HELP, keyboards.markup(keyboards.back())


def upload(ctx: Ctx) -> Screen:
    return views.upload_hub(ctx.is_private), keyboards.upload_hub(ctx.is_private)


def admin(ctx: Ctx) -> Screen:
    if not ctx.is_admin:
        return home(ctx)
    text = views.admin(ctx.repo.totals(), ctx.repo.count_users(), str(ctx.repo.database_path))
    events_on = None if ctx.is_private else ctx.repo.chat_events_on(ctx.chat_id)
    return text, keyboards.admin(events_on)


SCREENS: dict[str, Callable[[Ctx], Screen]] = {
    "home": home,
    "hall": hall,
    "bottom": bottom,
    "grave": grave,
    "top": top,
    "seasons": seasons_screen,
    "me": me,
    "games": games,
    "people": people,
    "casino": casino_screen,
    "shop": shop,
    "quests": quests,
    "help": help_screen,
    "up": upload,
    "adm": admin,
}


def render(name: str, ctx: Ctx) -> Screen:
    return SCREENS.get(name, home)(ctx)


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
        kind = "Рейд" if boss["raid"] else "Босс"
        lines.append(f"👹 {kind} · {boss['hp']}/{boss['max_hp']} · ещё {views.timer(boss['ends_at'] - now)}")
    if game.repo.active_challenge_battle(chat_id):
        lines.append("🤺 Идёт вызов")
    return lines

"""The player card."""

from html import escape
from dataclasses import dataclass

from bot.core import achievements as rules
from bot.core import economy, seasons
from bot.db.repo import UserStats
from bot.texts import tops as top_texts
from bot.texts.achievements import ACHIEVEMENTS
from bot.texts.pick import pick
from bot.tg.ui.views.layout import bare, money, note, num, plural, rating, who
from bot.tg.ui.views.seasons import points, season_badges


@dataclass(frozen=True)
class Wallet:
    coins: int
    earned: int
    streak: int  # days in a row with any vote or reaction
    right_guesses: int = 0
    wrong_guesses: int = 0
    nemesis: tuple[str, int] | None = None  # (name, defeats)
    crowns: tuple[str, ...] = ()
    spouse: tuple[str, int] | None = None  # (name, days)
    title: str | None = None
    chests: dict[str, int] | None = None
    jailed: int = 0  # seconds left
    season: tuple[str, int, int | None] | None = None  # (season, score, place) of the running month
    podiums: tuple[tuple[str, int], ...] = ()  # (season, place) of every podium, latest first
    casino: tuple[int, int, int, int] | None = None  # (bets, staked, returned, biggest single win)
    best_pic: tuple[str, float, int, int] | None = None  # (pic id, rating, wins, losses)
    records: tuple[tuple[str, int], ...] = ()  # (what, best value), only the ones above zero


def profile(
    label: str,
    stats: UserStats,
    owned: set[str],
    place: int | None,
    wallet: Wallet,
    owners: dict[str, int],
    players: int,
) -> str:
    """The player card: who you are, then one block per side of the game; blocks that would be
    empty are left out."""
    blocks = [
        identity(label, wallet),
        level_progress(wallet),
        pocket(wallet),
        statuses(wallet),
        season_block(wallet),
        storage(stats, place, wallet),
        uploader_title(stats),
        arena_and_courts(stats, wallet),
        casino_block(wallet),
        records(wallet),
        *achievements(owned, owners, players),
        [note(escape(pick(top_texts.PROFILE_ROASTS)))],
    ]
    return "\n\n".join("\n".join(block) for block in blocks if block)


def identity(label: str, wallet: Wallet) -> list[str]:
    level = economy.level_for(wallet.earned)
    title = [f"🏷 «{escape(wallet.title)}»"] if wallet.title else []
    return [f"👤 <b>{who(label)}</b>", *title, f"<i>{escape(level.name)} · уровень {level.index + 1} из {len(economy.LEVELS)}</i>"]


def level_progress(wallet: Wallet) -> list[str]:
    upcoming = economy.next_level(wallet.earned)
    if not upcoming:
        return []
    return [
        f"<code>{economy.progress(wallet.earned)}</code>  {num(wallet.earned)} / {num(upcoming.threshold)}",
        f"<i>дальше — {escape(bare(upcoming.name))}</i>",
    ]


def pocket(wallet: Wallet) -> list[str]:
    lines = [f"🪙 {money(wallet.coins)}"]
    if wallet.streak > 1:
        lines.append(f"🔥 {wallet.streak} {plural(wallet.streak, 'день', 'дня', 'дней')} подряд на складе")
    total = sum(count for count in (wallet.chests or {}).values() if count)
    if total:
        lines.append(
            f"🎁 {total} {plural(total, 'сундук', 'сундука', 'сундуков')} {plural(total, 'ждёт', 'ждут', 'ждут')} в /quests"
        )
    return lines


def statuses(wallet: Wallet) -> list[str]:
    lines = []
    for kind in wallet.crowns:
        badge, crown = economy.CROWNS[kind]
        lines.append(f"{badge} {escape(crown)}")
    if wallet.spouse:
        name, days_married = wallet.spouse
        lines.append(f"💍 В браке с <b>{who(name)}</b> · {days_married} {plural(days_married, 'день', 'дня', 'дней')}")
    if wallet.jailed:
        lines.append(f"🚔 В обезьяннике ещё {wallet.jailed // 60 + 1} мин")
    return lines


def season_block(wallet: Wallet) -> list[str]:
    if not wallet.season or not (wallet.season[1] or wallet.podiums):
        return []
    season, score, standing = wallet.season
    where = f" · {standing}-е место" if standing else ""
    return [f"🏆 <b>Сезон</b> · {escape(seasons.name(season))}", f"📊 {points(score)}{where}",
            *season_badges(list(wallet.podiums))]


def storage(stats: UserStats, place: int | None, wallet: Wallet) -> list[str]:
    rank = f" · {place}-е место" if place else ""
    alive = "все живы" if stats.pics_alive == stats.uploads else f"живых {stats.pics_alive}"
    lines = [
        f"📦 <b>Склад</b>{rank}",
        f"🖼 <b>{stats.uploads}</b> {plural(stats.uploads, 'пикча', 'пикчи', 'пикч')} · {alive}"
        + (f" · казнено {stats.pics_executed}" if stats.pics_executed else ""),
        f"🤙🏻 <b>{stats.likes_received}</b> {plural(stats.likes_received, 'лайк', 'лайка', 'лайков')}"
        f" · <b>{stats.dislikes_received}</b> {plural(stats.dislikes_received, 'дизлайк', 'дизлайка', 'дизлайков')}",
    ]
    if stats.legends or stats.best_streak > 1:
        lines.append(f"🏛 В зале славы: <b>{stats.legends}</b> · серия <b>{stats.best_streak}</b>")
    if wallet.best_pic:
        _, best_rating, wins, losses = wallet.best_pic
        lines.append(f"⭐ Лучшая пикча: <b>{rating(best_rating)}</b> · {wins}–{losses}")
    return lines


def uploader_title(stats: UserStats) -> list[str]:
    """The uploader title: its own item, «📦 <b>Title</b>» over the way to the next one."""
    title_code = rules.upload_title_code(stats.uploads)
    if not title_code:
        return []
    badge, _, name = ACHIEVEMENTS[title_code][0].partition(" ")
    goal = rules.next_upload_goal(stats.uploads)
    if goal is None:
        return [f"{badge} <b>{escape(name)}</b>", "<i>высший титул загрузчика</i>"]
    left = goal.threshold - stats.uploads
    upcoming = escape(bare(ACHIEVEMENTS[goal.code][0]))
    return [f"{badge} <b>{escape(name)}</b>", f"<i>до «{upcoming}» ещё {left} {plural(left, 'пикча', 'пикчи', 'пикч')}</i>"]


def arena_and_courts(stats: UserStats, wallet: Wallet) -> list[str]:
    voice = economy.people_voice(wallet.right_guesses, wallet.wrong_guesses)
    if not (voice or wallet.nemesis or stats.kill_votes or stats.spare_votes):
        return []
    lines = ["⚔️ <b>Арена и суды</b>"]
    if stats.kill_votes or stats.spare_votes:
        lines.append(f"⚖️ За казнь — <b>{stats.kill_votes}</b> · за помилование — <b>{stats.spare_votes}</b>")
    if voice:
        lines.append(f"🎯 <b>{voice[0]}%</b> угаданных · {escape(bare(voice[1]))}")
    if wallet.nemesis:
        name, defeats = wallet.nemesis
        lines.append(
            f"😈 немезида — <b>{who(name)}</b> · {defeats} "
            f"{plural(defeats, 'поражение', 'поражения', 'поражений')} твоих пикч"
        )
    return lines


def casino_block(wallet: Wallet) -> list[str]:
    if not wallet.casino or not wallet.casino[0]:
        return []
    bets, staked, returned, biggest = wallet.casino
    net = returned - staked
    result = f"плюс {money(net)}" if net > 0 else f"минус {money(-net)}" if net < 0 else "по нулям"
    lines = ["🎰 <b>Казино</b>", f"<b>{num(bets)}</b> {plural(bets, 'ставка', 'ставки', 'ставок')} · {result}"]
    if biggest:
        lines.append(f"<i>лучший выигрыш — {num(biggest)}</i>")
    return lines


def records(wallet: Wallet) -> list[str]:
    if not wallet.records:
        return []
    return ["📈 <b>Рекорды</b>", *(f"{escape(what)} — <b>{num(value)}</b>" for what, value in wallet.records)]


def achievements(owned: set[str], owners: dict[str, int], players: int) -> list[list[str]]:
    """The showcase block and, in a box of its own, the whole collection with how rare each is."""
    hidden = len(rules.SECRET - owned)
    secret = f" · ещё {hidden} {plural(hidden, 'секретная', 'секретные', 'секретных')}" if hidden else ""
    head = f"🏅 <b>Ачивки</b> · {len(owned)} из {len(rules.ALL_CODES)}"
    if not owned:
        return [[head, f"<i>Пока ни одной{secret}. Проголосуй в дуэли — это уже начало</i>"]]
    listing = [f"Вся коллекция · % — у скольких она есть{secret}"]
    for tier, heading in ((rules.LEGENDARY, "🌟 Легендарные"), ("rare", "✨ Редкие"), ("common", "▫️ Обычные")):
        codes = sorted(code for code in owned if rules.rarity(code) == tier)
        if codes:
            listing += ["", heading]
            listing += [f"{ACHIEVEMENTS[code][0]} · {round(100 * owners.get(code, 1) / players)}%" for code in codes]
    showcase = [escape(ACHIEVEMENTS[code][0]) for code in rules.showcase(owned, owners)]
    return [[head, *showcase], [f"<blockquote expandable>{escape(chr(10).join(listing))}</blockquote>"]]

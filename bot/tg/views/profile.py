"""The player card."""

from html import escape
from dataclasses import dataclass

from bot.core import achievements as rules
from bot.core import economy, seasons
from bot.db.repo import UserStats
from bot.texts import tops as top_texts
from bot.texts.achievements import ACHIEVEMENTS
from bot.texts.pick import pick
from bot.tg.views.layout import bare, money, num, plural, rating, who
from bot.tg.views.seasons import points, season_badges


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
    level = economy.level_for(wallet.earned)
    upcoming = economy.next_level(wallet.earned)
    lines = [f"👤 <b>{who(label)}</b>"]
    if wallet.title:
        lines.append(f"🏷 «{escape(wallet.title)}»")
    lines += [f"<i>{escape(level.name)} · уровень {level.index + 1} из {len(economy.LEVELS)}</i>", ""]
    if upcoming:
        lines += [
            f"<code>{economy.progress(wallet.earned)}</code>  {num(wallet.earned)} / {num(upcoming.threshold)}",
            f"<i>дальше — {escape(bare(upcoming.name))}</i>",
            "",
        ]
    lines.append(f"🪙 {money(wallet.coins)}")
    if wallet.streak > 1:
        lines.append(f"🔥 {wallet.streak} {plural(wallet.streak, 'день', 'дня', 'дней')} подряд на складе")
    owned_chests = [(tier, count) for tier, count in (wallet.chests or {}).items() if count]
    if owned_chests:
        total = sum(count for _, count in owned_chests)
        lines.append(
            f"🎁 {total} {plural(total, 'сундук', 'сундука', 'сундуков')} {plural(total, 'ждёт', 'ждут', 'ждут')} в /quests"
        )
    statuses = []
    for kind in wallet.crowns:
        badge, crown = economy.CROWNS[kind]
        statuses.append(f"{badge} {escape(crown)}")
    if wallet.spouse:
        name, days_married = wallet.spouse
        statuses.append(f"💍 В браке с <b>{who(name)}</b> · {days_married} {plural(days_married, 'день', 'дня', 'дней')}")
    if wallet.jailed:
        statuses.append(f"🚔 В обезьяннике ещё {wallet.jailed // 60 + 1} мин")
    if statuses:
        lines += ["", *statuses]

    if wallet.season and (wallet.season[1] or wallet.podiums):
        season, score, standing = wallet.season
        where = f" · {standing}-е место" if standing else ""
        lines += ["", f"🏆 <b>Сезон</b> · {escape(seasons.name(season))}", f"{points(score)}{where}"]
        lines += season_badges(list(wallet.podiums))

    rank = f" · {place}-е место" if place else ""
    lines += ["", f"📦 <b>Склад</b>{rank}"]
    alive = "все живы" if stats.pics_alive == stats.uploads else f"живых {stats.pics_alive}"
    lines.append(
        f"<b>{stats.uploads}</b> {plural(stats.uploads, 'пикча', 'пикчи', 'пикч')} · {alive}"
        + (f" · казнено {stats.pics_executed}" if stats.pics_executed else "")
    )
    lines.append(
        f"🤙🏻 <b>{stats.likes_received}</b> {plural(stats.likes_received, 'лайк', 'лайка', 'лайков')}"
        f" · <b>{stats.dislikes_received}</b> {plural(stats.dislikes_received, 'дизлайк', 'дизлайка', 'дизлайков')}"
    )
    if stats.legends or stats.best_streak > 1:
        lines.append(f"🏛 В зале славы: <b>{stats.legends}</b> · серия <b>{stats.best_streak}</b>")
    if wallet.best_pic:
        _, best_rating, wins, losses = wallet.best_pic
        lines.append(f"⭐ Лучшая пикча: <b>{rating(best_rating)}</b> · {wins}–{losses}")
    title_code = rules.upload_title_code(stats.uploads)
    goal = rules.next_upload_goal(stats.uploads)
    if title_code:  # the uploader title: its own item, "📦 <b>Title</b>" over the way to the next one
        badge, _, name = ACHIEVEMENTS[title_code][0].partition(" ")
        lines += ["", f"{badge} <b>{escape(name)}</b>"]
        if goal:
            left = goal.threshold - stats.uploads
            lines.append(
                f"<i>до «{escape(bare(ACHIEVEMENTS[goal.code][0]))}» ещё {left} {plural(left, 'пикча', 'пикчи', 'пикч')}</i>"
            )
        else:
            lines.append("<i>высший титул загрузчика</i>")

    voice = economy.people_voice(wallet.right_guesses, wallet.wrong_guesses)
    if voice or wallet.nemesis or stats.kill_votes or stats.spare_votes:
        lines += ["", "⚔️ <b>Арена и суды</b>"]
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

    if wallet.casino and wallet.casino[0]:
        bets, staked, returned, biggest = wallet.casino
        net = returned - staked
        result = f"плюс {money(net)}" if net > 0 else f"минус {money(-net)}" if net < 0 else "по нулям"
        lines += ["", "🎰 <b>Казино</b>", f"<b>{num(bets)}</b> {plural(bets, 'ставка', 'ставки', 'ставок')} · {result}"]
        if biggest:
            lines.append(f"<i>лучший выигрыш — {num(biggest)}</i>")

    if wallet.records:
        lines += ["", "📈 <b>Рекорды</b>"]
        lines += [f"{escape(what)} — <b>{num(value)}</b>" for what, value in wallet.records]

    hidden = len(rules.SECRET - owned)
    secret = f" · ещё {hidden} {plural(hidden, 'секретная', 'секретные', 'секретных')}" if hidden else ""
    lines += ["", f"🏅 <b>Ачивки</b> · {len(owned)} из {len(rules.ALL_CODES)}"]
    if owned:
        lines += [escape(ACHIEVEMENTS[code][0]) for code in rules.showcase(owned, owners)]
        lines.append("")  # the collection is a box of its own, not one more line of the showcase
        listing = [f"Вся коллекция · % — у скольких она есть{secret}"]
        for tier, heading in ((rules.LEGENDARY, "🌟 Легендарные"), ("rare", "✨ Редкие"), ("common", "▫️ Обычные")):
            codes = sorted(code for code in owned if rules.rarity(code) == tier)
            if codes:
                listing += ["", heading]
                for code in codes:
                    share = round(100 * owners.get(code, 1) / players)
                    listing.append(f"{ACHIEVEMENTS[code][0]} · {share}%")
        lines.append(f"<blockquote expandable>{escape(chr(10).join(listing))}</blockquote>\n")
    else:
        lines += [f"<i>Пока ни одной{secret}. Проголосуй в дуэли — это уже начало</i>", ""]
    lines.append(f"<i>{escape(pick(top_texts.PROFILE_ROASTS))}</i>")
    return "\n".join(lines)

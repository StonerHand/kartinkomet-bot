"""The player card."""

from html import escape
from dataclasses import dataclass

from bot.core import achievements as rules
from bot.core import economy
from bot.db.repo import UserStats
from bot.texts import tops as top_texts
from bot.texts.achievements import ACHIEVEMENTS
from bot.texts.pick import pick
from bot.tg.views.layout import bare, money, num, plural, who


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
    lines = [f"👤 <b>{who(label).upper()}</b>"]
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
        names = {"wood": "деревянных", "rare": "редких", "legend": "легендарных"}
        lines.append("🎁 Сундуки: " + " · ".join(f"{names[tier]} {count}" for tier, count in owned_chests))
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
        lines.append(f"🏛 <b>{stats.legends}</b> в зале славы · 🔥 лучшая серия <b>{stats.best_streak}</b>")
    title_code = rules.upload_title_code(stats.uploads)
    goal = rules.next_upload_goal(stats.uploads)
    if title_code and goal:
        left = goal.threshold - stats.uploads
        lines.append(
            f"<i>Титул «{escape(bare(ACHIEVEMENTS[title_code][0]))}», до «{escape(bare(ACHIEVEMENTS[goal.code][0]))}» "
            f"ещё {left} {plural(left, 'пикча', 'пикчи', 'пикч')}</i>"
        )
    elif title_code:
        lines.append(f"<i>{escape(ACHIEVEMENTS[title_code][0])}</i>")

    voice = economy.people_voice(wallet.right_guesses, wallet.wrong_guesses)
    if voice or wallet.nemesis or stats.kill_votes or stats.spare_votes:
        lines += ["", "⚔️ <b>Арена и суды</b>"]
        if stats.kill_votes or stats.spare_votes:
            lines.append(f"🪓 казнил <b>{stats.kill_votes}</b> · 🕊 спас <b>{stats.spare_votes}</b>")
        if voice:
            lines.append(f"🎯 Угадываешь в <b>{voice[0]}%</b> боёв · {escape(bare(voice[1]))}")
        if wallet.nemesis:
            name, defeats = wallet.nemesis
            lines.append(
                f"😈 немезида — <b>{who(name)}</b> · {defeats} "
                f"{plural(defeats, 'поражение', 'поражения', 'поражений')} твоих пикч"
            )

    hidden = len(rules.SECRET - owned)
    secret = f" · ещё {hidden} {plural(hidden, 'секретная', 'секретные', 'секретных')}" if hidden else ""
    lines += ["", f"🏅 <b>Ачивки</b> · {len(owned)} из {len(rules.ALL_CODES)}{secret}"]
    if owned:
        lines += [escape(ACHIEVEMENTS[code][0]) for code in rules.showcase(owned, owners)]
        listing = ["Вся коллекция · у скольких есть"]
        for tier, heading in ((rules.LEGENDARY, "🌟 Легендарные"), ("rare", "✨ Редкие"), ("common", "▫️ Обычные")):
            codes = sorted(code for code in owned if rules.rarity(code) == tier)
            if codes:
                listing += ["", heading]
                for code in codes:
                    share = round(100 * owners.get(code, 1) / players)
                    listing.append(f"{ACHIEVEMENTS[code][0]} · {share}%")
        lines.append(f"<blockquote expandable>{escape(chr(10).join(listing))}</blockquote>\n")
    else:
        lines += ["<i>Пока ни одной. Проголосуй в дуэли — это уже начало</i>", ""]
    lines.append(f"<i>{escape(pick(top_texts.PROFILE_ROASTS))}</i>")
    return "\n".join(lines)

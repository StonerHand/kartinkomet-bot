"""Casino screen and results."""

from html import escape

from bot.core import casino
from bot.services.casino import CasinoResult
from bot.texts import casino as casino_texts
from bot.texts.pick import pick
from bot.tg.views.layout import card, money, num, who


def stake_words(mode: str, value: int, stake: int) -> str:
    """'10% · 111 монет', 'ва-банк · 1 111 монет', '300 монет'."""
    if mode == "all":
        return f"ва-банк · {money(stake)}"
    if mode == "share":
        return f"{value}% · {money(stake)}"
    return money(stake)


def casino_screen(
    label: str, balance: int, stake: int, chat_id: int, lucky: bool, mode: str = "fixed", value: int = 0
) -> str:
    games = [
        f"{game.emoji} <b>{game.name}</b> · /{game.command}\n<i>{escape(casino_texts.RULES[game.code])}</i>"
        for game in casino.GAMES.values()
    ]
    return card(
        "🎰 <b>КАЗИНО</b>",
        pick(casino_texts.HEADERS, chat_id),
        [
            f"💼 <b>{who(label)}</b>: {money(balance)}",
            f"🎟 Ставка: {stake_words(mode, value, stake)}",
            "🍀 <b>Счастливый день:</b> выигрыши ×1.5" if lucky else "",
        ],
        *games,
        "<i>Ставка у каждого своя: кнопки с процентами и «ва-банк» меняют её тому, кто нажал. "
        "Своей суммой — /spin 300, /dice все</i>",
        "🤝 <b>1 на 1</b> · /pvp\n<i>Кости, дартс или боулинг против человека, без казино: /pvp 200 дартс</i>",
    )


def casino_title(game: str, kind: str) -> str:
    return casino_texts.TITLES.get(f"{game}:{kind}") or casino_texts.TITLES.get(kind, kind)


def casino_result(label: str, result: CasinoResult, values: tuple[int, ...], chat_id: int) -> str:
    if result.profit > 0:
        pool = casino_texts.BIG_WIN if result.profit >= result.stake * 5 else casino_texts.WIN
        verdict = f"🪙 +{money(result.profit)}"
    elif result.payout == result.stake:
        pool, verdict = casino_texts.DRAW, "↩️ Ставка вернулась"
    elif result.payout > 0:
        pool, verdict = casino_texts.REFUND, f"↩️ Вернулось <b>{num(result.payout)}</b> из {num(result.stake)}"
    else:
        pool, verdict = casino_texts.LOSE, f"🪙 −{money(result.stake)}"
    return card(
        f"<b>{casino_title(result.game, result.roll.kind)}</b> · {who(label)}",
        pick(pool, chat_id),
        [
            f"🎲 Ты: <b>{values[0]}</b> · бот: <b>{values[1]}</b>" if result.game == "dice" else "",
            f"{verdict} · баланс <b>{num(result.balance)}</b>",
        ],
    )

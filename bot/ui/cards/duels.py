"""Board duels on a stake: rock-paper-scissors and tic-tac-toe."""

from bot.rules import duels
from bot.texts import duels as texts
from bot.texts.pick import pick, steady
from bot.ui.cards.arena import score_line
from bot.ui.layout import card, money, note, timer, who


def duel_head(game: str, detail: str) -> str:
    info = duels.BOARD_GAMES[game]
    return f"{info.emoji} <b>{info.name}</b> · {detail}"


def rps_card(names: tuple[str, str], picked: tuple[bool, bool], remaining: int, rounds: int,
             last: list[int] | None, challenge_id: str = "") -> str:
    again = f"🔁 Раунд {rounds}: оба выбрали {duels.RPS_NAMES[last[0]]}" if rounds > 1 and last else ""
    return card(
        duel_head("rps", f"<b>{timer(remaining)}</b>"),
        steady(texts.RPS_FLAVOUR, challenge_id),
        again,
        [f"{'✅' if done else '▫️'} <b>{who(name)}</b> · {'выбор сделан' if done else 'думает'}"
         for name, done in zip(names, picked)],
        note(f"Жми камень, ножницы или бумагу — выбор видишь только ты. Камень бьёт ножницы, ножницы — бумагу, "
             f"бумага — камень. Не выбрать за {duels.RPS_SECONDS // 60} минуты — проиграть"),
    )


def rps_result(names: tuple[str, str], picks: list[int] | None, winner: str | None, pot: int,
               late: str | None, score: tuple[int, int], chat_id: int) -> str:
    shown = [f"{duels.RPS[pick_]} <b>{who(name)}</b> · {duels.RPS_NAMES[pick_]}" for name, pick_ in zip(names, picks)] \
        if picks else []
    return card(
        duel_head("rps", "итог"),
        pick(texts.RPS_RESULT if winner else texts.DUEL_DRAW, chat_id),
        shown,
        f"⏰ У <b>{who(late)}</b> кончилось время" if late else "",
        f"🏆 <b>{who(winner)}</b> забирает {money(pot)}" if winner else "↩️ Ставки вернулись",
        score_line(score),
    )


def ttt_card(names: tuple[str, str], turn: int, remaining: int, challenge_id: str = "") -> str:
    """turn: 0 — the challenger (X) moves, 1 — the opponent (O)."""
    return card(
        duel_head("ttt", f"<b>{timer(remaining)}</b>"),
        steady(texts.TTT_FLAVOUR, challenge_id),
        [f"❌ <b>{who(names[0])}</b>", f"⭕ <b>{who(names[1])}</b>"],
        f"👉 Ход: <b>{who(names[turn])}</b>",
        note(f"Жми клетку на доске. На ход — {duels.TTT_MOVE_SECONDS} секунд, время вышло — партия проиграна. "
             f"Три в ряд по горизонтали, вертикали или диагонали — банк твой"),
    )


def ttt_result(names: tuple[str, str], winner: str | None, pot: int, late: str | None,
               score: tuple[int, int], chat_id: int) -> str:
    return card(
        duel_head("ttt", "итог"),
        pick(texts.TTT_RESULT if winner else texts.DUEL_DRAW, chat_id),
        [f"❌ <b>{who(names[0])}</b>", f"⭕ <b>{who(names[1])}</b>"],
        f"⏰ У <b>{who(late)}</b> кончилось время" if late else "",
        f"🏆 <b>{who(winner)}</b> забирает {money(pot)}" if winner else "↩️ Ничья — ставки вернулись",
        score_line(score),
    )

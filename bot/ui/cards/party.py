"""Games about the people in the chat: the "who of us" poll, the bomb, bets on life."""

from html import escape

from bot.rules import party
from bot.texts import party as texts
from bot.texts.pick import pick, steady
from bot.ui.layout import MEDALS, bar, card, money, note, num, plural, timer, who


def votes_word(count: int) -> str:
    return plural(count, "голос", "голоса", "голосов")


# ── who of us ─────────────────────────────────────────────────────────


def who_card(question: str, people: list[str], counts: list[int], remaining: int, price: int,
             round_id: str = "") -> str:
    """The poll while it runs: the question, the people with their votes so far. price: what a
    question of one's own costs."""
    leader = max(counts, default=0)
    lines = [f"▫️ {who(name)} · <b>{count}</b>{bar(count, leader)}" for name, count in zip(people, counts)]
    return card(
        f"🗳 <b>Кто из нас</b> · <b>{timer(remaining)}</b>",
        steady(texts.WHO_FLAVOUR, round_id),
        f"❓ <b>{escape(question)}</b>",
        lines if sum(counts) else "",
        note(f"Жми на человека, голос можно поменять. Победитель носит титул сутки, каждому "
             f"проголосовавшему — монеты. Свой вопрос — /who и текст, {money(price)}"),
    )


def who_result(question: str, title: str, people: list[str], counts: list[int], winners: list[str], chat_id: int) -> str:
    ranked = sorted(zip(people, counts), key=lambda item: -item[1])
    lines = []
    for index, (name, count) in enumerate(item for item in ranked if item[1]):
        place = MEDALS[index] if index < len(MEDALS) else f"{index + 1}."
        lines.append(f"{place} {who(name)} · {count} {votes_word(count)}")
    if winners:
        crowned = ", ".join(f"<b>{who(name)}</b>" for name in winners)
        verdict = f"👑 {crowned} — «{escape(title)}» на сутки"
        flavour = pick(texts.WHO_RESULT, chat_id)
    else:
        verdict, flavour = "", pick(texts.WHO_NOBODY, chat_id)
    return card("🗳 <b>Кто из нас</b> · итог", flavour, f"❓ <b>{escape(question)}</b>", lines, verdict)


# ── the bomb ──────────────────────────────────────────────────────────


def bomb_card(holder: str, remaining: int, passes: int, round_id: str = "") -> str:
    return card(
        f"💣 <b>Бомба</b> · <b>{timer(remaining)}</b>",
        steady(texts.BOMB_FLAVOUR, round_id, holder),
        f"🔥 Бомба у <b>{who(holder)}</b>",
        f"🔁 Передач: <b>{passes}</b>" if passes else "",
        note(texts.BOMB_HINT),
    )


def bomb_result(victim: str, fine: int, passers: list[str], reward: int, chat_id: int) -> str:
    return card(
        "💥 <b>Бомба</b> · взрыв",
        pick(texts.BOMB_BOOM, chat_id),
        [f"💀 <b>{who(victim)}</b>" + (f" · −{money(fine)}" if fine else ""), "🏷 «Жертва бомбы» на сутки"],
        [f"🏃 <b>Передали</b> · +{money(reward)}", ", ".join(who(name) for name in passers)]
        if passers and reward else "",
    )


# ── bets on life ──────────────────────────────────────────────────────


def bet_lines(stakes: list[tuple[str, int, int]]) -> list[str]:
    """(name, side, coins) → the two sides with their pools."""
    lines = []
    for side, mark, label in ((1, "✅", "Сбудется"), (0, "❌", "Не сбудется")):
        mine = [(name, coins) for name, chosen, coins in stakes if chosen == side]
        if mine:
            pool = sum(coins for _, coins in mine)
            lines.append(f"{mark} <b>{label}</b> · {money(pool)}")
            lines.extend(f"▫️ {who(name)} · {num(coins)}" for name, coins in mine)
    return lines


def bet_card(claim: str, author: str, stakes: list[tuple[str, int, int]], days_left: int, round_id: str = "") -> str:
    return card(
        "🤝 <b>Спор</b> · " + who(author),
        steady(texts.BET_FLAVOUR, round_id),
        f"📜 <b>{escape(claim)}</b>",
        bet_lines(stakes),
        note(f"Ставь на «сбудется» или «не сбудется», ставка одна. Автор спора решает, чем кончилось, "
             f"и сам не ставит. Победители делят ставки проигравших. Не решит за "
             f"{days_left} {plural(days_left, 'день', 'дня', 'дней')} — ставки вернутся"),
    )


def bet_result(claim: str, author: str, outcome: int, stakes: list[tuple[str, int, int]],
               payouts: dict[str, int], chat_id: int) -> str:
    if outcome == -1:
        head, flavour = "🤝 <b>Спор</b> · отменён", pick(texts.BET_CALLED_OFF, chat_id)
    elif outcome == 1:
        head, flavour = "🤝 <b>Спор</b> · сбылось", pick(texts.BET_CAME_TRUE, chat_id)
    else:
        head, flavour = "🤝 <b>Спор</b> · не сбылось", pick(texts.BET_DID_NOT, chat_id)
    staked = {name: coins for name, _, coins in stakes}
    won = [(name, coins) for name, coins in payouts.items() if coins > staked.get(name, 0)]
    lines = [f"💰 <b>{who(name)}</b> · +{money(coins - staked.get(name, 0))}" for name, coins in
             sorted(won, key=lambda item: -item[1])]
    if outcome != -1 and not won and stakes:
        lines = ["🤷 Спорить было не с кем: ставки вернулись"]
    return card(head, flavour, f"📜 <b>{escape(claim)}</b> · {who(author)}", lines)


def bet_hint(claim_max: int = party.BET_CLAIM_MAX) -> str:
    return card(
        "🤝 <b>Спор</b>",
        "О чём спорим?",
        "✍️ Напиши /bet и сам спор",
        note(f"Например: /bet в пятницу половина чата проспит. До {claim_max} символов"),
    )

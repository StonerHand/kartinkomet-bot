"""Table games (the spy, the minefield, the safe), pic by pieces, the blind auction, the team week."""

from html import escape

from bot.rules import auction, games, table, teams
from bot.texts import table as texts
from bot.texts.pick import pick, steady
from bot.ui.cards.announce import NOTE_CHESTS
from bot.ui.layout import MEDALS, bar, card, money, note, num, plural, timer, who

TEAM_MARKS = {"red": "🔴", "blue": "🔵"}
TEAM_NAMES = {"red": "Красные", "blue": "Синие"}
PIECE_LETTERS = ("A", "B", "C", "D")


def people_word(count: int) -> str:
    return f"{count} {plural(count, 'человек', 'человека', 'человек')}"


# ── the spy ───────────────────────────────────────────────────────────


def spy_card(phase: str, players: list[str], remaining: int, counts: list[int] | None = None,
             round_id: str = "") -> str:
    """Recruiting, the talk (everyone checks their word and writes one about it), the vote."""
    if phase == "recruit":
        return card(
            f"🎭 <b>Шпион</b> · сбор · <b>{timer(remaining)}</b>",
            steady(texts.SPY_FLAVOUR, round_id),
            ["👥 <b>Играют</b>", *(f"▫️ {who(name)}" for name in players)],
            note(f"Жми «Играю», нужно от {table.SPY_MIN} до {table.SPY_MAX} человек. Всем придёт одно слово, "
                 f"а одному — «ты шпион». Шпион слова не знает и должен не спалиться"),
        )
    if phase == "talk":
        return card(
            f"🎭 <b>Шпион</b> · обсуждение · <b>{timer(remaining)}</b>",
            steady(texts.SPY_FLAVOUR, round_id),
            ["👥 <b>Играют</b>", *(f"▫️ {who(name)}" for name in players)],
            note("Жми «Моё слово» — увидишь только ты. Каждый пишет в чат одно слово про своё: "
                 "не слишком прямо, а то шпион догадается. Потом голосование"),
        )
    counts = counts or [0] * len(players)
    leader = max(counts, default=0)
    return card(
        f"🎭 <b>Шпион</b> · голосование · <b>{timer(remaining)}</b>",
        steady(texts.SPY_FLAVOUR, round_id),
        [f"▫️ {who(name)} · <b>{count}</b>{bar(count, leader)}" for name, count in zip(players, counts)],
        note("Кто шпион? Голосуют только игроки, за себя нельзя. Поймали — каждому знавшему слово "
             "монеты. Ничья или мимо — шпион уходит с призом"),
    )


def spy_result(kind: str, players: list[str], spy: str | None, counts: list[int], word: str, reward: int,
               chat_id: int) -> str:
    if kind == "cancelled":
        return card("🎭 <b>Шпион</b> · отменён", texts.SPY_CANCELLED)
    caught = kind == "caught"
    head = "🎭 <b>Шпион</b> · пойман" if caught else "🎭 <b>Шпион</b> · ушёл"
    verdict = (f"💰 Остальным по +{money(reward)}" if caught else f"💰 Шпиону +{money(reward)}") if reward else ""
    return card(
        head,
        pick(texts.SPY_CAUGHT if caught else texts.SPY_ESCAPED, chat_id),
        [f"🕶 Шпион — <b>{who(spy or '')}</b>", f"🔤 Слово было <b>{escape(word)}</b>"],
        [f"▫️ {who(name)} · {count} {plural(count, 'голос', 'голоса', 'голосов')}"
         for name, count in zip(players, counts)],
        verdict,
    )


# ── the minefield ─────────────────────────────────────────────────────


def mines_card(pots: list[tuple[str, int]], opened: int, next_value: int, remaining: int, round_id: str = "") -> str:
    """pots: (name, coins of today) of everyone with something in the field."""
    left = table.MINES_SIDE ** 2 - table.MINES_COUNT - opened
    return card(
        f"🧨 <b>Сапёр</b> · <b>{timer(remaining)}</b>",
        steady(texts.MINES_FLAVOUR, round_id),
        f"💎 Следующая клетка · {money(next_value)}",
        ["💰 <b>Не забрали</b>", *(f"▫️ {who(name)} · {num(coins)}" for name, coins in pots)] if pots else "",
        f"🔲 Чистых клеток осталось: <b>{left}</b>",
        note(f"Жми клетку: пустая кладёт монеты в твой банк, каждая следующая дороже. Под {table.MINES_COUNT} "
             f"клетками мины: на мине сгорает всё, что никто не забрал, у всех. «Забрать» — положить свой "
             f"банк в кошелёк"),
    )


def mines_result(kind: str, stepper: str | None, paid: list[tuple[str, int]], burned: list[tuple[str, int]],
                 chat_id: int) -> str:
    if kind == "boom":
        return card(
            "🧨 <b>Сапёр</b> · взрыв",
            pick(texts.MINES_BOOM, chat_id),
            [f"💀 <b>{who(stepper or '')}</b>", "🏷 «Жертва мины» на сутки"],
            ["🔥 <b>Сгорело</b>", *(f"▫️ {who(name)} · {num(coins)}" for name, coins in burned)] if burned else "",
        )
    pool = texts.MINES_CLEARED if kind == "cleared" else texts.MINES_TIME
    return card(
        "🧨 <b>Сапёр</b> · " + ("поле чистое" if kind == "cleared" else "время вышло"),
        pick(pool, chat_id),
        ["💰 <b>Забрали</b>", *(f"▫️ {who(name)} · +{num(coins)}" for name, coins in paid)] if paid else "",
    )


# ── the safe ──────────────────────────────────────────────────────────


def safe_log_lines(log: list[tuple[str, str, int, int]]) -> list[str]:
    """(name, try, in place, elsewhere) → '▫️ 1234 · 2 на месте, 1 не там': who tried stays out,
    the line has to fit a phone."""
    return [f"▫️ <code>{guess}</code> · {exact} на месте, {near} не там" for _, guess, exact, near in log[-table.SAFE_LOG:]]


def safe_card(log: list[tuple[str, str, int, int]], pot: int, price: int, seed: int, remaining: int,
              round_id: str = "") -> str:
    return card(
        f"🔐 <b>Сейф</b> · <b>{timer(remaining)}</b>",
        steady(texts.SAFE_FLAVOUR, round_id, len(log)),
        f"💰 Внутри · {money(pot + seed)}",
        ["🔢 <b>Попытки</b>", *safe_log_lines(log)] if log else "",
        note(f"Код — {table.SAFE_DIGITS} разные цифры. Ответь на это сообщение кодом, например 0729: "
             f"попытка стоит {money(price)}, они копятся в сейфе. «На месте» — цифра есть и стоит "
             f"там же, «не там» — есть, но в другом месте. Не вскроют — всё уйдёт в следующий сейф"),
    )


def safe_result(code: str, cracker: str | None, pot: int, seed: int, log: list[tuple[str, str, int, int]],
                chat_id: int) -> str:
    if cracker is None:
        return card("🔐 <b>Сейф</b> · устоял", pick(texts.SAFE_HELD, chat_id), f"🔢 Код был <code>{code}</code>",
                    f"💰 Ждёт следующего · {money(pot)}" if pot else "")
    return card(
        "🔐 <b>Сейф</b> · вскрыт",
        pick(texts.SAFE_CRACKED, chat_id),
        [f"🔢 Код <code>{code}</code>", f"<i>попыток: {len(log)}</i>"],
        f"💰 <b>{who(cracker)}</b> · +{money(pot + seed)}",
    )


# ── pic by pieces ─────────────────────────────────────────────────────


def piece_card(stage: int, answered: int, remaining: int, rewards: list[int], round_id: str = "") -> str:
    """rewards: what the right letter pays in each stage, today's money."""
    worth = " → ".join(num(amount) for amount in rewards)
    return card(
        f"🧩 <b>Пикча по кусочку</b> · <b>{timer(remaining)}</b>",
        steady(texts.PIECE_FLAVOUR, round_id),
        f"🔍 Кусочек {stage + 1} из {len(games.PIECE_ZOOMS)}",
        f"🙋 Ответили: <b>{answered}</b>" if answered else "",
        note(f"Слева кусочек одной из четырёх пикч справа. Из какой он? Жми букву, ответ один. "
             f"Кусочек растёт каждые {games.PIECE_STAGE_SECONDS} секунд, а награда тает: {worth}"),
    )


def piece_result(answer: int, paid: list[tuple[str, int]], wrong: int, chat_id: int) -> str:
    lines = [f"{MEDALS[index] if index < len(MEDALS) else '▫️'} {who(name)} · +{num(coins)}"
             for index, (name, coins) in enumerate(paid)]
    missed = f"🙈 Мимо: {wrong}" if wrong else ""
    return card(
        "🧩 <b>Пикча по кусочку</b> · итог",
        pick(texts.PIECE_RESULT, chat_id),
        f"✅ Это была пикча <b>{PIECE_LETTERS[answer]}</b>",
        lines or "🤷 Никто не угадал",
        missed,
    )


# ── the blind auction ─────────────────────────────────────────────────


def auction_card(lot: str, bidders: int, raises: list[int], min_price: int, round_id: str = "") -> str:
    return card(
        f"🔨 <b>Аукцион</b> · до {auction.CLOSE_HOUR}:00",
        steady(texts.AUCTION_FLAVOUR, round_id),
        f"🎁 Лот — {NOTE_CHESTS[lot]}",
        f"🙋 Ставок: <b>{bidders}</b>",
        note(f"Ставки вслепую: кнопки добавляют к твоей ставке {', '.join(num(r) for r in raises)}, "
             f"видно только тебе. Монеты сразу откладываются. В {auction.CLOSE_HOUR}:00 побеждает самая "
             f"большая ставка, а платит вторую по величине, не меньше {num(min_price)}. Остальным всё "
             f"вернётся"),
    )


def auction_result(lot: str, winner: str | None, price: int, bidders: int, chat_id: int) -> str:
    if winner is None:
        return card("🔨 <b>Аукцион</b> · итог", texts.AUCTION_NOBODY, f"🎁 Лот — {NOTE_CHESTS[lot]}")
    return card(
        "🔨 <b>Аукцион</b> · продано",
        pick(texts.AUCTION_SOLD, chat_id),
        f"🎁 {NOTE_CHESTS[lot].capitalize()} — <b>{who(winner)}</b>",
        [f"💸 Цена · {money(price)}", f"<i>{people_word(bidders)} в торгах, остальным ставки вернулись</i>"],
    )


# ── the team week ─────────────────────────────────────────────────────


def team_score_lines(scores: dict[str, int], mine: str | None) -> list[str]:
    """For «Сегодня»: each colour's points so far, the viewer's own marked."""
    return ["🚩 <b>Командная неделя</b>",
            *(f"{TEAM_MARKS[team]} {TEAM_NAMES[team]} · {num(scores.get(team, 0))}" + (" · твои" if team == mine else "")
              for team in teams.TEAMS)]


def team_blocks(members: list[tuple[str, str, int]], scores: dict[str, int] | None) -> list[list[str]]:
    """A block per colour: its players; with scores, the colour's points and each player's."""
    if scores is None:
        return [[f"{TEAM_MARKS[team]} <b>{TEAM_NAMES[team]}</b>",
                 *(f"▫️ {who(name)}" for name, colour, _ in members if colour == team)] for team in teams.TEAMS]
    return [
        [f"{TEAM_MARKS[team]} <b>{TEAM_NAMES[team]}</b> · {num(scores.get(team, 0))}",
         *(f"▫️ {who(name)} · {num(points)}" for name, colour, points in members if colour == team)]
        for team in teams.TEAMS
    ]


def teams_start(members: list[tuple[str, str, int]], chat_id: int) -> str:
    return card(
        "🚩 <b>Командная неделя</b>",
        pick(texts.TEAMS_START, chat_id),
        *team_blocks(members, None),
        note(f"Всё, что игроки зарабатывают игрой — дуэли, суды, игры, босс, квесты, — идёт в очки их цвета. "
             f"В воскресенье в {teams.END[1]}:00 команда с большим счётом получает бонус каждому и носит "
             f"победу неделю. Счёт — в «Сегодня»"),
    )


def teams_result(winner: str | None, members: list[tuple[str, str, int]], scores: dict[str, int], bonus: int,
                 chat_id: int) -> str:
    if winner is None:
        return card("🚩 <b>Командная неделя</b> · ничья", texts.TEAMS_TIE, *team_blocks(members, scores))
    return card(
        "🚩 <b>Командная неделя</b> · итог",
        pick(texts.TEAMS_RESULT, chat_id),
        f"{TEAM_MARKS[winner]} Победили {TEAM_NAMES[winner]} · каждому +{money(bonus)}",
        *team_blocks(members, scores),
    )

"""Duels, tournaments and challenges: live cards and results."""

from html import escape

from bot.core import casino
from bot.core import economy
from bot.core import shop
from bot.core.arena import DEATH_LOSS_STREAK
from bot.db.repo import Battle
from bot.services.types import BattleReport
from bot.texts import arena as arena_texts
from bot.texts import events as event_texts
from bot.texts import social as social_texts
from bot.texts.pick import pick
from bot.tg.views.layout import SLOT_COLORS, bar, card, delta, money, num, plural, rating, slot_names, timer, who


def vote_lines(counts: list[int], labels: tuple[str, ...]) -> list[str]:
    leader = max(counts) if counts else 0
    return [
        f"<b>{labels[slot]}</b> · <b>{count}</b>{bar(count, leader, SLOT_COLORS[slot])}"
        for slot, count in enumerate(counts)
    ]


def bets_line(battle: Battle) -> str | None:
    pool = battle.bet_pool()
    total = sum(pool)
    if not total:
        return None
    names = slot_names(battle.kind)
    parts = [f"{names[slot]} ×{value:g}" for slot, value in enumerate(casino.odds(pool)) if value]
    return f"💰 Ставки: банк {money(total)} · " + " · ".join(parts)


def battle_card(battle: Battle, remaining: int, fighters: str | None = None, flipped: bool = False) -> str:
    """fighters: the 'A vs B, stake' line of a player challenge."""
    counts = battle.vote_counts()
    total = sum(counts)
    is_duel = battle.kind == "duel"
    labels = slot_names(battle.kind)
    if battle.mode == "challenge":
        head = "🤺 <b>ВЫЗОВ</b>"
    else:
        head = "⚔️ <b>ДУЭЛЬ</b>" if is_duel else "🏟 <b>ТУРНИР ЧЕТЫРЁХ</b>"
    status_pool = arena_texts.DUEL_STATUS if is_duel else arena_texts.TOURNAMENT_STATUS
    marks = [shop.stage(pic.wins).emoji for pic in battle.pics]
    votes = [f"{line}  {mark}" if mark != "🥚" else line for line, mark in zip(vote_lines(counts, labels), marks)]
    if is_duel and battle.streak > 0:
        votes.insert(0, f"👑 Пикча {slot_names(battle.kind)[0]} — чемпионка, серия <b>{battle.streak}</b>")
    if battle.extended and not total:
        status = f"<b>{escape(pick(event_texts.EXTENDED, battle.chat_id))}</b>"
    elif battle.mode == "challenge":
        status = "<i>Голосуют только зрители</i>"
    else:
        status = f"<i>{escape(pick(status_pool, battle.chat_id))}</i>"
    footer = [
        "🙃 <b>Перевёртыш:</b> победит пикча, у которой МЕНЬШЕ голосов" if flipped else "",
        bets_line(battle) or f"💰 Ставок пока нет · по {casino.BET_STEP} монет",
        status,
    ]
    return card(f"{head} · <b>{timer(remaining)}</b>", battle.title or None, fighters, votes, footer)


def battle_result(
    report: BattleReport,
    uploaders: list[str],
    guessers: list[str] | None = None,
    extras: list[str] | None = None,
) -> str:
    """Table of pics (best first), then v4 blocks (`extras`: challenge pot, evolution, bets,
    bounty), then the duel's aftermath (streak, death)."""
    battle = report.battle
    is_duel = battle.kind == "duel"
    labels = slot_names(battle.kind)
    if battle.mode == "challenge":
        title = "🤺 <b>ИТОГ ВЫЗОВА</b>"
    else:
        title = "⚔️ <b>ИТОГ ДУЭЛИ</b>" if is_duel else "🏟 <b>ИТОГ ТУРНИРА</b>"
    if not report.counted:
        return card(title, pick(arena_texts.NOBODY_VOTED, battle.chat_id), *(extras or []))

    if battle.mode == "challenge":
        from bot.texts.social import CHALLENGE_WIN  # local: only challenges speak this voice

        pool = CHALLENGE_WIN if report.winner is not None else arena_texts.DUEL_DRAW
    elif is_duel:
        pool = arena_texts.DUEL_DRAW if report.winner is None else arena_texts.DUEL_WIN
    else:
        pool = arena_texts.TOURNAMENT_DRAW if report.winner is None else arena_texts.TOURNAMENT_WIN

    counts = battle.vote_counts()
    total = sum(counts)
    score = " : ".join(str(count) for count in counts) if is_duel else f"{total} {plural(total, 'голос', 'голоса', 'голосов')}"
    table = []
    executed_id = report.executed.id if report.executed else None
    for slot in sorted(range(len(battle.pics)), key=lambda slot: (-counts[slot], slot)):
        pic = battle.pics[slot]
        if slot == report.winner:
            marker = "👑"
        elif pic.id == executed_id:
            marker = "⚰️"
        elif report.winner is None and counts[slot] == max(counts):
            marker = "🤝"
        else:
            marker = "▫️"
        votes = "" if is_duel else f" · {counts[slot]} {plural(counts[slot], 'голос', 'голоса', 'голосов')}"
        name = f"<b>{who(uploaders[slot])}</b>" if slot == report.winner else who(uploaders[slot])
        change = delta(report.rating_before[slot], report.rating_after[slot])
        table.append(f"{marker} <b>{labels[slot]}</b> · {name}{votes}\n<i>рейтинг {rating(report.rating_after[slot])} ({change})</i>")
    if guessers:
        reward = report.guess_reward or economy.GUESS + economy.VOTE
        table.append(f"🎯 Угадали: {', '.join(who(name) for name in guessers)} <i>(+{reward} монет)</i>")
    if report.flipped:
        table.append("🙃 <i>Перевёртыш: победила пикча с меньшим числом голосов</i>")

    aftermath = []
    if is_duel and battle.mode != "challenge":
        if report.winner is not None and report.streak > 1:
            aftermath.append(f"🔥 Серия чемпионки: <b>{report.streak}</b>")
        if report.executed:
            aftermath.append(f"⚰️ <b>{escape(pick(arena_texts.DUEL_EXECUTION, battle.chat_id))}</b>")
            aftermath.append(
                f"<i>Рейтинг ниже {report.death_rating:.0f} или {DEATH_LOSS_STREAK}-е поражение подряд — арена не прощает</i>"
            )
    # Pic rows are two lines each (name, rating): every row is its own block.
    return card(f"{title} · <b>{score}</b>", pick(pool, battle.chat_id), *table, *(extras or []), aftermath)


def streak_announcement(milestone: int, streak: int, chat_id: int) -> str:
    pool = {3: arena_texts.STREAK_3, 5: arena_texts.STREAK_5}.get(milestone, arena_texts.STREAK_10)
    wins = plural(streak, "победа", "победы", "побед")
    return card(f"🔥 <b>СЕРИЯ: {streak} {wins.upper()} ПОДРЯД</b>", pick(pool, chat_id))


def bets_result(report, labels: dict[int, str]) -> list[str]:
    if not report.bets:
        return []
    winners = [(user, paid - staked) for user, (staked, paid) in report.bets.items() if paid > staked]
    pool = sum(staked for staked, _ in report.bets.values())
    lines = [f"💰 <b>Ставки</b> · банк {pool}"]
    if not report.counted or report.winner is None:
        lines.append("<i>Ничья — всем вернули ставки</i>")
    elif winners:
        winners.sort(key=lambda item: -item[1])
        lines.append(", ".join(f"{who(labels.get(user, '?'))} <b>+{profit}</b>" for user, profit in winners))
    else:
        lines.append(f"<i>На победителя никто не ставил — {num(report.bets_burned)} монет сгорели</i>")
    return lines


def evolution_lines(report) -> list[str]:
    labels = slot_names(report.battle.kind)
    lines = []
    for slot, old, new in report.evolved:
        before, after = shop.STAGES[old], shop.STAGES[new]
        lines.append(f"🧬 Пикча <b>{labels[slot]}</b> эволюционировала: {before.name} → <b>{after.name}</b>")
    return lines


def bounty_line(paid: dict[int, int], labels: dict[int, str]) -> str | None:
    if not paid:
        return None
    hunters = ", ".join(f"{who(labels.get(user, '?'))} +{amount}" for user, amount in paid.items())
    return f"🎯 Награда за голову: {hunters}"


def challenge_card(challenge: dict, labels: dict[int, str], chat_id: int, remaining: int) -> str:
    challenger = who(labels.get(challenge["from_user"], "?"))
    target = challenge["to_user"]
    opponent = f"<b>{who(labels.get(target, '?'))}</b>" if target else "любого смельчака"
    return card(
        f"🤺 <b>ВЫЗОВ НА ДУЭЛЬ</b> · <b>{timer(remaining)}</b>",
        pick(social_texts.CHALLENGE_CALL, chat_id),
        f"<b>{challenger}</b> ставит {money(challenge['stake'])} и ждёт {opponent}",
        "<i>Каждый выставит свою пикчу, чат проголосует. Победитель заберёт "
        f"{num(challenge['stake'] * 2)} монет. Нет своих пикч — склад выдаст наёмника</i>",
    )


def challenge_closed(challenge: dict, labels: dict[int, str], status: str) -> str:
    challenger = who(labels.get(challenge["from_user"], "?"))
    reason = {
        "declined": "Отказ. Ставка вернулась",
        "cancelled": "Вызов отозван. Ставка вернулась",
        "expired": "Никто не принял. Ставка вернулась",
        "accepted": "Вызов принят — бой ниже",
    }[status]
    return card(f"🤺 <b>ВЫЗОВ</b> · {challenger} · {money(challenge['stake'])}", reason)


def challenge_names(report, labels: dict[int, str]) -> str:
    challenge = report.challenge
    first, second = (who(labels.get(challenge[key], "?")) for key in ("from_user", "to_user"))
    return f"🤺 <b>{first}</b> против <b>{second}</b>\n💰 На кону {money(challenge['stake'] * 2)}"


def challenge_result(report, labels: dict[int, str], chat_id: int) -> list[str]:
    if report.champion is None:
        return ["🤺 <i>Победителя нет — обе ставки вернулись</i>"]
    return [f"🤺 <b>{who(labels.get(report.champion, '?'))}</b> забирает {money(report.challenge['stake'] * 2)}"]

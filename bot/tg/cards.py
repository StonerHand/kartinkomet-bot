"""Message texts for the v4 mechanics. Same visual language as bot.tg.views:
header + italic line, blocks split by empty lines, numbers bold, names without "@"."""

from html import escape

from bot.core import boss as boss_rules
from bot.core import casino, court, progress, shop
from bot.db.repo import Battle, Pic
from bot.services.casino import CasinoResult
from bot.services.progress import Daily, TaskState
from bot.texts import boss as boss_texts
from bot.texts import casino as casino_texts
from bot.texts import days as day_texts
from bot.texts import progress as progress_texts
from bot.texts import shop as shop_texts
from bot.texts import social as social_texts
from bot.texts.pick import pick
from bot.tg.keyboards import DUEL_LABELS, TOURNAMENT_LABELS
from bot.tg.views import MEDALS, plural, quote, rating, timer, who

COIN = "🪙"


def coins(amount: int) -> str:
    return f"<b>{amount}</b> {COIN}"


def duration(seconds: int) -> str:
    """Human wait: '2 ч 5 мин', '14 мин', '40 сек'."""
    seconds = max(0, seconds)
    if seconds >= 3600:
        hours, minutes = divmod(seconds // 60, 60)
        return f"{hours} ч {minutes} мин" if minutes else f"{hours} ч"
    if seconds >= 60:
        return f"{seconds // 60} мин"
    return f"{seconds} сек"


def hp_bar(hp: int, max_hp: int, cells: int = 10) -> str:
    filled = max(0, min(cells, round(cells * hp / max_hp))) if max_hp else 0
    if hp > 0:
        filled = max(1, filled)
    return "▰" * filled + "▱" * (cells - filled)


# ── event of the day ───────────────────────────────────────────────────


def day_event_line(code: str | None) -> str | None:
    if not code:
        return None
    name, rule = day_texts.NAMES[code], day_texts.RULES[code]
    return f"📰 Сегодня: <b>{escape(name)}</b> — {escape(rule[0].lower() + rule[1:])}"


def day_event(code: str, chat_id: int, tax: tuple[int, int, int] | None = None) -> str:
    name, rule, flavour = day_texts.NAMES[code], day_texts.RULES[code], day_texts.FLAVOUR[code]
    lines = [
        f"📰 <b>СОБЫТИЕ ДНЯ · {escape(name).upper()}</b>",
        f"<i>{escape(pick(day_texts.HEADERS, chat_id))}</i>",
        "",
        quote(pick(flavour, chat_id)),
        f"<b>Что меняется:</b> {escape(rule[0].lower() + rule[1:])}.",
    ]
    if code == "tax" and tax:
        total, share, people = tax
        lines.append(
            f"🧾 Собрано {coins(total)}, по {coins(share)} получили {people} "
            f"{plural(people, 'бедняк', 'бедняка', 'бедняков')}"
        )
    lines.append("<i>Действует до полуночи</i>")
    return "\n".join(lines)


# ── casino ─────────────────────────────────────────────────────────────


def casino_screen(label: str, balance: int, stake: int, chat_id: int, lucky: bool) -> str:
    lines = [
        "🎰 <b>КАЗИНО</b>",
        f"<i>{escape(pick(casino_texts.HEADERS, chat_id))}</i>",
        "",
        f"💼 <b>{who(label)}</b>: {coins(balance)} · ставка {coins(stake)}",
        "<i>Ставка у каждого своя: кнопки 50…500 и «ва-банк» меняют её тому, кто нажал</i>",
    ]
    if lucky:
        lines.append("🍀 <b>Сегодня счастливый день:</b> выигрыши ×1.5")
    lines.append("")
    for game in casino.GAMES.values():
        lines.append(f"{game.emoji} <b>{game.name}</b> · /{game.command}")
        lines.append(f"<i>{escape(casino_texts.RULES[game.code])}</i>")
    lines += ["", "<i>Ставка своей суммой: /spin 300, /dice все</i>"]
    return "\n".join(lines)


def casino_title(game: str, kind: str) -> str:
    return casino_texts.TITLES.get(f"{game}:{kind}") or casino_texts.TITLES.get(kind, kind)


def casino_result(label: str, result: CasinoResult, values: tuple[int, ...], chat_id: int) -> str:
    lines = [f"<b>{casino_title(result.game, result.roll.kind)}</b> · {who(label)}"]
    if result.game == "dice":
        lines.append(f"<i>У тебя {values[0]}, у бота {values[1]}</i>")
    if result.profit > 0:
        pool = casino_texts.BIG_WIN if result.profit >= result.stake * 5 else casino_texts.WIN
        verdict = f"➕ <b>+{result.profit}</b> {COIN}"
    elif result.payout == result.stake:
        pool, verdict = casino_texts.DRAW, "↩️ ставка вернулась"
    elif result.payout > 0:
        pool, verdict = casino_texts.REFUND, f"↩️ вернулось <b>{result.payout}</b> из {result.stake}"
    else:
        pool, verdict = casino_texts.LOSE, f"➖ <b>−{result.stake}</b> {COIN}"
    lines.append(quote(pick(pool, chat_id)))
    lines.append(f"{verdict} · баланс <b>{result.balance}</b>")
    return "\n".join(lines)


# ── arena bets, evolution, bounties ────────────────────────────────────


def bets_line(battle: Battle) -> str | None:
    pool = battle.bet_pool()
    total = sum(pool)
    if not total:
        return None
    labels = DUEL_LABELS if battle.kind == "duel" else TOURNAMENT_LABELS
    odds = casino.odds(pool)
    parts = [f"{labels[slot]} ×{value:g}" for slot, value in enumerate(odds) if value]
    return f"💰 Банк ставок <b>{total}</b> · " + " · ".join(parts)


def bets_hint(battle: Battle) -> str:
    return f"<i>💰 — поставить {casino.BET_STEP} {COIN} на пикчу, банк делят угадавшие</i>"


def stage_mark(pic: Pic) -> str:
    return shop.stage(pic.wins).emoji


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
        lines.append(f"<i>На победителя никто не ставил — {report.bets_burned} {COIN} сгорели</i>")
    return lines


def evolution_lines(report) -> list[str]:
    labels = DUEL_LABELS if report.battle.kind == "duel" else TOURNAMENT_LABELS
    lines = []
    for slot, old, new in report.evolved:
        before, after = shop.STAGES[old], shop.STAGES[new]
        lines.append(f"🧬 {labels[slot]} эволюционировала: {before.emoji} → {after.emoji} <b>{after.name}</b>")
    return lines


def bounty_line(paid: dict[int, int], labels: dict[int, str]) -> str | None:
    if not paid:
        return None
    hunters = ", ".join(f"{who(labels.get(user, '?'))} +{amount}" for user, amount in paid.items())
    return f"🎯 Награда за голову: {hunters}"


# ── challenges ─────────────────────────────────────────────────────────


def challenge_card(challenge: dict, labels: dict[int, str], chat_id: int, remaining: int) -> str:
    challenger = who(labels.get(challenge["from_user"], "?"))
    target = challenge["to_user"]
    lines = [
        f"🤺 <b>ВЫЗОВ НА ДУЭЛЬ</b> · ⏳ <b>{timer(remaining)}</b>",
        f"<i>{escape(pick(social_texts.CHALLENGE_CALL, chat_id))}</i>",
        "",
        f"<b>{challenger}</b> ставит {coins(challenge['stake'])} и ждёт "
        + (f"<b>{who(labels.get(target, '?'))}</b>" if target else "любого смельчака"),
        "",
        "Каждый выставит свою пикчу, чат проголосует. Победитель заберёт "
        f"{coins(challenge['stake'] * 2)}. Нет своих пикч — склад выдаст наёмника.",
    ]
    return "\n".join(lines)


def challenge_closed(challenge: dict, labels: dict[int, str], status: str) -> str:
    challenger = who(labels.get(challenge["from_user"], "?"))
    reason = {
        "declined": "отказ. Ставка вернулась",
        "cancelled": "вызов отозван. Ставка вернулась",
        "expired": "никто не принял. Ставка вернулась",
        "accepted": "вызов принят — бой ниже",
    }[status]
    return f"🤺 <b>ВЫЗОВ</b> · {challenger} · {coins(challenge['stake'])}\n<i>{reason}</i>"


def challenge_names(report, labels: dict[int, str]) -> str:
    challenge = report.challenge
    first, second = (who(labels.get(challenge[key], "?")) for key in ("from_user", "to_user"))
    return f"🅰️ <b>{first}</b> против 🅱️ <b>{second}</b> · на кону {coins(challenge['stake'] * 2)}"


def challenge_result(report, labels: dict[int, str], chat_id: int) -> list[str]:
    if report.champion is None:
        return ["🤺 <i>Победителя нет — обе ставки вернулись</i>"]
    return [f"🤺 <b>{who(labels.get(report.champion, '?'))}</b> забирает {coins(report.challenge['stake'] * 2)}"]


# ── court: appeal ──────────────────────────────────────────────────────


def appeal_hint(uploader: str) -> str:
    return (
        f"<i>📜 {who(uploader)} может подать апелляцию за {court.APPEAL_BAIL} {COIN} в течение "
        f"{court.APPEAL_WINDOW // 60} минут. На повторном суде для казни нужно 3 голоса</i>"
    )


# ── shop ───────────────────────────────────────────────────────────────


def shop_screen(label: str, balance: int, prices: dict[str, int], chat_id: int, event: str | None) -> str:
    lines = [
        "🛒 <b>ЛАВКА</b>",
        f"<i>{escape(pick(shop_texts.HEADERS, chat_id))}</i>",
        "",
        f"💼 <b>{who(label)}</b>: {coins(balance)}",
    ]
    if event in ("inflation", "black_friday", "dead_day"):
        lines.append(day_event_line(event) or "")
    lines.append("")
    for code, (emoji, name, about) in shop_texts.ITEMS.items():
        lines.append(f"{emoji} <b>{name}</b> — {coins(prices[code])}")
        lines.append(f"<i>{escape(about)}</i>")
    lines.append(f"🎯 <b>Награда за голову</b> — {' или '.join(str(a) for a in shop.BOUNTY_AMOUNTS)} {COIN}")
    lines.append("<i>получат те, кто казнит пикчу</i>")
    lines += [
        "",
        "<b>Как купить</b>",
        "Под каждой пикчей есть кнопка 🛒 — там всё, что можно сделать именно с ней.",
        "Воскрешение — на экране ⚰️ Кладбище. Титул — кнопкой ниже.",
    ]
    return "\n".join(lines)


def pic_menu(pic: Pic, uploader: str | None, balance: int, bounty: int, cursed: int, now: int) -> str:
    stage = shop.stage(pic.wins)
    facts = [f"{stage.emoji} {stage.name}", f"⭐ {rating(pic.rating)}"]
    if uploader:
        facts.append(f"📥 {who(uploader)}")
    lines = ["🛒 <b>ЧТО СДЕЛАТЬ С ПИКЧЕЙ</b>", f"<i>{' · '.join(facts)}</i>", ""]
    if pic.immune_until and pic.immune_until > now:
        lines.append(f"🛡 Под щитом ещё {duration(pic.immune_until - now)}")
    if cursed:
        lines.append(f"🧿 Проклята ещё {duration(cursed - now)}")
    if bounty:
        lines.append(f"🎯 Награда за голову: {coins(bounty)}")
    lines.append(f"💼 Твой баланс: {coins(balance)}")
    return "\n".join(lines)


def bought(item: str, chat_id: int) -> str:
    return pick(shop_texts.BOUGHT[item], chat_id)


PURCHASE_FACTS = {
    "shield": "пикчу нельзя судить 3 дня",
    "boost": f"+{shop.BOOST_RATING} ⭐ рейтинга",
    "uncurse": f"порча снята, +{shop.CURSE_RATING} ⭐ вернулись",
}


def purchase_notice(item: str, buyer: str, pic: Pic, chat_id: int) -> str:
    """Public line under the pic after a purchase: what happened, who paid, a dealer joke."""
    emoji, name, _ = shop_texts.ITEMS[item]
    phrase = bought(item, chat_id).split(" ", 1)[1]  # phrases start with the item emoji
    return (
        f"{emoji} <b>{name.upper()}</b> · {PURCHASE_FACTS[item]}\n"
        f"<i>{escape(phrase)}</i>\n\n"
        f"За счёт <b>{who(buyer)}</b> · теперь ⭐ {rating(pic.rating)}"
    )


def wanted_poster(pic: Pic, total: int, sponsor: str, chat_id: int) -> str:
    return (
        f"🎯 <b>РАЗЫСКИВАЕТСЯ</b> · награда {coins(total)}\n"
        f"{quote(pick(shop_texts.BOUNTY, chat_id))}"
        f"<i>Заказчик: {who(sponsor)}. Деньги получат те, кто её казнит — в суде или на арене</i>"
    )


# ── quests, daily, chests ──────────────────────────────────────────────


def task_line(task: TaskState) -> str:
    name = progress_texts.quest_name(task.kind, task.target)
    if task.finished:
        return f"✅ <s>{escape(name)}</s>"
    return f"▫️ {escape(name)} · <b>{min(task.done, task.target)}/{task.target}</b> · +{task.reward}"


def quests_screen(
    label: str,
    daily: list[TaskState],
    weekly: list[TaskState],
    chests: dict[str, int],
    daily_ready: bool,
    daily_streak: int,
    chat_id: int,
) -> str:
    lines = [
        f"📜 <b>КВЕСТЫ · {who(label).upper()}</b>",
        f"<i>{escape(pick(progress_texts.QUEST_HEADERS, chat_id))}</i>",
        "",
        "🎁 <b>Бонус дня</b>",
        "Можно забрать — жми 🎁" if daily_ready else f"Забран. Серия: <b>{daily_streak}</b> "
        f"{plural(daily_streak, 'день', 'дня', 'дней')}",
        "",
        "📋 <b>Квесты дня</b> <i>(все три — 🟫 сундук)</i>",
        *[task_line(task) for task in daily],
        "",
        "🏆 <b>Челленджи недели</b> <i>(каждый — 🟪 сундук)</i>",
        *[task_line(task) for task in weekly],
    ]
    owned = [(tier, count) for tier, count in chests.items() if count]
    lines.append("")
    if owned:
        lines.append("🎒 <b>Сундуки:</b> " + " · ".join(
            f"{progress_texts.CHESTS[tier][0]} {count}" for tier, count in owned
        ))
    else:
        lines.append("<i>🎒 Сундуков пока нет: они за квесты, челленджи, серию бонусов и боссов</i>")
    return "\n".join(lines)


def daily_result(label: str, daily: Daily, chat_id: int) -> str:
    day = daily.streak
    lines = [
        f"🎁 <b>БОНУС ДНЯ</b> · {who(label)}",
        quote(pick(progress_texts.DAILY, chat_id)),
        f"➕ {coins(daily.reward)} · серия <b>{day}</b> {plural(day, 'день', 'дня', 'дней')}",
    ]
    if daily.family_bonus:
        lines.append(f"💍 Семейная надбавка: +{daily.family_bonus} тебе и супругу")
    if daily.chest:
        lines.append(f"🟪 За {progress.DAILY_CHEST_EVERY} дней подряд — <b>редкий сундук</b>")
    else:
        left = progress.DAILY_CHEST_EVERY - day % progress.DAILY_CHEST_EVERY
        lines.append(f"<i>До редкого сундука: {left} {plural(left, 'день', 'дня', 'дней')}</i>")
    return "\n".join(lines)


def chest_opening(label: str, tier: str, chat_id: int) -> str:
    emoji, name = progress_texts.CHESTS[tier]
    return f"{emoji} <b>{name.upper()}</b> · {who(label)}\n<i>{escape(pick(progress_texts.OPENING, chat_id))}</i>"


def chest_opened(label: str, opened, chat_id: int) -> str:
    emoji, name = progress_texts.CHESTS[opened.tier]
    loot = opened.loot
    lines = [f"{emoji} <b>{name.upper()}</b> · {who(label)}", quote(pick(progress_texts.LOOT[loot.kind], chat_id))]
    if loot.coins:
        lines.append(f"➕ {coins(loot.coins)}")
    if loot.kind == "boost" and opened.pic is not None:
        lines.append(f"⚡ +{progress.CHEST_BOOST_RATING} ⭐ одной из твоих пикч")
    if loot.kind == "shield" and opened.pic is not None:
        lines.append(f"🛡 Щит на {progress.CHEST_SHIELD_SECONDS // 86400} дня самой слабой твоей пикче")
    if loot.kind == "chest":
        lines.append("🟫 +1 деревянный сундук")
    return "\n".join(lines)


# ── boss ───────────────────────────────────────────────────────────────


def boss_card(boss: dict, labels: dict[int, str], remaining: int, chat_id: int) -> str:
    lines = [
        f"👹 <b>БОСС: {escape(boss['title']).upper()}</b> · ⏳ <b>{timer(remaining)}</b>",
        f"<i>{escape(pick(boss_texts.STATUS if boss['hits'] else boss_texts.ARRIVE, chat_id))}</i>",
        "",
        f"❤️ <b>{boss['hp']}</b> / {boss['max_hp']}",
        f"<code>{hp_bar(boss['hp'], boss['max_hp'])}</code>",
        f"💰 Добыча: {coins(boss['loot'])}",
    ]
    if boss["damage"]:
        top = list(boss["damage"].items())[:5]
        lines += ["", "⚔️ <b>Урон</b>"]
        for index, (user, dealt) in enumerate(top):
            place = MEDALS[index] if index < 3 else f"{index + 1}."
            lines.append(f"{place} {who(labels.get(user, '?'))} — <b>{dealt}</b>")
    lines += [
        "",
        f"<i>🗡 Удар — бесплатно, раз в {boss_rules.HIT_COOLDOWN_SECONDS:g} сек. "
        f"🔥 Супер — {boss_rules.SUPER_PRICE} {COIN}, бьёт сильнее. Добычу делят по урону</i>",
    ]
    return "\n".join(lines)


def boss_result(report, labels: dict[int, str], chat_id: int) -> str:
    boss = report.boss
    if not report.won:
        return (
            f"👹 <b>БОСС СБЕЖАЛ · {escape(boss['title']).upper()}</b>\n"
            f"{quote(pick(boss_texts.ESCAPE, chat_id))}"
            f"❤️ Осталось <b>{boss['hp']}</b> из {boss['max_hp']} · пикча-босс +{boss_rules.ESCAPE_RATING_BONUS} ⭐"
        )
    lines = [
        f"🏆 <b>БОСС ПОВЕРЖЕН · {escape(boss['title']).upper()}</b>",
        quote(pick(boss_texts.WIN, chat_id)),
        f"💰 <b>Добыча</b> · {boss['loot']} {COIN} по урону",
    ]
    for index, (user, amount) in enumerate(sorted(report.payouts.items(), key=lambda item: -item[1])[:8]):
        place = MEDALS[index] if index < 3 else f"{index + 1}."
        dealt = boss["damage"].get(user, 0)
        lines.append(f"{place} {who(labels.get(user, '?'))} — <b>+{amount}</b> <i>({dealt} урона)</i>")
    if report.last_hit is not None:
        lines.append(f"💀 Добил: <b>{who(labels.get(report.last_hit, '?'))}</b> (+{boss_rules.LAST_HIT_BONUS})")
    if report.top is not None:
        lines.append(f"🟪 Редкий сундук — <b>{who(labels.get(report.top, '?'))}</b>")
    return "\n".join(lines)


# ── people ─────────────────────────────────────────────────────────────


def gift(giver: str, receiver: str, amount: int, chat_id: int) -> str:
    return (
        f"🎁 <b>ПОДАРОК</b>\n{quote(pick(social_texts.GIFT, chat_id))}"
        f"<b>{who(giver)}</b> → <b>{who(receiver)}</b>: {coins(amount)}"
    )


def robbery(robber: str, victim: str, result, chat_id: int) -> str:
    if result.status == "success":
        return (
            f"🕵️ <b>ОГРАБЛЕНИЕ</b>\n{quote(pick(social_texts.ROB_SUCCESS, chat_id))}"
            f"Добыча <b>{who(robber)}</b>: {coins(result.amount)} из кармана <b>{who(victim)}</b>"
        )
    return (
        f"🚔 <b>ПОПАЛСЯ</b>\n{quote(pick(social_texts.ROB_FAIL, chat_id))}"
        f"<b>{who(robber)}</b> платит <b>{who(victim)}</b> штраф {coins(result.amount)} "
        f"и сидит {duration(result.wait)}"
    )


def proposal(suitor: str, beloved: str, price: int, chat_id: int) -> str:
    cost = f"Свадьба стоит {coins(price)} с каждого" if price else "Сегодня свадьба бесплатно"
    return (
        f"💍 <b>ПРЕДЛОЖЕНИЕ</b>\n{quote(pick(social_texts.PROPOSAL, chat_id))}"
        f"<b>{who(suitor)}</b> делает предложение <b>{who(beloved)}</b>.\n"
        f"<i>{cost}. Ответить может только {who(beloved)}, предложение живёт "
        f"{shop.PROPOSAL_SECONDS // 60} минут</i>"
    )


def wedding(first: str, second: str, chat_id: int) -> str:
    return (
        f"💒 <b>СВАДЬБА</b>\n{quote(pick(social_texts.WEDDING, chat_id))}"
        f"💍 <b>{who(first)}</b> + <b>{who(second)}</b>\n"
        f"<i>Семейный бонус: +20% к /daily, если оба забрали его в один день. "
        f"При разводе всё имущество делится пополам</i>"
    )


def rejected(suitor: str, beloved: str, chat_id: int) -> str:
    return f"💔 <b>ОТКАЗ</b>\n{quote(pick(social_texts.REJECTED, chat_id))}<b>{who(beloved)}</b> не хочет за <b>{who(suitor)}</b>"


def divorce(first: str, second: str, result, chat_id: int) -> str:
    return (
        f"💔 <b>РАЗВОД</b>\n{quote(pick(social_texts.DIVORCE, chat_id))}"
        f"{who(first)}: {coins(result.mine)} · {who(second)}: {coins(result.theirs)}"
    )

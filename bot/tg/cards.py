"""Message texts for the v4 mechanics. Same visual language as bot.tg.views:
header + italic line, blocks split by empty lines, numbers bold, names without "@"."""

from html import escape

from bot.core import boss as boss_rules
from bot.core import casino, court, progress, shop
from bot.db.repo import Pic
from bot.services.casino import CasinoResult
from bot.services.progress import Daily, TaskState
from bot.texts import boss as boss_texts
from bot.texts import casino as casino_texts
from bot.texts import days as day_texts
from bot.texts import progress as progress_texts
from bot.texts import shop as shop_texts
from bot.texts import social as social_texts
from bot.texts.pick import pick
from bot.tg.views import MEDALS, bare, card, money, num, plural, rating, slot_names, timer, who

def coins(amount: int) -> str:
    return money(amount)


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
    return f"📰 Сегодня {escape(bare(name)).lower()}: {escape(rule[0].lower() + rule[1:])}"


def day_event(code: str, chat_id: int, tax: tuple[int, int, int] | None = None) -> str:
    name, rule = day_texts.NAMES[code], day_texts.RULES[code]
    facts = [f"<b>Что меняется:</b> {escape(rule[0].lower() + rule[1:])}."]
    if code == "tax" and tax:
        total, share, people = tax
        facts.append(
            f"🧾 Собрано {coins(total)}, по {coins(share)} получили {people} "
            f"{plural(people, 'бедняк', 'бедняка', 'бедняков')}"
        )
    return card(
        f"📰 <b>СОБЫТИЕ ДНЯ: {escape(bare(name)).upper()}</b>",
        pick(day_texts.FLAVOUR[code], chat_id),
        facts,
        "<i>Действует до полуночи</i>",
    )


# ── casino ─────────────────────────────────────────────────────────────


def casino_screen(label: str, balance: int, stake: int, chat_id: int, lucky: bool) -> str:
    games = [
        f"{game.emoji} <b>{game.name}</b> · /{game.command}\n<i>{escape(casino_texts.RULES[game.code])}</i>"
        for game in casino.GAMES.values()
    ]
    return card(
        "🎰 <b>КАЗИНО</b>",
        pick(casino_texts.HEADERS, chat_id),
        [
            f"💼 <b>{who(label)}</b>: {coins(balance)} · ставка {coins(stake)}",
            "🍀 <b>Счастливый день:</b> выигрыши ×1.5" if lucky else "",
        ],
        *games,
        "<i>Ставка у каждого своя: кнопки 50…500 и «ва-банк» меняют её тому, кто нажал. "
        "Своей суммой — /spin 300, /dice все</i>",
    )


def casino_title(game: str, kind: str) -> str:
    return casino_texts.TITLES.get(f"{game}:{kind}") or casino_texts.TITLES.get(kind, kind)


def casino_result(label: str, result: CasinoResult, values: tuple[int, ...], chat_id: int) -> str:
    if result.profit > 0:
        pool = casino_texts.BIG_WIN if result.profit >= result.stake * 5 else casino_texts.WIN
        verdict = f"➕ +{money(result.profit)}"
    elif result.payout == result.stake:
        pool, verdict = casino_texts.DRAW, "↩️ Ставка вернулась"
    elif result.payout > 0:
        pool, verdict = casino_texts.REFUND, f"↩️ Вернулось <b>{num(result.payout)}</b> из {num(result.stake)}"
    else:
        pool, verdict = casino_texts.LOSE, f"➖ −{money(result.stake)}"
    return card(
        f"<b>{casino_title(result.game, result.roll.kind)}</b> · {who(label)}",
        pick(pool, chat_id),
        [
            f"🎲 Ты: <b>{values[0]}</b> · бот: <b>{values[1]}</b>" if result.game == "dice" else "",
            f"{verdict} · баланс <b>{num(result.balance)}</b>",
        ],
    )


# ── arena bets, evolution, bounties ────────────────────────────────────





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


# ── challenges ─────────────────────────────────────────────────────────


def challenge_card(challenge: dict, labels: dict[int, str], chat_id: int, remaining: int) -> str:
    challenger = who(labels.get(challenge["from_user"], "?"))
    target = challenge["to_user"]
    opponent = f"<b>{who(labels.get(target, '?'))}</b>" if target else "любого смельчака"
    return card(
        f"🤺 <b>ВЫЗОВ НА ДУЭЛЬ</b> · <b>{timer(remaining)}</b>",
        pick(social_texts.CHALLENGE_CALL, chat_id),
        f"<b>{challenger}</b> ставит {coins(challenge['stake'])} и ждёт {opponent}",
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
    return card(f"🤺 <b>ВЫЗОВ</b> · {challenger} · {coins(challenge['stake'])}", reason)


def challenge_names(report, labels: dict[int, str]) -> str:
    challenge = report.challenge
    first, second = (who(labels.get(challenge[key], "?")) for key in ("from_user", "to_user"))
    return f"🤺 <b>{first}</b> против <b>{second}</b>\n💰 На кону {coins(challenge['stake'] * 2)}"


def challenge_result(report, labels: dict[int, str], chat_id: int) -> list[str]:
    if report.champion is None:
        return ["🤺 <i>Победителя нет — обе ставки вернулись</i>"]
    return [f"🤺 <b>{who(labels.get(report.champion, '?'))}</b> забирает {coins(report.challenge['stake'] * 2)}"]


# ── court: appeal ──────────────────────────────────────────────────────


def appeal_hint(uploader: str) -> str:
    return (
        f"<i>{who(uploader)} может подать апелляцию за {court.APPEAL_BAIL} монет в течение "
        f"{court.APPEAL_WINDOW // 60} минут. На повторном суде для казни нужно 3 голоса</i>"
    )


# ── shop ───────────────────────────────────────────────────────────────


def shop_screen(label: str, balance: int, prices: dict[str, int], chat_id: int, event: str | None) -> str:
    items = [
        f"{emoji} <b>{name}</b> — {coins(prices[code])}\n<i>{escape(about)}</i>"
        for code, (emoji, name, about) in shop_texts.ITEMS.items()
    ]
    bounty = (
        f"🎯 <b>Награда за голову</b> — от {shop.BOUNTY_AMOUNTS[0]} монет\n"
        "<i>получат те, кто казнит пикчу</i>"
    )
    return card(
        "🛒 <b>ЛАВКА</b>",
        pick(shop_texts.HEADERS, chat_id),
        [
            f"💼 <b>{who(label)}</b>: {coins(balance)}",
            day_event_line(event) if event in ("inflation", "black_friday", "dead_day") else "",
        ],
        *items,
        bounty,
        [
            "<b>Как купить</b>",
            "Под каждой пикчей есть кнопка с тележкой — там всё, что можно сделать именно с ней. "
            "Воскрешение — на экране «Кладбище», титул — кнопкой ниже.",
        ],
    )


def pic_menu(pic: Pic, uploader: str | None, balance: int, bounty: int, cursed: int, now: int) -> str:
    stage = shop.stage(pic.wins)
    facts = [stage.name, f"рейтинг {rating(pic.rating)}"]
    if uploader:
        facts.append(f"от {uploader}")  # card() escapes the flavour line itself
    status = [
        f"🛡 Под щитом ещё {duration(pic.immune_until - now)}" if pic.immune_until and pic.immune_until > now else "",
        f"🧿 Проклята ещё {duration(cursed - now)}" if cursed else "",
        f"🎯 Награда за голову: {coins(bounty)}" if bounty else "",
    ]
    return card(
        "🛒 <b>ЧТО СДЕЛАТЬ С ПИКЧЕЙ</b>",
        " · ".join(facts),
        status,
        f"💼 Твой баланс: {coins(balance)}",
    )


def bought(item: str, chat_id: int) -> str:
    return pick(shop_texts.BOUGHT[item], chat_id)


PURCHASE_FACTS = {
    "shield": "пикчу нельзя судить 3 дня",
    "boost": f"+{shop.BOOST_RATING} рейтинга",
    "uncurse": f"порча снята, +{shop.CURSE_RATING} рейтинга вернулись",
}


def purchase_notice(item: str, buyer: str, pic: Pic, chat_id: int) -> str:
    """Public line under the pic after a purchase: what happened, who paid, a dealer joke."""
    emoji, name, _ = shop_texts.ITEMS[item]
    phrase = bought(item, chat_id).split(" ", 1)[1]  # phrases start with the item emoji
    return card(
        f"{emoji} <b>{name.upper()}</b> · {PURCHASE_FACTS[item]}",
        phrase,
        f"За счёт <b>{who(buyer)}</b> · рейтинг теперь {rating(pic.rating)}",
    )


def wanted_poster(pic: Pic, total: int, sponsor: str, chat_id: int) -> str:
    return card(
        f"🎯 <b>РАЗЫСКИВАЕТСЯ</b> · награда {coins(total)}",
        pick(shop_texts.BOUNTY, chat_id),
        f"Заказчик: <b>{who(sponsor)}</b>",
        "<i>Деньги получат те, кто её казнит — в суде или на арене</i>",
    )


# ── quests, daily, chests ──────────────────────────────────────────────


def task_line(task: TaskState) -> str:
    name = progress_texts.quest_name(task.kind, task.target)
    if task.finished:
        return f"✅ <s>{escape(name)}</s>\n<i>готово · +{num(task.reward)} монет</i>"
    return f"▫️ {escape(name)}\n<i>{min(task.done, task.target)} из {task.target} · награда {num(task.reward)} монет</i>"


def quests_screen(
    label: str,
    daily: list[TaskState],
    weekly: list[TaskState],
    chests: dict[str, int],
    daily_ready: bool,
    daily_streak: int,
    chat_id: int,
) -> str:
    bonus = "Можно забрать — жми 🎁" if daily_ready else (
        f"Забран. Серия: <b>{daily_streak}</b> {plural(daily_streak, 'день', 'дня', 'дней')}"
    )
    owned = [(tier, count) for tier, count in chests.items() if count]
    backpack = (
        "🎒 <b>Сундуки:</b> " + " · ".join(f"{progress_texts.CHESTS[tier][0]} {count}" for tier, count in owned)
        if owned
        else "<i>🎒 Сундуков пока нет: они за квесты, челленджи, серию бонусов и боссов</i>"
    )
    return card(
        f"📜 <b>КВЕСТЫ · {who(label).upper()}</b>",
        pick(progress_texts.QUEST_HEADERS, chat_id),
        ["🎁 <b>Бонус дня</b>", bonus],
        ["📋 <b>Квесты дня</b>", "<i>За все три — деревянный сундук</i>"],
        *[task_line(task) for task in daily],
        ["🏆 <b>Челленджи недели</b>", "<i>За каждый — редкий сундук</i>"],
        *[task_line(task) for task in weekly],
        backpack,
    )


def daily_result(label: str, daily: Daily, chat_id: int) -> str:
    day = daily.streak
    left = progress.DAILY_CHEST_EVERY - day % progress.DAILY_CHEST_EVERY
    return card(
        f"🎁 <b>БОНУС ДНЯ</b> · {who(label)}",
        pick(progress_texts.DAILY, chat_id),
        [
            f"➕ {coins(daily.reward)} · серия <b>{day}</b> {plural(day, 'день', 'дня', 'дней')}",
            f"💍 Семейная надбавка: +{daily.family_bonus} тебе и супругу" if daily.family_bonus else "",
            f"🎁 За {progress.DAILY_CHEST_EVERY} дней подряд — <b>редкий сундук</b>" if daily.chest else "",
        ],
        None if daily.chest else f"<i>До редкого сундука: {left} {plural(left, 'день', 'дня', 'дней')}</i>",
    )


def chest_opening(label: str, tier: str, chat_id: int) -> str:
    emoji, name = progress_texts.CHESTS[tier]
    return card(f"{emoji} <b>{name.upper()}</b> · {who(label)}", pick(progress_texts.OPENING, chat_id))


def chest_opened(label: str, opened, chat_id: int) -> str:
    emoji, name = progress_texts.CHESTS[opened.tier]
    loot = opened.loot
    facts = [
        f"➕ {coins(loot.coins)}" if loot.coins else "",
        f"⚡ +{progress.CHEST_BOOST_RATING} рейтинга одной из твоих пикч" if loot.kind == "boost" and opened.pic else "",
        f"🛡 Щит на {progress.CHEST_SHIELD_SECONDS // 86400} дня самой слабой твоей пикче"
        if loot.kind == "shield" and opened.pic else "",
        "🎁 +1 деревянный сундук" if loot.kind == "chest" else "",
    ]
    return card(f"{emoji} <b>{name.upper()}</b> · {who(label)}", pick(progress_texts.LOOT[loot.kind], chat_id), facts)


# ── boss ───────────────────────────────────────────────────────────────


def boss_card(boss: dict, labels: dict[int, str], remaining: int, chat_id: int) -> str:
    health = [
        f"❤️ <b>{boss['hp']}</b> / {boss['max_hp']}",
        f"<code>{hp_bar(boss['hp'], boss['max_hp'])}</code>",
        f"💰 Добыча: {coins(boss['loot'])}",
    ]
    damage = []
    if boss["damage"]:
        damage.append("⚔️ <b>Урон</b>")
        for index, (user, dealt) in enumerate(list(boss["damage"].items())[:5]):
            place = MEDALS[index] if index < 3 else f"{index + 1}."
            damage.append(f"{place} {who(labels.get(user, '?'))} — <b>{dealt}</b>")
    return card(
        f"👹 <b>БОСС: {escape(boss['title']).upper()}</b> · <b>{timer(remaining)}</b>",
        pick(boss_texts.STATUS if boss["hits"] else boss_texts.ARRIVE, chat_id),
        health,
        damage,
        [
            f"🗡 <i>Удар — бесплатно, раз в {boss_rules.HIT_COOLDOWN_SECONDS:g} сек</i>",
            f"🔥 <i>Супер-удар — {boss_rules.SUPER_PRICE} монет, бьёт сильнее</i>",
            "💰 <i>Добычу делят по нанесённому урону</i>",
        ],
    )


def boss_result(report, labels: dict[int, str], chat_id: int) -> str:
    boss = report.boss
    title = escape(boss["title"]).upper()
    if not report.won:
        return card(
            f"👹 <b>БОСС СБЕЖАЛ · {title}</b>",
            pick(boss_texts.ESCAPE, chat_id),
            f"❤️ Осталось <b>{boss['hp']}</b> из {boss['max_hp']} · пикча-босс +{boss_rules.ESCAPE_RATING_BONUS} рейтинга",
        )
    loot = [f"💰 <b>Добыча</b> · {money(boss['loot'])} по урону"]
    for index, (user, amount) in enumerate(sorted(report.payouts.items(), key=lambda item: -item[1])[:8]):
        place = MEDALS[index] if index < 3 else f"{index + 1}."
        dealt = boss["damage"].get(user, 0)
        loot.append(f"{place} {who(labels.get(user, '?'))} — <b>+{num(amount)}</b> <i>({dealt} урона)</i>")
    honours = [
        f"💀 Добил: <b>{who(labels.get(report.last_hit, '?'))}</b> (+{boss_rules.LAST_HIT_BONUS})"
        if report.last_hit is not None else "",
        f"🎁 Редкий сундук — <b>{who(labels.get(report.top, '?'))}</b>" if report.top is not None else "",
    ]
    return card(f"🏆 <b>БОСС ПОВЕРЖЕН · {title}</b>", pick(boss_texts.WIN, chat_id), loot, honours)


# ── people ─────────────────────────────────────────────────────────────


def gift(giver: str, receiver: str, amount: int, chat_id: int) -> str:
    return card(
        "🎁 <b>ПОДАРОК</b>",
        pick(social_texts.GIFT, chat_id),
        f"<b>{who(giver)}</b> → <b>{who(receiver)}</b>: {coins(amount)}",
    )


def robbery(robber: str, victim: str, result, chat_id: int) -> str:
    if result.status == "success":
        return card(
            "🕵️ <b>ОГРАБЛЕНИЕ</b>",
            pick(social_texts.ROB_SUCCESS, chat_id),
            f"Добыча <b>{who(robber)}</b>: {coins(result.amount)} из кармана <b>{who(victim)}</b>",
        )
    return card(
        "🚔 <b>ПОПАЛСЯ</b>",
        pick(social_texts.ROB_FAIL, chat_id),
        f"<b>{who(robber)}</b> платит <b>{who(victim)}</b> штраф {coins(result.amount)} и сидит {duration(result.wait)}",
    )


def proposal(suitor: str, beloved: str, price: int, chat_id: int) -> str:
    cost = f"Свадьба стоит {num(price)} монет с каждого" if price else "Сегодня свадьба бесплатно"
    return card(
        "💍 <b>ПРЕДЛОЖЕНИЕ</b>",
        pick(social_texts.PROPOSAL, chat_id),
        f"<b>{who(suitor)}</b> делает предложение <b>{who(beloved)}</b>",
        f"<i>{cost}. Ответить может только {who(beloved)}, предложение живёт {shop.PROPOSAL_SECONDS // 60} минут</i>",
    )


def wedding(first: str, second: str, chat_id: int) -> str:
    return card(
        "💒 <b>СВАДЬБА</b>",
        pick(social_texts.WEDDING, chat_id),
        f"💍 <b>{who(first)}</b> + <b>{who(second)}</b>",
        "<i>Семейный бонус: +20% к /daily, если оба забрали его в один день. "
        "При разводе всё имущество делится пополам</i>",
    )


def rejected(suitor: str, beloved: str, chat_id: int) -> str:
    return card(
        "💔 <b>ОТКАЗ</b>",
        pick(social_texts.REJECTED, chat_id),
        f"<b>{who(beloved)}</b> не хочет за <b>{who(suitor)}</b>",
    )


def divorce(first: str, second: str, result, chat_id: int) -> str:
    return card(
        "💔 <b>РАЗВОД</b>",
        pick(social_texts.DIVORCE, chat_id),
        [f"{who(first)}: {coins(result.mine)}", f"{who(second)}: {coins(result.theirs)}"],
    )



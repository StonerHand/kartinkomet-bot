"""Boss card and its outcome."""

from html import escape

from bot.core import boss as boss_rules
from bot.texts import boss as boss_texts
from bot.texts.pick import pick
from bot.tg.views.layout import MEDALS, card, hp_bar, money, num, plural, timer, who


PHASES = {
    "rage": "😡 <b>Ярость:</b> отвечает чаще и бьёт по кошелькам вдвое больнее",
    "shield": "🛡 <b>Щит:</b> обычный удар снимает 1, пробивают только супер-удары",
}


def boss_card(
    boss: dict,
    labels: dict[int, str],
    remaining: int,
    chat_id: int,
    super_price: int = boss_rules.SUPER_PRICE,
    counter: tuple[str, int] | None = None,
) -> str:
    """counter: the last counterattack, (victim, coins taken)."""
    raid = bool(boss.get("raid"))
    current = boss_rules.phase(boss["hp"], boss["max_hp"], raid)
    health = [
        f"❤️ <b>{boss['hp']}</b> / {boss['max_hp']}",
        f"<code>{hp_bar(boss['hp'], boss['max_hp'])}</code>",
        f"💰 Добыча: {money(boss['loot'])}",
        f"⏳ Сбежит через <b>{timer(remaining)}</b>",
    ]
    struck = []
    if counter is not None:
        victim, fine = counter
        lost = f" · −{money(fine)} в добычу" if fine else ""
        struck = [f"😤 <b>{who(victim)}</b>{lost}", f"<i>{escape(pick(boss_texts.COUNTER, chat_id))}</i>"]
    damage = []
    if boss["damage"]:
        damage.append("⚔️ <b>Урон</b>")
        for index, (user, dealt) in enumerate(list(boss["damage"].items())[:5]):
            place = MEDALS[index] if index < 3 else f"{index + 1}."
            damage.append(f"{place} {who(labels.get(user, '?'))} — <b>{dealt}</b>")
    kind = "РЕЙД" if raid else "БОСС"
    rules = [
        f"🗡 <i>Удар бесплатный, раз в {boss_rules.HIT_COOLDOWN_SECONDS:g} сек</i>",
        f"🔥 <i>Супер-удар: {num(super_price)} монет</i>",
        "🤝 <i>Добыча — по нанесённому урону</i>",
    ]
    raid_rules = [
        "🩹 <i>30 мин без ударов — лечится</i>",
        "🎁 <i>Лучшему — легендарный сундук</i>",
        f"🟫 <i>Всем с {boss_rules.RAID_CHEST_DAMAGE}+ урона — деревянный</i>",
    ] if raid else []
    return card(
        f"👹 <b>{kind}</b> · {escape(boss['title'])}",
        pick(boss_texts.STATUS if boss["hits"] else boss_texts.ARRIVE, chat_id),
        health,
        PHASES.get(current, ""),
        struck,
        damage,
        rules,
        raid_rules,
    )


def boss_result(report, labels: dict[int, str], chat_id: int) -> str:
    boss = report.boss
    title = escape(boss["title"])
    if not report.won:
        return card(
            f"👹 <b>БОСС СБЕЖАЛ</b> · {title}",
            pick(boss_texts.ESCAPE, chat_id),
            [
                f"❤️ Осталось <b>{boss['hp']}</b> из {boss['max_hp']}",
                f"⭐ Пикча-босс: +{boss_rules.ESCAPE_RATING_BONUS} рейтинга",
            ],
        )
    loot = [f"💰 <b>Добыча</b> · {money(boss['loot'])} по урону"]
    for index, (user, amount) in enumerate(sorted(report.payouts.items(), key=lambda item: -item[1])[:8]):
        place = MEDALS[index] if index < 3 else f"{index + 1}."
        dealt = boss["damage"].get(user, 0)
        loot.append(f"{place} {who(labels.get(user, '?'))} — <b>+{num(amount)}</b> · <i>урон {dealt}</i>")
    raid = bool(boss.get("raid"))
    top_chest = "Легендарный" if raid else "Редкий"
    honours = [
        f"💀 Добил: <b>{who(labels.get(report.last_hit, '?'))}</b> (+{boss_rules.LAST_HIT_BONUS})"
        if report.last_hit is not None else "",
        f"🎁 {top_chest} сундук — <b>{who(labels.get(report.top, '?'))}</b>" if report.top is not None else "",
        f"🟫 Деревянный сундук ещё {report.chests} {plural(report.chests, 'игроку', 'игрокам', 'игрокам')}"
        if report.chests else "",
    ]
    return card(f"🏆 <b>БОСС ПОВЕРЖЕН</b> · {title}", pick(boss_texts.WIN, chat_id), loot, honours)

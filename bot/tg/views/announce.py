"""Announcements: achievements, level-ups, quests and chests of one event in one message."""

from html import escape

from bot.core import achievements as rules
from bot.services.types import Granted
from bot.texts.achievements import ACHIEVEMENTS, LEVEL_UP, UNLOCKED
from bot.texts.pick import pick
from bot.tg.views.layout import bare, card, num, who


NOTE_CHESTS = {"wood": "деревянный сундук", "rare": "редкий сундук", "legend": "легендарный сундук"}


def note_line(label: str, note) -> str:
    """Two lines: what happened and to whom, then the details in italics."""
    from bot.texts.progress import quest_name  # local: progress texts are only needed here

    name = f"<b>{who(label)}</b>"
    if note.kind == "quest":
        return f"📜 Квест выполнен — {name}\n<i>{escape(quest_name(note.code, note.target))} · +{num(note.amount)} монет</i>"
    if note.kind == "quests_all":
        return f"📋 Все квесты дня — {name}\n<i>+{num(note.amount)} монет и {NOTE_CHESTS['wood']}</i>"
    if note.kind == "challenge":
        return (
            f"🏆 Челлендж недели — {name}\n"
            f"<i>{escape(quest_name(note.code, note.target))} · +{num(note.amount)} монет и {NOTE_CHESTS['rare']}</i>"
        )
    if note.kind == "challenges_all":
        return f"💎 Все челленджи недели — {name}\n<i>{NOTE_CHESTS['legend']}</i>"
    return f"🎁 Находка — {name}\n<i>{NOTE_CHESTS.get(note.code, 'сундук')}</i>"


RARITY_WORDS = {"common": "", "rare": " · редкая", "legendary": " · легендарная"}


def announcement(items: list[tuple[str, Granted]]) -> str:
    """All achievements, level-ups, quests and chests of one event in a single message; the same
    achievement for several people becomes one block."""
    notes = [note_line(label, note) for label, granted in items for note in granted.notes]
    if not any(granted.codes or granted.level_up for _, granted in items):
        return card(*notes) if len(notes) == 1 else "\n\n".join(notes)
    blocks = [
        f"⬆️ <b>{who(label)}</b> — новый уровень «{escape(bare(granted.level_up))}»\n<i>{escape(pick(LEVEL_UP))}</i>"
        for label, granted in items
        if granted.level_up
    ]
    by_code: dict[str, list[str]] = {}
    for label, granted in items:
        for code in granted.codes:
            by_code.setdefault(code, []).append(label)
    for code in sorted(by_code, key=lambda code: (rules.RARITY_ORDER[rules.rarity(code)], code)):
        name, description = ACHIEVEMENTS.get(code, (code, ""))
        people = ", ".join(who(label) for label in by_code[code])
        rarity = RARITY_WORDS[rules.rarity(code)]
        blocks.append(f"<b>{escape(name)}</b>{rarity} — {people}\n<i>{escape(description)}</i>")
    return card(f"<b>{escape(pick(UNLOCKED))}</b>", None, *blocks, *notes)


def has_legendary(granted: list[Granted]) -> bool:
    return any(rules.rarity(code) == rules.LEGENDARY for item in granted for code in item.codes)

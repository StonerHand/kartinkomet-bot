"""Shared layout: card(), numbers, names, plurals. Rules of every message live here."""

from html import escape

BAR_CELLS = 5
SLOT_COLORS = ("🟥", "🟦", "🟩", "🟨")
MEDALS = ("🥇", "🥈", "🥉")
# Fighters inside text are plain letters; the emoji letters 🅰️🅱️ live on buttons and collages.
DUEL_SLOTS = ("A", "B")
TOURNAMENT_SLOTS = ("1", "2", "3", "4")


def timer(seconds: int) -> str:
    seconds = max(0, seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def bar(count: int, leader: int, color: str) -> str:
    if count <= 0 or leader <= 0:
        return ""
    return "  " + color * max(1, round(BAR_CELLS * count / leader))


def num(value: int) -> str:
    """10000322 → '10 000 322' (non-breaking spaces, so a number never wraps)."""
    return f"{value:,}".replace(",", "\u00a0")


def money(amount: int) -> str:
    """Coins inside a line are a word, not 🪙: '<b>1 111</b> монет'. One emoji per line, at its start."""
    return f"<b>{num(amount)}</b> {plural(abs(amount), 'монета', 'монеты', 'монет')}"


def bare(name: str) -> str:
    """'🐣 Птенец' → 'Птенец': names of levels, stages, titles and achievements lose their own
    emoji when they sit inside a line."""
    head, _, tail = name.partition(" ")
    return tail if tail and not any(char.isalnum() for char in head) else name


def slot_names(kind: str) -> tuple[str, ...]:
    return DUEL_SLOTS if kind == "duel" else TOURNAMENT_SLOTS


def rating(value: float) -> str:
    return f"{value:.0f}"


def delta(before: float, after: float) -> str:
    diff = round(after - before)
    return f"+{diff}" if diff >= 0 else f"−{abs(diff)}"


def who(label: str) -> str:
    return escape(label)


def card(head: str, flavour: str | None = None, *blocks) -> str:
    """The one layout of every message:

        HEADER · meta
        flavour line (italic)

        block

        block…

    A block is a string or a list of lines; empty lines inside a block and empty blocks are
    dropped, so callers never glue or double the spacing by hand."""
    top = head + (f"\n<i>{escape(bare(flavour))}</i>" if flavour else "")  # the header owns the emoji
    parts = [top]
    for block in blocks:
        if isinstance(block, (list, tuple)):
            block = "\n".join(line for line in block if line)
        if block:
            parts.append(block.strip("\n"))
    return "\n\n".join(parts)


def cited(text: str) -> str:
    """Words of a person (last word in court): a real blockquote, then an empty line."""
    return f"<blockquote>{escape(text)}</blockquote>\n"


def plural(value: int, one: str, few: str, many: str) -> str:
    tail = value % 100
    if 11 <= tail <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(value % 10, many)


def ago(seconds: int) -> str:
    if seconds < 3600:
        return "только что"
    hours = seconds // 3600
    if hours < 24:
        return f"{hours} ч назад"
    days = hours // 24
    return f"{days} {plural(days, 'день', 'дня', 'дней')} назад"


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

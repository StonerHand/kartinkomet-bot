"""Pikchecoins and player levels."""

from dataclasses import dataclass

# Coins per action.
VOTE = 1
GUESS = 3  # voted for the winner of a battle
COURT_VOTE = 1
LIKE_RECEIVED = 2  # someone liked your pic for the first time
UPLOAD = 1
CAPTION_WIN = 15
GOLD = 25


@dataclass(frozen=True)
class Level:
    index: int  # 0-based
    name: str
    threshold: int  # lifetime coins needed


LEVELS = (
    Level(0, "🥚 Залётный", 0),
    Level(1, "🐣 Зритель", 20),
    Level(2, "🙂 Свой", 60),
    Level(3, "😎 Завсегдатай", 150),
    Level(4, "🧠 Мемолог", 300),
    Level(5, "🔥 Задрот", 600),
    Level(6, "💀 Ветеран арены", 1000),
    Level(7, "👑 Аристократ склада", 1600),
    Level(8, "🗿 Живая легенда", 2500),
    Level(9, "🌌 Бог склада", 4000),
)


def level_for(earned: int) -> Level:
    current = LEVELS[0]
    for level in LEVELS:
        if earned >= level.threshold:
            current = level
    return current


def next_level(earned: int) -> Level | None:
    for level in LEVELS:
        if earned < level.threshold:
            return level
    return None


def progress(earned: int, cells: int = 10) -> str:
    """Progress bar to the next level, e.g. ▰▰▰▱▱▱▱▱▱▱ — inside a <code> block it renders evenly."""
    current = level_for(earned)
    upcoming = next_level(earned)
    if upcoming is None:
        return "▰" * cells
    span = upcoming.threshold - current.threshold
    filled = int(cells * (earned - current.threshold) / span) if span else cells
    return "▰" * filled + "▱" * (cells - filled)


# Weekly crowns: kind → (badge, title). Handed out with the Sunday digest, worn for a week.
CROWNS = {
    "uploader": ("👑", "Король загрузок"),
    "executioner": ("🪓", "Палач недели"),
    "advocate": ("😇", "Адвокат недели"),
    "oracle": ("🎯", "Оракул недели"),
    "rich": ("💰", "Богач недели"),
    "lucky": ("🍀", "Везунчик казино"),
}
CROWN_SECONDS = 7 * 24 * 3600


def people_voice(right: int, wrong: int) -> tuple[int, str] | None:
    """Share of votes that matched the winner, with a verdict. None until 5 decided votes."""
    total = right + wrong
    if total < 5:
        return None
    share = round(100 * right / total)
    if share >= 90:
        verdict = "🐑 голос стада"
    elif share >= 60:
        verdict = "🗳 голос народа"
    elif share > 30:
        verdict = "🤷 сам по себе"
    else:
        verdict = "🦄 уникальный вкус"
    return share, verdict


# ── everything follows the chat's money ────────────────────────────────
# Every amount in the game — prices, rewards, fines, stakes, minimums, the amount buttons — is
# set for a chat whose players hold BASE_WEALTH coins each on average, and moves with the pool:
# the coins of everyone who played in the last two weeks, admins included, over their number.
# One factor for all, uncapped, so in a rich chat a reward stays the same share of a wallet; a
# poor chat (a fresh season, everyone broke) plays at base amounts, which also pulls it back up.
# Transfers (gifts, robbery, the redistribution) don't move the pool; only what the game pays
# out and takes in does, and the first of the month resets it.
BASE_WEALTH = 2000
WEALTH_ACTIVE_DAYS = 14
# The great redistribution hands out at most this many average wallets; the rest burns.
REDISTRIBUTION_CAP_WALLETS = 10


def wealth_factor(average_wallet: float) -> float:
    """How much richer than the base chat this one is (≥ 1)."""
    return max(1.0, average_wallet / BASE_WEALTH)


def redistribution_cap(average_wallet: float) -> int:
    return int(REDISTRIBUTION_CAP_WALLETS * max(average_wallet, 1))


def scaled(amount: int, factor: float) -> int:
    """An amount in today's money: × factor, rounded to two significant digits (300 × 7.31 →
    2 200), and never below 1 coin for anything that was above zero."""
    if amount <= 0 or factor <= 1:
        return amount
    value = amount * factor
    step = 10 ** max(0, len(str(int(value))) - 2)
    return max(1, int(round(value / step) * step))

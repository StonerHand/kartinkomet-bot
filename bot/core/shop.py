"""Shop, pic evolution, robbery and marriage rules."""

from dataclasses import dataclass

# ── shop ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Item:
    code: str
    price: int


ITEMS = {
    "shield": Item("shield", 300),  # 3 days of immunity from court
    "boost": Item("boost", 400),  # +50 rating, once per pic per day
    "court": Item("court", 250),  # send someone's pic to court
    "uncurse": Item("uncurse", 150),  # lift the wheel's curse and return the rating
    "resurrect": Item("resurrect", 1000),  # bring a pic back from the graveyard
    "title": Item("title", 500),  # custom title in the profile
}
SHIELD_SECONDS = 3 * 86400
BOOST_RATING = 50
RESURRECT_RATING = 1000.0
RESURRECT_IMMUNITY = 3 * 86400
CURSE_RATING = 40
CURSE_SECONDS = 86400
TITLE_MAX_LENGTH = 24
# Rare titles the wheel and legendary chests hand out (a bought title is never replaced).
PRIZE_TITLES = (
    "Гроза склада", "Легенда рандома", "Икона кринжа", "Звезда арены", "Тень склада", "Ходячий мем",
    "Чудо в пикселях", "Сила рандома", "Совесть склада", "Душа чата", "Гордость кладбища",
    "Угроза рейтингу", "Магия JPEG", "Ужас модераторов", "Пиксельное величие",
)
BOUNTY_AMOUNTS = (100, 500)
INFLATION, SALE = 2.0, 0.5


def price(code: str, inflation: bool = False, sale: bool = False, dead_day_price: int | None = None) -> int:
    value = ITEMS[code].price
    if code == "resurrect" and dead_day_price is not None:
        value = dead_day_price
    if inflation:
        value = int(value * INFLATION)
    if sale:
        value = int(value * SALE)
    return value


# ── evolution ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Stage:
    index: int
    wins: int
    emoji: str
    name: str


STAGES = (
    Stage(0, 0, "🥚", "Яйцо"),
    Stage(1, 1, "🐣", "Птенец"),
    Stage(2, 3, "🐺", "Зверь"),
    Stage(3, 7, "🐉", "Дракон"),
    Stage(4, 15, "🌌", "Божество"),
)


def stage(wins: int) -> Stage:
    current = STAGES[0]
    for candidate in STAGES:
        if wins >= candidate.wins:
            current = candidate
    return current


# ── robbery ────────────────────────────────────────────────────────────

ROB_CHANCE = 0.4
ROB_MIN_BALANCE = 100  # both the robber and the victim
ROB_SHARE = (0.10, 0.20)
ROB_CAP = 1000
ROB_FINE_SHARE = 0.10
ROB_FINE_MIN = 50
ROB_COOLDOWN = 2 * 3600
JAIL_SECONDS = 6 * 3600
VICTIM_PROTECTION = 3600


def rob_fine(balance: int) -> int:
    return min(balance, max(ROB_FINE_MIN, int(balance * ROB_FINE_SHARE)))


# ── marriage ───────────────────────────────────────────────────────────

WEDDING_PRICE = 100  # from each
PROPOSAL_SECONDS = 600
GOLDEN_WEDDING_DAYS = 30


def divorce_split(first: int, second: int) -> tuple[int, int]:
    """Common property: both balances go into one pot and are split in half."""
    total = first + second
    return total - total // 2, total // 2


# ── challenges between players ─────────────────────────────────────────

CHALLENGE_MIN = 50
CHALLENGE_SECONDS = 180  # to accept

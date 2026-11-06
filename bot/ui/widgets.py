"""HTML widgets: the pages (widget_html/*.html) and the data each one draws, packed under the
1 KB Telegram allows a widget's data. Names are cut and lists shortened until the data fits."""

import json
from functools import cache
from pathlib import Path

from bot.ui.layout import bare

PAGES = Path(__file__).parent / "widget_html"
KINDS = ("mines", "safe", "spy", "rps", "ttt", "slots", "board")
NAME = 14  # characters of a name inside a widget
# The caption under a widget: its title, which is also what clients without widgets show.
CAPTIONS = {
    "mines": "🧨 <b>Сапёр</b>", "safe": "🔐 <b>Сейф</b>", "spy": "🎭 <b>Шпион</b>",
    "rps": "✊ <b>Камень, ножницы, бумага</b>", "ttt": "❌ <b>Крестики-нолики</b>", "slots": "🎰 <b>Автомат</b>",
    "board": "📊 <b>Табло</b>",
}


@cache
def page(kind: str) -> str:
    return (PAGES / f"{kind}.html").read_text(encoding="utf-8")


def name(label: str) -> str:
    label = bare(label)
    return label if len(label) <= NAME else label[: NAME - 1] + "…"


def packed(data: dict, trim: str | None = None) -> str:
    """JSON of at most 1 KB: the list under `trim` loses items from its end until it fits."""
    while True:
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(raw.encode()) <= 1024 or not trim or not data.get(trim):
            return raw
        data[trim] = data[trim][:-1]


def mines_data(opened: list[int], field: list[int] | None, pots: list[tuple[str, int]], worth: int,
               ends_at: int, over: int = 0, stepper: str | None = None) -> str:
    """over: 0 — on, 1 — a mine, 2 — a clean field, 3 — time. field: the mines, once it's over."""
    data = {"o": opened, "p": [[name(who), coins] for who, coins in pots], "n": worth, "t": ends_at, "x": over}
    if field is not None:
        data["m"] = field
    if stepper:
        data["b"] = name(stepper)
    return packed(data, "p")


def safe_data(log: list[tuple[str, int, int]], inside: int, price: int, ends_at: int, over: int = 0,
              code: str | None = None, cracker: str | None = None) -> str:
    """log: (try, in place, elsewhere), oldest first. over: 0 — on, 1 — cracked, 2 — held."""
    data = {"l": [list(item) for item in log[-6:]], "p": inside, "c": price, "t": ends_at, "x": over}
    if code:
        data["k"] = code
    if cracker:
        data["w"] = name(cracker)
    return packed(data, "l")


def spy_data(phase: str, players: list[str], counts: list[int], ready: int, ends_at: int,
             result: dict | None = None) -> str:
    """result, once it's over: {'k': caught|escaped|cancelled, 'spy': name, 'w': the word}."""
    data = {"f": phase, "p": [name(player) for player in players], "c": counts, "r": ready, "t": ends_at}
    if result is not None:
        data["z"] = {key: name(value) if key == "spy" else value for key, value in result.items()}
    return packed(data)


def rps_data(names: tuple[str, str], picked: tuple[bool, bool], rounds: int, until: int,
             result: dict | None = None) -> str:
    """result: {'w': the winner's name or '', 'k': both picks or None, 'late': who ran out of time}."""
    data = {"n": [name(item) for item in names], "p": [int(flag) for flag in picked], "r": rounds, "t": until}
    if result is not None:
        data["z"] = result
    return packed(data)


def ttt_data(board: str, names: tuple[str, str], turn: int, until: int, result: dict | None = None) -> str:
    """result: {'w': the winner's name or '', 'line': the winning three, 'late': who ran out of time}."""
    data = {"b": board, "n": [name(item) for item in names], "u": turn, "t": until}
    if result is not None:
        data["z"] = result
    return packed(data)


def slots_data(feed: list[tuple[str, int]]) -> str:
    """The machine's feed of big wins, latest first."""
    return packed({"f": [[name(who), coins] for who, coins in feed]}, "f")


def board_data(season: list[tuple[str, int]], teams: tuple[int, int] | None, updated: str) -> str:
    data = {"s": [[name(who), points] for who, points in season], "u": updated}
    if teams is not None:
        data["tm"] = list(teams)
    return packed(data, "s")

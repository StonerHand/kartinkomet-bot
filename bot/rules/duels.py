"""Board duels between two players on a stake: rock-paper-scissors and tic-tac-toe."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BoardGame:
    code: str
    emoji: str
    name: str
    rules: str  # how it goes, for the challenge card


BOARD_GAMES = {
    "rps": BoardGame("rps", "✊", "Камень, ножницы, бумага",
                     "Оба выбирают втайне, бот открывает разом. Ничья — ещё раз. Победитель забирает банк"),
    "ttt": BoardGame("ttt", "❌", "Крестики-нолики",
                     "Вызвавший ходит крестиками и первым. Три в ряд — банк твой, ничья — ставки вернутся"),
}

# ── rock, paper, scissors ─────────────────────────────────────────────
RPS = ("✊", "✌️", "✋")  # rock, scissors, paper: each beats the next one, paper beats rock
RPS_NAMES = ("камень", "ножницы", "бумага")
RPS_SECONDS = 120  # to pick; whoever didn't loses to whoever did


def rps_winner(first: int, second: int) -> int | None:
    """0: the first pick wins, 1: the second, None: the same pick."""
    if first == second:
        return None
    return 0 if (second - first) % 3 == 1 else 1


# ── tic-tac-toe ───────────────────────────────────────────────────────
TTT_EMPTY, TTT_MARKS = ".", ("X", "O")  # the challenger plays X and opens
TTT_MOVE_SECONDS = 60  # a player who lets it run out loses
TTT_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


def ttt_outcome(board: str) -> str | None:
    """'X' or 'O' with three in a row, 'draw' on a full board, None while it goes on."""
    for a, b, c in TTT_LINES:
        if board[a] != TTT_EMPTY and board[a] == board[b] == board[c]:
            return board[a]
    return "draw" if TTT_EMPTY not in board else None


def ttt_line(board: str) -> tuple[int, int, int] | None:
    """The winning three, to light them up."""
    for line in TTT_LINES:
        a, b, c = line
        if board[a] != TTT_EMPTY and board[a] == board[b] == board[c]:
            return line
    return None

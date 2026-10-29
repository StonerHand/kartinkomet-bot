import random
import tempfile
import unittest
from pathlib import Path

from bot.db.repo import Repo
from bot.game import Game
from bot.services.progress import STARTER_BONUS


class Clock:
    def __init__(self, start: float = 1_800_000_000) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def make_game(
    pics: int = 0, uploader: int = 1, quests: bool = False
) -> tuple[Game, Clock, tempfile.TemporaryDirectory]:
    temp = tempfile.TemporaryDirectory()
    repo = Repo(Path(temp.name) / "test.sqlite")
    clock = Clock()
    game = Game(repo, tz_offset_hours=0, rng=random.Random(42), clock=clock)
    game.quests_enabled = quests
    game.starter_bonus = STARTER_BONUS if quests else 0
    repo.remember_user(uploader, "uploader", "Up", None, game.now())
    for index in range(pics):
        repo.add_pic(f"file{index}", f"uniq{index}", uploader, None, game.now())
    return game, clock, temp


class GameCase(unittest.TestCase):
    """A game on a fresh SQLite database with a fake clock; players 2–8 are known by name."""

    quests = False

    def setUp(self) -> None:
        self.game, self.clock, temp = make_game(pics=12, uploader=1, quests=self.quests)
        self.addCleanup(temp.cleanup)
        for user in range(2, 9):
            self.game.repo.remember_user(user, f"user{user}", None, None, self.game.now())

    def coins(self, user: int) -> int:
        return self.game.repo.player(user)[0]

    def fund(self, user: int, amount: int = 1000) -> None:
        self.game.repo.add_coins(user, amount, "test", self.game.now(), earn=False)

    def set_event(self, code: str) -> None:
        self.clock.value = (self.game.local_day() * 86400) + 12 * 3600  # noon: events are on
        self.game.repo.set_meta(f"day_event:{self.game.local_day()}", code)

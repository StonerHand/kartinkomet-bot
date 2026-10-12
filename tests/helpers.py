import random
import tempfile
from pathlib import Path

from bot.db.repo import Repo
from bot.game import Game


class Clock:
    def __init__(self, start: float = 1_800_000_000) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def make_game(pics: int = 0, uploader: int = 1) -> tuple[Game, Clock, tempfile.TemporaryDirectory]:
    temp = tempfile.TemporaryDirectory()
    repo = Repo(Path(temp.name) / "test.sqlite")
    clock = Clock()
    game = Game(repo, tz_offset_hours=0, rng=random.Random(42), clock=clock)
    repo.remember_user(uploader, "uploader", "Up", None, game.now())
    for index in range(pics):
        repo.add_pic(f"file{index}", f"uniq{index}", uploader, None, game.now())
    return game, clock, temp

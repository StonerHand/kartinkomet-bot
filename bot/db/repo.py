"""Repo: every domain's SQL mixin in one object. Everything else talks to the database through it."""

from pathlib import Path

from bot.db.arena import ArenaRepo
from bot.db.chats import ChatsRepo
from bot.db.court import CourtRepo
from bot.db.economy import EconomyRepo
from bot.db.games import GamesRepo
from bot.db.meta import MetaRepo
from bot.db.people import PeopleRepo
from bot.db.pics import PicsRepo
from bot.db.schema import apply_schema, connect
from bot.db.seasons import SeasonsRepo
from bot.db.stats import StatsRepo


class Repo(
    MetaRepo, PicsRepo, ArenaRepo, CourtRepo, StatsRepo, EconomyRepo, GamesRepo, ChatsRepo, PeopleRepo, SeasonsRepo
):

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = connect(self.database_path)
        apply_schema(self.db)
        self._known_users: dict[int, tuple] = {}

    def close(self) -> None:
        self.db.close()

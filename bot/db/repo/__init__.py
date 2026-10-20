"""All SQL lives here, one mixin per domain. Everything else talks to the database through Repo."""

from pathlib import Path

from bot.db.repo.core import MetaRepo
from bot.db.repo.pics import PicsRepo
from bot.db.repo.arena import ArenaRepo
from bot.db.repo.court import CourtRepo
from bot.db.repo.stats import StatsRepo
from bot.db.repo.economy import EconomyRepo
from bot.db.repo.games import GamesRepo
from bot.db.repo.chats import ChatsRepo
from bot.db.repo.people import PeopleRepo
from bot.db.repo.models import (
    LEGEND_POOL_SIZE,
    MIN_EXPERIENCE,
    PIC_COLUMNS,
    SCHEMA_PATH,
    SCHEMA_VERSION,
    Battle,
    Court,
    Pic,
    UserStats,
    apply_schema,
    connect,
)

__all__ = [
    "LEGEND_POOL_SIZE", "MIN_EXPERIENCE", "PIC_COLUMNS", "SCHEMA_PATH", "SCHEMA_VERSION",
    "Battle", "Court", "Pic", "Repo", "UserStats", "apply_schema", "connect",
]


class Repo(MetaRepo, PicsRepo, ArenaRepo, CourtRepo, StatsRepo, EconomyRepo, GamesRepo, ChatsRepo, PeopleRepo):

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = connect(self.database_path)
        apply_schema(self.db)
        self._known_users: dict[int, tuple] = {}

    def close(self) -> None:
        self.db.close()

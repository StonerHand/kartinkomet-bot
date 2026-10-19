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
        self._fix_migrated_reaction_times()
        self._known_users: dict[int, tuple] = {}

    def _fix_migrated_reaction_times(self) -> None:
        """Early v2 migrations stamped v1 reactions with the migration time, which made them look
        like this week's. They happened at an unknown time: reset them to 0, once."""
        if self.meta_str("fixed_v1_reaction_times"):
            return
        migrated_at = self.meta_str("migrated_from_v1_at")
        with self.db:
            if migrated_at:
                self.db.execute("UPDATE reactions SET at = 0 WHERE at = ?", (int(migrated_at),))
            self.db.execute(
                "INSERT INTO meta (key, value) VALUES ('fixed_v1_reaction_times', '1') "
                "ON CONFLICT(key) DO NOTHING"
            )

    def close(self) -> None:
        self.db.close()

import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bot.db.migrate import history_scope, migrate_if_needed, seed_rating
from bot.db.repo import Repo

V1_SCHEMA = """
CREATE TABLE documents (name TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT);
CREATE TABLE users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, updated_at TEXT);
CREATE TABLE images (id TEXT PRIMARY KEY, position INTEGER NOT NULL DEFAULT 0, file_id TEXT NOT NULL,
    file_unique_id TEXT NOT NULL UNIQUE, added_by INTEGER, added_at TEXT, visual_hash TEXT,
    shown_count INTEGER NOT NULL DEFAULT 0, last_shown_at TEXT, likes INTEGER NOT NULL DEFAULT 0,
    dislikes INTEGER NOT NULL DEFAULT 0);
CREATE TABLE image_reactions (image_id TEXT NOT NULL, user_id TEXT NOT NULL, reaction TEXT NOT NULL,
    PRIMARY KEY (image_id, user_id));
CREATE TABLE image_chat_history (chat_id TEXT NOT NULL, position INTEGER NOT NULL, image_id TEXT NOT NULL,
    PRIMARY KEY (chat_id, position));
CREATE TABLE image_stats (key TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0);
CREATE TABLE jokes (id TEXT PRIMARY KEY);
"""


def build_v1(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(V1_SCHEMA)
    db.execute("INSERT INTO users VALUES (1, 'stoner', 'S', NULL, '2026-04-28T15:45:22+00:00')")
    db.executemany(
        "INSERT INTO images VALUES (?, ?, ?, ?, 1, '2026-04-28T15:45:22+00:00', NULL, 3, NULL, ?, ?)",
        [("a", 0, "fa", "ua", 20, 0), ("b", 1, "fb", "ub", 0, 2), ("c", 2, "fc", "uc", 1, 1)],
    )
    db.executemany(
        "INSERT INTO image_reactions VALUES (?, ?, ?)",
        [("a", "10", "like"), ("b", "10", "dislike"), ("b", "11", "dislike"), ("c", "x", "like")],
    )
    db.executemany(
        "INSERT INTO image_chat_history VALUES (?, ?, ?)",
        [("-100", 0, "a"), ("duel:-100", 0, "b"), ("tournament:-100", 0, "c")],
    )
    db.executemany("INSERT INTO image_stats VALUES (?, ?)", [("total", 7), ("executions", 3)])
    db.commit()
    db.close()


class MigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def test_seed_rating_is_clamped(self) -> None:
        self.assertEqual(seed_rating(20, 0), 1150)
        self.assertEqual(seed_rating(0, 2), 970)
        self.assertEqual(seed_rating(1, 1), 1000)

    def test_history_scopes(self) -> None:
        self.assertEqual(history_scope("-100"), "pic:-100")
        self.assertEqual(history_scope("duel:-100"), "arena:-100")
        self.assertEqual(history_scope("tournament:-100"), "arena:-100")

    def test_migrates_and_leaves_v1_untouched(self) -> None:
        legacy = self.dir / "kartinkomet.sqlite"
        target = self.dir / "kartinkomet_v2.sqlite"
        build_v1(legacy)
        before = legacy.read_bytes()

        self.assertTrue(migrate_if_needed(legacy, target))
        self.assertFalse(migrate_if_needed(legacy, target))
        self.assertEqual(legacy.read_bytes(), before)
        self.assertFalse((self.dir / "kartinkomet_v2.sqlite.migrating").exists())

        repo = Repo(target)
        self.addCleanup(repo.close)
        self.assertEqual(repo.count_pics(), 3)
        self.assertEqual(repo.get_pic("a").rating, 1150)
        self.assertEqual(repo.db.execute("SELECT COUNT(*) FROM reactions").fetchone()[0], 3)
        scopes = dict(repo.db.execute("SELECT scope, COUNT(*) FROM deck_seen GROUP BY scope").fetchall())
        self.assertEqual(scopes, {"pic:-100": 1, "arena:-100": 2})
        self.assertEqual(repo.meta_int("v1_executions"), 3)
        self.assertEqual(repo.user_label(1), "@stoner")

    def test_no_legacy_means_fresh_start(self) -> None:
        self.assertFalse(migrate_if_needed(self.dir / "missing.sqlite", self.dir / "v2.sqlite"))

    @unittest.skipUnless(os.getenv("KARTINKOMET_REAL_DB"), "set KARTINKOMET_REAL_DB to a v1 backup")
    def test_real_backup(self) -> None:
        source = Path(os.environ["KARTINKOMET_REAL_DB"])
        legacy = self.dir / "kartinkomet.sqlite"
        for suffix in ("", "-wal", "-shm"):
            if Path(f"{source}{suffix}").exists():
                shutil.copy(f"{source}{suffix}", f"{legacy}{suffix}")
        old = sqlite3.connect(legacy)
        expected = old.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        old.close()
        self.assertTrue(migrate_if_needed(legacy, self.dir / "v2.sqlite"))
        repo = Repo(self.dir / "v2.sqlite")
        self.addCleanup(repo.close)
        self.assertEqual(repo.count_pics(), expected)


if __name__ == "__main__":
    unittest.main()

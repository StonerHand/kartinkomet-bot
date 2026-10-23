"""Mini-games: caption contest, golden pics, bosses."""

import sqlite3
from uuid import uuid4

from bot.db.repo.models import Pic, PIC_COLUMNS, _pic


class GamesRepo:
    db: sqlite3.Connection

    def create_game(self, kind: str, chat_id: int, pic_id: str, now: int, duration: int) -> str:
        game_id = uuid4().hex[:16]
        with self.db:
            self.db.execute(
                "INSERT INTO games (id, chat_id, kind, pic_id, phase_ends_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (game_id, chat_id, kind, pic_id, now + duration, now),
            )
        return game_id

    def get_game(self, game_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if row is None:
            return None
        game = dict(row)
        game["entries"] = [
            dict(entry)
            for entry in self.db.execute(
                "SELECT user_id, text, at FROM game_entries WHERE game_id = ? ORDER BY at, user_id", (game_id,)
            )
        ]
        game["votes"] = {
            vote["user_id"]: vote["author_id"]
            for vote in self.db.execute("SELECT user_id, author_id FROM game_votes WHERE game_id = ?", (game_id,))
        }
        return game

    def active_game(self, chat_id: int, kind: str) -> dict | None:
        row = self.db.execute(
            "SELECT id FROM games WHERE chat_id = ? AND kind = ? AND phase != 'done' LIMIT 1", (chat_id, kind)
        ).fetchone()
        return self.get_game(row[0]) if row else None

    def game_by_message(self, chat_id: int, message_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT id FROM games WHERE chat_id = ? AND message_id = ? LIMIT 1", (chat_id, message_id)
        ).fetchone()
        return self.get_game(row[0]) if row else None

    def active_game_ids(self) -> list[str]:
        return [row[0] for row in self.db.execute("SELECT id FROM games WHERE phase != 'done'")]

    def set_game_message(self, game_id: str, message_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE games SET message_id = ? WHERE id = ?", (message_id, game_id))

    def set_game_phase(self, game_id: str, phase: str, ends_at: int, expect: str) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE games SET phase = ?, phase_ends_at = ? WHERE id = ? AND phase = ?",
                (phase, ends_at, game_id, expect),
            )
        return cursor.rowcount == 1

    def drop_game(self, game_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM games WHERE id = ?", (game_id,))

    def put_game_entry(self, game_id: str, user_id: int, text: str, now: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO game_entries (game_id, user_id, text, at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(game_id, user_id) DO UPDATE SET text = excluded.text",
                (game_id, user_id, text, now),
            )

    def put_game_vote(self, game_id: str, user_id: int, author_id: int) -> bool:
        row = self.db.execute(
            "SELECT author_id FROM game_votes WHERE game_id = ? AND user_id = ?", (game_id, user_id)
        ).fetchone()
        if row is not None and row[0] == author_id:
            return False
        with self.db:
            self.db.execute(
                "INSERT INTO game_votes (game_id, user_id, author_id) VALUES (?, ?, ?) "
                "ON CONFLICT(game_id, user_id) DO UPDATE SET author_id = excluded.author_id",
                (game_id, user_id, author_id),
            )
        return True

    def uploaders(self) -> list[int]:
        """Everyone who has a living pic on the warehouse."""
        return [
            row[0] for row in self.db.execute(
                "SELECT DISTINCT added_by FROM pics WHERE status = 'alive' AND added_by IS NOT NULL ORDER BY added_by"
            )
        ]

    def create_gold(self, chat_id: int, pic_id: str, now: int) -> str:
        token = uuid4().hex[:12]
        with self.db:
            self.db.execute(
                "INSERT INTO gold (token, chat_id, pic_id, created_at) VALUES (?, ?, ?, ?)",
                (token, chat_id, pic_id, now),
            )
        return token

    def claim_gold(self, token: str, user_id: int) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE gold SET claimed_by = ? WHERE token = ? AND claimed_by IS NULL", (user_id, token)
            )
        return cursor.rowcount == 1

    def last_gold_at(self, chat_id: int) -> int:
        row = self.db.execute("SELECT MAX(created_at) FROM gold WHERE chat_id = ?", (chat_id,)).fetchone()
        return row[0] or 0

    def random_alive_of(self, owner_id: int) -> Pic | None:
        row = self.db.execute(
            f"SELECT {PIC_COLUMNS} FROM pics WHERE status = 'alive' AND added_by = ? ORDER BY random() LIMIT 1",
            (owner_id,),
        ).fetchone()
        return _pic(row)

    def shift_rating(self, pic_id: str, delta: float) -> None:
        with self.db:
            self.db.execute("UPDATE pics SET rating = rating + ? WHERE id = ?", (delta, pic_id))

    def create_boss(
        self, chat_id: int, pic_id: str, title: str, hp: int, loot: int, now: int, ends_at: int, raid: bool = False
    ) -> str:
        boss_id = uuid4().hex[:12]
        with self.db:
            self.db.execute(
                "INSERT INTO bosses (id, chat_id, pic_id, title, hp, max_hp, loot, started_at, ends_at, raid, last_hit_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (boss_id, chat_id, pic_id, title, hp, hp, loot, now, ends_at, int(raid), now),
            )
        return boss_id

    def get_boss(self, boss_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM bosses WHERE id = ?", (boss_id,)).fetchone()
        if row is None:
            return None
        boss = dict(row)
        boss["damage"] = {
            hit[0]: hit[1]
            for hit in self.db.execute(
                "SELECT user_id, damage FROM boss_hits WHERE boss_id = ? ORDER BY damage DESC", (boss_id,)
            )
        }
        return boss

    def active_boss(self, chat_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT id FROM bosses WHERE status = 'active' AND chat_id = ? LIMIT 1", (chat_id,)
        ).fetchone()
        return self.get_boss(row[0]) if row else None

    def active_boss_ids(self) -> list[str]:
        return [row[0] for row in self.db.execute("SELECT id FROM bosses WHERE status = 'active'")]

    def last_boss_at(self, chat_id: int) -> int:
        row = self.db.execute("SELECT MAX(started_at) FROM bosses WHERE chat_id = ?", (chat_id,)).fetchone()
        return row[0] or 0

    def set_boss_message(self, boss_id: str, message_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE bosses SET message_id = ? WHERE id = ?", (message_id, boss_id))

    def drop_boss(self, boss_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM bosses WHERE id = ?", (boss_id,))

    def hit_boss(self, boss_id: str, user_id: int, damage: int, now: int = 0) -> tuple[int, int] | None:
        """Apply damage to a live boss. Returns (hp left, total hits) or None if it's over."""
        with self.db:
            cursor = self.db.execute(
                "UPDATE bosses SET hp = MAX(0, hp - ?), hits = hits + 1, last_hit_by = ?, "
                "last_hit_at = COALESCE(NULLIF(?, 0), last_hit_at) "
                "WHERE id = ? AND status = 'active' AND hp > 0",
                (damage, user_id, now, boss_id),
            )
            if cursor.rowcount != 1:
                return None
            self.db.execute(
                "INSERT INTO boss_hits (boss_id, user_id, damage, hits) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(boss_id, user_id) DO UPDATE SET damage = damage + excluded.damage, hits = hits + 1",
                (boss_id, user_id, damage),
            )
        row = self.db.execute("SELECT hp, hits FROM bosses WHERE id = ?", (boss_id,)).fetchone()
        return row[0], row[1]

    def heal_boss(self, boss_id: str, amount: int, now: int) -> int:
        """Restore up to `amount` hp of a live boss and restart its idle clock. Returns hp now."""
        with self.db:
            self.db.execute(
                "UPDATE bosses SET hp = MIN(max_hp, hp + ?), last_hit_at = ? WHERE id = ? AND status = 'active' AND hp > 0",
                (amount, now, boss_id),
            )
        row = self.db.execute("SELECT hp FROM bosses WHERE id = ?", (boss_id,)).fetchone()
        return row[0] if row else 0

    def add_boss_loot(self, boss_id: str, amount: int) -> None:
        with self.db:
            self.db.execute("UPDATE bosses SET loot = loot + ? WHERE id = ?", (amount, boss_id))

    def close_boss(self, boss_id: str, status: str) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE bosses SET status = ? WHERE id = ? AND status = 'active'", (status, boss_id)
            )
        return cursor.rowcount == 1

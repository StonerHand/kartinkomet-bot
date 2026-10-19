"""Meta keys, users, the live panel and admin tools."""

import sqlite3
from pathlib import Path


class MetaRepo:
    db: sqlite3.Connection

    def meta_int(self, key: str, default: int = 0) -> int:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return int(row["value"]) if row else default

    def meta_str(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: int | str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def incr_meta(self, key: str, by: int = 1) -> int:
        value = self.meta_int(key) + by
        self.set_meta(key, value)
        return value

    def remember_user(
        self,
        user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        now: int,
    ) -> None:
        fingerprint = (username, first_name, last_name)
        if self._known_users.get(user_id) == fingerprint:
            return
        with self.db:
            self.db.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    updated_at = excluded.updated_at
                WHERE users.username IS NOT excluded.username
                   OR users.first_name IS NOT excluded.first_name
                   OR users.last_name IS NOT excluded.last_name
                """,
                (user_id, username, first_name, last_name, now, now),
            )
        self._known_users[user_id] = fingerprint

    def user_label(self, user_id: int | None) -> str:
        if user_id is None:
            return "аноним"
        row = self.db.execute(
            "SELECT username, first_name, last_name FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return str(user_id)
        # Never prefix "@": Telegram turns it into a mention and pings the person every time.
        if row["username"]:
            return str(row["username"]).lstrip("@")
        name = " ".join(part for part in (row["first_name"], row["last_name"]) if part).strip()
        return name or str(user_id)

    def all_user_ids(self) -> list[int]:
        return [
            row[0]
            for row in self.db.execute(
                "SELECT user_id FROM users UNION SELECT added_by FROM pics WHERE added_by IS NOT NULL"
            )
        ]

    def count_users(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def panel_message(self, chat_id: int) -> int | None:
        row = self.db.execute(
            "SELECT message_id FROM panels WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return row[0] if row else None

    def set_panel_message(self, chat_id: int, message_id: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO panels (chat_id, message_id) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET message_id = excluded.message_id",
                (chat_id, message_id),
            )

    def reset_stats(self) -> None:
        with self.db:
            self.db.execute(
                "UPDATE pics SET rating = 1000, games = 0, wins = 0, losses = 0, loss_streak = 0, "
                "best_streak = 0, shown_count = 0, last_shown_at = NULL, likes = 0, dislikes = 0"
            )
            self.db.execute("DELETE FROM reactions")
            self.db.execute("DELETE FROM deck_seen")
            self.db.execute("DELETE FROM meta WHERE key != 'schema_version'")

    def export_backup(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination) as backup:
            self.db.backup(backup)
        backup.close()

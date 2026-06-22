import json
import sqlite3
from pathlib import Path
from typing import Any


IMAGE_DUEL_STAT_KEYS = (
    "total",
    "executions",
    "ties",
    "tournaments",
    "tournament_ties",
)
SQLITE_DELETE_BATCH_SIZE = 500


class SQLiteDocumentStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path, timeout=30)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout=30000")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                name TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS images (
                id TEXT PRIMARY KEY,
                position INTEGER NOT NULL DEFAULT 0,
                file_id TEXT NOT NULL,
                file_unique_id TEXT NOT NULL UNIQUE,
                added_by INTEGER,
                added_at TEXT,
                visual_hash TEXT,
                shown_count INTEGER NOT NULL DEFAULT 0,
                last_shown_at TEXT,
                likes INTEGER NOT NULL DEFAULT 0,
                dislikes INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_images_added_by ON images(added_by);
            CREATE INDEX IF NOT EXISTS idx_images_shown ON images(shown_count, last_shown_at);

            CREATE TABLE IF NOT EXISTS image_reactions (
                image_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                reaction TEXT NOT NULL,
                PRIMARY KEY (image_id, user_id),
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS image_chat_history (
                chat_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                image_id TEXT NOT NULL,
                PRIMARY KEY (chat_id, position),
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS image_stats (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            );

            """
        )
        self._ensure_image_columns()
        self._connection.commit()
        self._connection.execute("PRAGMA optimize")

    def load(self, name: str) -> Any | None:
        row = self._connection.execute(
            "SELECT payload FROM documents WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None

        return json.loads(row[0])

    def save(self, name: str, payload: Any) -> None:
        serialized_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO documents (name, payload, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (name, serialized_payload),
            )

    def export_database(self, destination_path: Path) -> None:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination_path) as backup_connection:
            self._connection.backup(backup_connection)

    def load_image_pool(self) -> dict[str, Any] | None:
        image_rows = self._connection.execute(
            """
            SELECT id, file_id, file_unique_id, added_by, added_at, visual_hash,
                   shown_count, last_shown_at, likes, dislikes
            FROM images
            ORDER BY position, rowid
            """
        ).fetchall()
        user_rows = self._connection.execute(
            """
            SELECT user_id, username, first_name, last_name, updated_at
            FROM users
            ORDER BY user_id
            """
        ).fetchall()
        history_rows = self._connection.execute(
            """
            SELECT chat_id, image_id
            FROM image_chat_history
            ORDER BY chat_id, position
            """
        ).fetchall()
        stat_rows = self._connection.execute(
            "SELECT key, value FROM image_stats"
        ).fetchall()

        if not image_rows and not user_rows and not history_rows and not stat_rows:
            return None

        reactions = self._load_reactions("image_reactions", "image_id")
        records = [
            {
                "id": row["id"],
                "file_id": row["file_id"],
                "file_unique_id": row["file_unique_id"],
                "added_by": row["added_by"],
                "added_at": row["added_at"],
                "visual_hash": row["visual_hash"],
                "shown_count": row["shown_count"],
                "last_shown_at": row["last_shown_at"],
                "likes": row["likes"],
                "dislikes": row["dislikes"],
                "reactions_by_user": reactions.get(row["id"], {}),
            }
            for row in image_rows
        ]
        return {
            "version": self._stat_value(stat_rows, "version", 5),
            "images": records,
            "chat_history": self._history_from_rows(history_rows, "image_id"),
            "users": self._users_from_rows(user_rows),
            "duel_stats": {
                key: self._stat_value(stat_rows, key, 0)
                for key in IMAGE_DUEL_STAT_KEYS
            },
        }

    def save_image_pool(self, payload: dict[str, Any]) -> None:
        records = list(payload.get("images") or [])
        chat_history = dict(payload.get("chat_history") or {})
        users = dict(payload.get("users") or {})
        duel_stats = dict(payload.get("duel_stats") or {})

        with self._connection:
            self._connection.execute("DELETE FROM image_reactions")
            self._connection.execute("DELETE FROM image_chat_history")
            self._connection.execute("DELETE FROM images")
            self._connection.execute("DELETE FROM users")
            self._connection.execute("DELETE FROM image_stats")

            self._save_users(users)
            self._connection.executemany(
                """
                INSERT INTO images (
                    id, position, file_id, file_unique_id, added_by, added_at, visual_hash,
                    shown_count, last_shown_at, likes, dislikes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(record["id"]),
                        position,
                        str(record["file_id"]),
                        str(record["file_unique_id"]),
                        record.get("added_by"),
                        record.get("added_at"),
                        record.get("visual_hash"),
                        int(record.get("shown_count") or 0),
                        record.get("last_shown_at"),
                        int(record.get("likes") or 0),
                        int(record.get("dislikes") or 0),
                    )
                    for position, record in enumerate(records)
                ],
            )
            self._save_reactions("image_reactions", "image_id", records)
            self._save_history("image_chat_history", "image_id", chat_history)
            self._save_stats(
                "image_stats",
                {
                    "version": int(payload.get("version") or 5),
                    **{
                        key: int(duel_stats.get(key) or 0)
                        for key in IMAGE_DUEL_STAT_KEYS
                    },
                },
            )

    def insert_image(self, record: dict[str, Any]) -> None:
        with self._connection:
            next_position = self._connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM images"
            ).fetchone()[0]
            self._connection.execute(
                """
                INSERT INTO images (
                    id, position, file_id, file_unique_id, added_by, added_at, visual_hash,
                    shown_count, last_shown_at, likes, dislikes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record["id"]),
                    int(next_position),
                    str(record["file_id"]),
                    str(record["file_unique_id"]),
                    record.get("added_by"),
                    record.get("added_at"),
                    record.get("visual_hash"),
                    int(record.get("shown_count") or 0),
                    record.get("last_shown_at"),
                    int(record.get("likes") or 0),
                    int(record.get("dislikes") or 0),
                ),
            )

    def upsert_user(self, user: dict[str, Any]) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    updated_at = excluded.updated_at
                """,
                (
                    int(user["id"]),
                    user.get("username"),
                    user.get("first_name"),
                    user.get("last_name"),
                    user.get("updated_at"),
                ),
            )

    def update_image_reaction(
        self,
        image_id: str,
        user_id: int,
        reaction: str,
        likes: int,
        dislikes: int,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO image_reactions (image_id, user_id, reaction)
                VALUES (?, ?, ?)
                ON CONFLICT(image_id, user_id) DO UPDATE SET
                    reaction = excluded.reaction
                """,
                (image_id, str(user_id), reaction),
            )
            self._connection.execute(
                "UPDATE images SET likes = ?, dislikes = ? WHERE id = ?",
                (int(likes), int(dislikes), image_id),
            )

    def update_image_shows(
        self,
        records: list[dict[str, Any]],
        chat_updates: dict[str, tuple[list[str], set[str]]],
    ) -> None:
        unique_records = {str(record["id"]): record for record in records}
        with self._connection:
            self._connection.executemany(
                """
                UPDATE images
                SET shown_count = ?, last_shown_at = ?
                WHERE id = ?
                """,
                [
                    (
                        int(record.get("shown_count") or 0),
                        record.get("last_shown_at"),
                        image_id,
                    )
                    for image_id, record in unique_records.items()
                ],
            )
            for chat_id, (appended_ids, removed_ids) in chat_updates.items():
                ids_to_remove = set(appended_ids) | removed_ids
                if ids_to_remove:
                    placeholders = ",".join("?" for _ in ids_to_remove)
                    self._connection.execute(
                        f"""
                        DELETE FROM image_chat_history
                        WHERE chat_id = ? AND image_id IN ({placeholders})
                        """,
                        (str(chat_id), *sorted(ids_to_remove)),
                    )

                next_position = self._connection.execute(
                    """
                    SELECT COALESCE(MAX(position), -1) + 1
                    FROM image_chat_history
                    WHERE chat_id = ?
                    """,
                    (str(chat_id),),
                ).fetchone()[0]
                self._connection.executemany(
                    """
                    INSERT INTO image_chat_history (chat_id, position, image_id)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (str(chat_id), int(next_position) + offset, str(image_id))
                        for offset, image_id in enumerate(appended_ids)
                    ],
                )

    def delete_images(
        self,
        image_ids: set[str],
        stats: dict[str, int] | None = None,
    ) -> None:
        if not image_ids and stats is None:
            return

        with self._connection:
            if image_ids:
                sorted_ids = sorted(image_ids)
                for offset in range(0, len(sorted_ids), SQLITE_DELETE_BATCH_SIZE):
                    batch = sorted_ids[offset : offset + SQLITE_DELETE_BATCH_SIZE]
                    placeholders = ",".join("?" for _ in batch)
                    self._connection.execute(
                        f"DELETE FROM images WHERE id IN ({placeholders})",
                        tuple(batch),
                    )
            if stats is not None:
                self._save_stats("image_stats", stats)

    def save_image_stats(self, stats: dict[str, int]) -> None:
        with self._connection:
            self._save_stats("image_stats", stats)

    def reset_image_stats(self, stats: dict[str, int]) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE images
                SET shown_count = 0,
                    last_shown_at = NULL,
                    likes = 0,
                    dislikes = 0
                """
            )
            self._connection.execute("DELETE FROM image_reactions")
            self._connection.execute("DELETE FROM image_chat_history")
            self._connection.execute("DELETE FROM image_stats")
            self._save_stats("image_stats", stats)

    def _load_reactions(self, table: str, item_column: str) -> dict[str, dict[str, str]]:
        rows = self._connection.execute(
            f"SELECT {item_column}, user_id, reaction FROM {table}"
        ).fetchall()
        reactions: dict[str, dict[str, str]] = {}
        for row in rows:
            reactions.setdefault(row[item_column], {})[row["user_id"]] = row["reaction"]
        return reactions

    def _ensure_image_columns(self) -> None:
        columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(images)").fetchall()
        }
        if "visual_hash" not in columns:
            self._connection.execute("ALTER TABLE images ADD COLUMN visual_hash TEXT")
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_images_visual_hash ON images(visual_hash)"
        )

    def _history_from_rows(
        self,
        rows: list[sqlite3.Row],
        item_column: str,
    ) -> dict[str, list[str]]:
        history: dict[str, list[str]] = {}
        for row in rows:
            history.setdefault(row["chat_id"], []).append(row[item_column])
        return history

    def _users_from_rows(self, rows: list[sqlite3.Row]) -> dict[str, dict[str, Any]]:
        return {
            str(row["user_id"]): {
                "id": row["user_id"],
                "username": row["username"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def _save_users(self, users: dict[str, Any]) -> None:
        self._connection.executemany(
            """
            INSERT INTO users (user_id, username, first_name, last_name, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    int(user.get("id") or user_id),
                    user.get("username"),
                    user.get("first_name"),
                    user.get("last_name"),
                    user.get("updated_at"),
                )
                for user_id, user in users.items()
                if isinstance(user, dict)
            ],
        )

    def _save_reactions(self, table: str, item_column: str, records: list[dict]) -> None:
        self._connection.executemany(
            f"""
            INSERT INTO {table} ({item_column}, user_id, reaction)
            VALUES (?, ?, ?)
            """,
            [
                (str(record["id"]), str(user_id), str(reaction))
                for record in records
                for user_id, reaction in dict(record.get("reactions_by_user") or {}).items()
            ],
        )

    def _save_history(
        self,
        table: str,
        item_column: str,
        chat_history: dict[str, list[str]],
    ) -> None:
        self._connection.executemany(
            f"""
            INSERT INTO {table} (chat_id, position, {item_column})
            VALUES (?, ?, ?)
            """,
            [
                (str(chat_id), position, str(item_id))
                for chat_id, history in chat_history.items()
                for position, item_id in enumerate(history)
            ],
        )

    def _save_stats(self, table: str, stats: dict[str, int]) -> None:
        self._connection.executemany(
            f"""
            INSERT INTO {table} (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            [(key, int(value)) for key, value in stats.items()],
        )

    def _stat_value(
        self,
        rows: list[sqlite3.Row],
        key: str,
        default: int,
    ) -> int:
        for row in rows:
            if row["key"] == key:
                return int(row["value"])
        return default

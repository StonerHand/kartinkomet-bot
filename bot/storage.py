import json
import sqlite3
from pathlib import Path
from typing import Any


class SQLiteDocumentStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path, timeout=30)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                name TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._connection.commit()

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

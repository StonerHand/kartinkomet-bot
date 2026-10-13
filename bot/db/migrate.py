"""One-shot migration of the v1 database (kartinkomet.sqlite) into a fresh v2 file.

The v1 file is opened read-only and never modified, so rolling back to v1 code
is always possible. The v2 file is built under a temporary name and renamed
into place only after the row counts check out.
"""

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from bot.db.repo import apply_schema, connect

LOGGER = logging.getLogger(__name__)
SEED_PER_REACTION = 15
SEED_LIMIT = 150


class MigrationError(RuntimeError):
    pass


def seed_rating(likes: int, dislikes: int) -> float:
    delta = SEED_PER_REACTION * (likes - dislikes)
    return 1000.0 + max(-SEED_LIMIT, min(SEED_LIMIT, delta))


def iso_to_epoch(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def history_scope(chat_key: str) -> str:
    kind, _, chat_id = chat_key.rpartition(":")
    if kind in ("duel", "tournament"):
        return f"arena:{chat_id}"
    return f"pic:{chat_key}"


def migrate_if_needed(legacy_path: Path, target_path: Path) -> bool:
    """Build target_path from legacy_path. Returns True if a migration ran."""
    if target_path.exists() or not legacy_path.exists():
        return False

    temp_path = target_path.with_name(target_path.name + ".migrating")
    for leftover in (temp_path, Path(f"{temp_path}-wal"), Path(f"{temp_path}-shm")):
        leftover.unlink(missing_ok=True)

    legacy = sqlite3.connect(f"file:{legacy_path}?mode=ro", uri=True)
    legacy.row_factory = sqlite3.Row
    target = connect(temp_path)
    try:
        apply_schema(target)
        counts = _copy(legacy, target)
        _verify(target, counts)
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        target.close()
        legacy.close()

    temp_path.replace(target_path)
    for leftover in (Path(f"{temp_path}-wal"), Path(f"{temp_path}-shm")):
        leftover.unlink(missing_ok=True)
    LOGGER.info("Migrated v1 database: %s", counts)
    return True


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _copy(legacy: sqlite3.Connection, target: sqlite3.Connection) -> dict[str, int]:
    tables = _tables(legacy)
    if "images" not in tables:
        raise MigrationError("Legacy database has no images table")

    now = int(datetime.now(UTC).timestamp())
    users = [
        (
            row["user_id"],
            row["username"],
            row["first_name"],
            row["last_name"],
            iso_to_epoch(row["updated_at"]) or now,
            iso_to_epoch(row["updated_at"]) or now,
        )
        for row in legacy.execute("SELECT * FROM users")
    ] if "users" in tables else []

    pics = [
        (
            row["id"],
            row["file_id"],
            row["file_unique_id"],
            row["added_by"],
            iso_to_epoch(row["added_at"]),
            row["visual_hash"],
            seed_rating(row["likes"], row["dislikes"]),
            row["shown_count"],
            iso_to_epoch(row["last_shown_at"]),
            row["likes"],
            row["dislikes"],
        )
        for row in legacy.execute("SELECT * FROM images ORDER BY position, rowid")
    ]
    pic_ids = {pic[0] for pic in pics}

    reactions = []
    if "image_reactions" in tables:
        for row in legacy.execute("SELECT * FROM image_reactions"):
            if row["image_id"] not in pic_ids or row["reaction"] not in ("like", "dislike"):
                continue
            try:
                user_id = int(row["user_id"])
            except (TypeError, ValueError):
                continue
            reactions.append(
                # v1 didn't record when a reaction happened: 0 keeps them out of "this week" stats.
                (row["image_id"], user_id, 1 if row["reaction"] == "like" else -1, 0)
            )

    seen = set()
    if "image_chat_history" in tables:
        for row in legacy.execute("SELECT chat_id, image_id FROM image_chat_history"):
            if row["image_id"] in pic_ids:
                seen.add((history_scope(str(row["chat_id"])), row["image_id"]))

    stats = {}
    if "image_stats" in tables:
        stats = {row["key"]: int(row["value"]) for row in legacy.execute("SELECT * FROM image_stats")}

    with target:
        target.executemany(
            "INSERT INTO users (user_id, username, first_name, last_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            users,
        )
        target.executemany(
            """
            INSERT INTO pics (id, file_id, file_unique_id, added_by, added_at, visual_hash,
                              rating, shown_count, last_shown_at, likes, dislikes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            pics,
        )
        target.executemany(
            "INSERT INTO reactions (pic_id, user_id, value, at) VALUES (?, ?, ?, ?)",
            reactions,
        )
        target.executemany("INSERT INTO deck_seen (scope, pic_id) VALUES (?, ?)", sorted(seen))
        for key in ("total", "executions", "ties", "tournaments", "tournament_ties"):
            target.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                (f"v1_{key}", str(stats.get(key, 0))),
            )
        target.execute(
            "INSERT INTO meta (key, value) VALUES ('migrated_from_v1_at', ?)", (str(now),)
        )

    return {"users": len(users), "pics": len(pics), "reactions": len(reactions)}


def _verify(target: sqlite3.Connection, expected: dict[str, int]) -> None:
    actual = {
        "users": target.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "pics": target.execute("SELECT COUNT(*) FROM pics").fetchone()[0],
        "reactions": target.execute("SELECT COUNT(*) FROM reactions").fetchone()[0],
    }
    if actual != expected:
        raise MigrationError(f"Row counts differ after migration: {expected} → {actual}")

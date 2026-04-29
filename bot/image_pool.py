import json
import random
from bisect import bisect_left, insort
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from heapq import nlargest
from pathlib import Path
from uuid import uuid4

from aiogram.types import Message, User

REACTION_FIELDS = {
    "like": "likes",
    "fire": "fires",
    "dislike": "dislikes",
}
STORAGE_VERSION = 3
MAX_CHAT_HISTORY = 500
UPLOAD_LIMIT_PER_HOUR = 100
RANDOM = random.SystemRandom()


@dataclass(frozen=True)
class AddResult:
    added: bool
    duplicate: bool = False
    rate_limited: bool = False


@dataclass(frozen=True)
class ImageRecord:
    id: str
    file_id: str
    likes: int = 0
    fires: int = 0
    dislikes: int = 0


@dataclass(frozen=True)
class ReactionUpdate:
    image: ImageRecord
    changed: bool


@dataclass(frozen=True)
class PoolStats:
    total_images: int
    total_shows: int
    total_likes: int
    total_fires: int
    total_dislikes: int
    total_duels: int
    duel_executions: int
    duel_ties: int


@dataclass(frozen=True)
class UserReactionStats:
    uploaded: int
    likes: int
    fires: int
    dislikes: int
    shown: int


@dataclass(frozen=True)
class DedupeResult:
    user_id: int
    scanned: int
    removed: int
    remaining: int


class ImagePool:
    def __init__(self, storage_path: str) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._records, self._chat_history, self._users, self._duel_stats = self._load()
        self._rebuild_indexes()

    def count(self) -> int:
        return len(self._records)

    def random_image(
        self,
        avoid_recent: bool = True,
        chat_id: int | str | None = None,
    ) -> ImageRecord | None:
        if not self._records:
            return None

        records = self._selectable_records(avoid_recent=avoid_recent, chat_id=chat_id)
        record = RANDOM.choice(records)
        self._mark_shown(record, chat_id=chat_id)
        return self._to_image_record(record)

    def add_from_message(self, message: Message) -> AddResult:
        self.remember_user(message.from_user)
        image_data = self._extract_image_data(message)
        if image_data is None:
            return AddResult(added=False)

        file_id, file_unique_id = image_data
        if file_unique_id in self._unique_ids:
            return AddResult(added=False, duplicate=True)

        user_id = message.from_user.id if message.from_user else None
        if isinstance(user_id, int) and self.user_uploads_in_last_hour(user_id) >= UPLOAD_LIMIT_PER_HOUR:
            return AddResult(added=False, rate_limited=True)

        record = self._normalize_record(
            {
                "id": uuid4().hex,
                "file_id": file_id,
                "file_unique_id": file_unique_id,
                "added_by": user_id,
                "added_at": datetime.now(UTC).isoformat(),
            }
        )
        self._records.append(record)
        self._index_record(record)
        self._write()
        return AddResult(added=True)

    def react(self, image_id: str, reaction: str, user_id: int) -> ReactionUpdate | None:
        field = REACTION_FIELDS.get(reaction)
        if field is None:
            return None

        record = self._find(image_id)
        if record is None:
            return None

        reactions_by_user = record["reactions_by_user"]
        user_key = str(user_id)
        previous_reaction = reactions_by_user.get(user_key)
        if previous_reaction == reaction:
            return ReactionUpdate(image=self._to_image_record(record), changed=False)

        if previous_reaction in REACTION_FIELDS:
            previous_field = REACTION_FIELDS[previous_reaction]
            record[previous_field] = max(0, record[previous_field] - 1)

        reactions_by_user[user_key] = reaction
        record[field] += 1
        self._write()
        return ReactionUpdate(image=self._to_image_record(record), changed=True)

    def delete(self, image_id: str) -> bool:
        record = self._find(image_id)
        if record is None:
            return False

        self._records.remove(record)
        self._remove_from_chat_history({image_id})
        self._rebuild_indexes()
        self._write()
        return True

    def finish_duel(self, loser_id: str | None) -> bool:
        removed = False
        if loser_id is None:
            self._duel_stats["ties"] += 1
        else:
            record = self._find(loser_id)
            if record is not None:
                self._records.remove(record)
                self._remove_from_chat_history({loser_id})
                self._rebuild_indexes()
                removed = True
            self._duel_stats["executions"] += 1

        self._duel_stats["total"] += 1
        self._write()
        return removed

    def stats(self) -> PoolStats:
        return PoolStats(
            total_images=len(self._records),
            total_shows=sum(record["shown_count"] for record in self._records),
            total_likes=sum(record["likes"] for record in self._records),
            total_fires=sum(record["fires"] for record in self._records),
            total_dislikes=sum(record["dislikes"] for record in self._records),
            total_duels=self._duel_stats["total"],
            duel_executions=self._duel_stats["executions"],
            duel_ties=self._duel_stats["ties"],
        )

    def record_duel_result(self, *, tied: bool) -> None:
        self._duel_stats["total"] += 1
        if tied:
            self._duel_stats["ties"] += 1
        else:
            self._duel_stats["executions"] += 1
        self._write()

    def reset_stats(self) -> None:
        for record in self._records:
            record["shown_count"] = 0
            record["last_shown_at"] = None
            record["likes"] = 0
            record["fires"] = 0
            record["dislikes"] = 0
            record["reactions_by_user"] = {}

        self._chat_history.clear()
        self._duel_stats = self._normalize_duel_stats({})
        self._write()

    def count_by_user(self, user_id: int) -> int:
        return self._uploads_by_user.get(user_id, 0)

    def reaction_stats_by_user(self, user_id: int) -> UserReactionStats:
        records = self._records_by_user.get(user_id, [])
        return UserReactionStats(
            uploaded=len(records),
            likes=sum(record["likes"] for record in records),
            fires=sum(record["fires"] for record in records),
            dislikes=sum(record["dislikes"] for record in records),
            shown=sum(record["shown_count"] for record in records),
        )

    def user_uploads_in_last_hour(self, user_id: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=1)
        upload_times = self._upload_times_by_user.get(user_id, [])
        return len(upload_times) - bisect_left(upload_times, cutoff)

    def top_uploaders(self, limit: int = 10) -> list[tuple[int, int]]:
        return sorted(
            self._uploads_by_user.items(),
            key=lambda item: (-item[1], item[0]),
        )[:limit]

    def dedupe_user(self, user_id: int) -> DedupeResult:
        scanned = self._uploads_by_user.get(user_id, 0)
        if scanned == 0:
            return DedupeResult(user_id=user_id, scanned=0, removed=0, remaining=0)

        seen_unique_ids: set[str] = set()
        kept_records = []
        removed_ids: set[str] = set()
        for record in self._records:
            file_unique_id = record["file_unique_id"]
            is_target_user_duplicate = (
                record.get("added_by") == user_id and file_unique_id in seen_unique_ids
            )
            if is_target_user_duplicate:
                removed_ids.add(record["id"])
                continue

            kept_records.append(record)
            seen_unique_ids.add(file_unique_id)
        if not removed_ids:
            return DedupeResult(
                user_id=user_id,
                scanned=scanned,
                removed=0,
                remaining=scanned,
            )

        self._records = kept_records
        self._remove_from_chat_history(removed_ids)
        self._rebuild_indexes()
        self._write()
        return DedupeResult(
            user_id=user_id,
            scanned=scanned,
            removed=len(removed_ids),
            remaining=self._uploads_by_user.get(user_id, 0),
        )

    def remember_user(self, user: User | None) -> None:
        if user is None:
            return

        user_key = str(user.id)
        existing_user = self._users.get(user_key)
        if (
            existing_user
            and existing_user.get("username") == user.username
            and existing_user.get("first_name") == user.first_name
            and existing_user.get("last_name") == user.last_name
        ):
            return

        user_data = {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self._users[user_key] = user_data
        self._write()

    def user_label(self, user_id: int) -> str:
        user = self._users.get(str(user_id))
        if not user:
            return str(user_id)

        username = user.get("username")
        if username:
            return str(username).lstrip("@")

        full_name = " ".join(
            part
            for part in [user.get("first_name"), user.get("last_name")]
            if part
        ).strip()
        return full_name or str(user_id)

    def _selectable_records(
        self,
        avoid_recent: bool,
        chat_id: int | str | None,
    ) -> list[dict]:
        if not avoid_recent or len(self._records) == 1:
            return self._records

        records = self._records
        chat_records = self._chat_fresh_records(chat_id)
        if chat_records:
            records = chat_records

        shown_records = [record for record in self._records if record.get("last_shown_at")]
        recent_limit = min(
            max(1, len(self._records) // 2),
            25,
            len(self._records) - 1,
            len(shown_records),
        )
        recent_ids = {
            record["id"]
            for record in nlargest(
                recent_limit,
                shown_records,
                key=lambda record: record.get("last_shown_at") or "",
            )
        }
        fresh_records = [record for record in records if record["id"] not in recent_ids]
        records = fresh_records or records
        lowest_shown_count = min(record["shown_count"] for record in records)
        least_shown_records = [
            record for record in records if record["shown_count"] == lowest_shown_count
        ]
        return least_shown_records or records

    def _chat_fresh_records(self, chat_id: int | str | None) -> list[dict]:
        if chat_id is None:
            return []

        history = self._chat_history.get(str(chat_id), [])
        if not history:
            return self._records

        history_ids = set(history)
        fresh_records = [record for record in self._records if record["id"] not in history_ids]
        if fresh_records:
            return fresh_records

        self._chat_history[str(chat_id)] = history[-1:]
        last_id = set(self._chat_history[str(chat_id)])
        return [record for record in self._records if record["id"] not in last_id] or self._records

    def _mark_shown(self, record: dict, chat_id: int | str | None) -> None:
        record["shown_count"] += 1
        record["last_shown_at"] = datetime.now(UTC).isoformat()
        self._remember_chat_show(record["id"], chat_id)
        self._write()

    def _remember_chat_show(self, image_id: str, chat_id: int | str | None) -> None:
        if chat_id is None:
            return

        chat_key = str(chat_id)
        history = self._chat_history.setdefault(chat_key, [])
        history[:] = [shown_id for shown_id in history if shown_id != image_id]
        history.append(image_id)

        max_history = min(MAX_CHAT_HISTORY, max(1, len(self._records) - 1))
        if len(history) > max_history:
            del history[:-max_history]

    def _remove_from_chat_history(self, image_ids: set[str]) -> None:
        for chat_key, history in list(self._chat_history.items()):
            history[:] = [shown_id for shown_id in history if shown_id not in image_ids]
            if not history:
                del self._chat_history[chat_key]

    def _find(self, image_id: str) -> dict | None:
        return self._record_by_id.get(image_id)

    def _to_image_record(self, record: dict) -> ImageRecord:
        return ImageRecord(
            id=record["id"],
            file_id=record["file_id"],
            likes=record["likes"],
            fires=record["fires"],
            dislikes=record["dislikes"],
        )

    def _added_at_datetime(self, record: dict) -> datetime | None:
        added_at = record.get("added_at")
        if not isinstance(added_at, str):
            return None

        try:
            value = datetime.fromisoformat(added_at)
        except ValueError:
            return None

        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _extract_image_data(self, message: Message) -> tuple[str, str] | None:
        if message.photo:
            photo = message.photo[-1]
            return photo.file_id, photo.file_unique_id

        if message.document and message.document.mime_type:
            if message.document.mime_type.startswith("image/"):
                return message.document.file_id, message.document.file_unique_id

        return None

    def _load(self) -> tuple[list[dict], dict[str, list[str]], dict[str, dict], dict[str, int]]:
        if not self.storage_path.exists():
            duel_stats = self._normalize_duel_stats({})
            self._atomic_write([], {}, {}, duel_stats)
            return [], {}, {}, duel_stats

        with self.storage_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        needs_write = False
        if isinstance(data, list):
            raw_records = data
            raw_chat_history = {}
            raw_users = {}
            raw_duel_stats = {}
            needs_write = True
        elif isinstance(data, dict):
            raw_records = data.get("images")
            raw_chat_history = data.get("chat_history", {})
            raw_users = data.get("users", {})
            raw_duel_stats = data.get("duel_stats", {})
            needs_write = data.get("version") != STORAGE_VERSION
        else:
            raise RuntimeError(f"{self.storage_path} must contain a JSON list or object.")

        if not isinstance(raw_records, list):
            raise RuntimeError(f"{self.storage_path} must contain an images list.")

        records = [self._normalize_record(item) for item in raw_records]
        if records != raw_records:
            needs_write = True

        seen_unique_ids: set[str] = set()
        deduped = []
        for record in records:
            uid = record["file_unique_id"]
            if uid not in seen_unique_ids:
                seen_unique_ids.add(uid)
                deduped.append(record)
        if len(deduped) != len(records):
            records = deduped
            needs_write = True

        chat_history = self._normalize_chat_history(raw_chat_history, records)
        if chat_history != raw_chat_history:
            needs_write = True

        users = self._normalize_users(raw_users)
        if users != raw_users:
            needs_write = True

        duel_stats = self._normalize_duel_stats(raw_duel_stats)
        if duel_stats != raw_duel_stats:
            needs_write = True

        if needs_write:
            self._atomic_write(records, chat_history, users, duel_stats)

        return records, chat_history, users, duel_stats

    def _normalize_record(self, item: object) -> dict:
        if isinstance(item, str):
            return {
                "id": uuid4().hex,
                "file_id": item,
                "file_unique_id": item,
                "added_by": None,
                "added_at": None,
                "shown_count": 0,
                "last_shown_at": None,
                "likes": 0,
                "fires": 0,
                "dislikes": 0,
                "reactions_by_user": {},
            }

        if not isinstance(item, dict) or "file_id" not in item:
            raise RuntimeError(f"{self.storage_path} contains an invalid image record.")

        file_id = str(item["file_id"])
        added_by = item.get("added_by")
        if isinstance(added_by, str) and added_by.isdigit():
            added_by = int(added_by)

        reactions_by_user = self._normalize_reactions(item.get("reactions_by_user"))
        if reactions_by_user:
            reaction_totals = self._reaction_totals(reactions_by_user)
        else:
            reaction_totals = {
                "likes": int(item.get("likes") or 0),
                "fires": int(item.get("fires") or 0),
                "dislikes": int(item.get("dislikes") or 0),
            }

        return {
            "id": str(item.get("id") or uuid4().hex),
            "file_id": file_id,
            "file_unique_id": str(item.get("file_unique_id") or file_id),
            "added_by": added_by,
            "added_at": item.get("added_at"),
            "shown_count": int(item.get("shown_count") or 0),
            "last_shown_at": item.get("last_shown_at"),
            "likes": reaction_totals["likes"],
            "fires": reaction_totals["fires"],
            "dislikes": reaction_totals["dislikes"],
            "reactions_by_user": reactions_by_user,
        }

    def _normalize_reactions(self, item: object) -> dict[str, str]:
        if not isinstance(item, dict):
            return {}

        return {
            str(user_id): reaction
            for user_id, reaction in item.items()
            if reaction in REACTION_FIELDS
        }

    def _reaction_totals(self, reactions_by_user: dict[str, str]) -> dict[str, int]:
        totals = {"likes": 0, "fires": 0, "dislikes": 0}
        for reaction in reactions_by_user.values():
            totals[REACTION_FIELDS[reaction]] += 1

        return totals

    def _write(self) -> None:
        self._atomic_write(self._records, self._chat_history, self._users, self._duel_stats)

    def _rebuild_indexes(self) -> None:
        self._record_by_id: dict[str, dict] = {}
        self._unique_ids: set[str] = set()
        self._uploads_by_user: dict[int, int] = {}
        self._records_by_user: dict[int, list[dict]] = {}
        self._upload_times_by_user: dict[int, list[datetime]] = {}
        for record in self._records:
            self._index_record(record, keep_upload_times_sorted=False)
        for upload_times in self._upload_times_by_user.values():
            upload_times.sort()

    def _index_record(self, record: dict, keep_upload_times_sorted: bool = True) -> None:
        self._record_by_id[record["id"]] = record
        self._unique_ids.add(record["file_unique_id"])
        if isinstance(record["added_by"], int):
            self._uploads_by_user[record["added_by"]] = (
                self._uploads_by_user.get(record["added_by"], 0) + 1
            )
            self._records_by_user.setdefault(record["added_by"], []).append(record)
            added_at = self._added_at_datetime(record)
            if added_at is not None:
                upload_times = self._upload_times_by_user.setdefault(record["added_by"], [])
                if keep_upload_times_sorted and upload_times and added_at < upload_times[-1]:
                    insort(upload_times, added_at)
                else:
                    upload_times.append(added_at)

    def _normalize_chat_history(
        self,
        item: object,
        records: list[dict],
    ) -> dict[str, list[str]]:
        if not isinstance(item, dict):
            return {}

        record_ids = {record["id"] for record in records}
        max_history = min(MAX_CHAT_HISTORY, max(1, len(record_ids) - 1)) if record_ids else 0
        chat_history: dict[str, list[str]] = {}
        for chat_id, history in item.items():
            if not isinstance(history, list):
                continue

            seen_ids: set[str] = set()
            valid_history = []
            for image_id in history:
                image_key = str(image_id)
                if image_key in record_ids and image_key not in seen_ids:
                    valid_history.append(image_key)
                    seen_ids.add(image_key)

            if max_history:
                valid_history = valid_history[-max_history:]
            if valid_history:
                chat_history[str(chat_id)] = valid_history

        return chat_history

    def _normalize_users(self, item: object) -> dict[str, dict]:
        if not isinstance(item, dict):
            return {}

        users: dict[str, dict] = {}
        for user_id, user in item.items():
            if not isinstance(user, dict):
                continue

            try:
                normalized_id = int(user.get("id") or user_id)
            except (TypeError, ValueError):
                continue

            users[str(normalized_id)] = {
                "id": normalized_id,
                "username": user.get("username"),
                "first_name": user.get("first_name"),
                "last_name": user.get("last_name"),
                "updated_at": user.get("updated_at"),
            }

        return users

    def _normalize_duel_stats(self, item: object) -> dict[str, int]:
        if not isinstance(item, dict):
            item = {}

        def normalized_count(key: str) -> int:
            try:
                return max(0, int(item.get(key) or 0))
            except (TypeError, ValueError):
                return 0

        stats = {
            "total": normalized_count("total"),
            "executions": normalized_count("executions"),
            "ties": normalized_count("ties"),
        }
        stats["total"] = max(stats["total"], stats["executions"] + stats["ties"])
        return stats

    def _atomic_write(
        self,
        records: list[dict],
        chat_history: dict[str, list[str]],
        users: dict[str, dict],
        duel_stats: dict[str, int],
    ) -> None:
        temp_path = self.storage_path.with_suffix(f"{self.storage_path.suffix}.tmp")
        payload = {
            "version": STORAGE_VERSION,
            "images": records,
            "chat_history": chat_history,
            "users": users,
            "duel_stats": duel_stats,
        }
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, separators=(",", ":"))
            file.write("\n")

        temp_path.replace(self.storage_path)

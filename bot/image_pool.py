import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from aiogram.types import Message

REACTION_FIELDS = {
    "like": "likes",
    "fire": "fires",
    "dislike": "dislikes",
}


@dataclass(frozen=True)
class AddResult:
    added: bool
    duplicate: bool = False


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


class ImagePool:
    def __init__(self, storage_path: str) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._records = self._load()

    def count(self) -> int:
        return len(self._records)

    def random_image(self, avoid_recent: bool = True) -> ImageRecord | None:
        if not self._records:
            return None

        records = self._selectable_records(avoid_recent=avoid_recent)
        record = random.choice(records)
        self._mark_shown(record)
        return self._to_image_record(record)

    def add_from_message(self, message: Message) -> AddResult:
        image_data = self._extract_image_data(message)
        if image_data is None:
            return AddResult(added=False)

        file_id, file_unique_id = image_data
        if any(record["file_unique_id"] == file_unique_id for record in self._records):
            return AddResult(added=False, duplicate=True)

        self._records.append(
            self._normalize_record(
                {
                    "id": uuid4().hex,
                    "file_id": file_id,
                    "file_unique_id": file_unique_id,
                    "added_by": message.from_user.id if message.from_user else None,
                    "added_at": datetime.now(UTC).isoformat(),
                }
            )
        )
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
        original_count = len(self._records)
        self._records = [record for record in self._records if record["id"] != image_id]
        if len(self._records) == original_count:
            return False

        self._write()
        return True

    def stats(self) -> PoolStats:
        return PoolStats(
            total_images=len(self._records),
            total_shows=sum(record["shown_count"] for record in self._records),
            total_likes=sum(record["likes"] for record in self._records),
            total_fires=sum(record["fires"] for record in self._records),
            total_dislikes=sum(record["dislikes"] for record in self._records),
        )

    def reset_stats(self) -> None:
        for record in self._records:
            record["shown_count"] = 0
            record["last_shown_at"] = None
            record["likes"] = 0
            record["fires"] = 0
            record["dislikes"] = 0
            record["reactions_by_user"] = {}

        self._write()

    def count_by_user(self, user_id: int) -> int:
        return sum(1 for record in self._records if record["added_by"] == user_id)

    def _selectable_records(self, avoid_recent: bool) -> list[dict]:
        if not avoid_recent or len(self._records) == 1:
            return self._records

        shown_records = [record for record in self._records if record.get("last_shown_at")]
        recent_limit = min(
            max(1, len(self._records) // 2),
            25,
            len(self._records) - 1,
            len(shown_records),
        )
        recent_ids = {
            record["id"]
            for record in sorted(
                shown_records,
                key=lambda record: record.get("last_shown_at") or "",
                reverse=True,
            )[:recent_limit]
        }
        fresh_records = [record for record in self._records if record["id"] not in recent_ids]
        records = fresh_records or self._records
        lowest_shown_count = min(record["shown_count"] for record in records)
        least_shown_records = [
            record for record in records if record["shown_count"] == lowest_shown_count
        ]
        return least_shown_records or records

    def _mark_shown(self, record: dict) -> None:
        record["shown_count"] += 1
        record["last_shown_at"] = datetime.now(UTC).isoformat()
        self._write()

    def _find(self, image_id: str) -> dict | None:
        return next((record for record in self._records if record["id"] == image_id), None)

    def _to_image_record(self, record: dict) -> ImageRecord:
        return ImageRecord(
            id=record["id"],
            file_id=record["file_id"],
            likes=record["likes"],
            fires=record["fires"],
            dislikes=record["dislikes"],
        )

    def _extract_image_data(self, message: Message) -> tuple[str, str] | None:
        if message.photo:
            photo = message.photo[-1]
            return photo.file_id, photo.file_unique_id

        if message.document and message.document.mime_type:
            if message.document.mime_type.startswith("image/"):
                return message.document.file_id, message.document.file_unique_id

        return None

    def _load(self) -> list[dict]:
        if not self.storage_path.exists():
            self._atomic_write([])
            return []

        with self.storage_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            raise RuntimeError(f"{self.storage_path} must contain a JSON list.")

        records = [self._normalize_record(item) for item in data]
        if records != data:
            self._atomic_write(records)

        return records

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
        return {
            "id": str(item.get("id") or uuid4().hex),
            "file_id": file_id,
            "file_unique_id": str(item.get("file_unique_id") or file_id),
            "added_by": item.get("added_by"),
            "added_at": item.get("added_at"),
            "shown_count": int(item.get("shown_count") or 0),
            "last_shown_at": item.get("last_shown_at"),
            "likes": int(item.get("likes") or 0),
            "fires": int(item.get("fires") or 0),
            "dislikes": int(item.get("dislikes") or 0),
            "reactions_by_user": dict(item.get("reactions_by_user") or {}),
        }

    def _write(self) -> None:
        self._atomic_write(self._records)

    def _atomic_write(self, records: list[dict]) -> None:
        temp_path = self.storage_path.with_suffix(f"{self.storage_path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(records, file, ensure_ascii=False, indent=2)
            file.write("\n")

        temp_path.replace(self.storage_path)

import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from aiogram.types import Message


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
        if not self.storage_path.exists():
            self._write([])

    def count(self) -> int:
        return len(self._read())

    def random_image(self, avoid_recent: bool = False) -> ImageRecord | None:
        records = self._read()
        if not records:
            return None

        if avoid_recent and len(records) > 1:
            recent_ids = {
                record["id"]
                for record in sorted(
                    records,
                    key=lambda record: record.get("last_shown_at") or "",
                    reverse=True,
                )[: min(10, len(records) - 1)]
            }
            fresh_records = [record for record in records if record["id"] not in recent_ids]
            if fresh_records:
                records = fresh_records

        record = random.choice(records)
        self.mark_shown(record["id"])
        return self._to_image_record(record)

    def add_from_message(self, message: Message) -> AddResult:
        image_data = self._extract_image_data(message)
        if image_data is None:
            return AddResult(added=False)

        file_id, file_unique_id = image_data
        records = self._read()
        if any(record["file_unique_id"] == file_unique_id for record in records):
            return AddResult(added=False, duplicate=True)

        records.append(
            {
                "id": uuid4().hex,
                "file_id": file_id,
                "file_unique_id": file_unique_id,
                "added_by": message.from_user.id if message.from_user else None,
                "added_at": datetime.now(UTC).isoformat(),
            }
        )
        self._write(records)
        return AddResult(added=True)

    def react(self, image_id: str, reaction: str) -> ImageRecord | None:
        reaction_fields = {
            "like": "likes",
            "fire": "fires",
            "dislike": "dislikes",
        }
        field = reaction_fields.get(reaction)
        if field is None:
            return None

        records = self._read()
        for record in records:
            if record["id"] == image_id:
                record[field] += 1
                self._write(records)
                return self._to_image_record(record)

        return None

    def mark_shown(self, image_id: str) -> None:
        records = self._read()
        for record in records:
            if record["id"] == image_id:
                record["shown_count"] += 1
                record["last_shown_at"] = datetime.now(UTC).isoformat()
                self._write(records)
                return

    def stats(self) -> PoolStats:
        records = self._read()
        return PoolStats(
            total_images=len(records),
            total_shows=sum(record["shown_count"] for record in records),
            total_likes=sum(record["likes"] for record in records),
            total_fires=sum(record["fires"] for record in records),
            total_dislikes=sum(record["dislikes"] for record in records),
        )

    def count_by_user(self, user_id: int) -> int:
        return sum(1 for record in self._read() if record["added_by"] == user_id)

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

    def _read(self) -> list[dict]:
        with self.storage_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            raise RuntimeError(f"{self.storage_path} must contain a JSON list.")

        records = [self._normalize_record(item) for item in data]
        if records != data:
            self._write(records)

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
        }

    def _write(self, records: list[dict]) -> None:
        with self.storage_path.open("w", encoding="utf-8") as file:
            json.dump(records, file, ensure_ascii=False, indent=2)
            file.write("\n")

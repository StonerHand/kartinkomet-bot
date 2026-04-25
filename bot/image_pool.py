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
STORAGE_VERSION = 2
MAX_CHAT_HISTORY = 500


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
        self._records, self._chat_history = self._load()

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
        record = random.choice(records)
        self._mark_shown(record, chat_id=chat_id)
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

        for chat_key, history in list(self._chat_history.items()):
            history[:] = [shown_id for shown_id in history if shown_id != image_id]
            if not history:
                del self._chat_history[chat_key]
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

        self._chat_history.clear()
        self._write()

    def count_by_user(self, user_id: int) -> int:
        return sum(1 for record in self._records if record["added_by"] == user_id)

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
            for record in sorted(
                shown_records,
                key=lambda record: record.get("last_shown_at") or "",
                reverse=True,
            )[:recent_limit]
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

    def _load(self) -> tuple[list[dict], dict[str, list[str]]]:
        if not self.storage_path.exists():
            self._atomic_write([], {})
            return [], {}

        with self.storage_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        needs_write = False
        if isinstance(data, list):
            raw_records = data
            raw_chat_history = {}
            needs_write = True
        elif isinstance(data, dict):
            raw_records = data.get("images")
            raw_chat_history = data.get("chat_history", {})
            needs_write = data.get("version") != STORAGE_VERSION
        else:
            raise RuntimeError(f"{self.storage_path} must contain a JSON list or object.")

        if not isinstance(raw_records, list):
            raise RuntimeError(f"{self.storage_path} must contain an images list.")

        records = [self._normalize_record(item) for item in raw_records]
        if records != raw_records:
            needs_write = True

        chat_history = self._normalize_chat_history(raw_chat_history, records)
        if chat_history != raw_chat_history:
            needs_write = True

        if needs_write:
            self._atomic_write(records, chat_history)

        return records, chat_history

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
        self._atomic_write(self._records, self._chat_history)

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

    def _atomic_write(self, records: list[dict], chat_history: dict[str, list[str]]) -> None:
        temp_path = self.storage_path.with_suffix(f"{self.storage_path.suffix}.tmp")
        payload = {
            "version": STORAGE_VERSION,
            "images": records,
            "chat_history": chat_history,
        }
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")

        temp_path.replace(self.storage_path)

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


class ImagePool:
    def __init__(self, storage_path: str) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self._write([])

    def count(self) -> int:
        return len(self._read())

    def random_image(self) -> ImageRecord | None:
        records = self._read()
        if not records:
            return None

        record = random.choice(records)
        return ImageRecord(id=record["id"], file_id=record["file_id"])

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

    def delete(self, image_id: str) -> bool:
        records = self._read()
        filtered_records = [record for record in records if record["id"] != image_id]
        if len(filtered_records) == len(records):
            return False

        self._write(filtered_records)
        return True

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
        }

    def _write(self, records: list[dict]) -> None:
        with self.storage_path.open("w", encoding="utf-8") as file:
            json.dump(records, file, ensure_ascii=False, indent=2)
            file.write("\n")

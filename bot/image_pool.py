import json
import random
from pathlib import Path

from aiogram.types import Message


class ImagePool:
    def __init__(self, storage_path: str) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self._write([])

    def count(self) -> int:
        return len(self._read())

    def random_file_id(self) -> str | None:
        file_ids = self._read()
        if not file_ids:
            return None

        return random.choice(file_ids)

    def add_from_message(self, message: Message) -> bool:
        file_id = self._extract_file_id(message)
        if file_id is None:
            return False

        file_ids = self._read()
        file_ids.append(file_id)
        self._write(file_ids)
        return True

    def _extract_file_id(self, message: Message) -> str | None:
        if message.photo:
            return message.photo[-1].file_id

        if message.document and message.document.mime_type:
            if message.document.mime_type.startswith("image/"):
                return message.document.file_id

        return None

    def _read(self) -> list[str]:
        with self.storage_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            raise RuntimeError(f"{self.storage_path} must contain a JSON list.")

        return [str(item) for item in data]

    def _write(self, file_ids: list[str]) -> None:
        with self.storage_path.open("w", encoding="utf-8") as file:
            json.dump(file_ids, file, ensure_ascii=False, indent=2)
            file.write("\n")

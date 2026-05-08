import json
import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from heapq import nlargest, nsmallest
from pathlib import Path
from uuid import uuid4

from aiogram.types import Message

from bot.storage import SQLiteDocumentStore

REACTION_FIELDS = {
    "like": "likes",
    "dislike": "dislikes",
}
STORAGE_VERSION = 1
JOKE_DOCUMENT_NAME = "joke_pool"
MAX_CHAT_HISTORY = 200
RANDOM_CANDIDATE_LIMIT = 80
RANDOM = random.SystemRandom()


@dataclass(frozen=True)
class AddJokeResult:
    added: bool
    duplicate: bool = False
    empty: bool = False


@dataclass(frozen=True)
class JokeRecord:
    id: str
    text: str
    likes: int = 0
    dislikes: int = 0


@dataclass(frozen=True)
class JokeReactionUpdate:
    joke: JokeRecord
    changed: bool


@dataclass(frozen=True)
class JokeStats:
    total_jokes: int
    total_shows: int
    total_likes: int
    total_dislikes: int


class JokePool:
    def __init__(self, storage_path: str, database_path: str | None = None) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._store = SQLiteDocumentStore(database_path) if database_path else None
        self._records, self._chat_history = self._load()
        self._rebuild_indexes()

    def count(self) -> int:
        return len(self._records)

    def random_joke(
        self,
        avoid_recent: bool = True,
        chat_id: int | str | None = None,
    ) -> JokeRecord | None:
        if not self._records:
            return None

        records = self._selectable_records(avoid_recent=avoid_recent, chat_id=chat_id)
        record = RANDOM.choice(records)
        self._mark_shown(record, chat_id=chat_id)
        return self._to_joke_record(record)

    def random_duel_pair(
        self,
        chat_id: int | str,
        avoid_recent: bool = True,
    ) -> tuple[JokeRecord, JokeRecord] | None:
        if len(self._records) < 2:
            return None

        duel_chat_id = f"joke-duel:{chat_id}"
        records = self._selectable_records(
            avoid_recent=avoid_recent,
            chat_id=duel_chat_id,
            minimum_candidates=2,
        )
        if len(records) < 2:
            records = self._records

        left_record, right_record = RANDOM.sample(records, 2)
        self._mark_shown_many(
            [
                (left_record, duel_chat_id),
                (right_record, duel_chat_id),
            ]
        )
        return self._to_joke_record(left_record), self._to_joke_record(right_record)

    def add_from_message(self, message: Message) -> AddJokeResult:
        text = normalize_joke_text(message.text or "")
        if not text:
            return AddJokeResult(added=False, empty=True)

        normalized_key = joke_key(text)
        if normalized_key in self._joke_keys:
            return AddJokeResult(added=False, duplicate=True)

        record = self._normalize_record(
            {
                "id": uuid4().hex,
                "text": text,
                "normalized_text": normalized_key,
                "added_by": message.from_user.id if message.from_user else None,
                "added_at": datetime.now(UTC).isoformat(),
            }
        )
        self._records.append(record)
        self._index_record(record)
        self._write()
        return AddJokeResult(added=True)

    def react(self, joke_id: str, reaction: str, user_id: int) -> JokeReactionUpdate | None:
        field = REACTION_FIELDS.get(reaction)
        if field is None:
            return None

        record = self._find(joke_id)
        if record is None:
            return None

        reactions_by_user = record["reactions_by_user"]
        user_key = str(user_id)
        previous_reaction = reactions_by_user.get(user_key)
        if previous_reaction == reaction:
            return JokeReactionUpdate(joke=self._to_joke_record(record), changed=False)

        if previous_reaction in REACTION_FIELDS:
            previous_field = REACTION_FIELDS[previous_reaction]
            record[previous_field] = max(0, record[previous_field] - 1)

        reactions_by_user[user_key] = reaction
        record[field] += 1
        self._write()
        return JokeReactionUpdate(joke=self._to_joke_record(record), changed=True)

    def delete(self, joke_id: str) -> bool:
        record = self._find(joke_id)
        if record is None:
            return False

        self._records.remove(record)
        self._remove_from_chat_history({joke_id})
        self._rebuild_indexes()
        self._write()
        return True

    def stats(self) -> JokeStats:
        return JokeStats(
            total_jokes=len(self._records),
            total_shows=sum(record["shown_count"] for record in self._records),
            total_likes=sum(record["likes"] for record in self._records),
            total_dislikes=sum(record["dislikes"] for record in self._records),
        )

    def reset_stats(self) -> None:
        for record in self._records:
            record["shown_count"] = 0
            record["last_shown_at"] = None
            record["likes"] = 0
            record["dislikes"] = 0
            record["reactions_by_user"] = {}

        self._chat_history.clear()
        self._write()

    def _selectable_records(
        self,
        avoid_recent: bool,
        chat_id: int | str | None,
        minimum_candidates: int = 1,
    ) -> list[dict]:
        if not avoid_recent or len(self._records) == 1:
            return self._records

        records = self._chat_fresh_records(chat_id)
        shown_records = [record for record in records if record.get("last_shown_at")]
        recent_limit = min(
            max(1, len(records) // 2),
            60,
            max(0, len(records) - minimum_candidates),
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
        if len(fresh_records) >= minimum_candidates:
            records = fresh_records

        return self._least_shown_window(records, minimum_candidates)

    def _least_shown_window(
        self,
        records: list[dict],
        minimum_candidates: int,
    ) -> list[dict]:
        if len(records) <= minimum_candidates:
            return records

        window_size = min(
            len(records),
            max(
                minimum_candidates,
                min(RANDOM_CANDIDATE_LIMIT, max(8, len(records) // 8)),
            ),
        )
        least_shown = nsmallest(
            window_size,
            records,
            key=lambda record: (record["shown_count"], record.get("last_shown_at") or ""),
        )
        shown_threshold = least_shown[-1]["shown_count"]
        return [record for record in records if record["shown_count"] <= shown_threshold]

    def _chat_fresh_records(self, chat_id: int | str | None) -> list[dict]:
        if chat_id is None:
            return self._records

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
        self._mark_shown_many([(record, chat_id)])

    def _mark_shown_many(self, shows: list[tuple[dict, int | str | None]]) -> None:
        shown_at = datetime.now(UTC).isoformat()
        for record, chat_id in shows:
            record["shown_count"] += 1
            record["last_shown_at"] = shown_at
            self._remember_chat_show(record["id"], chat_id)

        self._write()

    def _remember_chat_show(self, joke_id: str, chat_id: int | str | None) -> None:
        if chat_id is None:
            return

        chat_key = str(chat_id)
        history = self._chat_history.setdefault(chat_key, [])
        history[:] = [shown_id for shown_id in history if shown_id != joke_id]
        history.append(joke_id)

        max_history = min(MAX_CHAT_HISTORY, max(1, len(self._records) - 1))
        if len(history) > max_history:
            del history[:-max_history]

    def _remove_from_chat_history(self, joke_ids: set[str]) -> None:
        for chat_key, history in list(self._chat_history.items()):
            history[:] = [shown_id for shown_id in history if shown_id not in joke_ids]
            if not history:
                del self._chat_history[chat_key]

    def _find(self, joke_id: str) -> dict | None:
        return self._record_by_id.get(joke_id)

    def _to_joke_record(self, record: dict) -> JokeRecord:
        return JokeRecord(
            id=record["id"],
            text=record["text"],
            likes=record["likes"],
            dislikes=record["dislikes"],
        )

    def _load(self) -> tuple[list[dict], dict[str, list[str]]]:
        data = self._store.load(JOKE_DOCUMENT_NAME) if self._store else None
        needs_write = False

        if data is None and not self.storage_path.exists():
            self._atomic_write([], {})
            return [], {}

        if data is None:
            with self.storage_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            needs_write = self._store is not None

        if isinstance(data, list):
            raw_records = data
            raw_chat_history = {}
            needs_write = True
        elif isinstance(data, dict):
            raw_records = data.get("jokes")
            raw_chat_history = data.get("chat_history", {})
            needs_write = data.get("version") != STORAGE_VERSION
        else:
            raise RuntimeError(f"{self.storage_path} must contain a JSON list or object.")

        if not isinstance(raw_records, list):
            raise RuntimeError(f"{self.storage_path} must contain a jokes list.")

        records = [
            record
            for record in (self._normalize_record(item) for item in raw_records)
            if record["text"]
        ]
        if records != raw_records:
            needs_write = True

        seen_keys: set[str] = set()
        deduped = []
        for record in records:
            key = record["normalized_text"]
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(record)
        if len(deduped) != len(records):
            records = deduped
            needs_write = True

        chat_history = self._normalize_chat_history(raw_chat_history, records)
        if chat_history != raw_chat_history:
            needs_write = True

        if needs_write:
            self._atomic_write(records, chat_history)

        return records, chat_history

    def _normalize_record(self, item: object) -> dict:
        if isinstance(item, str):
            text = normalize_joke_text(item)
            return self._record_from_text(text)

        if not isinstance(item, dict) or "text" not in item:
            raise RuntimeError(f"{self.storage_path} contains an invalid joke record.")

        text = normalize_joke_text(str(item["text"]))
        reactions_by_user = self._normalize_reactions(item.get("reactions_by_user"))
        if reactions_by_user:
            reaction_totals = self._reaction_totals(reactions_by_user)
        else:
            reaction_totals = {
                "likes": int(item.get("likes") or 0),
                "dislikes": int(item.get("dislikes") or 0),
            }

        added_by = item.get("added_by")
        if isinstance(added_by, str) and added_by.isdigit():
            added_by = int(added_by)

        return {
            "id": str(item.get("id") or uuid4().hex),
            "text": text,
            "normalized_text": str(item.get("normalized_text") or joke_key(text)),
            "added_by": added_by,
            "added_at": item.get("added_at"),
            "shown_count": int(item.get("shown_count") or 0),
            "last_shown_at": item.get("last_shown_at"),
            "likes": reaction_totals["likes"],
            "dislikes": reaction_totals["dislikes"],
            "reactions_by_user": reactions_by_user,
        }

    def _record_from_text(self, text: str) -> dict:
        return {
            "id": uuid4().hex,
            "text": text,
            "normalized_text": joke_key(text),
            "added_by": None,
            "added_at": None,
            "shown_count": 0,
            "last_shown_at": None,
            "likes": 0,
            "dislikes": 0,
            "reactions_by_user": {},
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
        totals = {"likes": 0, "dislikes": 0}
        for reaction in reactions_by_user.values():
            totals[REACTION_FIELDS[reaction]] += 1

        return totals

    def _rebuild_indexes(self) -> None:
        self._record_by_id: dict[str, dict] = {}
        self._joke_keys: set[str] = set()
        for record in self._records:
            self._index_record(record)

    def _index_record(self, record: dict) -> None:
        self._record_by_id[record["id"]] = record
        self._joke_keys.add(record["normalized_text"])

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
            for joke_id in history:
                joke_key_value = str(joke_id)
                if joke_key_value in record_ids and joke_key_value not in seen_ids:
                    valid_history.append(joke_key_value)
                    seen_ids.add(joke_key_value)

            if max_history:
                valid_history = valid_history[-max_history:]
            if valid_history:
                chat_history[str(chat_id)] = valid_history

        return chat_history

    def _write(self) -> None:
        self._atomic_write(self._records, self._chat_history)

    def _atomic_write(self, records: list[dict], chat_history: dict[str, list[str]]) -> None:
        payload = {
            "version": STORAGE_VERSION,
            "jokes": records,
            "chat_history": chat_history,
        }
        if self._store:
            self._store.save(JOKE_DOCUMENT_NAME, payload)
            return

        temp_path = self.storage_path.with_suffix(f"{self.storage_path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, separators=(",", ":"))
            file.write("\n")

        temp_path.replace(self.storage_path)


def normalize_joke_text(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines()]
    clean_lines: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line
        if is_blank and previous_blank:
            continue
        clean_lines.append(line)
        previous_blank = is_blank

    return "\n".join(clean_lines).strip()


def joke_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()

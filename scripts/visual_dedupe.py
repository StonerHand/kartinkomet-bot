from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import aiohttp
from PIL import Image, UnidentifiedImageError

DEFAULT_THRESHOLD = 5
DEFAULT_CONCURRENCY = 8
TELEGRAM_API = "https://api.telegram.org"
TELEGRAM_FILE_API = "https://api.telegram.org/file"


@dataclass(frozen=True)
class HashResult:
    record_id: str
    file_unique_id: str
    image_hash: int


@dataclass(frozen=True)
class DuplicateMatch:
    duplicate_id: str
    keeper_id: str
    distance: int


def dhash(image_bytes: bytes) -> int:
    with Image.open(BytesIO(image_bytes)) as image:
        grayscale = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(grayscale.getdata())

    value = 0
    for row in range(8):
        row_offset = row * 9
        for column in range(8):
            value <<= 1
            if pixels[row_offset + column] > pixels[row_offset + column + 1]:
                value |= 1

    return value


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def find_duplicates(
    hashes: list[HashResult],
    threshold: int = DEFAULT_THRESHOLD,
) -> list[DuplicateMatch]:
    keepers: list[HashResult] = []
    duplicates: list[DuplicateMatch] = []

    for item in hashes:
        match: DuplicateMatch | None = None
        for keeper in keepers:
            distance = hamming_distance(item.image_hash, keeper.image_hash)
            if distance <= threshold:
                match = DuplicateMatch(
                    duplicate_id=item.record_id,
                    keeper_id=keeper.record_id,
                    distance=distance,
                )
                break

        if match is None:
            keepers.append(item)
        else:
            duplicates.append(match)

    return duplicates


def load_pool(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict) or not isinstance(data.get("images"), list):
        raise RuntimeError(f"{path} must contain a versioned image pool object")

    return data


def write_pool(path: Path, data: dict[str, Any]) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")

    temp_path.replace(path)


def backup_pool(path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.stem}.backup-{timestamp}{path.suffix}")
    shutil.copy2(path, backup_path)
    return backup_path


def clean_chat_history(data: dict[str, Any], removed_ids: set[str]) -> None:
    chat_history = data.get("chat_history")
    if not isinstance(chat_history, dict):
        return

    for chat_id, history in list(chat_history.items()):
        if not isinstance(history, list):
            del chat_history[chat_id]
            continue

        filtered = [image_id for image_id in history if str(image_id) not in removed_ids]
        if filtered:
            chat_history[chat_id] = filtered
        else:
            del chat_history[chat_id]


def target_records(data: dict[str, Any], user_id: int) -> list[dict[str, Any]]:
    return [
        record
        for record in data["images"]
        if isinstance(record, dict) and record.get("added_by") == user_id
    ]


async def fetch_file_bytes(
    session: aiohttp.ClientSession,
    bot_token: str,
    file_id: str,
) -> bytes:
    async with session.get(f"{TELEGRAM_API}/bot{bot_token}/getFile", params={"file_id": file_id}) as response:
        response.raise_for_status()
        payload = await response.json()

    if not payload.get("ok") or not payload.get("result", {}).get("file_path"):
        raise RuntimeError(f"Telegram did not return file_path for {file_id}")

    file_path = payload["result"]["file_path"]
    async with session.get(f"{TELEGRAM_FILE_API}/bot{bot_token}/{file_path}") as response:
        response.raise_for_status()
        return await response.read()


async def hash_record(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    bot_token: str,
    record: dict[str, Any],
    cache: dict[str, str],
) -> HashResult | None:
    record_id = str(record.get("id") or "")
    file_id = str(record.get("file_id") or "")
    file_unique_id = str(record.get("file_unique_id") or file_id)
    if not record_id or not file_id:
        return None

    cached_hash = cache.get(file_unique_id)
    if cached_hash:
        return HashResult(record_id, file_unique_id, int(cached_hash, 16))

    try:
        async with semaphore:
            image_bytes = await fetch_file_bytes(session, bot_token, file_id)
        image_hash = dhash(image_bytes)
    except (aiohttp.ClientError, RuntimeError, UnidentifiedImageError, OSError) as error:
        print(f"skip {record_id}: {error}")
        return None

    cache[file_unique_id] = f"{image_hash:016x}"
    return HashResult(record_id, file_unique_id, image_hash)


async def build_hashes(
    records: list[dict[str, Any]],
    bot_token: str,
    cache: dict[str, str],
    concurrency: int,
) -> list[HashResult]:
    semaphore = asyncio.Semaphore(concurrency)
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [
            hash_record(session, semaphore, bot_token, record, cache)
            for record in records
        ]
        results = await asyncio.gather(*tasks)

    return [result for result in results if result is not None]


def load_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        return {}

    return {str(key): str(value) for key, value in data.items()}


def write_cache(path: Path, cache: dict[str, str]) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(cache, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")

    temp_path.replace(path)


async def run(args: argparse.Namespace) -> None:
    pool_path = Path(args.pool_path)
    cache_path = Path(args.cache_path or pool_path.with_name(".visual_hash_cache.json"))
    data = load_pool(pool_path)
    records = target_records(data, args.user_id)
    cache = load_cache(cache_path)

    print(f"user_id: {args.user_id}")
    print(f"target records: {len(records)}")
    if not records:
        return

    hashes = await build_hashes(
        records=records,
        bot_token=args.bot_token,
        cache=cache,
        concurrency=args.concurrency,
    )
    write_cache(cache_path, cache)

    duplicates = find_duplicates(hashes, threshold=args.threshold)
    removed_ids = {match.duplicate_id for match in duplicates}

    print(f"hashed records: {len(hashes)}")
    print(f"visual duplicates: {len(duplicates)}")
    print(f"threshold: {args.threshold}")
    for match in duplicates[: args.preview]:
        print(
            f"duplicate {match.duplicate_id} -> keep {match.keeper_id} "
            f"(distance {match.distance})"
        )
    if len(duplicates) > args.preview:
        print(f"...and {len(duplicates) - args.preview} more")

    if not args.apply:
        print("dry-run only: database was not changed")
        return

    backup_path = backup_pool(pool_path)
    data["images"] = [
        record
        for record in data["images"]
        if str(record.get("id")) not in removed_ids
    ]
    clean_chat_history(data, removed_ids)
    write_pool(pool_path, data)
    print(f"backup: {backup_path}")
    print(f"removed: {len(removed_ids)}")
    print("database updated")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find and remove visual duplicate images uploaded by one Telegram user.",
    )
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument(
        "--pool-path",
        default=os.getenv("IMAGE_POOL_PATH") or "/data/image_pool.json",
    )
    parser.add_argument("--bot-token", default=os.getenv("BOT_TOKEN"), required=False)
    parser.add_argument("--cache-path", default=None)
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--preview", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true", help="Report only. This is the default.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.bot_token:
        parser.error("--bot-token or BOT_TOKEN is required")
    if args.threshold < 0:
        parser.error("--threshold must be >= 0")
    if args.concurrency < 1:
        parser.error("--concurrency must be >= 1")

    return args


if __name__ == "__main__":
    asyncio.run(run(parse_args()))

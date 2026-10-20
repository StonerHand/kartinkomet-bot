import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    database_path: Path
    admin_user_ids: frozenset[int]
    tz_offset_hours: int


def load_config() -> Config:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set. Add it to .env first.")

    data_dir = Path(os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or "data")
    return Config(
        bot_token=bot_token,
        database_path=Path(os.getenv("DATABASE_PATH") or data_dir / "kartinkomet_v2.sqlite"),
        admin_user_ids=parse_user_ids(os.getenv("ADMIN_USER_IDS", "")),
        # Used only to decide what counts as a night upload. Default: Moscow (UTC+3).
        tz_offset_hours=int(os.getenv("BOT_TZ_OFFSET", "3")),
    )


def parse_user_ids(value: str) -> frozenset[int]:
    user_ids: set[int] = set()
    for raw_user_id in value.replace(";", ",").split(","):
        raw_user_id = raw_user_id.strip()
        if not raw_user_id:
            continue
        try:
            user_ids.add(int(raw_user_id))
        except ValueError as error:
            raise RuntimeError(f"ADMIN_USER_IDS contains an invalid user ID: {raw_user_id}") from error

    return frozenset(user_ids)

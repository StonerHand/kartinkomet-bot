import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    image_pool_path: str
    target_channel_id: str | None


def load_config() -> Config:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set. Add it to .env first.")

    railway_volume_path = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    default_pool_path = (
        os.path.join(railway_volume_path, "image_pool.json")
        if railway_volume_path
        else "data/image_pool.json"
    )

    return Config(
        bot_token=bot_token,
        image_pool_path=os.getenv("IMAGE_POOL_PATH", default_pool_path),
        target_channel_id=os.getenv("TARGET_CHANNEL_ID") or None,
    )

"""Pics from Telegram: downloads (cached) and the arena collage built from them."""

import asyncio
import logging
from collections import OrderedDict
from io import BytesIO

from aiogram import Bot

from bot.core import progress, shop
from bot.media import collage
from bot.tg.runtime import send

LOGGER = logging.getLogger(__name__)

# Pics fetched from Telegram, newest last. A champion fights again and again, hall-of-fame pics
# come back: two round trips each to Telegram's servers are the slow part of starting a battle.
DOWNLOAD_CACHE_BYTES = 40 * 1024 * 1024
_downloads: OrderedDict[str, bytes] = OrderedDict()


async def download(bot: Bot, file_id: str) -> bytes | None:
    if (cached := _downloads.get(file_id)) is not None:
        _downloads.move_to_end(file_id)
        return cached
    telegram_file = await send.retry(lambda: bot.get_file(file_id), "collage get_file")
    if not telegram_file.file_path:
        return None
    buffer = BytesIO()
    await send.retry(
        lambda: bot.download_file(telegram_file.file_path, destination=buffer), "collage download"
    )
    data = buffer.getvalue()
    _downloads[file_id] = data
    while sum(len(item) for item in _downloads.values()) > DOWNLOAD_CACHE_BYTES and len(_downloads) > 1:
        _downloads.popitem(last=False)
    return data


async def build_collage(bot: Bot, pics) -> bytes | None:
    try:
        # In parallel: sequential downloads made tournaments take up to 7 s to start.
        images = await asyncio.gather(*(download(bot, pic.file_id) for pic in pics))
        if any(image is None for image in images):
            return None
        stages = [shop.stage(pic.wins).index for pic in pics]
        frames = [progress.FRAMES[pic.frame][1] if pic.frame in progress.FRAMES else None for pic in pics]
        return await asyncio.to_thread(collage.build, list(images), stages, frames)
    except Exception:  # any failure here just means "no collage", the album fallback still works
        LOGGER.warning("Collage failed, falling back to album", exc_info=True)
        return None

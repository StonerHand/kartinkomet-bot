"""Inline mode: type @bot in any chat and pick a pic from the vault.

Empty query → random pics; "топ"/"top"/"слава" → hall of fame. Requires inline mode to be
enabled once in @BotFather (/setinline).
"""

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultCachedDocument,
    InlineQueryResultCachedPhoto,
)

from bot.db.repo import Pic
from bot.game import Game

router = Router(name="inline")
RESULTS = 20
TOP_WORDS = {"топ", "top", "слава", "лучшие", "легенды"}
# Telegram file_id prefixes: photos start with "AgAC"; anything else was uploaded as a document.
PHOTO_PREFIX = "AgAC"


def result_for(pic: Pic):
    if pic.file_id.startswith(PHOTO_PREFIX):
        return InlineQueryResultCachedPhoto(id=pic.id, photo_file_id=pic.file_id)
    return InlineQueryResultCachedDocument(id=pic.id, title="🎲 Пикча со склада", document_file_id=pic.file_id)


@router.inline_query()
async def inline_pics(query: InlineQuery, game: Game) -> None:
    text = query.query.strip().casefold()
    if text in TOP_WORDS:
        pics = game.repo.top_rated(RESULTS)
    else:
        pics = game.repo.random_alive(RESULTS)
    await query.answer(
        [result_for(pic) for pic in pics],
        cache_time=5,
        is_personal=True,
    )

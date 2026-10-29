"""Buttons left over from v1 messages, unknown callbacks and the global error handler."""

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, ErrorEvent

from bot.game import Game
from bot.texts import ui
from bot.texts.pick import pick
from bot.tg.handlers.pics import react
from bot.tg.runtime.timers import Live

LOGGER = logging.getLogger(__name__)
router = Router(name="fallback")

V1_REACTIONS = {"like": "+", "dislike": "-"}


@router.callback_query(F.data.regexp(r"^react:(like|dislike):"))
async def v1_reaction(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    """v1 pic messages still carry react:<like|dislike>:<id>; pic ids survived the migration."""
    _, kind, pic_id = callback.data.split(":", 2)
    await react(callback.model_copy(update={"data": f"r:{V1_REACTIONS[kind]}:{pic_id}"}), bot, game, live)


@router.callback_query()
async def stale_button(callback: CallbackQuery) -> None:
    await callback.answer(f"{pick(ui.STALE_BUTTON)}. Жми /menu", show_alert=True)


async def on_error(event: ErrorEvent) -> bool:
    error = event.exception
    if isinstance(error, TelegramBadRequest) and "query is too old" in str(error):
        return True
    LOGGER.error("Unhandled error in update %s", event.update.update_id, exc_info=error)
    return True

"""Replies to the bot's own messages. Each mechanic that asks for a typed answer checks whether
the reply is its own, in this order: a defendant's last word, a custom title, a name or an amount
the bot asked for, a caption-contest entry."""

from aiogram import Bot, F, Router
from aiogram.types import Message

from bot.game import Game
from bot.tg.handlers.court import last_word_reply
from bot.tg.handlers.games import caption_reply
from bot.tg.handlers.shop import title_reply
from bot.tg.handlers.targets import answer
from bot.tg.runtime.timers import Live

router = Router(name="replies")


@router.message(F.reply_to_message.from_user.is_bot & F.text)
async def reply_to_bot(message: Message, bot: Bot, game: Game, live: Live) -> None:
    if await last_word_reply(message, bot, game, live):
        return
    if await title_reply(message, bot, game):
        return
    if await answer(message, bot, game, live):
        return
    await caption_reply(message, bot, game, live)

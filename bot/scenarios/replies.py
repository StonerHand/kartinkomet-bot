"""Replies to the bot's own messages. Each mechanic that asks for a typed answer checks whether
the reply is its own, in this order: a defendant's last word, a custom title, a name or an amount
the bot asked for, a caption-contest entry."""

from aiogram import Bot, F, Router
from aiogram.types import Message

from bot.game.engine import Game
from bot.live.timers import Live
from bot.scenarios.court import last_word_reply
from bot.scenarios.games import caption_reply
from bot.scenarios.shop import title_reply
from bot.scenarios.targets import answer

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

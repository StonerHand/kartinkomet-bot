"""Remembers every user who touches the bot, so tops and profiles have names."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from bot.game import Game


class RememberUser(BaseMiddleware):
    def __init__(self, game: Game) -> None:
        self.game = game

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None and not user.is_bot:
            self.game.repo.remember_user(
                user.id, user.username, user.first_name, user.last_name, self.game.now()
            )
        return await handler(event, data)

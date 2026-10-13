"""Remembers every user who touches the bot (names for tops and profiles) and every group
chat it lives in (targets for scheduled events)."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Chat, TelegramObject, User

from bot.game import Game


class RememberUser(BaseMiddleware):
    def __init__(self, game: Game) -> None:
        self.game = game
        self._chat_seen: dict[int, int] = {}
        self._starter_checked: set[int] = set()

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
            if user.id not in self._starter_checked:  # newcomers get the starter coins too
                self._starter_checked.add(user.id)
                self.game.give_starter(user.id)
        chat: Chat | None = data.get("event_chat")
        if chat is not None and chat.type in ("group", "supergroup"):
            self._touch_chat(chat)
        return await handler(event, data)

    def _touch_chat(self, chat: Chat) -> None:
        """Remember group chats for scheduled events; at most one write per chat per 10 minutes."""
        now = self.game.now()
        if now - self._chat_seen.get(chat.id, 0) < 600:
            return
        self._chat_seen[chat.id] = now
        self.game.repo.touch_chat(chat.id, chat.title, now)

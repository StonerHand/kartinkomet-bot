"""Startup after downtime: a stale update backlog is dropped, a short one is kept."""

import unittest
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.types import CallbackQuery, Message, Update

from bot.__main__ import STALE_BACKLOG_SECONDS, drop_stale_backlog
from tests.test_bot import GROUP, FakeSession, user


def command(age_seconds: float) -> Update:
    sent = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return Update(update_id=1, message=Message(message_id=1, date=sent, chat=GROUP, from_user=user(2), text="/pic"))


class StaleBacklogTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = FakeSession()
        self.bot = Bot(token="42:TEST", session=self.session)

    async def test_hours_old_backlog_is_dropped(self) -> None:
        self.session.pending = [command(8 * 3600), command(60)]
        self.assertEqual(await drop_stale_backlog(self.bot), 2)
        self.assertEqual(self.session.pending, [])
        self.assertTrue(self.session.of("DeleteWebhook")[0].drop_pending_updates)

    async def test_backlog_of_a_deploy_is_kept(self) -> None:
        self.session.pending = [command(20), command(5)]
        self.assertEqual(await drop_stale_backlog(self.bot), 0)
        self.assertEqual(len(self.session.pending), 2)
        self.assertEqual(self.session.of("DeleteWebhook"), [])

    async def test_old_button_press_counts_as_stale(self) -> None:
        old = command(STALE_BACKLOG_SECONDS + 60).message
        press = CallbackQuery(id="1", from_user=user(2), chat_instance="c", data="bh", message=old)
        self.session.pending = [Update(update_id=1, callback_query=press)]
        self.assertEqual(await drop_stale_backlog(self.bot), 1)

    async def test_empty_queue_is_left_alone(self) -> None:
        self.assertEqual(await drop_stale_backlog(self.bot), 0)
        self.assertEqual(self.session.of("GetUpdates"), [])


if __name__ == "__main__":
    unittest.main()

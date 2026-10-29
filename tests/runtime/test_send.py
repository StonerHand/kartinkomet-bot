"""Telegram failures: flood waits, network blips, refused edits and the fallbacks behind them."""

import asyncio
import unittest
from unittest import mock

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendMessage

from bot.tg.runtime import send
from tests.harness import FakeSession

METHOD = SendMessage(chat_id=-100, text="x")


def flood(seconds: int) -> TelegramRetryAfter:
    return TelegramRetryAfter(method=METHOD, message="Too Many Requests", retry_after=seconds)


def blip() -> TelegramNetworkError:
    return TelegramNetworkError(method=METHOD, message="timeout")


class SendTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = FakeSession()
        self.bot = Bot(token="42:TEST", session=self.session)
        self.slept: list[float] = []
        real_sleep = asyncio.sleep

        async def fake_sleep(seconds: float) -> None:
            self.slept.append(seconds)
            await real_sleep(0)

        patcher = mock.patch.object(send.asyncio, "sleep", fake_sleep)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_short_flood_wait_is_waited_out(self) -> None:
        self.session.errors["SendMessage"] = [flood(3)]
        self.assertIsNotNone(await send.send_text(self.bot, -100, "x"))
        self.assertEqual(self.slept, [3.0])
        self.assertEqual(len(self.session.of("SendMessage")), 2)

    async def test_long_flood_wait_gives_up_at_once(self) -> None:
        self.session.errors["SendMessage"] = [flood(send.MAX_FLOOD_WAIT + 1)]
        with self.assertLogs("bot.tg.runtime.send", "WARNING"):
            self.assertIsNone(await send.send_text(self.bot, -100, "x"))
        self.assertEqual((self.slept, len(self.session.of("SendMessage"))), ([], 1))

    async def test_network_blips_are_retried_then_given_up(self) -> None:
        self.session.errors["SendMessage"] = [blip(), blip()]
        with self.assertLogs("bot.tg.runtime.send", "WARNING"):
            self.assertIsNotNone(await send.send_text(self.bot, -100, "x"))
        self.session.errors["SendMessage"] = [blip()] * send.RETRIES
        with self.assertLogs("bot.tg.runtime.send", "WARNING"):
            self.assertIsNone(await send.send_text(self.bot, -100, "x"))
        self.assertEqual(len(self.session.of("SendMessage")), 3 + send.RETRIES)

    async def test_unchanged_edit_counts_as_done(self) -> None:
        self.session.errors["EditMessageText"] = [
            TelegramBadRequest(method=METHOD, message="Bad Request: message is not modified"),
            TelegramBadRequest(method=METHOD, message="Bad Request: message to edit not found"),
        ]
        self.assertTrue(await send.edit_text(self.bot, -100, 5, "x", None))
        with self.assertLogs("bot.tg.runtime.send", "WARNING"):
            self.assertFalse(await send.edit_text(self.bot, -100, 5, "x", None))

    async def test_document_pic_falls_back_to_send_document(self) -> None:
        self.session.errors["SendPhoto"] = [
            TelegramBadRequest(method=METHOD, message="Bad Request: can't use file of type Document as Photo")
        ]
        self.assertIsNotNone(await send.send_photo(self.bot, -100, "file", "caption"))
        self.assertEqual(len(self.session.of("SendDocument")), 1)

    async def test_refused_album_becomes_single_photos(self) -> None:
        self.session.errors["SendMediaGroup"] = [TelegramBadRequest(method=METHOD, message="Bad Request: nope")]
        with self.assertLogs("bot.tg.runtime.send", "WARNING"):
            self.assertTrue(await send.send_album(self.bot, -100, ["a", "b", "c"]))
        self.assertEqual([photo.caption for photo in self.session.of("SendPhoto")], ["<b>1</b>", "<b>2</b>", "<b>3</b>"])

    async def test_cosmetic_calls_never_raise(self) -> None:
        refused = TelegramBadRequest(method=METHOD, message="Bad Request: not allowed")
        self.session.errors = {name: [refused] for name in ("SetMessageReaction", "DeleteMessage", "SendChatAction")}
        with self.assertLogs("bot.tg.runtime.send", "INFO"):
            await send.react(self.bot, -100, 5, "🔥")
        await send.delete(self.bot, -100, 5)
        await send.chat_action(self.bot, -100, "typing")


if __name__ == "__main__":
    unittest.main()

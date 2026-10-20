"""Uploads: visual duplicates, image documents, junk and bursts."""

from datetime import UTC, datetime
from io import BytesIO

from aiogram.types import Chat, Document, Message, PhotoSize, Update
from PIL import Image, ImageDraw

from bot.tg import upload
from tests.test_bot import BotHarness, user

PRIVATE = Chat(id=5, type="private")


def picture(seed: int, size: int = 256, quality: int = 90) -> bytes:
    """A simple drawing: the same seed gives the same picture at any size and quality."""
    image = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(image)
    for step in range(8):
        shade = (seed * 37 + step * 29) % 256
        draw.rectangle((step * 32, (seed * step * 13) % 200, step * 32 + 31, 255), fill=(shade, 255 - shade, 128))
    buffer = BytesIO()
    image.resize((size, size)).save(buffer, "JPEG", quality=quality)
    return buffer.getvalue()


class UploadTest(BotHarness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.send("/upload", sender=5, chat=PRIVATE)

    async def drop(self, unique: str, image: bytes | None = None, **content) -> None:
        self.session.image = image
        if not content:
            content = {"photo": [PhotoSize(file_id=f"f-{unique}", file_unique_id=unique, width=10, height=10)]}
        message = Message(message_id=next(self.session.ids), date=datetime.now(UTC), chat=PRIVATE,
                          from_user=user(5), **content)
        await self.dispatcher.feed_update(self.bot, Update(update_id=next(self.update_ids), message=message))

    def counts(self) -> tuple[int, int, int]:
        session = upload.sessions[5]
        return session.added, session.duplicates, session.failed

    async def test_recompressed_copy_is_a_duplicate(self) -> None:
        await self.drop("a", picture(1))
        await self.drop("b", picture(1, size=180, quality=40))  # same picture, new file
        await self.drop("c", picture(7))  # a different one
        self.assertEqual(self.counts(), (2, 1, 0))
        self.assertTrue(self.game.repo.pic_known("c"))
        self.assertFalse(self.game.repo.pic_known("b"))

    async def test_image_documents_count_and_junk_does_not(self) -> None:
        png = Document(file_id="doc", file_unique_id="doc-u", mime_type="image/png")
        await self.drop("doc-u", picture(3), document=png)
        pdf = Document(file_id="pdf", file_unique_id="pdf-u", mime_type="application/pdf")
        await self.drop("pdf-u", None, document=pdf)
        self.assertEqual(self.counts(), (1, 0, 1))

    async def test_unreadable_bytes_still_upload(self) -> None:
        await self.drop("x", b"not an image")  # no hash, but the pic itself is fine
        self.assertEqual(self.counts(), (1, 0, 0))

    async def test_a_burst_is_cut(self) -> None:
        for index in range(upload.BURST_LIMIT + 3):
            await self.drop(f"burst-{index}")
        added, _, failed = self.counts()
        self.assertEqual((added, failed), (upload.BURST_LIMIT, 3))

    async def test_photo_without_a_session_gets_a_hint(self) -> None:
        await self.send("/cancel", sender=5, chat=PRIVATE)
        await self.drop("late", picture(2))
        self.assertIn("/upload", self.session.of("SendMessage")[-1].text)
        self.assertFalse(self.game.repo.pic_known("late"))

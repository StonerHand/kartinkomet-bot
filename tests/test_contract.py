import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bot.__main__ import BOT_COMMANDS
from bot.config import parse_user_ids
from bot.handlers import current_achievement_for, next_achievement_for
from bot.image_pool import ImagePool
from bot.texts import (
    ACHIEVEMENTS,
    AUTO_DELETE_DISLIKES,
    EMPTY_POOL_PHRASES,
    JURY_THRESHOLDS,
    PICTURE_CAPTIONS,
    UPLOAD_FINISH_PHRASES,
    UPLOAD_START_PHRASES,
)


def fake_photo_message(file_id: str, file_unique_id: str, user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        photo=[SimpleNamespace(file_id=file_id, file_unique_id=file_unique_id)],
        document=None,
        from_user=SimpleNamespace(id=user_id),
    )


class BotContractTest(unittest.TestCase):
    def test_upload_pidor_is_the_only_slash_upload_command(self) -> None:
        commands = [command.command for command in BOT_COMMANDS]

        self.assertIn("upload_pidor", commands)
        self.assertIn("me", commands)
        self.assertIn("top", commands)
        self.assertNotIn("upload", commands)
        self.assertNotIn("addpack_pidor", commands)

    def test_text_pool_sizes_stay_intentional(self) -> None:
        self.assertEqual(len(PICTURE_CAPTIONS), 1500)
        self.assertEqual(len(UPLOAD_START_PHRASES), 150)
        self.assertEqual(len(UPLOAD_FINISH_PHRASES), 150)
        self.assertEqual(len(EMPTY_POOL_PHRASES), 150)
        self.assertEqual(len(ACHIEVEMENTS), 50)

    def test_admin_user_ids_parser_accepts_commas_and_semicolons(self) -> None:
        self.assertEqual(parse_user_ids("1, 2;3"), frozenset({1, 2, 3}))

    def test_achievement_progress_helpers(self) -> None:
        self.assertEqual(current_achievement_for(0), "пока без медали, но путь начат")
        self.assertEqual(current_achievement_for(1), "первый вброс")
        self.assertEqual(next_achievement_for(1), (2, "двойной занос"))

    def test_dislike_jury_thresholds_stay_intentional(self) -> None:
        self.assertEqual(AUTO_DELETE_DISLIKES, 3)
        self.assertNotIn(1, JURY_THRESHOLDS)
        self.assertIn(2, JURY_THRESHOLDS)


class ImagePoolTest(unittest.TestCase):
    def test_migrates_old_file_id_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "pool.json"
            storage_path.write_text(json.dumps(["file-a", "file-b"]), encoding="utf-8")

            pool = ImagePool(str(storage_path))

            self.assertEqual(pool.count(), 2)
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 2)
            self.assertEqual(len(payload["images"]), 2)

    def test_rejects_duplicate_file_unique_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))

            first = pool.add_from_message(fake_photo_message("file-a", "unique-a"))
            second = pool.add_from_message(fake_photo_message("file-b", "unique-a"))

            self.assertTrue(first.added)
            self.assertFalse(second.added)
            self.assertTrue(second.duplicate)
            self.assertEqual(pool.count(), 1)

    def test_deduplicates_existing_records_by_file_unique_id_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "pool.json"
            storage_path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "images": [
                            {
                                "id": "first",
                                "file_id": "file-a",
                                "file_unique_id": "same-image",
                                "shown_count": 2,
                            },
                            {
                                "id": "duplicate",
                                "file_id": "file-b",
                                "file_unique_id": "same-image",
                                "shown_count": 9,
                            },
                            {
                                "id": "second",
                                "file_id": "file-c",
                                "file_unique_id": "other-image",
                            },
                        ],
                        "chat_history": {"1": ["duplicate", "first", "second"]},
                    }
                ),
                encoding="utf-8",
            )

            pool = ImagePool(str(storage_path))

            self.assertEqual(pool.count(), 2)
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
            self.assertEqual([record["id"] for record in payload["images"]], ["first", "second"])
            self.assertEqual(payload["chat_history"], {"1": ["second"]})

    def test_reactions_accumulate_by_user_and_can_be_switched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            pool.add_from_message(fake_photo_message("file-a", "unique-a"))
            image = pool.random_image(chat_id=1)
            self.assertIsNotNone(image)
            assert image is not None

            pool.react(image.id, "like", user_id=1)
            switched = pool.react(image.id, "dislike", user_id=1)
            another_user = pool.react(image.id, "dislike", user_id=2)

            self.assertTrue(switched.changed)
            self.assertTrue(another_user.changed)
            stats = pool.stats()
            self.assertEqual(stats.total_likes, 0)
            self.assertEqual(stats.total_dislikes, 2)

    def test_top_uploaders_uses_upload_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            pool.add_from_message(fake_photo_message("file-a", "unique-a", user_id=20))
            pool.add_from_message(fake_photo_message("file-b", "unique-b", user_id=10))
            pool.add_from_message(fake_photo_message("file-c", "unique-c", user_id=10))

            self.assertEqual(pool.count_by_user(10), 2)
            self.assertEqual(pool.top_uploaders(), [(10, 2), (20, 1)])

    def test_random_avoids_immediate_repeat_per_chat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            pool.add_from_message(fake_photo_message("file-a", "unique-a"))
            pool.add_from_message(fake_photo_message("file-b", "unique-b"))

            first = pool.random_image(chat_id=123)
            second = pool.random_image(chat_id=123)

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            assert first is not None
            assert second is not None
            self.assertNotEqual(first.id, second.id)

    def test_reset_stats_clears_reactions_views_and_random_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "pool.json"
            pool = ImagePool(str(storage_path))
            pool.add_from_message(fake_photo_message("file-a", "unique-a"))
            image = pool.random_image(chat_id=555)
            self.assertIsNotNone(image)
            assert image is not None
            pool.react(image.id, "fire", user_id=1)

            pool.reset_stats()

            stats = pool.stats()
            self.assertEqual(stats.total_shows, 0)
            self.assertEqual(stats.total_fires, 0)
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["chat_history"], {})


if __name__ == "__main__":
    unittest.main()

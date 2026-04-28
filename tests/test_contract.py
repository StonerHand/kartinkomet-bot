import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bot.__main__ import BOT_COMMANDS
from bot.config import parse_user_ids
from bot.handlers import (
    combo_achievements_for,
    current_achievement_for,
    format_duel_score,
    format_duel_result,
    format_help,
    format_mood,
    format_start,
    format_user_progress,
    format_top_uploaders,
    format_upload_limit,
    next_achievement_for,
    parse_user_id_argument,
    quality_title,
)
from bot.image_pool import UPLOAD_LIMIT_PER_HOUR, ImagePool
from bot.keyboards import main_menu, upload_menu
from bot.texts import (
    ACHIEVEMENTS,
    AUTO_DELETE_DISLIKES,
    DUEL_ANNOUNCEMENTS,
    DUEL_RESULT_PHRASES,
    EMPTY_POOL_PHRASES,
    JURY_THRESHOLDS,
    PICTURE_CAPTIONS,
    UPLOAD_FINISH_PHRASES,
    UPLOAD_START_PHRASES,
)
from scripts.visual_dedupe import HashResult, clean_chat_history, find_duplicates, hamming_distance


def fake_photo_message(file_id: str, file_unique_id: str, user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        photo=[SimpleNamespace(file_id=file_id, file_unique_id=file_unique_id)],
        document=None,
        from_user=SimpleNamespace(
            id=user_id,
            username=None,
            first_name=f"User {user_id}",
            last_name=None,
        ),
    )


def fake_user(
    user_id: int,
    username: str | None = None,
    first_name: str = "Test",
    last_name: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
    )


class BotContractTest(unittest.TestCase):
    def test_upload_pidor_is_the_only_slash_upload_command(self) -> None:
        commands = [command.command for command in BOT_COMMANDS]

        self.assertIn("upload_pidor", commands)
        self.assertIn("me", commands)
        self.assertIn("top", commands)
        self.assertIn("duel", commands)
        self.assertNotIn("upload", commands)
        self.assertNotIn("addpack_pidor", commands)
        self.assertNotIn("dedupe_user", commands)

    def test_hidden_dedupe_user_argument_parser(self) -> None:
        self.assertEqual(
            parse_user_id_argument(SimpleNamespace(text="/dedupe_user 1045485205", caption=None)),
            1045485205,
        )
        self.assertIsNone(parse_user_id_argument(SimpleNamespace(text="/dedupe_user", caption=None)))
        self.assertIsNone(parse_user_id_argument(SimpleNamespace(text="/dedupe_user nope", caption=None)))

    def test_visual_dedupe_finds_near_hashes(self) -> None:
        hashes = [
            HashResult("keep", "unique-a", 0b11110000),
            HashResult("duplicate", "unique-b", 0b11110001),
            HashResult("other", "unique-c", 0b00001111),
        ]

        duplicates = find_duplicates(hashes, threshold=1)

        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].duplicate_id, "duplicate")
        self.assertEqual(duplicates[0].keeper_id, "keep")
        self.assertEqual(hamming_distance(0b11110000, 0b11110001), 1)

    def test_visual_dedupe_cleans_chat_history(self) -> None:
        data = {"chat_history": {"1": ["keep", "remove"], "2": ["remove"]}}

        clean_chat_history(data, {"remove"})

        self.assertEqual(data["chat_history"], {"1": ["keep"]})

    def test_text_pool_sizes_stay_intentional(self) -> None:
        self.assertEqual(len(PICTURE_CAPTIONS), 1500)
        self.assertEqual(len(UPLOAD_START_PHRASES), 150)
        self.assertEqual(len(UPLOAD_FINISH_PHRASES), 150)
        self.assertEqual(len(EMPTY_POOL_PHRASES), 150)
        self.assertEqual(len(ACHIEVEMENTS), 50)

    def test_duel_phrase_pools_have_expected_size(self) -> None:
        self.assertEqual(len(DUEL_ANNOUNCEMENTS), 111)
        self.assertEqual(len(DUEL_RESULT_PHRASES), 111)
        self.assertEqual(len(DUEL_ANNOUNCEMENTS) + len(DUEL_RESULT_PHRASES), 222)
        self.assertNotIn(". голосуй", "\n".join(DUEL_ANNOUNCEMENTS))

    def test_main_keyboard_keeps_structured_actions(self) -> None:
        main_buttons = [button.text for row in main_menu().inline_keyboard for button in row]

        self.assertEqual(
            main_buttons,
            ["🎲 Рандом", "⚔️ Дуэль", "⬆️ Загрузка", "👤 Мой вклад", "🏆 Топ", "📊 Статы"],
        )

    def test_upload_keyboard_has_finish_and_cancel(self) -> None:
        upload_buttons = [button.text for row in upload_menu().inline_keyboard for button in row]

        self.assertEqual(upload_buttons, ["✅ Закончить", "❌ Отмена"])

    def test_admin_user_ids_parser_accepts_commas_and_semicolons(self) -> None:
        self.assertEqual(parse_user_ids("1, 2;3"), frozenset({1, 2, 3}))

    def test_achievement_progress_helpers(self) -> None:
        self.assertEqual(current_achievement_for(0), "пока без медали, но путь начат")
        self.assertEqual(current_achievement_for(1), "первый вброс")
        self.assertEqual(next_achievement_for(1), (2, "двойной занос"))

    def test_dislike_jury_thresholds_stay_intentional(self) -> None:
        self.assertEqual(AUTO_DELETE_DISLIKES, 2)
        self.assertNotIn(1, JURY_THRESHOLDS)
        self.assertNotIn(2, JURY_THRESHOLDS)

    def test_duel_score_format(self) -> None:
        self.assertIn("⏱ <b>60 секунд</b>", format_duel_score(2, 1))
        self.assertIn("🅰️ слева: <b>2</b>", format_duel_score(2, 1))
        self.assertIn("🅱️ проиграла и удалена из пула", format_duel_result(2, 1, "left"))
        self.assertIn("Обе пикчи выжили", format_duel_result(1, 1, None))

    def test_quality_title_and_combos(self) -> None:
        stats = SimpleNamespace(uploaded=100, likes=60, fires=1, dislikes=0, shown=60)

        self.assertEqual(quality_title(stats), "поставщик годноты")
        self.assertIn("заливочный марафонец", combo_achievements_for(stats))
        self.assertIn("частый гость рандома", combo_achievements_for(stats))

    def test_user_progress_is_grouped_by_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            pool.add_from_message(fake_photo_message("file-a", "unique-a", user_id=10))

            text = format_user_progress(10, pool)

            self.assertIn("<b>📦 Загрузка</b>", text)
            self.assertIn("<b>📊 Реакции на ваши пикчи</b>", text)
            self.assertIn("<b>🎖 Статус</b>", text)
            self.assertIn("<b>🎯 Следующий рубеж</b>", text)

    def test_core_command_texts_are_grouped(self) -> None:
        self.assertIn("<b>Я @kartinkomet_bot</b>", format_start())
        self.assertIn("⚔️ Дуэль", format_start())
        self.assertIn("<b>⬆️ Загрузка</b>", format_help())
        self.assertIn("<b>⚔️ Игры</b>", format_help())
        self.assertIn("<b>🧠 Режим дня</b>", format_mood())
        self.assertIn("100</b> новых пикч в час", format_upload_limit())


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
            self.assertEqual(payload["users"], {})

    def test_rejects_duplicate_file_unique_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))

            first = pool.add_from_message(fake_photo_message("file-a", "unique-a"))
            second = pool.add_from_message(fake_photo_message("file-b", "unique-a"))

            self.assertTrue(first.added)
            self.assertFalse(second.added)
            self.assertTrue(second.duplicate)
            self.assertEqual(pool.count(), 1)

    def test_limits_successful_uploads_per_user_per_hour(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            user_id = 1628762436

            for index in range(UPLOAD_LIMIT_PER_HOUR):
                result = pool.add_from_message(
                    fake_photo_message(f"file-{index}", f"unique-{index}", user_id=user_id)
                )
                self.assertTrue(result.added)

            blocked = pool.add_from_message(
                fake_photo_message("file-blocked", "unique-blocked", user_id=user_id)
            )
            other_user = pool.add_from_message(
                fake_photo_message("file-other", "unique-other", user_id=1)
            )

            self.assertFalse(blocked.added)
            self.assertTrue(blocked.rate_limited)
            self.assertTrue(other_user.added)
            self.assertEqual(pool.count_by_user(user_id), UPLOAD_LIMIT_PER_HOUR)

    def test_upload_limit_index_updates_after_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            user_id = 10
            for index in range(UPLOAD_LIMIT_PER_HOUR):
                pool.add_from_message(
                    fake_photo_message(f"file-{index}", f"unique-{index}", user_id=user_id)
                )

            deleted = pool.delete(pool._records[0]["id"])
            added_after_delete = pool.add_from_message(
                fake_photo_message("file-new", "unique-new", user_id=user_id)
            )

            self.assertTrue(deleted)
            self.assertTrue(added_after_delete.added)

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

    def test_reaction_stats_by_user(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            pool.add_from_message(fake_photo_message("file-a", "unique-a", user_id=10))
            image = pool.random_image(chat_id=1)
            assert image is not None
            pool.react(image.id, "like", user_id=1)
            pool.react(image.id, "fire", user_id=2)

            stats = pool.reaction_stats_by_user(10)

            self.assertEqual(stats.uploaded, 1)
            self.assertEqual(stats.likes, 1)
            self.assertEqual(stats.fires, 1)
            self.assertEqual(stats.shown, 1)

    def test_remembers_user_labels_for_top_uploaders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            pool.add_from_message(fake_photo_message("file-a", "unique-a", user_id=10))
            pool.remember_user(fake_user(10, username="artem"))

            self.assertEqual(pool.user_label(10), "@artem")
            top_text = format_top_uploaders(pool)
            self.assertIn("<b>👑 Пьедестал</b>", top_text)
            self.assertIn("🥇 <b>@artem</b>", top_text)

    def test_top_uploaders_escapes_user_names_for_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            pool.add_from_message(fake_photo_message("file-a", "unique-a", user_id=10))
            pool.remember_user(fake_user(10, first_name="A < B"))

            self.assertIn("A &lt; B", format_top_uploaders(pool))

    def test_user_label_falls_back_to_id_for_unknown_users(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))

            self.assertEqual(pool.user_label(999), "999")

    def test_dedupe_user_removes_only_target_user_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "pool.json"
            pool = ImagePool(str(storage_path))
            first = pool._normalize_record(
                {
                    "id": "first",
                    "file_id": "file-a",
                    "file_unique_id": "same-image",
                    "added_by": 10,
                }
            )
            duplicate = pool._normalize_record(
                {
                    "id": "duplicate",
                    "file_id": "file-b",
                    "file_unique_id": "same-image",
                    "added_by": 10,
                }
            )
            other_user = pool._normalize_record(
                {
                    "id": "other-user",
                    "file_id": "file-c",
                    "file_unique_id": "other-image",
                    "added_by": 20,
                }
            )
            pool._records = [first, duplicate, other_user]
            pool._chat_history = {"1": ["first", "duplicate", "other-user"]}
            pool._rebuild_indexes()

            result = pool.dedupe_user(10)

            self.assertEqual(result.scanned, 2)
            self.assertEqual(result.removed, 1)
            self.assertEqual(result.remaining, 1)
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
            self.assertEqual([record["id"] for record in payload["images"]], ["first", "other-user"])
            self.assertEqual(payload["chat_history"], {"1": ["first", "other-user"]})

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

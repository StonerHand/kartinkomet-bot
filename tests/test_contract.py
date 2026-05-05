import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bot.__main__ import BOT_COMMANDS
from bot.config import parse_user_ids
from bot.handlers import (
    active_duel_id_for_chat,
    active_duels_by_chat,
    achievement_for,
    clear_active_duel,
    combo_achievements_for,
    current_achievement_for,
    duel_is_stale,
    duel_remaining_seconds,
    duel_sessions,
    duel_tasks,
    format_count,
    format_duel_already_active,
    format_duel_score,
    format_duel_result,
    format_empty_joke_pool,
    format_help,
    format_joke,
    format_joke_duel_result,
    format_joke_duel_score,
    format_mood,
    format_start,
    format_stats,
    format_user_progress,
    format_top_uploaders,
    format_upload_limit,
    format_upload_not_active,
    format_upload_private_only,
    next_achievement_for,
    parse_user_id_argument,
    quality_title,
    register_active_duel,
)
from bot.image_pool import UPLOAD_LIMIT_PER_HOUR, ImagePool
from bot.joke_pool import JokePool, normalize_joke_text
from bot.keyboards import (
    joke_actions,
    joke_actions_with_counts,
    joke_duel_vote,
    main_menu,
    new_joke_duel,
    picture_actions,
    picture_actions_with_counts,
    upload_menu,
)
from bot.texts import (
    ACHIEVEMENTS,
    AUTO_DELETE_DISLIKES,
    DUEL_START_PHRASES,
    DUEL_STATUS_PHRASES,
    DUEL_TIE_PHRASES,
    DUEL_WIN_PHRASES,
    EMPTY_POOL_PHRASES,
    JURY_THRESHOLDS,
    PICTURE_CAPTIONS,
    UPLOAD_FINISH_PHRASES,
    UPLOAD_START_PHRASES,
)
from bot.weather import WeatherReport, format_weather_report, parse_weather_report
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


def fake_text_message(text: str, user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
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
    def test_public_command_order_stays_intentional(self) -> None:
        commands = [command.command for command in BOT_COMMANDS]

        self.assertEqual(
            commands,
            [
                "pic",
                "joke",
                "duel",
                "jokeduel",
                "weather",
                "menu",
                "upload_pidor",
                "upload_joke",
                "done",
                "cancel",
                "stats",
                "me",
                "top",
                "count",
                "mood",
                "help",
            ],
        )
        self.assertIn("upload_pidor", commands)
        self.assertIn("upload_joke", commands)
        self.assertIn("joke", commands)
        self.assertIn("me", commands)
        self.assertIn("top", commands)
        self.assertIn("duel", commands)
        self.assertIn("jokeduel", commands)
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
        self.assertEqual(len(DUEL_START_PHRASES), 100)
        self.assertEqual(len(DUEL_STATUS_PHRASES), 100)
        self.assertEqual(len(DUEL_WIN_PHRASES), 100)
        self.assertEqual(len(DUEL_TIE_PHRASES), 100)
        duel_phrases = "\n".join(
            DUEL_START_PHRASES + DUEL_STATUS_PHRASES + DUEL_WIN_PHRASES + DUEL_TIE_PHRASES
        )
        self.assertNotIn("file_id", duel_phrases)
        self.assertIsNone(re.search(r"\. [а-яё]", duel_phrases))

    def test_main_keyboard_keeps_structured_actions(self) -> None:
        main_buttons = [button.text for row in main_menu().inline_keyboard for button in row]

        self.assertEqual(
            main_buttons,
            [
                "🎲 Рандом",
                "😂 Анекдот",
                "⚔️ Пикчи",
                "😂 Дуэль",
                "🌦 Погода",
                "📊 Сводка",
                "👤 Мой вклад",
                "🏆 Топ",
                "📥 Пикчи",
                "📝 Анекдоты",
            ],
        )

    def test_upload_keyboard_has_finish_and_cancel(self) -> None:
        upload_buttons = [button.text for row in upload_menu().inline_keyboard for button in row]

        self.assertEqual(upload_buttons, ["✅ Закончить", "❌ Отмена"])

    def test_picture_reactions_use_two_buttons_only(self) -> None:
        buttons = [button.text for row in picture_actions("image-id").inline_keyboard for button in row]
        counted_buttons = [
            button.text
            for row in picture_actions_with_counts("image-id", likes=2, dislikes=1).inline_keyboard
            for button in row
        ]

        self.assertEqual(buttons, ["🤙🏻", "🖕🏻", "🎲 Ещё"])
        self.assertEqual(counted_buttons, ["🤙🏻 2", "🖕🏻 1", "🎲 Ещё"])

    def test_joke_reactions_match_picture_reactions(self) -> None:
        buttons = [button.text for row in joke_actions("joke-id").inline_keyboard for button in row]
        counted_buttons = [
            button.text
            for row in joke_actions_with_counts("joke-id", likes=2, dislikes=1).inline_keyboard
            for button in row
        ]

        self.assertEqual(buttons, ["🤙🏻", "🖕🏻", "😂 Ещё анекдот"])
        self.assertEqual(counted_buttons, ["🤙🏻 2", "🖕🏻 1", "😂 Ещё анекдот"])

    def test_joke_duel_keyboard_uses_separate_callbacks(self) -> None:
        buttons = [button.text for row in joke_duel_vote("duel-id", 3, 2).inline_keyboard for button in row]
        callbacks = [
            button.callback_data
            for row in joke_duel_vote("duel-id", 3, 2).inline_keyboard
            for button in row
        ]
        new_buttons = [button.text for row in new_joke_duel().inline_keyboard for button in row]

        self.assertEqual(buttons, ["🅰️ Первый · 3", "🅱️ Второй · 2"])
        self.assertEqual(callbacks, ["joke_duel:duel-id:left", "joke_duel:duel-id:right"])
        self.assertEqual(new_buttons, ["😂 Новая дуэль"])

    def test_admin_user_ids_parser_accepts_commas_and_semicolons(self) -> None:
        self.assertEqual(parse_user_ids("1, 2;3"), frozenset({1, 2, 3}))

    def test_achievement_progress_helpers(self) -> None:
        self.assertEqual(current_achievement_for(0), "пока без медали, но путь начат")
        self.assertEqual(current_achievement_for(1), "первый вброс")
        self.assertEqual(next_achievement_for(1), (2, "двойной занос"))

    def test_achievement_message_does_not_ping_username(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            message = fake_photo_message("file-a", "unique-a", user_id=10)
            message.from_user.username = "artem"
            pool.add_from_message(message)

            text = achievement_for(message, pool)
            duplicate_text = achievement_for(message, pool, {1})

            self.assertIsNotNone(text)
            assert text is not None
            self.assertIn("artem загрузил пикч", text)
            self.assertNotIn("@artem", text)
            self.assertIsNone(duplicate_text)

    def test_dislike_jury_thresholds_stay_intentional(self) -> None:
        self.assertEqual(AUTO_DELETE_DISLIKES, 2)
        self.assertNotIn(1, JURY_THRESHOLDS)
        self.assertNotIn(2, JURY_THRESHOLDS)

    def test_duel_score_format(self) -> None:
        score = format_duel_score(
            2,
            1,
            title="Суд мемов",
            status="Чат держит паузу",
            remaining_seconds=45,
        )

        self.assertIn("<b>⚔️ Суд мемов</b>", score)
        self.assertIn("Чат держит паузу", score)
        self.assertIn("🅰️ слева: <b>2</b> · 🅱️ справа: <b>1</b>\n\n⏱", score)
        self.assertIn("<b>45 секунд</b>", score)
        self.assertIn("🔥 🅰️ ведёт", score)
        self.assertIn("👑 Выжила: <b>🅰️ слева</b>", format_duel_result(2, 1, "left"))
        self.assertIn("🗑 Улетела из пула: <b>🅱️ справа</b>", format_duel_result(2, 1, "left"))
        self.assertIn("⚖️ Ничья. Обе пикчи остаются в пуле", format_duel_result(1, 1, None))

    def test_one_active_duel_per_chat_guard(self) -> None:
        duel_sessions.clear()
        active_duels_by_chat.clear()
        duel_tasks.clear()

        duel_sessions["duel-1"] = {"active": True, "expires_at": 10**12}
        register_active_duel(123, "duel-1")

        self.assertEqual(active_duel_id_for_chat(123), "duel-1")

        duel_sessions["duel-1"]["active"] = False

        self.assertIsNone(active_duel_id_for_chat(123))
        self.assertNotIn(123, active_duels_by_chat)
        self.assertIn("Дуэль уже идёт", format_duel_already_active())

        duel_sessions["duel-2"] = {"active": True, "expires_at": 10**12}
        register_active_duel(123, "duel-2")
        clear_active_duel(123, "other-duel")
        self.assertEqual(active_duel_id_for_chat(123), "duel-2")
        clear_active_duel(123, "duel-2")
        self.assertIsNone(active_duel_id_for_chat(123))
        duel_sessions.clear()
        duel_tasks.clear()

    def test_stale_duel_is_cleared_from_active_guard(self) -> None:
        duel_sessions.clear()
        active_duels_by_chat.clear()
        duel_tasks.clear()

        duel_sessions["stale-duel"] = {"active": True, "expires_at": 0}
        register_active_duel(123, "stale-duel")

        self.assertTrue(duel_is_stale(duel_sessions["stale-duel"]))
        self.assertEqual(duel_remaining_seconds(duel_sessions["stale-duel"]), 0)
        self.assertIsNone(active_duel_id_for_chat(123))
        self.assertNotIn(123, active_duels_by_chat)
        self.assertNotIn("stale-duel", duel_sessions)

    def test_quality_title_and_combos(self) -> None:
        stats = SimpleNamespace(uploaded=100, likes=60, dislikes=0, shown=60)

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
        self.assertIn("<b>👋 Я @kartinkomet_bot</b>", format_start())
        self.assertIn("😂 Анекдот", format_start())
        self.assertIn("⚔️ Пикчи", format_start())
        self.assertIn("😂 Дуэль", format_start())
        self.assertIn("🌦 Погода", format_start())
        self.assertIn("📝 Анекдоты", format_start())
        self.assertIn("<b>📥 Загрузка</b>", format_help())
        self.assertIn("<b>😂 Анекдоты</b>", format_help())
        self.assertIn("/upload_joke", format_help())
        self.assertIn("/jokeduel", format_help())
        self.assertIn("<b>⚔️ Дуэли</b>", format_help())
        self.assertIn("/weather", format_help())
        self.assertIn("<b>🧠 Режим дня</b>", format_mood())
        self.assertIn("Загрузка уехала в личку", format_upload_private_only())
        self.assertIn("/upload_pidor", format_upload_private_only())
        self.assertIn("Лимит: <b>100 новых пикч в час</b>", format_upload_limit())
        self.assertIn("Загрузка не открыта", format_upload_not_active())
        self.assertIn("/upload_joke", format_upload_not_active())
        self.assertIn("Анекдотов пока нет", format_empty_joke_pool())
        self.assertIn("<blockquote>A &lt; B</blockquote>", format_joke("A < B"))

    def test_joke_duel_score_and_result_are_quoted(self) -> None:
        score = format_joke_duel_score(
            "Первый <текст>",
            "Второй текст",
            1,
            2,
            title="Суд шуток",
            status="Чат слушает",
            remaining_seconds=30,
        )

        self.assertIn("<b>😂⚔️ Суд шуток</b>", score)
        self.assertIn("<blockquote>Первый &lt;текст&gt;</blockquote>", score)
        self.assertIn("🅰️ первый: <b>1</b> · 🅱️ второй: <b>2</b>\n\n⏱", score)
        self.assertIn("🔥 🅱️ ведёт", score)
        self.assertIn("🗑 Улетел из блокнота: <b>🅰️ первый</b>", format_joke_duel_result("a", "b", 1, 2, "right"))
        self.assertIn("⚖️ Ничья. Оба анекдота остаются в блокноте", format_joke_duel_result("a", "b", 1, 1, None))

    def test_weather_report_format(self) -> None:
        report = WeatherReport(
            place="Малая Токмачка",
            temperature=12.4,
            apparent_temperature=10.2,
            wind_speed=18.1,
            weather_code=3,
            daily_min=7.1,
            daily_max=15.8,
            precipitation_probability=42,
            fetched_at="2026-04-29T10:00",
        )

        text = format_weather_report(report)

        self.assertIn("<b>☁️ Малая Токмачка</b>", text)
        self.assertIn("пасмурно", text)
        self.assertIn("+12°C", text)
        self.assertIn("42%", text)

    def test_weather_payload_parser(self) -> None:
        payload = {
            "current": {
                "time": "2026-04-29T10:00",
                "temperature_2m": 12.4,
                "apparent_temperature": 10.2,
                "weather_code": 3,
                "wind_speed_10m": 18.1,
            },
            "daily": {
                "temperature_2m_min": [7.1],
                "temperature_2m_max": [15.8],
                "precipitation_probability_max": [42],
            },
        }

        report = parse_weather_report(payload)

        self.assertEqual(report.place, "Малая Токмачка")
        self.assertEqual(report.weather_code, 3)
        self.assertEqual(report.precipitation_probability, 42)


class JokePoolTest(unittest.TestCase):
    def test_normalizes_text_and_rejects_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = JokePool(str(Path(temp_dir) / "jokes.json"))

            first = pool.add_from_message(fake_text_message("  Первая строка\n\n\nВторая строка  "))
            duplicate = pool.add_from_message(fake_text_message("первая строка\nвторая строка"))

            self.assertTrue(first.added)
            self.assertFalse(duplicate.added)
            self.assertTrue(duplicate.duplicate)
            self.assertEqual(pool.count(), 1)
            self.assertEqual(normalize_joke_text("a\n\n\nb"), "a\n\nb")

    def test_random_joke_avoids_immediate_repeat_per_chat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = JokePool(str(Path(temp_dir) / "jokes.json"))
            pool.add_from_message(fake_text_message("Анекдот один"))
            pool.add_from_message(fake_text_message("Анекдот два"))

            first = pool.random_joke(chat_id=123)
            second = pool.random_joke(chat_id=123)

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            assert first is not None
            assert second is not None
            self.assertNotEqual(first.id, second.id)

    def test_random_joke_duel_pair_marks_two_distinct_jokes_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = JokePool(str(Path(temp_dir) / "jokes.json"))
            pool.add_from_message(fake_text_message("Анекдот один"))
            pool.add_from_message(fake_text_message("Анекдот два"))

            pair = pool.random_duel_pair(chat_id=123)

            self.assertIsNotNone(pair)
            assert pair is not None
            left, right = pair
            self.assertNotEqual(left.id, right.id)
            self.assertEqual(pool.stats().total_shows, 2)

    def test_joke_reactions_accumulate_and_can_be_switched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = JokePool(str(Path(temp_dir) / "jokes.json"))
            pool.add_from_message(fake_text_message("Анекдот"))
            joke = pool.random_joke(chat_id=1)
            self.assertIsNotNone(joke)
            assert joke is not None

            pool.react(joke.id, "like", user_id=1)
            switched = pool.react(joke.id, "dislike", user_id=1)
            another_user = pool.react(joke.id, "dislike", user_id=2)
            ignored = pool.react(joke.id, "poop", user_id=3)

            self.assertTrue(switched.changed)
            self.assertTrue(another_user.changed)
            self.assertIsNone(ignored)
            stats = pool.stats()
            self.assertEqual(stats.total_likes, 0)
            self.assertEqual(stats.total_dislikes, 2)

    def test_joke_delete_and_reset_stats(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "jokes.json"
            pool = JokePool(str(storage_path))
            pool.add_from_message(fake_text_message("Анекдот"))
            joke = pool.random_joke(chat_id=555)
            self.assertIsNotNone(joke)
            assert joke is not None

            pool.react(joke.id, "dislike", user_id=1)
            pool.reset_stats()
            stats = pool.stats()
            self.assertEqual(stats.total_shows, 0)
            self.assertEqual(stats.total_dislikes, 0)
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["chat_history"], {})

            self.assertTrue(pool.delete(joke.id))
            self.assertEqual(pool.count(), 0)

    def test_stats_and_count_include_jokes_when_pool_is_passed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            joke_pool = JokePool(str(Path(temp_dir) / "jokes.json"))
            joke_pool.add_from_message(fake_text_message("Анекдот"))

            self.assertIn("<b>😂 Анекдоты</b>", format_stats(image_pool, joke_pool))
            self.assertIn("Анекдотов в блокноте: <b>1</b>", format_count(image_pool, joke_pool))


class ImagePoolTest(unittest.TestCase):
    def test_migrates_old_file_id_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "pool.json"
            storage_path.write_text(json.dumps(["file-a", "file-b"]), encoding="utf-8")

            pool = ImagePool(str(storage_path))

            self.assertEqual(pool.count(), 2)
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 3)
            self.assertEqual(len(payload["images"]), 2)
            self.assertEqual(payload["users"], {})
            self.assertEqual(payload["duel_stats"], {"total": 0, "executions": 0, "ties": 0})

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

    def test_duel_stats_are_persisted_and_shown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "pool.json"
            pool = ImagePool(str(storage_path))

            pool.record_duel_result(tied=False)
            pool.record_duel_result(tied=True)

            stats = pool.stats()
            self.assertEqual(stats.total_duels, 2)
            self.assertEqual(stats.duel_executions, 1)
            self.assertEqual(stats.duel_ties, 1)
            self.assertIn("<b>⚔️ Дуэли</b>", format_stats(pool))
            self.assertIn("Казней: <b>1</b>", format_stats(pool))

            reloaded_pool = ImagePool(str(storage_path))
            self.assertEqual(reloaded_pool.stats().total_duels, 2)

    def test_finish_duel_removes_loser_and_records_stats_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "pool.json"
            pool = ImagePool(str(storage_path))
            pool.add_from_message(fake_photo_message("file-a", "unique-a"))
            pool.add_from_message(fake_photo_message("file-b", "unique-b"))
            loser_id = pool._records[0]["id"]

            removed = pool.finish_duel(loser_id=loser_id)

            self.assertTrue(removed)
            self.assertEqual(pool.count(), 1)
            stats = pool.stats()
            self.assertEqual(stats.total_duels, 1)
            self.assertEqual(stats.duel_executions, 1)
            self.assertEqual(stats.duel_ties, 0)

    def test_random_duel_pair_marks_two_distinct_images_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            pool.add_from_message(fake_photo_message("file-a", "unique-a"))
            pool.add_from_message(fake_photo_message("file-b", "unique-b"))

            pair = pool.random_duel_pair(chat_id=123)

            self.assertIsNotNone(pair)
            assert pair is not None
            left, right = pair
            self.assertNotEqual(left.id, right.id)
            self.assertEqual(pool.stats().total_shows, 2)

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
            ignored = pool.react(image.id, "poop", user_id=3)

            self.assertTrue(switched.changed)
            self.assertTrue(another_user.changed)
            self.assertIsNone(ignored)
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
            pool.react(image.id, "dislike", user_id=2)

            stats = pool.reaction_stats_by_user(10)

            self.assertEqual(stats.uploaded, 1)
            self.assertEqual(stats.likes, 1)
            self.assertEqual(stats.dislikes, 1)
            self.assertEqual(stats.shown, 1)

    def test_remembers_user_labels_for_top_uploaders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = ImagePool(str(Path(temp_dir) / "pool.json"))
            pool.add_from_message(fake_photo_message("file-a", "unique-a", user_id=10))
            pool.remember_user(fake_user(10, username="artem"))

            self.assertEqual(pool.user_label(10), "artem")
            top_text = format_top_uploaders(pool)
            self.assertIn("<b>👑 Пьедестал:</b>", top_text)
            self.assertIn("🥇 <b>artem</b> — <b>1</b> пикч", top_text)
            self.assertNotIn("@artem", top_text)

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
            pool.react(image.id, "dislike", user_id=1)
            pool.record_duel_result(tied=False)
            pool.record_duel_result(tied=True)

            pool.reset_stats()

            stats = pool.stats()
            self.assertEqual(stats.total_shows, 0)
            self.assertEqual(stats.total_dislikes, 0)
            self.assertEqual(stats.total_duels, 0)
            self.assertEqual(stats.duel_executions, 0)
            self.assertEqual(stats.duel_ties, 0)
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["chat_history"], {})
            self.assertEqual(payload["duel_stats"], {"total": 0, "executions": 0, "ties": 0})


if __name__ == "__main__":
    unittest.main()

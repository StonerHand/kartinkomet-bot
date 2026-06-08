import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bot.__main__ import BOT_COMMANDS
from bot.config import parse_user_ids
from bot.handlers import (
    active_duel_id_for_chat,
    active_duels_by_chat,
    active_tournament_id_for_chat,
    active_tournaments_by_chat,
    backup_json_sources,
    clear_active_duel,
    clear_active_tournament,
    duel_sessions,
    format_admin_panel,
    format_arena_menu,
    format_count,
    format_count_alert,
    format_duel_already_active,
    format_duel_result,
    format_duel_score,
    format_empty_picture_pool,
    format_help,
    format_health,
    format_main_menu,
    format_random_menu,
    format_start,
    format_stats,
    format_storage_menu,
    format_upload_burst_limit,
    format_upload_cancelled,
    format_upload_opened,
    format_upload_progress,
    format_tournament_result,
    format_tournament_score,
    format_upload_hub,
    format_upload_not_active,
    format_upload_private_only,
    new_upload_session,
    parse_user_id_argument,
    register_active_duel,
    register_active_tournament,
    resolve_image_duel_result,
    resolve_tournament_result,
    tournament_sessions,
)
from bot.image_pool import (
    GLOBAL_RECENT_LIMIT,
    MAX_CHAT_HISTORY,
    RANDOM_CANDIDATE_LIMIT,
    UPLOAD_LIMIT_PER_HOUR,
    ImagePool,
)
from bot.keyboards import (
    admin_menu,
    arena_menu,
    duel_vote,
    empty_picture_pool_actions,
    main_menu,
    new_duel,
    new_tournament,
    picture_actions,
    picture_actions_with_counts,
    random_menu,
    storage_menu,
    tournament_vote,
    upload_hub,
    upload_menu,
)
from bot.texts import AUTO_DELETE_DISLIKES, PICTURE_CAPTIONS
from bot.visual_hash import visual_hash_distance
from scripts.visual_dedupe import HashResult, clean_chat_history, find_duplicates, hamming_distance


def fake_photo_message(file_id: str, file_unique_id: str, user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        photo=[SimpleNamespace(file_id=file_id, file_unique_id=file_unique_id)],
        document=None,
        from_user=SimpleNamespace(
            id=user_id,
            username=f"user_{user_id}",
            first_name=f"User {user_id}",
            last_name=None,
        ),
    )


def button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def callback_data(markup) -> list[str | None]:
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def button_styles(markup) -> list[str | None]:
    return [getattr(button, "style", None) for row in markup.inline_keyboard for button in row]


class BotContractTest(unittest.TestCase):
    def tearDown(self) -> None:
        active_duels_by_chat.clear()
        active_tournaments_by_chat.clear()
        duel_sessions.clear()
        tournament_sessions.clear()

    def test_public_commands_are_image_only_and_ordered(self) -> None:
        commands = [command.command for command in BOT_COMMANDS]

        self.assertEqual(
            commands,
            [
                "start",
                "menu",
                "pic",
                "duel",
                "tournament",
                "upload_pidor",
                "stats",
                "count",
                "me",
                "top",
                "help",
            ],
        )
        self.assertNotIn("weather", commands)
        self.assertNotIn("joke", commands)
        self.assertNotIn("jokeduel", commands)
        self.assertNotIn("upload_joke", commands)
        self.assertNotIn("roulette", commands)

    def test_parse_user_ids_accepts_commas_and_semicolons(self) -> None:
        self.assertEqual(parse_user_ids("1, 2;3"), frozenset({1, 2, 3}))
        with self.assertRaises(RuntimeError):
            parse_user_ids("1, nope")

    def test_sqlite_schema_is_image_only_for_new_databases(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            temp_dir = Path(raw_temp_dir)
            pool = ImagePool(
                str(temp_dir / "image_pool.json"),
                database_path=str(temp_dir / "kartinkomet.sqlite"),
            )
            backup_path = temp_dir / "backup.sqlite"

            self.assertTrue(pool.export_database_backup(backup_path))
            with sqlite3.connect(backup_path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                image_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(images)")
                }

        self.assertIn("images", tables)
        self.assertIn("image_reactions", tables)
        self.assertIn("image_chat_history", tables)
        self.assertIn("visual_hash", image_columns)
        self.assertNotIn("jokes", tables)
        self.assertNotIn("joke_reactions", tables)

    def test_existing_sqlite_database_migrates_visual_hash_column(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            temp_dir = Path(raw_temp_dir)
            database_path = temp_dir / "kartinkomet.sqlite"
            with sqlite3.connect(database_path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE images (
                        id TEXT PRIMARY KEY,
                        position INTEGER NOT NULL DEFAULT 0,
                        file_id TEXT NOT NULL,
                        file_unique_id TEXT NOT NULL UNIQUE,
                        added_by INTEGER,
                        added_at TEXT,
                        shown_count INTEGER NOT NULL DEFAULT 0,
                        last_shown_at TEXT,
                        likes INTEGER NOT NULL DEFAULT 0,
                        dislikes INTEGER NOT NULL DEFAULT 0
                    );
                    INSERT INTO images (
                        id, position, file_id, file_unique_id, shown_count, likes, dislikes
                    )
                    VALUES ('legacy', 0, 'file-id', 'unique-id', 0, 0, 0);
                    """
                )

            pool = ImagePool(
                str(temp_dir / "image_pool.json"),
                database_path=str(database_path),
            )

            with sqlite3.connect(database_path) as connection:
                image_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(images)")
                }

        self.assertEqual(pool.count(), 1)
        self.assertIn("visual_hash", image_columns)

    def test_backup_sources_are_railway_image_storage_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            pool = ImagePool(str(Path(raw_temp_dir) / "image_pool.json"))
            sources = backup_json_sources(pool)

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0][0].name, "image_pool.json")
        self.assertIn("пикч", sources[0][1])

    def test_image_pool_add_react_random_and_duel_delete(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            pool = ImagePool(str(Path(raw_temp_dir) / "image_pool.json"))
            visual_hashes = [
                "0000000000000000",
                "ffffffffffffffff",
                "aaaaaaaaaaaaaaaa",
            ]
            for index in range(3):
                result = pool.add_from_message(
                    fake_photo_message(f"file-{index}", f"unique-{index}"),
                    visual_hash=visual_hashes[index],
                )
                self.assertTrue(result.added)

            duplicate = pool.add_from_message(fake_photo_message("file-0", "unique-0"))
            self.assertTrue(duplicate.duplicate)
            visual_duplicate = pool.add_from_message(
                fake_photo_message("file-visual", "unique-visual"),
                visual_hash="0000000000000001",
            )
            self.assertTrue(visual_duplicate.duplicate)
            self.assertTrue(visual_duplicate.visual_duplicate)
            self.assertEqual(pool.count(), 3)
            self.assertEqual(pool.health().visual_hashes, 3)

            first = pool.random_image(chat_id=10)
            second = pool.random_image(chat_id=10)
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            assert first is not None and second is not None
            self.assertNotEqual(first.id, second.id)

            switched = pool.react(first.id, "like", user_id=1)
            self.assertIsNotNone(switched)
            switched = pool.react(first.id, "dislike", user_id=1)
            self.assertIsNotNone(switched)
            second_dislike = pool.react(first.id, "dislike", user_id=2)
            self.assertIsNotNone(second_dislike)
            assert second_dislike is not None
            self.assertEqual(second_dislike.image.likes, 0)
            self.assertEqual(second_dislike.image.dislikes, 2)

            pair = pool.random_duel_pair(chat_id=20)
            self.assertIsNotNone(pair)
            assert pair is not None
            loser_id = pair[0].id
            self.assertTrue(pool.finish_duel(loser_id=loser_id))
            self.assertEqual(pool.count(), 2)
            self.assertEqual(pool.stats().duel_executions, 1)

    def test_random_image_falls_back_when_candidate_window_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            pool = ImagePool(str(Path(raw_temp_dir) / "image_pool.json"))
            pool.add_from_message(fake_photo_message("file-one", "unique-one"))
            pool._selectable_records = lambda *args, **kwargs: []  # type: ignore[method-assign]

            image = pool.random_image(chat_id=10)

        self.assertIsNotNone(image)

    def test_upload_limit_and_user_labels(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            pool = ImagePool(str(Path(raw_temp_dir) / "image_pool.json"))
            user = SimpleNamespace(id=777, username="NamedUser", first_name="Named", last_name=None)
            pool.remember_user(user)

            self.assertEqual(pool.user_label(777), "NamedUser")
            self.assertEqual(UPLOAD_LIMIT_PER_HOUR, 1000)

    def test_random_memory_constants_are_tuned_for_large_pool(self) -> None:
        self.assertGreaterEqual(RANDOM_CANDIDATE_LIMIT, 180)
        self.assertGreaterEqual(GLOBAL_RECENT_LIMIT, 500)
        self.assertGreaterEqual(MAX_CHAT_HISTORY, 900)

    def test_hidden_dedupe_argument_parser(self) -> None:
        self.assertEqual(
            parse_user_id_argument(SimpleNamespace(text="/dedupe_user 1045485205", caption=None)),
            1045485205,
        )
        self.assertIsNone(parse_user_id_argument(SimpleNamespace(text="/dedupe_user", caption=None)))
        self.assertIsNone(parse_user_id_argument(SimpleNamespace(text="/dedupe_user nope", caption=None)))

    def test_keyboards_have_clean_image_only_navigation(self) -> None:
        self.assertEqual(button_texts(random_menu()), ["🎲 Рандомная пикча", "↩️ Пульт"])
        self.assertEqual(
            button_texts(arena_menu()),
            ["⚔️ Пикч-бой", "🏟 Турнир", "📊 Сводка арен", "↩️ Пульт"],
        )
        self.assertEqual(
            button_texts(main_menu()),
            ["🎲 Рандом", "⚔️ Дуэль", "🏟 Турнир", "📦 Склад", "📊 Сводка", "📥 Загрузка"],
        )
        self.assertEqual(
            button_texts(main_menu(is_private=True, is_admin=True)),
            ["🎲 Рандом", "⚔️ Дуэль", "🏟 Турнир", "📦 Склад", "📊 Сводка", "📥 Загрузка", "🧰 Админка"],
        )
        self.assertEqual(
            button_texts(admin_menu()),
            ["🩺 Health", "🗄 Бэкап", "♻️ Сброс стат", "🧹 Дубли", "🎛 Пульт"],
        )
        self.assertEqual(button_texts(upload_hub(is_private=True)), ["📥 Начать загрузку", "↩️ Пульт"])
        self.assertEqual(button_texts(upload_menu()), ["✅ Закончить", "❌ Отмена"])
        self.assertEqual(
            callback_data(picture_actions("image-id")),
            [
                "react:like:image-id",
                "react:dislike:image-id",
                "pic",
                "duel_new",
                "tournament_new",
            ],
        )
        self.assertEqual(button_texts(picture_actions_with_counts("image-id", 3, 1))[:2], ["🤙🏻 3", "🖕🏻 1"])
        self.assertEqual(button_texts(duel_vote("duel-id")), ["🅰️ Первый: 0", "🅱️ Второй: 0"])
        self.assertEqual(
            button_texts(tournament_vote("tournament-id")),
            ["1️⃣ Первая: 0", "2️⃣ Вторая: 0", "3️⃣ Третья: 0", "4️⃣ Четвёртая: 0"],
        )
        self.assertEqual(button_texts(new_duel()), ["⚔️ Реванш", "🎲 Рандом", "🏟 Турнир", "🎛 Пульт"])
        self.assertEqual(button_texts(new_tournament()), ["🏟 Реванш", "🎲 Рандом", "⚔️ Дуэль", "🎛 Пульт"])
        self.assertEqual(button_texts(storage_menu()), ["📦 Счётчик", "📬 В личку", "🏆 Топ", "👤 Мой вклад", "↩️ Пульт"])
        self.assertEqual(button_texts(empty_picture_pool_actions()), ["📬 Как загрузить пикчи", "🎛 Пульт"])

    def test_keyboards_use_semantic_button_styles(self) -> None:
        self.assertEqual(
            button_styles(main_menu()),
            ["primary", "primary", "primary", "primary", "primary", "success"],
        )
        self.assertEqual(button_styles(upload_menu()), ["success", "danger"])
        self.assertEqual(button_styles(picture_actions_with_counts("image-id", 3, 1))[:2], ["success", "danger"])
        self.assertEqual(button_styles(random_menu()), ["primary", None])
        self.assertEqual(
            button_styles(admin_menu()),
            ["primary", "success", "danger", "primary", None],
        )

    def test_ui_text_is_current_and_not_feature_noisy(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            pool = ImagePool(str(Path(raw_temp_dir) / "image_pool.json"))
            texts = [
                format_start(),
                format_help(),
                format_main_menu(pool, chat_id=1, is_private=False),
                format_random_menu(),
                format_arena_menu(chat_id=1),
                format_storage_menu(pool),
                format_stats(pool, chat_id=1),
                format_count(pool),
                format_count_alert(pool),
                format_admin_panel(pool),
                format_health(pool),
                format_upload_hub(is_private=True),
                format_upload_opened("Скидывайте визуальные улики"),
                format_upload_progress(new_upload_session()),
                format_upload_cancelled(),
                format_upload_burst_limit(),
                format_upload_private_only(),
                format_upload_not_active(),
                format_empty_picture_pool("Пока пусто", is_private=False),
            ]

        joined = "\n".join(texts).lower()
        self.assertIn("пикч", joined)
        self.assertIn("турнир", joined)
        self.assertNotIn("анек", joined)
        self.assertNotIn("погод", joined)
        self.assertNotIn("cloudflare", joined)

    def test_readme_keeps_admin_commands_out_of_public_command_map(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for readme_name in ("README.md", "README.en.md"):
            text = (root / readme_name).read_text(encoding="utf-8")
            public_commands = text.split("## UX", maxsplit=1)[0]

            self.assertNotIn("/reset_stats", public_commands)
            self.assertIn("/reset_stats", text)

    def test_docs_describe_current_storage_and_button_styles(self) -> None:
        root = Path(__file__).resolve().parents[1]
        docs = [
            (root / "README.md").read_text(encoding="utf-8"),
            (root / "README.en.md").read_text(encoding="utf-8"),
            (root / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8"),
        ]

        for text in docs:
            self.assertIn("kartinkomet.sqlite", text)
            self.assertIn("primary", text)
            self.assertIn("success", text)
            self.assertIn("danger", text)
            self.assertNotIn("Cloudflare Worker", text)

    def test_duel_and_tournament_sessions_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            pool = ImagePool(str(Path(raw_temp_dir) / "image_pool.json"))
            pool.add_from_message(fake_photo_message("left-file", "left-unique"))
            pool.add_from_message(fake_photo_message("right-file", "right-unique"))
            pair = pool.random_duel_pair(chat_id=1)
            self.assertIsNotNone(pair)
            assert pair is not None

            duel = {"left": pair[0].id, "right": pair[1].id, "votes": {1: "left"}, "active": True}
            first_result = resolve_image_duel_result(duel, pool)
            second_result = resolve_image_duel_result(duel, pool)
            self.assertEqual(first_result, second_result)
            self.assertEqual(pool.count(), 1)

            for index in range(4):
                pool.add_from_message(fake_photo_message(f"file-{index}", f"unique-{index}"))
            candidates = pool.random_tournament_candidates(chat_id=1, size=4)
            self.assertIsNotNone(candidates)
            assert candidates is not None
            tournament = {
                "candidates": [candidate.id for candidate in candidates],
                "votes": {1: 0, 2: 1, 3: 1},
                "active": True,
            }
            result = resolve_tournament_result(tournament, pool)
            self.assertEqual(result, resolve_tournament_result(tournament, pool))
            self.assertIn("Финал витрины", result)

    def test_active_arena_registry_clears_the_right_chat(self) -> None:
        duel_sessions["duel-1"] = {"kind": "image", "active": True, "expires_at": 10**12}
        register_active_duel(123, "image", "duel-1")
        self.assertEqual(active_duel_id_for_chat(123, "image"), "duel-1")
        clear_active_duel(123, "image", "duel-1")
        self.assertIsNone(active_duel_id_for_chat(123, "image"))

        tournament_sessions["tournament-1"] = {"active": True, "expires_at": 10**12}
        register_active_tournament(123, "tournament-1")
        self.assertEqual(active_tournament_id_for_chat(123), "tournament-1")
        clear_active_tournament(123, "tournament-1")
        self.assertIsNone(active_tournament_id_for_chat(123))

    def test_score_cards_keep_readable_sections(self) -> None:
        self.assertIn("Счёт", format_duel_score(1, 2, status="Ведёт B", remaining_seconds=30))
        self.assertIn("🅰️ Первый: <b>1</b>", format_duel_score(1, 2, status="Ведёт B", remaining_seconds=30))
        self.assertIn("Статус", format_duel_score(1, 2, status="Ведёт B", remaining_seconds=30))
        self.assertIn("Приговор арены", format_duel_result(2, 1, winner="left"))
        self.assertIn("Счёт", format_tournament_score([1, 2, 3, 4], status="Идёт", remaining_seconds=50))
        self.assertIn("1️⃣ Первая: <b>1</b> · 2️⃣ Вторая: <b>2</b>", format_tournament_score([1, 2, 3, 4], status="Идёт", remaining_seconds=50))
        self.assertIn("Чемпион", format_tournament_result([0, 3, 1, 1], winner=1))
        self.assertIn("чемпион не выбран", format_tournament_result([1, 1, 1, 1], winner=None).lower())
        self.assertIn("пикчевая арена", format_duel_already_active())

    def test_upload_panel_uses_one_compact_progress_card(self) -> None:
        data = new_upload_session()
        data["added"] = 7
        data["duplicates"] = 2
        data["failed"] = 1

        progress = format_upload_progress(data)
        cancelled = format_upload_cancelled()

        self.assertIn("Прогресс пакета", progress)
        self.assertIn("✅ Добавлено: <b>7</b>", progress)
        self.assertIn("♻️ Дубли: <b>2</b>", progress)
        self.assertIn("🚫 Не принято: <b>1</b>", progress)
        self.assertIn("<code>✅ Закончить</code>", progress)
        self.assertIn("<code>❌ Отмена</code>", progress)
        self.assertNotIn("Уже добавлено", cancelled)

    def test_visual_dedupe_helpers(self) -> None:
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
        self.assertEqual(visual_hash_distance("0000000000000000", "0000000000000001"), 1)
        self.assertIsNone(visual_hash_distance("nope", "0000000000000001"))

        data = {"chat_history": {"1": ["keep", "remove"], "2": ["remove"]}}
        clean_chat_history(data, {"remove"})
        self.assertEqual(data["chat_history"], {"1": ["keep"]})

    def test_picture_caption_pool_is_large(self) -> None:
        self.assertGreaterEqual(len(PICTURE_CAPTIONS), 1500)
        self.assertEqual(AUTO_DELETE_DISLIKES, 2)


if __name__ == "__main__":
    unittest.main()

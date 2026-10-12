import unittest

from bot.core import court
from tests.helpers import make_game


class RandomTest(unittest.TestCase):
    def test_deck_shows_every_pic_once_per_cycle(self) -> None:
        game, _, temp = make_game(pics=20)
        self.addCleanup(temp.cleanup)
        first_cycle = [game.draw_pic(1)[0].id for _ in range(20)]
        self.assertEqual(len(set(first_cycle)), 20)
        # Next draw starts a new cycle instead of failing.
        self.assertIsNotNone(game.draw_pic(1))

    def test_chats_have_separate_decks(self) -> None:
        game, _, temp = make_game(pics=3)
        self.addCleanup(temp.cleanup)
        for _ in range(3):
            game.draw_pic(1)
        self.assertEqual(game.repo.db.execute("SELECT COUNT(*) FROM deck_seen WHERE scope='pic:2'").fetchone()[0], 0)

    def test_empty_pool(self) -> None:
        game, _, temp = make_game(pics=0)
        self.addCleanup(temp.cleanup)
        self.assertIsNone(game.draw_pic(1))

    def test_executed_pics_never_drop(self) -> None:
        game, clock, temp = make_game(pics=2)
        self.addCleanup(temp.cleanup)
        dead = game.repo.draw("x", "deck", game.now())[0]
        game.repo.remove_pic(dead.id, "executed", "court", game.now())
        for _ in range(10):
            self.assertNotEqual(game.draw_pic(1)[0].id, dead.id)


class ReactionTest(unittest.TestCase):
    def test_second_dislike_calls_court_once(self) -> None:
        game, _, temp = make_game(pics=1)
        self.addCleanup(temp.cleanup)
        pic = game.draw_pic(1)[0]
        self.assertFalse(game.react(pic.id, 10, -1).court_due)
        self.assertTrue(game.react(pic.id, 11, -1).court_due)
        result = game.react(pic.id, 11, -1)
        self.assertFalse(result.changed)

    def test_switching_vote_moves_counters(self) -> None:
        game, _, temp = make_game(pics=1)
        self.addCleanup(temp.cleanup)
        pic = game.draw_pic(1)[0]
        game.react(pic.id, 10, 1)
        result = game.react(pic.id, 10, -1)
        self.assertEqual((result.pic.likes, result.pic.dislikes), (0, 1))


class DuelTest(unittest.TestCase):
    def test_full_duel_updates_ratings_and_allows_champion(self) -> None:
        game, clock, temp = make_game(pics=5)
        self.addCleanup(temp.cleanup)
        started = game.start_duel(1)
        self.assertEqual(started.status, "started")
        battle = started.battle
        self.assertEqual(game.start_duel(1).status, "active")

        self.assertEqual(game.vote_battle(battle.id, 100, 0)[0], "ok")
        self.assertEqual(game.vote_battle(battle.id, 100, 0)[0], "same")
        game.vote_battle(battle.id, 101, 0)
        game.vote_battle(battle.id, 102, 1)
        clock.advance(61)
        self.assertEqual(game.vote_battle(battle.id, 103, 1)[0], "expired")

        report = game.finish_battle(battle.id)
        self.assertIsNotNone(report)
        self.assertIsNone(game.finish_battle(battle.id))
        self.assertEqual(report.winner, 0)
        self.assertGreater(report.rating_after[0], report.rating_before[0])
        winner = game.repo.get_pic(battle.pics[0].id)
        self.assertEqual((winner.games, winner.wins), (1, 1))

        champion_duel = game.start_duel(1, champion_of=battle.id)
        self.assertEqual(champion_duel.status, "started")
        self.assertEqual(champion_duel.battle.pics[0].id, winner.id)
        self.assertEqual(champion_duel.battle.streak, 1)

    def test_old_champion_button_is_stale(self) -> None:
        game, clock, temp = make_game(pics=6)
        self.addCleanup(temp.cleanup)
        first = game.start_duel(1).battle
        game.vote_battle(first.id, 100, 0)
        clock.advance(61)
        game.finish_battle(first.id)
        second = game.start_duel(1).battle
        clock.advance(61)
        game.finish_battle(second.id)
        self.assertEqual(game.start_duel(1, champion_of=first.id).status, "stale")

    def test_weak_loser_is_executed(self) -> None:
        game, clock, temp = make_game(pics=2)
        self.addCleanup(temp.cleanup)
        battle = game.start_duel(1).battle
        game.repo.db.execute("UPDATE pics SET rating = 880 WHERE id = ?", (battle.pics[1].id,))
        game.repo.db.commit()
        game.vote_battle(battle.id, 100, 0)
        clock.advance(61)
        report = game.finish_battle(battle.id)
        self.assertEqual(report.executed.id, battle.pics[1].id)
        self.assertEqual(game.repo.get_pic(battle.pics[1].id).status, "executed")

    def test_shortage(self) -> None:
        game, _, temp = make_game(pics=1)
        self.addCleanup(temp.cleanup)
        self.assertEqual(game.start_duel(1).status, "shortage")
        self.assertEqual(game.start_tournament(1).status, "shortage")

    def test_tournament(self) -> None:
        game, clock, temp = make_game(pics=4)
        self.addCleanup(temp.cleanup)
        battle = game.start_tournament(1).battle
        self.assertEqual(len(battle.pics), 4)
        game.vote_battle(battle.id, 100, 2)
        clock.advance(91)
        report = game.finish_battle(battle.id)
        self.assertEqual(report.winner, 2)
        self.assertIsNone(report.executed)


class CourtFlowTest(unittest.TestCase):
    def test_execution_and_graveyard(self) -> None:
        game, clock, temp = make_game(pics=2)
        self.addCleanup(temp.cleanup)
        pic = game.draw_pic(1)[0]
        trial = game.start_court(1, pic.id, "dislikes", 5).court
        self.assertEqual(game.start_court(1, pic.id, "bottom", 6).status, "active")
        game.vote_court(trial.id, 10, "kill")
        game.vote_court(trial.id, 11, "kill")
        game.vote_court(trial.id, 12, "spare")
        clock.advance(61)
        report = game.finish_court(trial.id)
        self.assertEqual(report.verdict, "executed")
        self.assertEqual(game.repo.count_pics("executed"), 1)
        self.assertEqual(game.repo.graveyard()[0].removed_reason, "court")

    def test_pardon_gives_immunity(self) -> None:
        game, clock, temp = make_game(pics=2)
        self.addCleanup(temp.cleanup)
        pic = game.draw_pic(1)[0]
        trial = game.start_court(1, pic.id, "dislikes", 5).court
        game.vote_court(trial.id, 10, "kill")
        clock.advance(61)
        self.assertEqual(game.finish_court(trial.id).verdict, "pardoned")
        self.assertEqual(game.start_court(1, pic.id, "bottom", 6).status, "immune")
        clock.advance(court.IMMUNITY_SECONDS)
        self.assertEqual(game.start_court(1, pic.id, "bottom", 6).status, "started")

    def test_only_uploader_gets_last_word_once(self) -> None:
        game, _, temp = make_game(pics=1, uploader=7)
        self.addCleanup(temp.cleanup)
        pic = game.draw_pic(1)[0]
        trial = game.start_court(1, pic.id, "dislikes", 5).court
        game.repo.set_court_message(trial.id, 555)
        self.assertIsNone(game.last_word(1, 555, 8, "не я"))
        self.assertEqual(game.last_word(1, 555, 7, "  она   смешная  ").last_word, "она смешная")
        self.assertIsNone(game.last_word(1, 555, 7, "ещё раз"))

    def test_admin_pardon_revives(self) -> None:
        game, _, temp = make_game(pics=1)
        self.addCleanup(temp.cleanup)
        pic = game.draw_pic(1)[0]
        game.repo.remove_pic(pic.id, "executed", "duel", game.now())
        self.assertTrue(game.pardon(pic.id))
        self.assertEqual(game.repo.get_pic(pic.id).status, "alive")


class AchievementFlowTest(unittest.TestCase):
    def test_upload_grants_first_achievement_once(self) -> None:
        game, _, temp = make_game()
        self.addCleanup(temp.cleanup)
        _, granted = game.add_pic("f", "u", 1, None)
        self.assertEqual(granted[0].codes, ["up_1"])
        _, granted = game.add_pic("f2", "u2", 1, None)
        self.assertEqual(granted, [])

    def test_backfill_runs_once(self) -> None:
        game, _, temp = make_game(pics=12)
        self.addCleanup(temp.cleanup)
        self.assertEqual(game.backfill_achievements(), 2)
        self.assertEqual(game.backfill_achievements(), 0)

    def test_night_uploads_use_offset(self) -> None:
        game, clock, temp = make_game()
        self.addCleanup(temp.cleanup)
        clock.value = 1_800_000_000 - (1_800_000_000 % 86400) + 2 * 3600  # 02:00 UTC
        _, granted = game.add_pic("f", "u", 1, None)
        self.assertIn("night_1", granted[0].codes)


if __name__ == "__main__":
    unittest.main()

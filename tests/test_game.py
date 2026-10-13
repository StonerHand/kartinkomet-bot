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


class EconomyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game, self.clock, temp = make_game(pics=6, uploader=1)
        self.addCleanup(temp.cleanup)

    def codes(self, granted, user_id) -> list[str]:
        return [code for item in granted if item.user_id == user_id for code in item.codes]

    def test_first_like_pays_owner_once(self) -> None:
        pic = self.game.draw_pic(-1)[0]
        self.game.react(pic.id, 5, 1)
        self.game.react(pic.id, 5, -1)
        self.game.react(pic.id, 5, 1)
        self.assertEqual(self.game.repo.player(1)[0], 2)

    def test_own_like_pays_nothing(self) -> None:
        pic = self.game.draw_pic(-1)[0]
        self.game.react(pic.id, 1, 1)
        self.assertEqual(self.game.repo.player(1)[0], 0)

    def test_battle_pays_voters_and_guessers(self) -> None:
        battle = self.game.start_duel(-1).battle
        self.game.vote_battle(battle.id, 5, 0)
        self.game.vote_battle(battle.id, 6, 0)
        self.game.vote_battle(battle.id, 7, 1)
        self.clock.advance(61)
        report = self.game.finish_battle(battle.id)
        self.assertEqual(sorted(report.guessers), [5, 6])
        self.assertEqual(self.game.repo.player(5)[0], 4)
        self.assertEqual(self.game.repo.player(7)[0], 1)
        self.assertEqual(self.game.repo.counter(7, "wrong_guesses"), 1)

    def test_oracle_after_five_right_guesses(self) -> None:
        granted = []
        for _ in range(5):
            battle = self.game.start_duel(-1).battle
            self.game.vote_battle(battle.id, 5, 0)
            self.clock.advance(61)
            granted = self.game.finish_battle(battle.id).granted
            self.game.repo.db.execute("UPDATE pics SET status = 'alive', loss_streak = 0, rating = 1000")
            self.game.repo.db.commit()
        self.assertIn("oracle", self.codes(granted, 5))

    def test_level_up_is_reported_once(self) -> None:
        self.game.pay(5, 25, "test")
        first = self.game.check_achievements([5])
        second = self.game.check_achievements([5])
        self.assertEqual(first[0].level_up, "🐣 Зритель")
        self.assertEqual(second, [])

    def test_lone_warrior_and_regicide(self) -> None:
        champion = self.game.start_duel(-1).battle
        self.game.vote_battle(champion.id, 5, 0)
        self.clock.advance(61)
        self.game.finish_battle(champion.id)
        self.game.repo.db.execute("UPDATE battles SET result_streak = 3 WHERE id = ?", (champion.id,))
        self.game.repo.db.commit()
        duel = self.game.start_duel(-1, champion_of=champion.id).battle
        self.game.vote_battle(duel.id, 6, 1)
        self.clock.advance(61)
        granted = self.game.finish_battle(duel.id).granted
        self.assertIn("lone_warrior", self.codes(granted, 6))
        self.assertIn("regicide", self.codes(granted, 1))

    def test_court_events(self) -> None:
        pic = self.game.draw_pic(-1)[0]
        trial = self.game.start_court(-1, pic.id, "bottom", None).court
        self.game.vote_court(trial.id, 1, "kill")  # the uploader votes against their own pic
        self.game.vote_court(trial.id, 5, "kill")
        self.game.vote_court(trial.id, 6, "spare")
        self.clock.advance(61)
        report = self.game.finish_court(trial.id)
        self.assertIn("self_executioner", self.codes(report.granted, 1))
        self.assertIn("devils_advocate", self.codes(report.granted, 6))
        self.assertEqual(self.game.repo.player(5)[0], 1)

    def test_deja_vu_and_lucky(self) -> None:
        pic, _, granted = self.game.draw_for(-1, 1)
        self.assertIn("deja_vu", self.codes(granted, 1))

    def test_ghost_after_a_silent_week(self) -> None:
        pic = self.game.draw_pic(-1)[0]
        self.game.react(pic.id, 5, 1)
        self.clock.advance(8 * 86400)
        other = self.game.draw_pic(-1)[0]
        result = self.game.react(other.id, 5, 1)
        self.assertIn("ghost", self.codes(result.granted, 5))

    def test_activity_streak(self) -> None:
        for day in range(3):
            pic = self.game.draw_pic(-1)[0]
            self.game.react(pic.id, 5, 1)
            self.clock.advance(86400)
        self.assertEqual(self.game.repo.counter(5, "active_streak"), 3)

    def test_duplicate_streak(self) -> None:
        for _ in range(10):
            self.game.note_duplicate(5)
        self.game.add_pic("x", "x-uniq", 5, None)
        self.assertEqual(self.game.repo.counter(5, "dup_streak"), 0)
        self.assertIn("garbage_chute", self.game.repo.achievements_of(5))


class MiniGamesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game, self.clock, temp = make_game(pics=6, uploader=1)
        self.addCleanup(temp.cleanup)

    def test_caption_contest_full_cycle(self) -> None:
        status, contest = self.game.start_caption(-1)
        self.assertEqual(status, "started")
        self.assertEqual(self.game.start_caption(-1)[0], "active")
        self.game.repo.set_game_message(contest["id"], 50)
        self.assertIsNotNone(self.game.caption_entry(-1, 50, 5, "  когда бот   выдал легенду "))
        self.game.caption_entry(-1, 50, 6, "нет")
        self.game.caption_entry(-1, 50, 6, "передумал")  # rewriting keeps one entry per person
        self.assertIsNone(self.game.caption_entry(-1, 999, 7, "не та пикча"))
        self.clock.advance(61)
        outcome, contest, _ = self.game.advance_caption(contest["id"])
        self.assertEqual(outcome, "vote")
        self.assertEqual([entry["text"] for entry in contest["entries"]], ["когда бот выдал легенду", "передумал"])
        self.assertIsNone(self.game.caption_entry(-1, 50, 7, "поздно"))
        self.assertEqual(self.game.caption_vote(contest["id"], 5, 0), "own")
        self.assertEqual(self.game.caption_vote(contest["id"], 6, 0), "ok")
        self.assertEqual(self.game.caption_vote(contest["id"], 7, 0), "ok")
        self.clock.advance(46)
        outcome, contest, granted = self.game.advance_caption(contest["id"])
        self.assertEqual((outcome, contest["winner"]), ("done", 5))
        self.assertEqual(self.game.repo.player(5)[0], 15)
        self.assertIn("wit", [code for item in granted if item.user_id == 5 for code in item.codes])
        self.assertEqual(self.game.advance_caption(contest["id"])[0], "noop")

    def test_caption_cancelled_without_two_entries(self) -> None:
        _, contest = self.game.start_caption(-1)
        self.game.repo.set_game_message(contest["id"], 50)
        self.game.caption_entry(-1, 50, 5, "одна")
        self.clock.advance(61)
        self.assertEqual(self.game.advance_caption(contest["id"])[0], "cancelled")
        self.assertEqual(self.game.start_caption(-1)[0], "started")

    def test_gold_goes_to_the_first(self) -> None:
        token = self.game.repo.create_gold(-1, "x", self.game.now())
        self.assertTrue(self.game.claim_gold(token, 5)[0])
        self.assertFalse(self.game.claim_gold(token, 6)[0])
        self.assertEqual(self.game.repo.player(5)[0], 25)

    def test_gold_cooldown(self) -> None:
        self.game.rng.random = lambda: 0.0
        self.assertTrue(self.game.roll_gold(-1))
        self.game.repo.create_gold(-1, "x", self.game.now())
        self.assertFalse(self.game.roll_gold(-1))

    def test_spin_is_free_once_a_day(self) -> None:
        self.assertEqual(self.game.spin_price(5), 0)
        self.assertTrue(self.game.pay_for_spin(5))
        self.assertEqual(self.game.spin_price(5), 20)
        self.assertFalse(self.game.pay_for_spin(5))  # no coins
        self.game.pay(5, 30, "test")
        self.assertTrue(self.game.pay_for_spin(5))
        self.assertEqual(self.game.repo.player(5)[0], 10)
        spin, _, _ = self.game.resolve_spin(5, 64)
        self.assertEqual((spin.kind, self.game.repo.player(5)[0]), ("jackpot", 110))

    def test_curse_hits_own_pic(self) -> None:
        self.game.rng.uniform = lambda a, b: 60  # lands in the "curse" weight band
        spin, pic, _ = self.game.resolve_spin(1, 2 + 4 * 2 + 16 * 3)  # no pair, no triple
        self.assertEqual(spin.kind, "curse")
        self.assertEqual(self.game.repo.get_pic(pic.id).rating, pic.rating - 20)

    def test_horoscope_once_a_day(self) -> None:
        pic, already, _ = self.game.horoscope(5)
        self.assertIsNotNone(pic)
        self.assertTrue(self.game.horoscope(5)[1])
        self.clock.advance(86400)
        self.assertFalse(self.game.horoscope(5)[1])

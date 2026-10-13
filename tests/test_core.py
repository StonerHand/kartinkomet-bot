import random
import unittest
from collections import Counter

from bot.core import achievements, arena, court, deck, elo
from bot.db.repo import UserStats


class EloTest(unittest.TestCase):
    def test_duel_is_zero_sum_for_equal_k(self) -> None:
        first, second = elo.duel((1000, 1000), (0, 0), 1.0)
        self.assertEqual((first, second), (1016.0, 984.0))

    def test_draw_between_equals_changes_nothing(self) -> None:
        self.assertEqual(elo.duel((1000, 1000), (20, 20), 0.5), (1000.0, 1000.0))

    def test_stable_pics_move_slower(self) -> None:
        new, _ = elo.duel((1000, 1000), (50, 50), 1.0)
        self.assertEqual(new, 1008.0)

    def test_tournament_winner_gains_and_losers_drop(self) -> None:
        ratings = elo.tournament([1000] * 4, [0] * 4, [5, 1, 1, 0])
        self.assertGreater(ratings[0], 1000)
        self.assertLess(ratings[3], 1000)
        self.assertAlmostEqual(sum(ratings), 4000, places=6)


class ArenaTest(unittest.TestCase):
    def fighters(self, rating_b: float = 1000, loss_streak_b: int = 0) -> list[arena.Fighter]:
        return [arena.Fighter("a", 1000, 0, 0), arena.Fighter("b", rating_b, 0, loss_streak_b)]

    def test_no_votes_changes_nothing(self) -> None:
        outcome = arena.resolve_duel(self.fighters(), [0, 0], 0)
        self.assertFalse(outcome.counted)
        self.assertIsNone(outcome.executed)

    def test_healthy_loser_survives(self) -> None:
        outcome = arena.resolve_duel(self.fighters(), [2, 1], 0)
        self.assertEqual(outcome.winner, 0)
        self.assertIsNone(outcome.executed)
        self.assertEqual(outcome.streak, 1)

    def test_weak_loser_dies(self) -> None:
        outcome = arena.resolve_duel(self.fighters(rating_b=905), [2, 1], 0)
        self.assertEqual(outcome.executed, 1)

    def test_third_loss_in_a_row_kills(self) -> None:
        outcome = arena.resolve_duel(self.fighters(loss_streak_b=2), [2, 1], 0)
        self.assertEqual(outcome.executed, 1)

    def test_champion_streak_grows_and_new_winner_starts_at_one(self) -> None:
        self.assertEqual(arena.resolve_duel(self.fighters(), [3, 0], 4).streak, 5)
        self.assertEqual(arena.resolve_duel(self.fighters(), [0, 3], 4).streak, 1)

    def test_draw_keeps_streak(self) -> None:
        outcome = arena.resolve_duel(self.fighters(), [1, 1], 4)
        self.assertIsNone(outcome.winner)
        self.assertEqual(outcome.streak, 4)

    def test_tournament_tie_on_top_has_no_winner(self) -> None:
        fighters = [arena.Fighter(str(i), 1000, 0, 0) for i in range(4)]
        outcome = arena.resolve_tournament(fighters, [2, 2, 1, 0])
        self.assertIsNone(outcome.winner)
        self.assertEqual(outcome.outcomes[:2], ["draw", "draw"])

    def test_streak_milestones(self) -> None:
        self.assertEqual([arena.streak_milestone(n) for n in (1, 3, 4, 5, 10, 15, 16)], [None, 3, None, 5, 10, 10, None])


class CourtTest(unittest.TestCase):
    def test_verdict_needs_majority_and_two_kill_votes(self) -> None:
        self.assertEqual(court.verdict(1, 0), "pardoned")
        self.assertEqual(court.verdict(2, 2), "pardoned")
        self.assertEqual(court.verdict(2, 1), "executed")

    def test_trigger_fires_on_second_dislike_only(self) -> None:
        self.assertFalse(court.dislikes_trigger_court(0, 1))
        self.assertTrue(court.dislikes_trigger_court(1, 2))
        self.assertFalse(court.dislikes_trigger_court(2, 3))
        self.assertTrue(court.dislikes_trigger_court(3, 4))
        self.assertFalse(court.dislikes_trigger_court(3, 2))

    def test_immunity(self) -> None:
        self.assertFalse(court.can_be_tried("alive", 200, 100))
        self.assertTrue(court.can_be_tried("alive", 100, 100))
        self.assertFalse(court.can_be_tried("executed", None, 100))


class AchievementsTest(unittest.TestCase):
    def stats(self, **values: int) -> UserStats:
        base = dict.fromkeys(UserStats.__dataclass_fields__, 0)
        base["counters"] = {}
        base.update(values)
        return UserStats(**base)

    def test_catalog_codes_are_unique_and_rated(self) -> None:
        self.assertEqual(len(achievements.ALL_CODES), 64)
        self.assertEqual(len(set(achievements.ALL_CODES)), 64)
        self.assertEqual(set(achievements.RARITY), set(achievements.ALL_CODES))
        self.assertTrue(achievements.SECRET <= set(achievements.ALL_CODES))

    def test_counter_rules(self) -> None:
        stats = self.stats(counters={"best_guess_streak": 5, "spins": 9})
        earned = achievements.earned(stats, set())
        self.assertIn("oracle", earned)
        self.assertNotIn("croupier", earned)

    def test_showcase_prefers_rare(self) -> None:
        owned = {"up_1", "oracle", "generous"}
        self.assertEqual(achievements.showcase(owned, {"oracle": 1}, limit=2), ["oracle", "generous"])

    def test_earned_skips_owned(self) -> None:
        earned = achievements.earned(self.stats(uploads=12), {"up_1"})
        self.assertEqual(earned, ["up_10"])

    def test_title_and_next_goal(self) -> None:
        self.assertEqual(achievements.upload_title_code(60), "up_50")
        self.assertIsNone(achievements.upload_title_code(0))
        self.assertEqual(achievements.next_upload_goal(60).code, "up_100")


class DeckTest(unittest.TestCase):
    def test_bucket_shares(self) -> None:
        rng = random.Random(1)
        counts = Counter(deck.roll_bucket(rng) for _ in range(20_000))
        self.assertAlmostEqual(counts["deck"] / 20_000, 0.70, delta=0.02)
        self.assertAlmostEqual(counts["fresh"] / 20_000, 0.20, delta=0.02)
        self.assertAlmostEqual(counts["legend"] / 20_000, 0.10, delta=0.02)


if __name__ == "__main__":
    unittest.main()


class GamesRulesTest(unittest.TestCase):
    def test_caption_winner_and_tie_break(self) -> None:
        from bot.core.games import caption_winner

        entries = [{"user_id": 1}, {"user_id": 2}, {"user_id": 3}]
        self.assertEqual(caption_winner(entries, {10: 2, 11: 2, 12: 3}), 2)
        self.assertEqual(caption_winner(entries, {10: 3, 11: 2}), 2)  # tie → earlier entry
        self.assertIsNone(caption_winner(entries, {}))

    def test_slot_machine_outcomes(self) -> None:
        import random

        from bot.core.games import reels, spin_outcome

        self.assertEqual(reels(64), (3, 3, 3))
        self.assertEqual(spin_outcome(64, random.Random(1)).kind, "jackpot")
        self.assertEqual(spin_outcome(1, random.Random(1)).kind, "triple")  # BAR BAR BAR
        self.assertEqual(spin_outcome(2, random.Random(1)).kind, "pair")  # grapes BAR BAR
        kinds = {spin_outcome(value, random.Random(value)).kind for value in range(1, 65)}
        self.assertTrue({"jackpot", "triple", "pair"} <= kinds)

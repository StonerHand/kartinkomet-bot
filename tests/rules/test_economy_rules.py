"""Pure economy rules: casino tables, parimutuel bets, day events, quests, chests, boss, shop."""

import random
import unittest

from bot.core import boss, casino, days, progress, shop


class CasinoTest(unittest.TestCase):
    def expected(self, table, values) -> float:
        return sum(table(value).multiplier for value in values) / len(values)

    def test_house_keeps_an_edge_everywhere_but_dice(self) -> None:
        self.assertAlmostEqual(self.expected(casino.slots, range(1, 65)), 62 / 64)
        for table, faces in ((casino.darts, 6), (casino.basket, 5), (casino.football, 5), (casino.bowling, 6)):
            with self.subTest(table=table.__name__):
                self.assertLess(self.expected(table, range(1, faces + 1)), 1)
                self.assertGreater(self.expected(table, range(1, faces + 1)), 0.85)
        fair = [casino.dice_duel(a, b).multiplier for a in range(1, 7) for b in range(1, 7)]
        self.assertAlmostEqual(sum(fair) / len(fair), 1)

    def test_slot_outcomes(self) -> None:
        self.assertEqual(casino.slots(64).kind, "jackpot")
        self.assertEqual(casino.slots(1).kind, "triple")  # BAR BAR BAR
        sevens = 1 + 3 + 3 * 4 + 0 * 16  # seven, seven, bar
        self.assertEqual(casino.slots(sevens).kind, "sevens")
        self.assertEqual(casino.slots(1 + 0 + 1 * 4 + 2 * 16).kind, "miss")

    def test_payout_and_lucky_day(self) -> None:
        self.assertEqual(casino.payout(100, casino.Roll("x", 2.3)), 230)
        self.assertEqual(casino.payout(100, casino.Roll("x", 2), lucky=True), 300)
        self.assertEqual(casino.payout(100, casino.Roll("x", 0.5), lucky=True), 50)

    def test_parse_stake(self) -> None:
        self.assertEqual(casino.parse_stake("", 500, 50), 50)
        self.assertEqual(casino.parse_stake("200", 500, 50), 200)
        self.assertEqual(casino.parse_stake("все", 500, 50), 500)
        self.assertEqual(casino.parse_stake("2к", 5000, 50), 2000)
        self.assertIsNone(casino.parse_stake("много", 500, 50))

    def test_parimutuel(self) -> None:
        bets = {1: (0, 100), 2: (0, 300), 3: (1, 400)}
        self.assertEqual(casino.settle_bets(bets, 0), {1: 200, 2: 600})
        self.assertEqual(casino.settle_bets(bets, None), {1: 100, 2: 300, 3: 400})
        self.assertEqual(casino.settle_bets({1: (1, 50)}, 0), {})
        self.assertEqual(casino.odds([100, 300]), [4.0, 1.33])


class DaysTest(unittest.TestCase):
    def test_never_twice_in_a_row(self) -> None:
        rng = random.Random(1)
        for code in days.CODES:
            for _ in range(30):
                self.assertNotEqual(days.roll(rng, code), code)

    def test_tax_takes_from_the_rich_and_gives_to_the_poor(self) -> None:
        taken, given = days.tax([(1, 10000), (2, 5000), (3, 2000), (4, 1500), (5, 100), (6, 0)])
        self.assertEqual(taken, {1: 1000, 2: 500, 3: 200})
        self.assertEqual(given, {5: 850, 6: 850})
        self.assertEqual(days.tax([(1, 10000)]), ({}, {}))


class ProgressTest(unittest.TestCase):
    def test_quests_are_stable_per_day_and_differ_by_person(self) -> None:
        self.assertEqual(progress.daily_quests(1, 100), progress.daily_quests(1, 100))
        self.assertEqual(len({task.kind for task in progress.daily_quests(1, 100)}), 3)
        days_seen = {tuple(task.kind for task in progress.daily_quests(1, day)) for day in range(20)}
        self.assertGreater(len(days_seen), 10)

    def test_weekly_challenges_are_shared(self) -> None:
        self.assertEqual(progress.weekly_challenges(7), progress.weekly_challenges(7))
        self.assertEqual(len(progress.weekly_challenges(7)), 3)

    def test_daily_rewards_grow_and_cap(self) -> None:
        self.assertEqual([progress.daily_reward(day) for day in (1, 2, 7, 30)], [50, 60, 150, 150])
        self.assertTrue(progress.daily_chest(14))
        self.assertFalse(progress.daily_chest(6))

    def test_every_chest_tier_opens(self) -> None:
        rng = random.Random(3)
        for tier in progress.TIERS:
            kinds = {progress.open_chest(tier, rng).kind for _ in range(300)}
            self.assertIn("coins", kinds)


class BossShopTest(unittest.TestCase):
    def test_boss_hp_scales(self) -> None:
        self.assertEqual(boss.max_hp(0), boss.MIN_HP)
        self.assertEqual(boss.max_hp(10), 190)
        self.assertEqual(boss.max_hp(10, double=True), 380)

    def test_loot_split_by_damage(self) -> None:
        self.assertEqual(boss.split_loot(300, {1: 20, 2: 10}), {1: 200, 2: 100})

    def test_evolution_stages(self) -> None:
        self.assertEqual([shop.stage(wins).emoji for wins in (0, 1, 3, 7, 15, 99)], ["🥚", "🐣", "🐺", "🐉", "🌌", "🌌"])

    def test_prices_bend_with_the_day(self) -> None:
        self.assertEqual(shop.price("shield"), 300)
        self.assertEqual(shop.price("shield", inflation=True), 600)
        self.assertEqual(shop.price("shield", sale=True), 150)
        self.assertEqual(shop.price("resurrect", dead_day_price=300), 300)

    def test_divorce_splits_the_pot(self) -> None:
        self.assertEqual(shop.divorce_split(1000, 101), (551, 550))


if __name__ == "__main__":
    unittest.main()

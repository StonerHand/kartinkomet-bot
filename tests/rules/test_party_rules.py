"""Games about people: who wins a poll, how a bet's pool is shared, the bomb's fuse."""

import random
import unittest

from bot.rules import party


class PollTest(unittest.TestCase):
    def test_the_most_votes_win_and_a_tie_crowns_everyone_in_it(self) -> None:
        self.assertEqual(party.poll_winners({1: 7, 2: 7, 3: 8}), [7])
        self.assertEqual(party.poll_winners({1: 7, 2: 8}), [7, 8])
        self.assertEqual(party.poll_winners({}), [])


class BetPayoutTest(unittest.TestCase):
    def test_winners_share_the_losers_pool_by_stake(self) -> None:
        stakes = {1: (1, 100), 2: (1, 300), 3: (0, 500), 4: (0, 500)}
        payouts = party.bet_payouts(stakes, 1)
        self.assertEqual(payouts, {1: 100 + 250, 2: 300 + 750})
        self.assertEqual(sum(payouts.values()), sum(coins for _, coins in stakes.values()))

    def test_the_rounding_goes_to_the_biggest_stake(self) -> None:
        payouts = party.bet_payouts({1: (0, 100), 2: (0, 200), 3: (1, 100)}, 0)
        self.assertEqual(sum(payouts.values()), 400)
        self.assertEqual(payouts, {1: 133, 2: 267})

    def test_a_one_sided_bet_gives_everyone_their_stake_back(self) -> None:
        self.assertEqual(party.bet_payouts({1: (1, 100), 2: (1, 500)}, 0), {1: 100, 2: 500})
        self.assertEqual(party.bet_payouts({1: (1, 100), 2: (1, 500)}, 1), {1: 100, 2: 500})


class FuseTest(unittest.TestCase):
    def test_the_fuse_stays_in_its_range(self) -> None:
        rng = random.Random(1)
        low, high = party.BOMB_FUSE_SECONDS
        self.assertTrue(all(low <= party.fuse(rng) <= high for _ in range(200)))


class GuessTest(unittest.TestCase):
    def test_case_yo_punctuation_and_spaces_dont_matter(self) -> None:
        self.assertEqual(party.normalize("  Новый   ГОД!! "), "новый год")
        self.assertEqual(party.normalize("Самолёт"), party.normalize("самолет"))
        self.assertNotEqual(party.normalize("кот"), party.normalize("кофе"))

"""Pure rules of the table games, pic by pieces, the auction and the team week."""

import random
import unittest

from bot.rules import auction, games, table, teams


class SpyRulesTest(unittest.TestCase):
    def test_the_spy_is_caught_only_by_the_most_votes_alone(self) -> None:
        self.assertTrue(table.spy_caught({2: 5, 3: 5, 4: 2}, 5))
        self.assertFalse(table.spy_caught({2: 5, 3: 4}, 5))  # a tie lets the spy slip away
        self.assertFalse(table.spy_caught({2: 3, 3: 3, 5: 4}, 5))
        self.assertFalse(table.spy_caught({}, 5))


class MinesRulesTest(unittest.TestCase):
    def test_the_field_hides_its_mines_on_distinct_cells(self) -> None:
        for seed in range(50):
            mines = table.minefield(random.Random(seed))
            self.assertEqual(len(set(mines)), table.MINES_COUNT)
            self.assertTrue(all(0 <= cell < table.MINES_SIDE ** 2 for cell in mines))

    def test_each_safe_cell_is_dearer_than_the_last(self) -> None:
        self.assertEqual([table.cell_value(opened) for opened in range(3)], [10, 20, 30])


class SafeRulesTest(unittest.TestCase):
    def test_a_code_has_four_different_digits(self) -> None:
        for seed in range(50):
            code = table.safe_code(random.Random(seed))
            self.assertTrue(table.valid_guess(code), code)

    def test_tries_must_be_four_different_digits(self) -> None:
        self.assertTrue(table.valid_guess("0729"))
        for wrong in ("072", "07290", "0779", "07a9", ""):
            self.assertFalse(table.valid_guess(wrong), wrong)

    def test_the_hint_counts_digits_in_place_and_elsewhere(self) -> None:
        self.assertEqual(table.safe_hint("1234", "1234"), (4, 0))
        self.assertEqual(table.safe_hint("1234", "4321"), (0, 4))
        self.assertEqual(table.safe_hint("1234", "1243"), (2, 2))
        self.assertEqual(table.safe_hint("1234", "5678"), (0, 0))
        self.assertEqual(table.safe_hint("1234", "1567"), (1, 0))


class PieceRulesTest(unittest.TestCase):
    def test_the_piece_grows_and_its_reward_melts(self) -> None:
        self.assertEqual(sorted(games.PIECE_ZOOMS), list(games.PIECE_ZOOMS))
        self.assertEqual(sorted(games.PIECE_REWARDS, reverse=True), list(games.PIECE_REWARDS))
        self.assertEqual(len(games.PIECE_ZOOMS), len(games.PIECE_REWARDS))

    def test_the_piece_is_cut_away_from_the_edges(self) -> None:
        for seed in range(50):
            x, y = games.piece_center(random.Random(seed))
            self.assertTrue(0.25 <= x <= 0.75 and 0.25 <= y <= 0.75)


class AuctionRulesTest(unittest.TestCase):
    def test_the_highest_bid_pays_the_second_price(self) -> None:
        self.assertEqual(auction.settle({2: (500, 10), 3: (300, 5), 4: (100, 1)}, 50), (2, 300))

    def test_a_tie_goes_to_whoever_got_there_first(self) -> None:
        self.assertEqual(auction.settle({2: (500, 10), 3: (500, 5)}, 50), (3, 500))

    def test_a_lone_bid_pays_the_minimum_never_more_than_itself(self) -> None:
        self.assertEqual(auction.settle({2: (500, 10)}, 50), (2, 50))
        self.assertEqual(auction.settle({2: (30, 10)}, 50), (2, 30))
        self.assertEqual(auction.settle({2: (0, 10)}, 50), (None, 0))  # a withdrawn bid
        self.assertEqual(auction.settle({}, 50), (None, 0))

    def test_the_lot_is_a_chest_worth_bidding_for(self) -> None:
        lots = {auction.lot(random.Random(seed)) for seed in range(100)}
        self.assertEqual(lots, {"rare", "legend"})


class TeamRulesTest(unittest.TestCase):
    def test_the_snake_draft_keeps_the_teams_even(self) -> None:
        drafted = teams.draft([10, 9, 8, 7, 6, 5, 4, 3], random.Random(1))
        first = drafted[10]
        second = "blue" if first == "red" else "red"
        self.assertEqual([drafted[user] for user in (10, 9, 8, 7, 6, 5, 4, 3)],
                         [first, second, second, first, first, second, second, first])

    def test_more_points_win_and_a_tie_has_no_winner(self) -> None:
        self.assertEqual(teams.winner({"red": 10, "blue": 3}), "red")
        self.assertEqual(teams.winner({"blue": 1}), "blue")
        self.assertIsNone(teams.winner({"red": 5, "blue": 5}))

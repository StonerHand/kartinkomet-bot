"""Board duels' pure rules: who beats whom, three in a row."""

import unittest

from bot.rules import duels


class DuelRulesTest(unittest.TestCase):
    def test_rock_beats_scissors_beats_paper_beats_rock(self) -> None:
        rock, scissors, paper = range(3)
        self.assertEqual(duels.rps_winner(rock, scissors), 0)
        self.assertEqual(duels.rps_winner(scissors, paper), 0)
        self.assertEqual(duels.rps_winner(paper, rock), 0)
        self.assertEqual(duels.rps_winner(scissors, rock), 1)
        self.assertIsNone(duels.rps_winner(paper, paper))

    def test_three_in_a_row_a_full_board_and_a_game_going_on(self) -> None:
        self.assertEqual(duels.ttt_outcome("XXXOO...."), "X")
        self.assertEqual(duels.ttt_outcome("XO.XO.X.O"), "X")
        self.assertEqual(duels.ttt_outcome("OX.XO.X.O"), "O")  # the diagonal
        self.assertEqual(duels.ttt_outcome("XOXXOOOXX"), "draw")
        self.assertIsNone(duels.ttt_outcome("XO......."))
        self.assertEqual(duels.ttt_line("..X.X.X.."), (2, 4, 6))

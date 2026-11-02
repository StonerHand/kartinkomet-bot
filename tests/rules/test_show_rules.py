"""The evening show's rules: the crew's choice, the odds, tonight's show."""

import random
import unittest

from bot.rules import show


class HeistRulesTest(unittest.TestCase):
    def test_the_majority_decides_and_a_tie_is_a_coin_toss(self) -> None:
        rng = random.Random(3)
        self.assertEqual(show.chosen([0, 0, 1], rng), 0)
        self.assertEqual(show.chosen([1, 1, 0], rng), 1)
        self.assertEqual({show.chosen([0, 1], rng) for _ in range(50)}, {0, 1})
        self.assertIn(show.chosen([], rng), (0, 1))

    def test_the_right_role_makes_an_option_likelier_up_to_a_cap(self) -> None:
        option = show.Option("x", 0.9, "hacker")
        self.assertEqual(show.chance(option, set()), 0.9)
        self.assertEqual(show.chance(option, {"hacker"}), 0.95)
        self.assertAlmostEqual(show.chance(show.Option("y", 0.5, "driver"), {"driver"}), 0.7)

    def test_a_night_has_three_different_events_and_roles_go_round(self) -> None:
        events = show.plan(random.Random(1))
        self.assertEqual(len(set(events)), show.STAGES)
        self.assertTrue(set(events) <= set(show.EVENTS))
        self.assertEqual([show.role_of(index) for index in range(5)], [*show.ROLES, show.ROLES[0]])

    def test_the_shows_take_turns(self) -> None:
        self.assertNotEqual(show.show_of(100), show.show_of(101))

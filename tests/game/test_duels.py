"""Board duels on a real database: picks, moves, the clock, the pot."""

from bot.rules import duels
from tests.helpers import GameCase

CHAT = -100


class BoardDuelCase(GameCase):
    def accepted(self, game: str, stake: int = 100) -> dict:
        self.fund(2, 1000)
        self.fund(3, 1000)
        status, created = self.game.create_challenge(CHAT, 2, 3, stake, game)
        self.assertEqual(status, "ok")
        answer = self.game.answer_challenge(created["id"], 3, True)
        self.assertEqual(answer.status, "accepted")
        self.game.deal_board(answer.challenge)
        return answer.challenge


class RockPaperScissorsTest(BoardDuelCase):
    def test_picks_stay_secret_until_both_are_in(self) -> None:
        challenge = self.accepted("rps")
        self.assertEqual(self.game.pick_rps(challenge["id"], 2, 0), ("ok", None))
        self.assertEqual(self.game.pick_rps(challenge["id"], 2, 2)[0], "already")
        self.assertEqual(self.game.pick_rps(challenge["id"], 5, 1)[0], "not_player")
        status, duel = self.game.pick_rps(challenge["id"], 3, 1)  # scissors lose to rock
        self.assertEqual((status, duel.winner, duel.pot), ("done", 2, 200))
        self.assertEqual((self.coins(2), self.coins(3)), (1100, 900))
        self.assertEqual(self.game.pick_rps(challenge["id"], 3, 0)[0], "gone")

    def test_the_same_pick_plays_again(self) -> None:
        challenge = self.accepted("rps")
        self.game.pick_rps(challenge["id"], 2, 1)
        self.assertEqual(self.game.pick_rps(challenge["id"], 3, 1), ("draw", None))
        state = self.game.duel_state(challenge["id"])
        self.assertEqual((state["round"], state["picks"], state["last"]), (2, {}, [1, 1]))
        self.game.pick_rps(challenge["id"], 2, 2)
        self.assertEqual(self.game.pick_rps(challenge["id"], 3, 1)[1].winner, 3)  # scissors cut paper

    def test_whoever_picked_wins_when_the_clock_runs_out(self) -> None:
        challenge = self.accepted("rps")
        self.game.pick_rps(challenge["id"], 3, 2)
        self.assertIsNone(self.game.time_out_duel(challenge["id"]))  # not yet
        self.clock.advance(duels.RPS_SECONDS)
        duel = self.game.time_out_duel(challenge["id"])
        self.assertEqual((duel.winner, duel.timed_out), (3, 2))
        other = self.accepted("rps")
        staked = self.coins(2) + self.coins(3)
        self.clock.advance(duels.RPS_SECONDS)
        self.assertIsNone(self.game.time_out_duel(other["id"]).winner)  # nobody picked: stakes back
        self.assertEqual(self.coins(2) + self.coins(3), staked + 2 * other["stake"])


class TicTacToeTest(BoardDuelCase):
    def test_turns_three_in_a_row_and_the_pot(self) -> None:
        challenge = self.accepted("ttt")
        self.assertEqual(self.game.move_ttt(challenge["id"], 3, 0)[0], "not_turn")  # X opens
        for user, cell in ((2, 0), (3, 3), (2, 1), (3, 4)):
            self.assertEqual(self.game.move_ttt(challenge["id"], user, cell)[0], "ok")
        self.assertEqual(self.game.move_ttt(challenge["id"], 2, 3)[0], "taken")
        status, duel = self.game.move_ttt(challenge["id"], 2, 2)
        self.assertEqual((status, duel.winner, duel.state["board"]), ("done", 2, "XXXOO...."))
        self.assertEqual(self.coins(2), 1100)

    def test_a_full_board_returns_the_stakes(self) -> None:
        challenge = self.accepted("ttt")
        for user, cell in ((2, 0), (3, 1), (2, 2), (3, 4), (2, 3), (3, 5), (2, 7), (3, 6)):
            self.assertEqual(self.game.move_ttt(challenge["id"], user, cell)[0], "ok")
        status, duel = self.game.move_ttt(challenge["id"], 2, 8)
        self.assertEqual((status, duel.winner), ("done", None))
        self.assertEqual((self.coins(2), self.coins(3)), (1000, 1000))

    def test_the_one_who_lets_the_clock_run_out_loses(self) -> None:
        challenge = self.accepted("ttt")
        self.game.move_ttt(challenge["id"], 2, 4)
        self.clock.advance(duels.TTT_MOVE_SECONDS)
        duel = self.game.time_out_duel(challenge["id"])
        self.assertEqual((duel.winner, duel.timed_out), (2, 3))

    def test_a_restart_refunds_dice_but_keeps_boards(self) -> None:
        challenge = self.accepted("ttt")
        self.assertEqual(self.game.refund_unthrown_dice_duels(), 0)
        self.assertEqual(self.game.open_board_duels(), [challenge["id"]])

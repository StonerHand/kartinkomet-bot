"""Social deals never create or lose coins: every way a challenge or a proposal can end."""

from bot.core import shop
from bot.core.arena import DUEL_SECONDS
from tests.helpers import GameCase


class SocialMoneyTest(GameCase):
    def setUp(self) -> None:
        super().setUp()
        for user in (2, 3, 4):
            self.fund(user, 1000)

    def total(self) -> int:
        return sum(self.coins(user) for user in (2, 3, 4))

    # ── challenges ─────────────────────────────────────────────────────

    def challenge(self, opponent: int | None = 3, stake: int = 200) -> dict:
        status, challenge = self.game.create_challenge(-100, 2, opponent, stake)
        self.assertEqual(status, "ok")
        self.assertEqual(self.coins(2), 1000 - stake)  # the stake is held
        return challenge

    def test_challenge_refusals_refund_the_stake_once(self) -> None:
        for answerer, expected in ((2, "cancelled"), (3, "declined")):
            with self.subTest(expected):
                challenge = self.challenge()
                self.assertEqual(self.game.answer_challenge(challenge["id"], 4, False).status, "not_for_you")
                self.assertEqual(self.game.answer_challenge(challenge["id"], answerer, False).status, expected)
                self.assertEqual(self.game.answer_challenge(challenge["id"], answerer, False).status, "gone")
                self.assertEqual(self.total(), 3000)

    def test_expired_challenge_refunds_once(self) -> None:
        challenge = self.challenge()
        self.clock.advance(shop.CHALLENGE_SECONDS + 1)
        self.assertEqual(self.game.answer_challenge(challenge["id"], 3, True).status, "gone")
        self.assertFalse(self.game.expire_challenge(challenge))  # the timer comes late: nothing twice
        self.assertEqual(self.total(), 3000)

    def test_wrong_accepts_hold_no_money(self) -> None:
        challenge = self.challenge()
        self.assertEqual(self.game.answer_challenge(challenge["id"], 2, True).status, "own")
        self.assertEqual(self.game.answer_challenge(challenge["id"], 4, True).status, "not_for_you")
        self.repo_broke(3)
        self.assertEqual(self.game.answer_challenge(challenge["id"], 3, True).status, "broke")
        self.assertEqual(self.total(), 3000 - 1000 - 200)  # 3 spent everything elsewhere; 2's stake is held

    def repo_broke(self, user: int) -> None:
        self.game.repo.spend(user, self.coins(user), "test", self.game.now())

    def test_one_challenge_at_a_time(self) -> None:
        self.challenge()
        self.assertEqual(self.game.create_challenge(-100, 2, 4, 100)[0], "pending")
        self.assertEqual(self.coins(2), 800)
        self.assertEqual(self.game.create_challenge(-100, 3, 4, 10)[0], "small")
        self.assertEqual(self.game.create_challenge(-100, 3, 3, 100)[0], "self")

    def test_fought_challenge_moves_the_pot_to_the_winner(self) -> None:
        challenge = self.challenge(opponent=None)  # open: anyone may take it
        answer = self.game.answer_challenge(challenge["id"], 4, True)
        self.assertEqual(answer.status, "accepted")
        self.game.vote_battle(answer.battle.id, 5, 1)  # the taker's pic wins
        self.clock.advance(DUEL_SECONDS + 1)
        report = self.game.finish_battle(answer.battle.id)
        self.assertEqual(report.champion, 4)
        self.assertEqual((self.coins(2), self.coins(4)), (800, 1200))
        self.assertEqual(self.total(), 3000)

    def test_unfought_challenge_refunds_both(self) -> None:
        answer = self.game.answer_challenge(self.challenge()["id"], 3, True)
        self.clock.advance(DUEL_SECONDS + 600)
        report = self.game.finish_battle(answer.battle.id)
        self.assertIsNone(report.champion)
        self.assertEqual((self.coins(2), self.coins(3)), (1000, 1000))

    # ── proposals ──────────────────────────────────────────────────────

    def propose(self) -> str:
        status, proposal_id = self.game.propose(-100, 2, 3)
        self.assertEqual(status, "ok")
        return proposal_id

    def test_proposal_endings_without_a_wedding_cost_nothing(self) -> None:
        cases = ((2, False, "withdrawn"), (3, False, "declined"), (4, True, "not_for_you"))
        for user, yes, expected in cases:
            with self.subTest(expected):
                proposal_id = self.propose()
                self.assertEqual(self.game.answer_proposal(proposal_id, user, yes)[0], expected)
                self.assertEqual(self.total(), 3000)
        proposal_id = self.propose()
        self.clock.advance(shop.PROPOSAL_SECONDS + 1)
        self.assertEqual(self.game.answer_proposal(proposal_id, 3, True)[0], "expired")
        self.assertEqual(self.total(), 3000)

    def test_wedding_charges_both_or_nobody(self) -> None:
        proposal_id = self.propose()
        self.repo_broke(3)
        self.assertEqual(self.game.answer_proposal(proposal_id, 3, True)[0], "broke")
        self.assertEqual(self.coins(2), 1000)  # the suitor's half came back
        self.fund(3, 500)
        self.assertEqual(self.game.answer_proposal(proposal_id, 3, True)[0], "married")
        self.assertEqual((self.coins(2), self.coins(3)), (1000 - shop.WEDDING_PRICE, 500 - shop.WEDDING_PRICE))
        self.assertEqual(self.game.propose(-100, 4, 2)[0], "taken")
        self.assertEqual(self.game.propose(-100, 2, 4)[0], "married")

    def test_divorce_splits_without_losing_coins(self) -> None:
        self.game.answer_proposal(self.propose(), 3, True)
        self.fund(2, 777)
        before = self.coins(2) + self.coins(3)
        result = self.game.divorce(3)
        self.assertEqual(result.status, "ok")
        self.assertEqual(self.coins(2) + self.coins(3), before)
        self.assertLessEqual(abs(self.coins(2) - self.coins(3)), 1)
        self.assertEqual(self.game.divorce(3).status, "single")

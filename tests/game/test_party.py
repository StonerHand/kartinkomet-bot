"""Games about people on a real database: "who of us" polls, the bomb, bets on life."""

from bot.rules import economy, party
from tests.helpers import GameCase

CHAT = -100


class PartyCase(GameCase):
    def setUp(self) -> None:
        super().setUp()
        for user in range(2, 7):
            self.game.repo.touch_member(CHAT, user, self.game.now())


class WhoOfUsTest(PartyCase):
    def start(self, **kwargs):
        return self.game.start_who(CHAT, "Кто проспит?", "Чемпион по сну", **kwargs)

    def test_a_poll_needs_two_people_and_one_at_a_time(self) -> None:
        self.assertEqual(self.game.start_who(-200, "?", "t")[0], "shortage")
        status, found = self.start()
        self.assertEqual(status, "started")
        self.assertEqual(sorted(found["options"]), [2, 3, 4, 5, 6])
        self.assertEqual(self.start()[0], "active")

    def test_votes_change_and_the_winner_wears_the_title_for_a_day(self) -> None:
        _, found = self.start()
        options = found["options"]
        target = options.index(4)
        self.assertEqual(self.game.vote_who(found["id"], 2, options.index(3)), "ok")
        self.assertEqual(self.game.vote_who(found["id"], 2, target), "ok")  # changed the mind
        self.assertEqual(self.game.vote_who(found["id"], 2, target), "same")
        self.assertEqual(self.game.vote_who(found["id"], 3, target), "ok")
        self.assertEqual(self.game.vote_who(found["id"], 5, options.index(5)), "ok")
        self.clock.advance(party.WHO_SECONDS)
        self.assertEqual(self.game.vote_who(found["id"], 6, target), "closed")
        result = self.game.finish_who(found["id"])
        self.assertEqual((result.winners, result.counts[4], result.counts[3]), ([4], 2, 0))
        self.assertEqual(self.game.badges_of(4), [("who", "Чемпион по сну")])
        self.assertEqual([self.coins(user) for user in (2, 3, 5)], [economy.VOTE] * 3)
        self.assertIsNone(self.game.finish_who(found["id"]))
        self.clock.advance(party.BADGE_SECONDS)
        self.assertEqual(self.game.badges_of(4), [])

    def test_by_hand_once_in_a_while_the_daily_one_and_a_paid_question_any_time(self) -> None:
        _, found = self.start()
        self.game.finish_who(found["id"])
        self.assertEqual(self.start()[0], "cooldown")
        self.assertEqual(self.start(author=2)[0], "poor")
        self.fund(2, self.game.who_question_price())
        status, paid = self.start(author=2)
        self.assertEqual((status, self.coins(2)), ("started", 0))
        self.game.drop_round(paid["id"])  # its card never made it: the question is refunded
        self.assertEqual(self.coins(2), self.game.who_question_price())
        self.assertEqual(self.start(scheduled=True)[0], "started")


class BombTest(PartyCase):
    def test_the_holder_passes_it_and_gets_no_more_time_than_the_fuse(self) -> None:
        status, found = self.game.start_bomb(CHAT)
        self.assertEqual(status, "started")
        holder = found["holder"]
        other = next(user for user in range(2, 7) if user != holder)
        self.assertEqual(self.game.pass_bomb(found["id"], other, holder), "not_holder")
        self.assertEqual(self.game.pass_bomb(found["id"], holder, holder), "self")
        self.clock.advance(5)
        self.assertEqual(self.game.pass_bomb(found["id"], holder, other), "ok")
        fresh = self.game.repo.get_round(found["id"])
        self.assertEqual(fresh["holder"], other)
        self.assertEqual(fresh["ends_at"], min(self.game.now() + party.BOMB_PASS_SECONDS, fresh["fuse_at"]))
        self.assertEqual(self.game.start_bomb(CHAT)[0], "active")

    def test_it_goes_off_on_the_holder_and_pays_the_passers(self) -> None:
        _, found = self.game.start_bomb(CHAT)
        first = found["holder"]
        second = next(user for user in range(2, 7) if user != first)
        self.game.pass_bomb(found["id"], first, second)
        self.fund(second, 1000)
        result = self.game.finish_bomb(found["id"])
        self.assertEqual((result.victim, result.fine, result.passers), (second, party.BOMB_FINE, [first]))
        self.assertEqual(self.coins(second), 1000 - party.BOMB_FINE)
        self.assertEqual(self.coins(first), party.BOMB_PASS_REWARD)
        self.assertEqual(self.game.badges_of(second), [("bomb", "Жертва бомбы")])
        self.assertIsNone(self.game.finish_bomb(found["id"]))
        self.assertEqual(self.game.start_bomb(CHAT)[0], "cooldown")

    def test_a_poor_victim_loses_what_there_is(self) -> None:
        _, found = self.game.start_bomb(CHAT)
        self.assertEqual(self.game.finish_bomb(found["id"]).fine, 0)


class BetTest(PartyCase):
    def open(self, claim: str = "В пятницу половина чата проспит"):
        return self.game.open_bet(CHAT, 2, claim)

    def test_a_claim_is_needed_short_and_a_few_at_a_time(self) -> None:
        self.assertEqual(self.open("   ")[0], "empty")
        self.assertEqual(self.open("x" * (party.BET_CLAIM_MAX + 1))[0], "long")
        for _ in range(party.BET_OPEN_MAX):
            self.assertEqual(self.open()[0], "opened")
        self.assertEqual(self.open()[0], "too_many")

    def test_stakes_then_the_author_settles_and_winners_share(self) -> None:
        _, found = self.open()
        small, big = self.game.bet_stakes()
        for user in (3, 4, 5):
            self.fund(user, 1000)
        self.assertEqual(self.game.stake_bet(found["id"], 2, 1, small), "author")
        self.assertEqual(self.game.stake_bet(found["id"], 3, 1, small), "ok")
        self.assertEqual(self.game.stake_bet(found["id"], 3, 0, small), "already")
        self.assertEqual(self.game.stake_bet(found["id"], 4, 0, big), "ok")
        self.assertEqual(self.game.stake_bet(found["id"], 5, 1, big), "ok")
        self.assertEqual(self.game.stake_bet(found["id"], 6, 1, small), "poor")
        self.assertEqual(self.game.settle_bet(found["id"], 3, 1)[0], "not_author")
        status, result = self.game.settle_bet(found["id"], 2, 1)
        self.assertEqual(status, "settled")
        self.assertEqual(result.payouts, {3: small + big * small // (small + big), 5: big + big - big * small // (small + big)})
        self.assertEqual(self.coins(3) + self.coins(4) + self.coins(5), 3000)  # coins only moved
        self.assertEqual(self.coins(4), 1000 - big)
        self.assertEqual(self.game.settle_bet(found["id"], 2, 0)[0], "closed")

    def test_an_admin_can_settle_and_a_forgotten_bet_is_called_off(self) -> None:
        self.game.admins = frozenset({8})
        _, settled = self.open()
        self.assertEqual(self.game.settle_bet(settled["id"], 8, 0)[0], "settled")
        _, forgotten = self.open()
        self.fund(3, 500)
        self.game.stake_bet(forgotten["id"], 3, 1, self.game.bet_stakes()[0])
        self.assertEqual(self.game.expire_bets(), [])
        self.clock.advance(party.BET_DAYS * 86400)
        [result] = self.game.expire_bets()
        self.assertEqual((result.outcome, self.coins(3)), (-1, 500))

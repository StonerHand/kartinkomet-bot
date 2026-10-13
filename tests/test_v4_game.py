"""v4 game services against a real SQLite database."""

import unittest

from bot.core import casino, court, progress
from bot.core.arena import DUEL_SECONDS
from bot.services.progress import STARTER_BONUS
from tests.helpers import make_game

UPLOADER = 1


class V4Case(unittest.TestCase):
    quests = False

    def setUp(self) -> None:
        self.game, self.clock, temp = make_game(pics=12, uploader=UPLOADER, quests=self.quests)
        self.addCleanup(temp.cleanup)
        for user in range(2, 9):
            self.game.repo.remember_user(user, f"user{user}", None, None, self.game.now())

    def coins(self, user: int) -> int:
        return self.game.repo.player(user)[0]

    def fund(self, user: int, amount: int = 1000) -> None:
        self.game.repo.add_coins(user, amount, "test", self.game.now(), earn=False)

    def set_event(self, code: str) -> None:
        self.clock.value = (self.game.local_day() * 86400) + 12 * 3600  # noon: events are on
        self.game.repo.set_meta(f"day_event:{self.game.local_day()}", code)


class EconomyTest(V4Case):
    def test_starter_bonus_once_and_not_a_level(self) -> None:
        self.game.starter_bonus = STARTER_BONUS
        self.assertTrue(self.game.give_starter(5))
        self.assertFalse(self.game.give_starter(5))
        self.assertEqual(self.game.repo.player(5), (STARTER_BONUS, 0, 0))

    def test_spend_is_all_or_nothing(self) -> None:
        self.fund(5, 100)
        self.assertFalse(self.game.repo.spend(5, 101, "x", self.game.now()))
        self.assertTrue(self.game.repo.spend(5, 100, "x", self.game.now()))
        self.assertEqual(self.coins(5), 0)

    def test_double_coins_and_sniper_days(self) -> None:
        self.set_event("double_coins")
        self.game.pay(5, 1, "vote")
        self.game.pay(5, 10, "casino_win", earn=False)
        self.assertEqual(self.coins(5), 12)
        self.set_event("sniper_day")
        self.assertEqual(self.game.guess_reward(), 3 * 3 + 1)


class CasinoGameTest(V4Case):
    def test_bet_and_settle(self) -> None:
        self.fund(5, 500)
        self.assertEqual(self.game.place_casino_bet(5, 100), "ok")
        result = self.game.settle_casino(5, "slots", 100, (64,))
        self.assertEqual((result.payout, result.balance), (2000, 2400))
        self.assertIn("triple_seven", result.granted[0].codes)

    def test_refusals(self) -> None:
        self.assertEqual(self.game.place_casino_bet(5, 5), "broke")  # all-in with nothing left
        self.assertEqual(self.game.place_casino_bet(5, 50), "broke")
        self.fund(5, 100)
        self.assertEqual(self.game.place_casino_bet(5, 5), "small")

    def test_all_in_and_bankrupt(self) -> None:
        self.fund(5, 300)
        self.game.place_casino_bet(5, 300)
        result = self.game.settle_casino(5, "basket", 300, (1,))
        self.assertEqual(result.balance, 0)
        self.assertTrue({"all_in", "bankrupt"} <= set(result.granted[0].codes))

    def test_dice_against_the_bot(self) -> None:
        self.fund(5, 100)
        self.game.place_casino_bet(5, 100)
        self.assertEqual(self.game.settle_casino(5, "dice", 100, (3, 3)).balance, 100)

    def test_all_in_stake_mode(self) -> None:
        self.fund(5, 777)
        self.game.set_stake(5, None)
        self.assertEqual(self.game.stake_for_play(5), 777)
        self.game.set_stake(5, 30)
        self.assertEqual(self.game.stake_for_play(5), 30)


class ArenaBetsTest(V4Case):
    def duel(self):
        return self.game.start_duel(-1).battle

    def test_parimutuel_payout(self) -> None:
        battle = self.duel()
        for user in (5, 6, 7):
            self.fund(user)
        self.assertEqual(self.game.bet_battle(battle.id, 5, 0), ("ok", 50))
        self.assertEqual(self.game.bet_battle(battle.id, 5, 0), ("ok", 100))
        self.assertEqual(self.game.bet_battle(battle.id, 5, 1)[0], "other_slot")
        self.game.bet_battle(battle.id, 6, 1)
        self.game.vote_battle(battle.id, 7, 0)
        self.clock.advance(DUEL_SECONDS + 1)
        report = self.game.finish_battle(battle.id)
        self.assertEqual(report.bets[5], (100, 150))
        self.assertEqual(report.bets[6], (50, 0))
        self.assertEqual(self.coins(5), 1050)

    def test_draw_refunds(self) -> None:
        battle = self.duel()
        self.fund(5)
        self.game.bet_battle(battle.id, 5, 1)
        self.clock.advance(DUEL_SECONDS + 1)
        self.game.finish_battle(battle.id)
        self.assertEqual(self.coins(5), 1000)

    def test_bet_limits(self) -> None:
        battle = self.duel()
        self.assertEqual(self.game.bet_battle(battle.id, 5, 0)[0], "broke")
        self.fund(5, 5000)
        for _ in range(casino.BET_MAX // casino.BET_STEP):
            self.game.bet_battle(battle.id, 5, 0)
        self.assertEqual(self.game.bet_battle(battle.id, 5, 0)[0], "max")


class DayEventsTest(V4Case):
    def test_upside_down_gives_the_win_to_the_minority(self) -> None:
        self.set_event("upside_down")
        battle = self.game.start_duel(-1).battle
        self.game.vote_battle(battle.id, 5, 0)
        self.game.vote_battle(battle.id, 6, 0)
        self.game.vote_battle(battle.id, 7, 1)
        self.clock.advance(DUEL_SECONDS + 1)
        report = self.game.finish_battle(battle.id)
        self.assertEqual(report.winner, 1)
        self.assertTrue(report.flipped)
        self.assertEqual(report.guessers, [7])

    def test_amnesty_and_plague(self) -> None:
        self.set_event("plague")
        pic = self.game.draw_pic(-1)[0]
        self.assertTrue(self.game.react(pic.id, 5, -1).court_due)
        self.set_event("amnesty")
        trial = self.game.start_court(-1, pic.id, "bottom", None).court
        for user in (5, 6, 7):
            self.game.vote_court(trial.id, user, "kill")
        self.clock.advance(court.COURT_SECONDS + 1)
        report = self.game.finish_court(trial.id)
        self.assertEqual((report.verdict, report.amnesty), ("pardoned", True))

    def test_roll_once_a_day_and_tax(self) -> None:
        self.fund(5, 10000)
        self.fund(6, 10)
        self.game.rng.uniform = lambda a, b: sum(e.weight for e in __import__("bot.core.days", fromlist=["x"]).EVENTS[:7]) + 0.5
        code, fresh = self.game.roll_day_event()
        self.assertEqual((code, fresh), ("tax", True))
        self.assertEqual(self.game.roll_day_event(), ("tax", False))
        self.assertEqual(self.coins(5), 9000)
        self.assertEqual(self.coins(6), 1010)


class CourtAppealTest(V4Case):
    def executed_trial(self):
        pic = self.game.draw_pic(-1)[0]
        trial = self.game.start_court(-1, pic.id, "bottom", None).court
        self.game.vote_court(trial.id, 5, "kill")
        self.game.vote_court(trial.id, 6, "kill")
        self.clock.advance(court.COURT_SECONDS + 1)
        report = self.game.finish_court(trial.id)
        self.assertEqual(report.verdict, "executed")
        return trial

    def test_won_appeal_returns_bail(self) -> None:
        trial = self.executed_trial()
        self.fund(UPLOADER, 200)
        self.assertEqual(self.game.appeal(trial.id, 5).status, "not_owner")
        appeal = self.game.appeal(trial.id, UPLOADER)
        self.assertEqual(appeal.status, "started")
        self.assertEqual(self.game.appeal(trial.id, UPLOADER).status, "late")
        self.game.vote_court(appeal.court.id, 5, "kill")
        self.game.vote_court(appeal.court.id, 6, "kill")  # two isn't enough on appeal
        self.clock.advance(court.APPEAL_SECONDS + 1)
        report = self.game.finish_court(appeal.court.id)
        self.assertEqual((report.verdict, report.bail_back), ("pardoned", 200))
        self.assertEqual(self.coins(UPLOADER), 200)
        self.assertIn("appeal_won", report.granted[0].codes)

    def test_appeal_window_and_bail(self) -> None:
        trial = self.executed_trial()
        self.assertEqual(self.game.appeal(trial.id, UPLOADER).status, "broke")
        self.clock.advance(court.APPEAL_WINDOW + 1)
        self.fund(UPLOADER, 500)
        self.assertEqual(self.game.appeal(trial.id, UPLOADER).status, "late")


class ShopTest(V4Case):
    def test_shield_blocks_court(self) -> None:
        pic = self.game.draw_pic(-1)[0]
        self.fund(5)
        self.assertEqual(self.game.buy(5, "shield", pic.id)[0], "ok")
        self.assertEqual(self.coins(5), 700)
        self.assertEqual(self.game.start_court(-1, pic.id, "bottom", None).status, "immune")
        self.assertEqual(self.game.buy(5, "court", pic.id)[0], "immune")

    def test_boost_once_a_day(self) -> None:
        pic = self.game.draw_pic(-1)[0]
        self.fund(5)
        self.game.buy(5, "boost", pic.id)
        self.assertEqual(self.game.repo.get_pic(pic.id).rating, pic.rating + 50)
        self.assertEqual(self.game.buy(5, "boost", pic.id)[0], "boosted")

    def test_curse_and_uncurse(self) -> None:
        pic = self.game.draw_pic(-1)[0]
        self.fund(5)
        self.assertEqual(self.game.buy(5, "uncurse", pic.id)[0], "not_cursed")
        self.game.curse(pic)
        self.assertEqual(self.game.buy(5, "uncurse", pic.id)[0], "ok")
        self.assertEqual(self.game.repo.get_pic(pic.id).rating, pic.rating)

    def test_resurrection(self) -> None:
        pic = self.game.draw_pic(-1)[0]
        self.game.repo.remove_pic(pic.id, "executed", "court", self.game.now())
        self.fund(5, 1000)
        status, revived = self.game.buy(5, "resurrect", pic.id)
        self.assertEqual((status, revived.status, revived.rating), ("ok", "alive", 1000))
        self.assertEqual(self.game.buy(5, "resurrect", pic.id)[0], "alive")

    def test_title(self) -> None:
        self.fund(5)
        self.assertEqual(self.game.buy_title(5, "   "), "empty")
        self.assertEqual(self.game.buy_title(5, "Король кринжа " * 5), "ok")
        self.assertEqual(len(self.game.repo.title_of(5)), 24)

    def test_bounty_paid_to_court_killers(self) -> None:
        pic = self.game.draw_pic(-1)[0]
        self.fund(5)
        self.assertEqual(self.game.put_bounty(UPLOADER, pic.id, 100)[0], "own")
        self.assertEqual(self.game.put_bounty(5, pic.id, 500), ("ok", 500))
        trial = self.game.start_court(-1, pic.id, "bottom", None).court
        self.game.vote_court(trial.id, 6, "kill")
        self.game.vote_court(trial.id, 7, "kill")
        self.clock.advance(court.COURT_SECONDS + 1)
        report = self.game.finish_court(trial.id)
        self.assertEqual(report.bounty, {6: 250, 7: 250})
        self.assertEqual(self.game.repo.bounty_on(pic.id), 0)


class SocialTest(V4Case):
    def test_give(self) -> None:
        self.fund(5, 100)
        self.assertEqual(self.game.give(5, 5, 10)[0], "self")
        self.assertEqual(self.game.give(5, 6, 101)[0], "broke")
        self.assertEqual(self.game.give(5, 6, 100)[0], "ok")
        self.assertEqual((self.coins(5), self.coins(6)), (0, 100))
        self.assertEqual(self.game.repo.player(6)[1], 0)  # gifts don't level anyone up

    def test_robbery_success_and_protection(self) -> None:
        self.fund(5, 200)
        self.fund(6, 1000)
        self.game.rng.random = lambda: 0.0
        self.game.rng.uniform = lambda a, b: 0.1
        result = self.game.rob(5, 6)
        self.assertEqual((result.status, result.amount), ("success", 100))
        self.assertEqual(self.game.rob(5, 6).status, "cooldown")
        self.assertEqual(self.game.rob(7, 6).status, "protected")  # the victim was just robbed
        self.assertEqual(self.game.rob(7, 8).status, "poor_robber")

    def test_robbery_failure_jails(self) -> None:
        self.fund(5, 1000)
        self.fund(6, 1000)
        self.game.rng.random = lambda: 0.99
        result = self.game.rob(5, 6)
        self.assertEqual((result.status, result.amount), ("fail", 100))
        self.assertEqual(self.coins(6), 1100)
        self.clock.advance(3 * 3600)
        self.assertEqual(self.game.rob(5, 6).status, "jailed")
        self.assertIn("caught", result.granted[0].codes)

    def test_marriage_and_divorce(self) -> None:
        self.fund(5, 1000)
        self.fund(6, 101)
        status, proposal = self.game.propose(-1, 5, 6)
        self.assertEqual(status, "ok")
        self.assertEqual(self.game.answer_proposal(proposal, 7, True)[0], "not_for_you")
        self.assertEqual(self.game.answer_proposal(proposal, 6, True)[0], "married")
        self.assertEqual(self.game.repo.spouse_of(5)[0], 6)
        self.assertEqual(self.game.rob(5, 6).status, "spouse")
        self.assertEqual(self.game.propose(-1, 7, 6)[0], "taken")
        result = self.game.divorce(6)
        self.assertEqual((result.mine, result.theirs), (451, 450))
        self.assertIsNone(self.game.repo.spouse_of(5))

    def test_challenge_full_cycle(self) -> None:
        self.fund(5, 500)
        self.fund(6, 500)
        status, challenge = self.game.create_challenge(-1, 5, 6, 200)
        self.assertEqual(status, "ok")
        self.assertEqual(self.game.answer_challenge(challenge["id"], 7, True).status, "not_for_you")
        answer = self.game.answer_challenge(challenge["id"], 6, True)
        self.assertEqual(answer.status, "accepted")
        battle = answer.battle
        self.assertEqual(battle.mode, "challenge")
        self.assertEqual(self.game.vote_battle(battle.id, 5, 0)[0], "fighter")
        self.game.vote_battle(battle.id, 7, 1)
        self.clock.advance(DUEL_SECONDS + 1)
        report = self.game.finish_battle(battle.id)
        self.assertEqual(report.champion, 6)
        self.assertIsNone(report.executed)
        self.assertEqual((self.coins(5), self.coins(6)), (300, 700))
        self.assertIsNone(self.game.repo.active_battle(-1, "duel"))  # regular duels aren't blocked

    def test_challenge_expires_with_refund(self) -> None:
        self.fund(5, 500)
        _, challenge = self.game.create_challenge(-1, 5, None, 100)
        self.assertEqual(self.coins(5), 400)
        self.clock.advance(1000)
        self.assertEqual(self.game.answer_challenge(challenge["id"], 6, True).status, "gone")
        self.assertEqual(self.coins(5), 500)


class BossTest(V4Case):
    def test_win_splits_loot(self) -> None:
        status, boss = self.game.summon_boss(-1, "Тест")
        self.assertEqual(status, "ok")
        self.assertEqual(self.game.summon_boss(-1, "Ещё")[0], "active")
        self.game.repo.db.execute("UPDATE bosses SET hp = 5 WHERE id = ?", (boss["id"],))
        self.game.rng.randint = lambda a, b: b
        self.game.rng.random = lambda: 0.5
        self.assertEqual(self.game.hit_boss(boss["id"], 5).damage, 3)
        self.assertEqual(self.game.hit_boss(boss["id"], 5).status, "cooldown")
        self.fund(6, 100)
        hit = self.game.hit_boss(boss["id"], 6, super_hit=True)
        self.assertTrue(hit.killed)
        report = self.game.finish_boss(boss["id"])
        self.assertTrue(report.won)
        self.assertEqual(report.top, 6)
        self.assertEqual(report.last_hit, 6)
        self.assertGreater(report.payouts[6], report.payouts[5])
        self.assertEqual(self.game.chests_of(6)["rare"], 1)
        self.assertEqual(self.game.summon_boss(-1, "Скоро")[0], "cooldown")

    def test_escape(self) -> None:
        _, boss = self.game.summon_boss(-1, "Тест")
        rating = self.game.repo.get_pic(boss["pic_id"]).rating
        self.clock.advance(601)
        report = self.game.finish_boss(boss["id"])
        self.assertFalse(report.won)
        self.assertEqual(self.game.repo.get_pic(boss["pic_id"]).rating, rating + 30)


class EvolutionTest(V4Case):
    def test_pic_evolves_after_a_win(self) -> None:
        battle = self.game.start_duel(-1).battle
        self.game.vote_battle(battle.id, 5, 0)
        self.clock.advance(DUEL_SECONDS + 1)
        report = self.game.finish_battle(battle.id)
        self.assertEqual(report.evolved, [(0, 0, 1)])


class ProgressTest(V4Case):
    quests = True

    def test_quest_completion_pays_and_notes(self) -> None:
        tasks = progress.daily_quests(5, self.game.local_day())
        task = tasks[0]
        for _ in range(task.target):
            self.game.progress(5, task.kind)
        self.assertTrue(self.game.quests_of(5)[0][0].finished)
        granted = self.game.flush([5])
        self.assertEqual(granted[0].notes[0].kind, "quest")
        self.assertGreaterEqual(self.coins(5), task.reward)

    def test_all_three_quests_give_a_chest(self) -> None:
        for task in progress.daily_quests(5, self.game.local_day()):
            self.game.progress(5, task.kind, task.target)
        self.assertEqual(self.game.chests_of(5)["wood"], 1)
        opened = self.game.open_chest(5, "wood")
        self.assertIsNotNone(opened)
        self.assertIsNone(self.game.open_chest(5, "wood"))

    def test_daily_streak_and_chest(self) -> None:
        for day in range(7):
            daily = self.game.claim_daily(5)
            self.assertEqual((daily.status, daily.streak), ("ok", day + 1))
            self.assertEqual(self.game.claim_daily(5).status, "already")
            self.clock.advance(86400)
        self.assertTrue(daily.chest)
        self.assertGreaterEqual(self.game.chests_of(5)["rare"], 1)
        self.clock.advance(2 * 86400)
        self.assertEqual(self.game.claim_daily(5).streak, 1)

    def test_married_daily_bonus(self) -> None:
        self.game.repo.marry(5, 6, self.game.now())
        self.game.claim_daily(6)
        daily = self.game.claim_daily(5)
        self.assertEqual(daily.family_bonus, 10)


if __name__ == "__main__":
    unittest.main()

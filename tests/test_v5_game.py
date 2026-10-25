"""v5 game services: seasons, prices, stakes, new games, dice duels, raids, prizes, usage."""

from unittest import mock

from bot.core import boss as boss_rules
from bot.core import economy, games, progress, shop
from bot.services.economy import STARTER_COINS
from tests.test_v4_game import V4Case


class SeasonTest(V4Case):
    def test_season_closes_once_and_resets_everyone_but_admins(self) -> None:
        game, repo = self.game, self.game.repo
        game.admins = frozenset({2})
        self.assertIsNone(game.roll_season())  # the first start only begins the count
        season = game.season()
        for user_id, earned in ((3, 50), (4, 30), (5, 10)):
            game.pay(user_id, earned, "vote")
        repo.add_coins(6, 5000, "casino_win", game.now(), earn=False)  # casino doesn't score
        self.fund(2, 9999)
        self.assertEqual(game.season_standing(4), (30, 2))
        self.clock.value = game.season_bounds()[1] + 60
        report = game.roll_season()
        self.assertEqual((report.season, report.podium), (season, [(3, 50), (4, 30), (5, 10)]))
        self.assertEqual([self.coins(user_id) for user_id in (3, 4, 6)], [STARTER_COINS] * 3)
        self.assertEqual(self.coins(2), 9999)  # admins keep their test money
        self.assertIsNone(game.roll_season())
        self.assertEqual(repo.podiums_of(3), [(season, 1)])
        self.assertEqual(repo.podiums(), [(season, [(3, 50), (4, 30), (5, 10)])])
        self.assertEqual(game.season_standing(3), (0, None))

    def test_last_day_is_the_month_end(self) -> None:
        end = self.game.season_bounds()[1]
        self.clock.value = end - 3600
        self.assertTrue(self.game.season_last_day())
        self.clock.value = end - 2 * 86400
        self.assertFalse(self.game.season_last_day())


class PricesTest(V4Case):
    def test_prices_follow_the_median_balance_of_active_players(self) -> None:
        game = self.game
        base = game.price("shield")
        for user_id in (3, 4, 5):
            game.pay(user_id, 1, "vote")
            self.fund(user_id, 100_000)
        game._wealth = None
        factor = game.wealth()
        self.assertAlmostEqual(factor, 100_001 / economy.BASE_WEALTH)
        self.assertEqual(game.price("shield"), economy.scaled(base, factor))
        self.assertEqual(game.bet_step(), economy.scaled(50, factor))
        self.assertEqual(game.super_price(), economy.scaled(boss_rules.SUPER_PRICE, factor))
        game.admins, game._wealth = frozenset({3, 4, 5}), None
        self.assertEqual(game.price("shield"), base)  # admins' balances don't make the chat rich

    def test_stake_is_a_share_of_the_balance(self) -> None:
        self.fund(3, 1000)
        self.assertEqual(self.game.stake_for_play(3), 100)  # newcomers stake 10%
        self.game.set_stake_share(3, 50)
        self.assertEqual(self.game.stake_for_play(3), 500)
        self.game.set_stake(3, 30)
        self.assertEqual(self.game.stake_for_play(3), 30)
        self.game.set_stake(3, None)
        self.assertEqual(self.game.stake_for_play(3), 1000)


class WhoseTest(V4Case):
    def test_a_round_pays_only_right_guesses(self) -> None:
        repo = self.game.repo
        repo.add_pic("f-x", "u-x", 3, None, self.game.now())  # a second uploader
        status, round_ = self.game.start_whose(-100)
        self.assertEqual(status, "started")
        author = repo.get_pic(round_["pic_id"]).added_by
        self.assertEqual(sorted(round_["options"]), [1, 3])
        right = round_["options"].index(author)
        self.assertEqual(self.game.guess_whose(round_["id"], author, right), "own")
        self.assertEqual(self.game.guess_whose(round_["id"], 5, right), "ok")
        self.assertEqual(self.game.guess_whose(round_["id"], 5, 1 - right), "same")
        self.assertEqual(self.game.guess_whose(round_["id"], 6, 1 - right), "ok")
        self.assertEqual(self.game.start_whose(-100)[0], "active")
        self.clock.advance(games.WHOSE_SECONDS)
        self.assertEqual(self.game.guess_whose(round_["id"], 7, right), "closed")
        finished, winners, _ = self.game.finish_whose(round_["id"])
        self.assertEqual(winners, [5])
        self.assertEqual((self.coins(5), self.coins(6)), (games.WHOSE_REWARD, 0))
        self.assertEqual(finished["options"], round_["options"])
        self.assertIsNone(self.game.finish_whose(round_["id"])[0])
        self.assertEqual(self.game.start_whose(-100)[0], "cooldown")

    def test_one_uploader_is_not_a_game(self) -> None:
        self.assertEqual(self.game.start_whose(-100)[0], "shortage")


class HigherLowerTest(V4Case):
    def setUp(self) -> None:
        super().setUp()
        for index, pic in enumerate(self.game.repo.random_alive(12)):
            self.game.repo.set_rating(pic.id, 1000 + index * 10)

    def right(self, round_) -> int:
        return 0 if round_.first.rating > round_.second.rating else 1

    def test_streak_record_and_stale_taps(self) -> None:
        round_ = self.game.hl_round(5)
        self.assertGreaterEqual(abs(round_.first.rating - round_.second.rating), games.HL_MIN_GAP)
        result = self.game.hl_answer(5, round_.token, self.right(round_))
        self.assertEqual((result.status, result.streak, result.paid), ("right", 1, games.HL_REWARD))
        self.assertEqual(self.game.hl_answer(5, round_.token, self.right(round_)).status, "stale")  # double tap
        round_ = self.game.hl_round(5)
        self.assertEqual(round_.streak, 1)
        result = self.game.hl_answer(5, round_.token, 1 - self.right(round_))
        self.assertEqual((result.status, result.streak), ("wrong", 1))
        self.assertEqual(self.game.repo.counter(5, "hl_best"), 1)
        self.assertEqual(self.game.hl_round(5).streak, 0)
        self.assertEqual(self.game.usage()["higher"], 2)

    def test_only_so_many_answers_pay_a_day(self) -> None:
        for _ in range(games.HL_PAID_PER_DAY + 5):
            round_ = self.game.hl_round(5)
            self.game.hl_answer(5, round_.token, self.right(round_))
        self.assertEqual(self.coins(5), games.HL_REWARD * games.HL_PAID_PER_DAY)
        self.assertEqual(self.game.repo.counter(5, "hl_best"), games.HL_PAID_PER_DAY + 5)


class DiceDuelTest(V4Case):
    def setUp(self) -> None:
        super().setUp()
        for user_id in (2, 3):
            self.fund(user_id, 1000)

    def accepted(self) -> dict:
        status, challenge = self.game.create_challenge(-100, 2, 3, 200, "dice")
        self.assertEqual(status, "ok")
        answer = self.game.answer_challenge(challenge["id"], 3, True)
        self.assertEqual((answer.status, answer.battle), ("accepted", None))
        self.assertEqual((self.coins(2), self.coins(3)), (800, 800))
        return answer.challenge

    def test_higher_throw_takes_the_pot_and_scores(self) -> None:
        challenge = self.accepted()
        duel = self.game.settle_dice_duel(challenge["id"], (6, 2))
        self.assertEqual((duel.winner, duel.pot, duel.score), (2, 400, (1, 0)))
        self.assertEqual((self.coins(2), self.coins(3)), (1200, 800))
        self.assertIsNone(self.game.settle_dice_duel(challenge["id"], (1, 6)))
        self.assertEqual(self.game.rematch(challenge["id"], 4)[0], "not_for_you")
        status, again = self.game.rematch(challenge["id"], 3)
        self.assertEqual((status, again["from_user"], again["to_user"], again["game"]), ("ok", 3, 2, "dice"))
        self.assertEqual(self.coins(3), 600)

    def test_draw_refunds_and_counts_for_nobody(self) -> None:
        challenge = self.accepted()
        duel = self.game.settle_dice_duel(challenge["id"], (4, 4))
        self.assertEqual((duel.winner, duel.score), (None, (0, 0)))
        self.assertEqual((self.coins(2), self.coins(3)), (1000, 1000))
        self.assertIsNone(self.game.settle_dice_duel(challenge["id"], (4, 4)))  # a draw settles once too

    def test_unthrown_duels_are_refunded_on_restart(self) -> None:
        self.accepted()
        self.assertEqual(self.game.refund_unthrown_dice_duels(), 1)
        self.assertEqual((self.coins(2), self.coins(3)), (1000, 1000))
        self.assertEqual(self.game.refund_unthrown_dice_duels(), 0)

    def test_only_comparable_games(self) -> None:
        self.assertEqual(self.game.create_challenge(-100, 2, 3, 200, "slots")[0], "gone")


class RaidTest(V4Case):
    def test_phases_healing_and_chests(self) -> None:
        game, repo = self.game, self.game.repo
        status, boss = game.summon_boss(-100, "Рейд", forced=True, raid=True)
        self.assertEqual((status, boss["raid"]), ("ok", 1))
        self.assertEqual(boss["ends_at"] - game.now(), boss_rules.RAID_SECONDS)
        self.assertEqual(boss_rules.phase(boss["max_hp"] // 2, boss["max_hp"], True), "rage")
        self.assertEqual(boss_rules.phase(boss["max_hp"] // 2, boss["max_hp"], False), "calm")
        repo.db.execute("UPDATE bosses SET hp = ? WHERE id = ?", (boss["max_hp"] // 10, boss["id"]))
        repo.db.commit()
        hit = game.hit_boss(boss["id"], 3)
        self.assertEqual((hit.status, hit.damage, hit.phase), ("ok", 1, "shield"))
        self.assertEqual(game.heal_idle_raid(boss["id"]), 0)  # just hit
        self.clock.advance(boss_rules.HEAL_IDLE_SECONDS)
        hp_before = repo.get_boss(boss["id"])["hp"]
        healed = game.heal_idle_raid(boss["id"])
        self.assertEqual(repo.get_boss(boss["id"])["hp"], hp_before + healed)
        self.assertGreater(healed, 0)
        repo.hit_boss(boss["id"], 4, 30)
        repo.hit_boss(boss["id"], 5, boss_rules.RAID_CHEST_DAMAGE)
        repo.db.execute("UPDATE bosses SET hp = 0 WHERE id = ?", (boss["id"],))
        repo.db.commit()
        report = game.finish_boss(boss["id"])
        self.assertTrue(report.won)
        self.assertEqual(report.top, 4)
        self.assertEqual(game.chests_of(4)["legend"], 1)
        self.assertEqual(game.chests_of(5)["wood"], 1)
        self.assertEqual(game.chests_of(3)["wood"], 0)  # one damage isn't enough
        self.assertEqual(report.chests, 1)


class PrizeTest(V4Case):
    def test_wheel_title_once_then_a_chest(self) -> None:
        with mock.patch.object(games, "spin_outcome", return_value=games.Spin("title", 0)):
            spin, _, _ = self.game.resolve_spin(3, 1)
            self.assertEqual(self.game.repo.title_of(3), spin.prize)
            again, _, _ = self.game.resolve_spin(3, 1)
        self.assertEqual(again.kind, "chest")
        self.assertEqual(self.game.chests_of(3)["wood"], 1)
        self.assertEqual(self.game.usage()["spin"], 2)

    def test_chest_frame_lands_on_the_best_pic(self) -> None:
        best = self.game.repo.pics_of(1, limit=1)[0]
        self.game.grant_chest(1, "rare")
        with mock.patch.object(progress, "open_chest", return_value=progress.Loot("frame")):
            opened = self.game.open_chest(1, "rare")
        self.assertEqual((opened.loot.kind, opened.pic.id), ("frame", best.id))
        self.assertIn(self.game.repo.get_pic(best.id).frame, progress.FRAMES)

    def test_frame_or_title_without_a_target_becomes_coins(self) -> None:
        self.game.repo.set_title(3, "Свой")
        self.game.grant_chest(3, "legend")
        with mock.patch.object(progress, "open_chest", return_value=progress.Loot("title")):
            opened = self.game.open_chest(3, "legend")
        self.assertEqual(opened.loot.kind, "coins")
        self.assertEqual(self.game.repo.title_of(3), "Свой")  # a title someone has is never replaced


class AdminTrapTest(V4Case):
    """Robbing an admin always fails: the robber pays the admin what they reached for, and sits."""

    def test_the_robber_pays_what_they_reached_for(self) -> None:
        game = self.game
        game.admins = frozenset({2})
        self.fund(2, 3000)
        self.fund(3, 5000)
        with mock.patch.object(game.rng, "random", return_value=0.0), \
                mock.patch.object(game.rng, "uniform", return_value=0.15):  # a sure success on anyone else
            result = game.rob(3, 2)
        reached = min(game.rob_cap(), int(3000 * 0.15))
        self.assertEqual((result.status, result.guarded, result.amount), ("fail", True, reached))
        self.assertEqual((self.coins(3), self.coins(2)), (5000 - reached, 3000 + reached))
        self.assertEqual(game.rob(3, 2).status, "jailed")  # the usual jail
        self.assertEqual(result.wait, shop.JAIL_SECONDS)

    def test_a_poor_robber_loses_all_they_have_at_most(self) -> None:
        game = self.game
        game.admins = frozenset({2})
        self.fund(2, 1_000_000)
        self.fund(3, 150)
        result = game.rob(3, 2)
        self.assertEqual((result.amount, self.coins(3)), (150, 0))

    def test_others_are_robbed_as_usual(self) -> None:
        game = self.game
        game.admins = frozenset({2})
        self.fund(4, 3000)
        self.fund(3, 5000)
        with mock.patch.object(game.rng, "random", return_value=0.0):
            self.assertEqual(game.rob(3, 4).status, "success")


class RewardsFollowWealthTest(V4Case):
    """When everyone holds a million, rewards the game creates grow like prices do; levels don't."""

    quests = True

    def setUp(self) -> None:
        super().setUp()
        for user in range(2, 9):  # an active chat of millionaires: the median is a million
            self.game.repo.add_coins(user, 1, "vote", self.game.now())
            self.fund(user, 1_000_000)
        self.factor = self.game.wealth()

    def test_the_factor_is_the_median_wallet_over_the_base(self) -> None:
        self.assertGreater(self.factor, 400)
        self.assertEqual(self.game.reward(economy.VOTE), economy.scaled(economy.VOTE, self.factor))
        self.assertEqual(self.game.reward(-10), -economy.scaled(10, self.factor))

    def test_a_vote_pays_today_s_money_but_levels_by_its_base(self) -> None:
        coins, earned, _ = self.game.repo.player(3)
        paid = self.game.pay(3, economy.VOTE, "vote")
        self.assertEqual(paid, economy.scaled(economy.VOTE, self.factor))
        self.assertEqual(self.game.repo.player(3)[:2], (coins + paid, earned + economy.VOTE))

    def test_daily_quests_and_the_screen_agree(self) -> None:
        daily = self.game.claim_daily(4)
        self.assertEqual(daily.reward, economy.scaled(progress.daily_reward(1), self.factor))
        tasks, _ = self.game.quests_of(4)
        self.assertEqual(tasks[0].reward, economy.scaled(progress.daily_quests(4, self.game.local_day())[0].reward, self.factor))

    def test_shares_of_a_pool_are_not_scaled_twice(self) -> None:
        coins = self.coins(5)
        self.assertEqual(self.game.pay(5, 1000, "boss"), 1000)  # loot already grew when the boss came
        self.assertEqual(self.coins(5), coins + 1000)

    def test_boss_loot_grows_with_the_chat(self) -> None:
        status, boss = self.game.summon_boss(-100, "Тест", forced=True)
        self.assertEqual(status, "ok")
        self.assertGreater(boss["loot"], 100_000)

    def test_a_fresh_season_brings_rewards_back_to_base(self) -> None:
        self.game.repo.reset_coins(1111, frozenset(), "season_reset", self.game.now())
        self.game._wealth = None
        self.assertEqual(self.game.reward(economy.VOTE), economy.VOTE)

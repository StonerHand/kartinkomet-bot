"""The evening show on a real database: the heist's crew and stages, the cup's bracket."""

from unittest import mock

from bot.rules import shop, show
from tests.helpers import GameCase, make_game

CHAT = -100


class HeistTest(GameCase):
    def crew(self, *users: int) -> str:
        status, found = self.game.start_heist(CHAT)
        self.assertEqual(status, "started")
        for user in users:
            self.assertEqual(self.game.join_heist(found["id"], user), "ok")
        return found["id"]

    def test_joining_and_too_small_a_crew_calls_it_off(self) -> None:
        round_id = self.crew(2)
        self.assertEqual(self.game.join_heist(round_id, 2), "already")
        self.game.repo.set_counter(3, "jail_until", self.game.now() + 60)
        self.assertEqual(self.game.join_heist(round_id, 3), "jailed")
        self.clock.advance(show.RECRUIT_SECONDS)
        step = self.game.advance_heist(round_id)
        self.assertEqual(step.kind, "cancelled")
        self.assertEqual(self.game.start_heist(CHAT)[0], "done_today")

    def test_a_clean_job_pays_every_member(self) -> None:
        round_id = self.crew(2, 3, 4)
        self.assertEqual(self.game.vote_heist(round_id, 2, 0), "closed")  # still recruiting
        self.clock.advance(show.RECRUIT_SECONDS)
        self.assertEqual(self.game.advance_heist(round_id).kind, "stage")
        self.assertEqual(self.game.join_heist(round_id, 5), "started")
        self.assertEqual(self.game.vote_heist(round_id, 5, 0), "not_crew")
        with mock.patch.object(self.game.rng, "random", return_value=0.0):
            for stage in range(show.STAGES):
                self.assertEqual(self.game.vote_heist(round_id, 2, 1), "ok")
                self.assertEqual(self.game.vote_heist(round_id, 2, 1), "same")
                self.clock.advance(show.STAGE_SECONDS)
                step = self.game.advance_heist(round_id)
                self.assertEqual(step.option, 1)
        self.assertEqual((step.kind, step.loot), ("clean", show.LOOT_PER_MEMBER))
        self.assertEqual([self.coins(user) for user in (2, 3, 4)], [show.LOOT_PER_MEMBER] * 3)

    def test_a_failed_stage_busts_the_whole_crew(self) -> None:
        round_id = self.crew(2, 3)
        self.clock.advance(show.RECRUIT_SECONDS)
        self.game.advance_heist(round_id)
        self.clock.advance(show.STAGE_SECONDS)
        with mock.patch.object(self.game.rng, "random", return_value=0.999):
            step = self.game.advance_heist(round_id)
        self.assertEqual(step.kind, "busted")
        for user in (2, 3):
            self.assertEqual(self.game.repo.counter(user, "jail_until"), self.game.now() + shop.JAIL_SECONDS)
        self.assertIsNone(self.game.advance_heist(round_id))


class CupTest(GameCase):
    def play_match(self, step, slot: int = 0):
        battle = step.battle
        self.assertEqual((battle.mode, battle.kind), ("cup", "duel"))
        for voter in range(2, 5):
            self.game.vote_battle(battle.id, voter, slot)
        self.clock.advance(show.CUP_DUEL_SECONDS)
        self.game.finish_battle(battle.id)
        return battle.pics[slot]

    def test_eight_pics_seven_duels_one_champion(self) -> None:
        status, found = self.game.start_cup(CHAT)
        self.assertEqual(status, "started")
        self.assertEqual(self.game.start_cup(CHAT)[0], "active")
        step = self.game.cup_step(found["id"])
        self.assertIsNone(self.game.cup_step(found["id"]))  # its match is still on
        titles = []
        for _ in range(7):
            titles.append(step.battle.title)
            winner = self.play_match(step)
            step = self.game.cup_step(found["id"])
        self.assertEqual(step.kind, "champion")
        self.assertEqual(step.champion.id, winner.id)
        self.assertEqual(step.prize, show.CUP_PRIZE)
        self.assertEqual(self.coins(1), show.CUP_PRIZE)  # the uploader of every test pic
        self.assertEqual(titles.count("Кубок · четвертьфинал"), 4)
        self.assertEqual(titles[-1], "Кубок · финал")
        self.assertEqual(self.game.start_cup(CHAT)[0], "done_today")

    def test_a_draw_sends_the_higher_rating_on(self) -> None:
        _, found = self.game.start_cup(CHAT)
        step = self.game.cup_step(found["id"])
        first, second = step.battle.pics
        self.game.repo.shift_rating(second.id, 50)
        self.clock.advance(show.CUP_DUEL_SECONDS)
        self.game.finish_battle(step.battle.id)  # nobody voted
        self.game.cup_step(found["id"])
        state = self.game.repo.get_round(found["id"])["text"]
        self.assertIn(second.id, state)

    def test_a_small_warehouse_has_no_cup(self) -> None:
        game, _, temp = make_game(pics=show.CUP_SIZE - 1)
        self.addCleanup(temp.cleanup)
        self.assertEqual(game.start_cup(CHAT), ("shortage", None))
        self.assertIsNone(game.repo.meta_str(f"show:cup:{CHAT}"))  # tonight's show isn't spent

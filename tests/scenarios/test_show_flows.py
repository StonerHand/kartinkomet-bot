"""The evening show end to end: a heist from recruiting to the loot, the cup from intro to champion."""

from unittest import mock

from bot.rules import show as rules
from bot.scenarios import show
from tests.harness import BotHarness


class ShowFlowsTest(BotHarness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.remember(*range(2, 8))

    async def test_a_heist_from_recruiting_to_the_loot(self) -> None:
        await self.send("/heist", sender=2)
        card = self.session.of("SendMessage")[-1]
        self.assertIn("Ограбление", card.text)
        found = self.game.repo.open_rounds(-100, "heist")[0]
        for member in (2, 3, 4):
            await self.press(f"hj:{found['id']}", sender=member)
        self.clock.advance(rules.RECRUIT_SECONDS)
        self.assertEqual(self.game.advance_heist(found["id"]).kind, "stage")
        await self.live.refresh_round(found["id"])
        self.assertIn("этап 1/3", self.session.of("EditMessageText")[-1].text)
        with mock.patch.object(self.game.rng, "random", return_value=0.0):
            for _ in range(rules.STAGES):
                await self.press(f"hv:{found['id']}:0", sender=3)
                self.clock.advance(rules.STAGE_SECONDS)
                step = self.game.advance_heist(found["id"])
        await self.live.settle_heist(step)
        self.assertIn("чисто", self.session.of("EditMessageText")[-1].text)
        self.assertEqual(self.coins(4), rules.LOOT_PER_MEMBER)
        await self.send("/heist", sender=5)
        self.assertIn("уже было", self.session.of("SendEphemeralMessage")[-1].text)

    async def test_the_cup_from_intro_to_champion(self) -> None:
        await self.send("/cup", sender=2)
        self.assertTrue(any("Большой турнир" in text for text in self.texts()))
        found = self.game.repo.open_rounds(-100, "cup")[0]
        for _ in range(7):
            battle = self.game.repo.active_battle(-100, "duel", mode="cup")
            self.assertIsNotNone(battle)
            await self.press(f"v:{battle.id}:0", sender=3)
            self.clock.advance(rules.CUP_DUEL_SECONDS)
            await self.live.finish_battle(battle.id)
            await show.advance_cups(self.bot, self.game, self.live)
        self.assertEqual(self.game.repo.get_round(found["id"])["status"], "done")
        self.assertIn("Чемпионка", self.session.of("SendPhoto")[-1].caption)

    async def test_the_show_comes_by_itself_at_nine(self) -> None:
        self.at_hour(rules.SHOW_HOUR)
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        await self.events().tick()
        tonight = rules.show_of(self.game.local_day())
        expected = "Ограбление" if tonight == "heist" else "Большой турнир"
        self.assertTrue(any(expected in text for text in self.texts()))

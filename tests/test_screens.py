"""Every screen and card the bot can show, rendered with rich data and held to the layout rules.

The harness checks every message sent through the fake Telegram (BotHarness.check_outgoing);
views that are hard to reach through handlers are rendered directly and checked here.
"""

import random
from datetime import UTC, datetime

from aiogram.types import Message

from bot.core import days as day_rules
from bot.core import games as game_rules
from bot.core import progress as progress_rules
from bot.core.arena import DUEL_SECONDS
from bot.services.progress import Opened
from bot.tg import casino as casino_tg
from bot.tg import pics as pics_tg
from bot.tg import progress as progress_tg
from bot.tg import views
from bot.tg.events import Events
from tests.test_bot import ADMIN, GROUP, BotHarness, user
from tests.test_texts import assert_html, layout_problems

NAMES = {1: "stoner_hand", 2: "train", 3: "Михаил", 4: "fata11st", 5: "Захар", 6: "kcifekzhue"}


class ScreensTest(BotHarness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        casino_tg.ANIMATION_SCALE = 0
        casino_tg._last_play.clear()
        progress_tg.CHEST_PAUSE = 0
        pics_tg._last_drop.clear()
        repo = self.game.repo
        for user_id, name in NAMES.items():
            repo.remember_user(user_id, name, name, None, self.game.now())
            repo.add_coins(user_id, 5000, "test", self.game.now(), earn=False)

    def assert_layout(self, text: str) -> None:
        assert_html(text)
        self.assertEqual(layout_problems(text), [], text)

    def reply_to(self, user_id: int) -> Message:
        return Message(message_id=500, date=datetime.now(UTC), chat=GROUP, from_user=user(user_id), text="…")

    def fill_history(self) -> None:
        game, repo = self.game, self.game.repo
        for _ in range(8):
            battle = game.start_duel(-100).battle
            for voter in (3, 4, 5):
                game.vote_battle(battle.id, voter, 0)
            self.clock.advance(DUEL_SECONDS + 1)
            game.finish_battle(battle.id)
        # Enough history for the hall of fame and the bottom: both list only experienced pics.
        repo.db.execute("UPDATE pics SET games = games + 5, wins = wins + 4, best_streak = 3, dislikes = 2")
        repo.db.commit()
        for pic in repo.pics_of(ADMIN, limit=2, weakest=True):
            repo.remove_pic(pic.id, "executed", "court", game.now())
        repo.marry(ADMIN, 2, game.now() - 5 * 86400)
        game.grant_chest(ADMIN, "wood", announce=False)
        game.grant_chest(ADMIN, "legend", announce=False)
        game.buy_title(ADMIN, "Король кринжа")
        repo.set_meta("crowns", f"uploader:{ADMIN},rich:{ADMIN}")
        repo.set_meta("crowns_until", game.now() + 86400)
        repo.incr_counter(ADMIN, "right_guesses", 8)
        repo.incr_counter(ADMIN, "wrong_guesses", 2)
        repo.set_counter(ADMIN, "jail_until", game.now() + 1800)

    async def test_panel_screens(self) -> None:
        self.fill_history()
        await self.send("/menu", ADMIN)
        for screen in ("m:games", "m:casino", "m:shop", "m:hall", "m:bottom", "m:grave", "m:help", "m:up",
                       "m:adm", "adm:health", "adm:reset", "m:home:refresh"):
            await self.press(screen, sender=ADMIN)
        for board in ("uploads", "loved", "killers", "streaks", "rich"):
            await self.press(f"m:top:{board}", sender=ADMIN)
        self.session.refuse = {"SendEphemeralMessage"}  # personal screens fall back to the panel
        await self.press("m:me", sender=ADMIN)
        await self.press("m:quests", sender=ADMIN)

    async def test_games_and_people(self) -> None:
        self.game.roll_gold = lambda chat_id: True
        await self.send("/pic", 3)
        self.game.roll_gold = lambda chat_id: False
        await self.send("/wheel", 2)
        await self.send("/spin 100", 3)
        self.session.dice_values = [5, 2]
        casino_tg._last_play.clear()
        await self.send("/dice 200", 4)
        await self.send("/horoscope", 4)
        await self.send("/caption", 2)
        await self.send("/give 150", 2, reply_to=self.reply_to(3))
        self.game.rng.random = lambda: 0.1
        await self.send("/rob", 4, reply_to=self.reply_to(2))
        self.game.rng.random = lambda: 0.9
        await self.send("/rob", 5, reply_to=self.reply_to(3))
        self.game.rng = random.Random(7)
        await self.send("/marry", 2, reply_to=self.reply_to(3))
        await self.send("/challenge 200", 4, reply_to=self.reply_to(5))
        await self.send("/daily", 6)
        await self.send("/boss", 2)
        for command in ("/rob", "/give 100", "/marry", "/challenge 10", "/divorce"):
            await self.send(command, 6, reply_to=self.reply_to(6))

    async def test_schedule(self) -> None:
        self.fill_history()
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        events = Events(self.bot, self.game, self.live, frozenset({ADMIN}), 0)
        await events.pic_of_the_day(-100)
        await events.weekly(-100)
        for code in day_rules.CODES:
            self.assert_layout(views.day_event(code, -100, (1500, 300, 4) if code == "tax" else None))

    def test_rare_cards(self) -> None:
        pic = self.game.draw_pic(-100)[0]
        for tier in progress_rules.TIERS:
            for kind in ("coins", "boost", "shield", "chest", "empty"):
                opened = Opened(tier, progress_rules.Loot(kind, 300 if kind == "coins" else 0), pic, [])
                self.assert_layout(views.chest_opened("stoner_hand", opened, -100))
        for kind, coins in game_rules.SPIN_COINS.items():
            spin = game_rules.Spin(kind, coins)
            self.assert_layout(views.spin_result("stoner_hand", spin, pic, 1234, -100))
        for milestone in (3, 5, 10):
            self.assert_layout(views.streak_announcement(milestone, milestone, -100))

    def test_every_achievement_and_level_announcement(self) -> None:
        """Checked one by one: in a live test only a random few of them would come up."""
        from bot.core import achievements, economy
        from bot.services.types import Granted

        many = [(name, Granted(index, [])) for index, name in enumerate(NAMES.values())]
        for code in achievements.ALL_CODES:
            granted = [(label, Granted(item.user_id, [code])) for label, item in many]
            self.assert_layout(views.announcement(granted))
        for level in economy.LEVELS:
            self.assert_layout(views.announcement([("kcifekzhue", Granted(1, [], level.name))]))

    def test_live_cards_in_every_state(self) -> None:
        """Battle and court cards with every optional line, over every status phrase: a live test
        shows one random phrase and rarely a twist day or a full bet pool."""
        from dataclasses import replace
        from unittest import mock

        from bot.texts import arena as arena_texts
        from bot.texts import court as court_texts
        from bot.tg.views import arena as arena_views
        from bot.tg.views import court as court_views

        game = self.game
        duel = game.start_duel(-100).battle
        game.finish_battle(duel.id)
        tournament = game.start_tournament(-100).battle
        fighters = views.challenge_names({"from_user": 1, "to_user": 6, "stake": 1500}, NAMES)
        duels = [
            replace(duel, votes={3: 0, 4: 1}, bets={3: (0, 50), 4: (1, 600)}),
            replace(duel, streak=4, votes={3: 0}),
            replace(duel, extended=True),
            replace(duel, mode="challenge", bets={}),
        ]
        cards = []
        for phrase in (*arena_texts.DUEL_STATUS, *arena_texts.TOURNAMENT_STATUS):
            with mock.patch.object(arena_views, "pick", lambda pool, *args: phrase):
                for battle in duels:
                    cards.append(views.battle_card(battle, 14, fighters if battle.mode else None, flipped=True))
                    cards.append(views.battle_card(battle, 14))
                bets = {user: (user % 4, 50 * user) for user in NAMES}
                cards.append(views.battle_card(replace(tournament, bets=bets, votes={3: 0, 4: 1, 5: 3}), 75))
        pic = game.draw_pic(-100)[0]
        trial = game.start_court(-100, pic.id, "bottom", None).court
        for phrase in court_texts.STATUS:
            with mock.patch.object(court_views, "pick", lambda pool, *args: phrase):
                for state in (trial, replace(trial, appeal=True), replace(trial, appeal=True, last_word="я не виновата")):
                    cards.append(views.court_card(state, 50, "stoner_hand"))
        for text in cards:
            self.assert_layout(text)

    def test_results_in_every_state(self) -> None:
        """Result cards with every optional block: battles, courts, bosses, challenges, purchases."""
        from dataclasses import replace

        from bot.core.arena import TOURNAMENT_SECONDS
        from bot.core.court import COURT_SECONDS
        from bot.tg.views.shop import PURCHASE_FACTS

        game, repo, labels = self.game, self.game.repo, dict(NAMES)
        texts = []
        duel = game.start_duel(-100).battle
        for voter in (3, 4, 5):
            game.vote_battle(duel.id, voter, 0)
        self.clock.advance(DUEL_SECONDS + 1)
        report = game.finish_battle(duel.id)
        challenge = {"from_user": 1, "to_user": 6, "stake": 1500}
        duels = [
            report,
            replace(report, flipped=True, executed=report.battle.pics[1], bets={3: (50, 300), 4: (250, 0)},
                    bounty={3: 500, 4: 250}, evolved=[(0, 0, 1)], streak=5, milestone=5, guessers=[3, 4, 5],
                    guess_reward=4),
            replace(report, bets={3: (50, 0)}, bets_burned=50),
            replace(report, bets={3: (50, 50)}),
            replace(report, counted=False, winner=None, bets={3: (50, 50)}),
            replace(report, challenge=challenge, champion=1),
            replace(report, challenge=challenge, champion=None),
        ]
        tournament = game.start_tournament(-100).battle
        for voter, slot in ((3, 0), (4, 1), (5, 0), (6, 3)):
            game.vote_battle(tournament.id, voter, slot)
        self.clock.advance(TOURNAMENT_SECONDS + 1)
        for item in [*duels, game.finish_battle(tournament.id)]:
            texts.append(views.battle_report(item, labels))

        pic = game.draw_pic(-100)[0]
        trial = game.start_court(-100, pic.id, "bottom", None).court
        for voter in (3, 4):
            game.vote_court(trial.id, voter, "kill")
        self.clock.advance(COURT_SECONDS + 1)
        verdict = game.finish_court(trial.id)
        appealed = replace(verdict.court, appeal=True, last_word="я не виновата, это всё загрузчик, он меня таким сделал")
        extras = [views.bounty_line({3: 500}, labels), views.appeal_hint("stoner_hand")]
        for item in (verdict, replace(verdict, verdict="pardoned"), replace(verdict, verdict="pardoned", amnesty=True),
                     replace(verdict, court=appealed, verdict="pardoned", bail_back=200), replace(verdict, court=appealed)):
            texts.append(views.court_result(item, "stoner_hand", extras))

        _, boss = game.summon_boss(-100, "Тест", forced=True)
        for user_id in (2, 3, 4, 5, 6):
            game.hit_boss(boss["id"], user_id, super_hit=user_id == 3)
        texts.append(views.boss_card(repo.get_boss(boss["id"]), labels, 300, -100))
        self.clock.advance(3600)
        texts.append(views.boss_result(game.finish_boss(boss["id"]), labels, -100))

        for status in ("declined", "cancelled", "expired", "accepted"):
            texts.append(views.challenge_closed(challenge, labels, status))
        for item in PURCHASE_FACTS:
            texts.append(views.purchase_notice(item, "stoner_hand", pic, -100))
        for text in texts:
            self.assert_layout(text)

    def test_v5_cards_in_every_state(self) -> None:
        """Seasons, the new games, dice duels, raids, prizes and the admin stats; prices as a very
        rich chat sees them, so long numbers still fit."""
        from bot.core import boss as boss_rules
        from bot.core import games as game_rules
        from bot.core import progress as progress_rules
        from bot.services.quiz import HLAnswer
        from bot.services.challenges import DiceDuel

        game, repo = self.game, self.game.repo
        for user_id in NAMES:
            game.pay(user_id, 3, "vote")
            repo.add_coins(user_id, 5_000_000, "test", game.now(), earn=False)
        game._wealth = None
        self.assertGreater(game.wealth(), 100)
        texts = []
        podium = [("stoner_hand", 123_456), ("kcifekzhue", 9_999), ("Михаил", 1)]
        texts += [
            views.season_results("2026-10", podium, 1111, -100),
            views.season_results("2026-12", [], 1111, -100),
            views.season_warning("2026-10", podium, 1111, -100),
            views.seasons_hall("2026-11", podium[:2], [("2026-10", podium), ("2026-09", podium[:1])]),
            views.seasons_hall("2026-11", [], []),
        ]
        pic = game.draw_pic(-100)[0]
        whose = {"votes": {2: 1, 3: 1}, "phase_ends_at": 0}
        texts += [
            views.whose_card(whose, 30, -100),
            views.whose_card({"votes": {}}, 30, -100),
            views.whose_result("stoner_hand", list(NAMES.values()), 3, -100),
            views.whose_result("stoner_hand", [], 0, -100),
        ]
        higher = HLAnswer("right", pic, game.draw_pic(-100)[0], 12, 30, game_rules.HL_REWARD)
        texts += [
            views.hl_card(0, 0),
            views.hl_card(12, 30, higher),
            views.hl_over(HLAnswer("wrong", pic, pic, 31, 30), -100),
            views.hl_over(HLAnswer("wrong", pic, pic, 0, 30), -100),
        ]
        for code in ("dice", "darts", "bowling"):
            challenge = {"from_user": 1, "to_user": 6, "stake": 5_000_000, "game": code, "expires_at": 0}
            texts.append(views.challenge_card({**challenge, "to_user": None}, NAMES, -100, 180))
            texts.append(views.challenge_card(challenge, NAMES, -100, 180))
            texts.append(views.challenge_closed(challenge, NAMES, "accepted"))
            for values, winner in (((6, 1), 1), ((3, 3), None)):
                duel = DiceDuel(challenge, values, winner, 10_000_000, (12, 11))
                texts.append(views.dice_duel_result(duel, NAMES, -100))
        _, raid = game.summon_boss(-100, "Пожиратель лайков", forced=True, raid=True)
        for share in (1.0, 0.5, 0.1):
            boss = {**repo.get_boss(raid["id"]), "hp": int(raid["max_hp"] * share), "hits": 3}
            texts.append(views.boss_card(boss, NAMES, 7 * 3600 + 59, -100, game.super_price()))
        for kind in ("frame", "title"):
            loot = progress_rules.Loot(kind, prize="gold" if kind == "frame" else "Пиксельное величие")
            opened = Opened("legend", loot, pic, [])
            texts.append(views.chest_opened("stoner_hand", opened, -100))
        for kind in ("chest", "title"):
            spin = game_rules.Spin(kind, 0, "Пиксельное величие" if kind == "title" else "")
            texts.append(views.spin_result("stoner_hand", spin, None, 5_000_000, -100))
        texts.append(views.admin_stats({key: 12345 for key in ("players_today", "duels", "spin", "higher")}))
        texts.append(views.shop_screen("stoner_hand", 5_000_000, {item: game.price(item) for item in (
            "shield", "boost", "court", "uncurse", "resurrect", "title")} | {"bounty": game.bounty_amounts()[0]},
            -100, None, game.wealth()))
        texts.append(views.battle_card(game.start_duel(-100).battle, 14, bet_step=game.bet_step()))
        texts.append(views.appeal_hint("stoner_hand", game.appeal_bail()))
        self.assertGreater(boss_rules.RAID_HP_FACTOR, 1)
        for text in texts:
            self.assertNotIn("\n\n\n", text)
            self.assert_layout(text)

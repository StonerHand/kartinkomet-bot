"""Table games, pic by pieces, the auction and the team week on a real database."""

import json

from bot.rules import auction, games, table, teams
from tests.helpers import GameCase

CHAT = -100


class SpyTest(GameCase):
    def start(self, players=(2, 3, 4)):
        status, found = self.game.start_spy(CHAT, players[0], "кактус")
        self.assertEqual(status, "started")
        for user in players[1:]:
            self.assertEqual(self.game.join_spy(found["id"], user), "ok")
        return found["id"]

    def to_vote(self, round_id: str):
        self.clock.advance(table.SPY_RECRUIT_SECONDS)
        talk = self.game.advance_spy(round_id)
        self.clock.advance(table.SPY_TALK_SECONDS)
        self.assertEqual(self.game.advance_spy(round_id).kind, "vote")
        return talk

    def test_too_few_players_call_it_off(self) -> None:
        round_id = self.start((2, 3))
        self.clock.advance(table.SPY_RECRUIT_SECONDS)
        self.assertEqual(self.game.advance_spy(round_id).kind, "cancelled")
        self.assertEqual(self.game.start_spy(CHAT, 2, "кот")[0], "cooldown")

    def test_one_spy_does_not_know_the_word(self) -> None:
        round_id = self.start()
        self.assertEqual(self.game.spy_secret(round_id, 2), ("waiting", None))
        self.assertEqual(self.game.join_spy(round_id, 2), "already")
        talk = self.to_vote(round_id)
        self.assertEqual(talk.kind, "talk")
        self.assertIn(talk.spy, (2, 3, 4))
        for user in (2, 3, 4):
            expected = ("spy", None) if user == talk.spy else ("word", "кактус")
            self.assertEqual(self.game.spy_secret(round_id, user), expected)
        self.assertEqual(self.game.spy_secret(round_id, 7), ("not_player", None))
        self.assertEqual(self.game.join_spy(round_id, 7), "started")

    def test_a_caught_spy_pays_the_others(self) -> None:
        round_id = self.start()
        spy = self.to_vote(round_id).spy
        players = self.game.spy_players(self.game.repo.get_round(round_id))
        others = [user for user in players if user != spy]
        self.assertEqual(self.game.vote_spy(round_id, others[0], players.index(others[0])), "self")
        self.assertEqual(self.game.vote_spy(round_id, 7, players.index(spy)), "not_player")
        for user in others:
            self.assertEqual(self.game.vote_spy(round_id, user, players.index(spy)), "ok")
        self.assertEqual(self.game.vote_spy(round_id, others[0], players.index(spy)), "same")
        self.clock.advance(table.SPY_VOTE_SECONDS)
        step = self.game.advance_spy(round_id)
        self.assertEqual((step.kind, step.spy, step.counts[spy]), ("caught", spy, 2))
        self.assertEqual([self.coins(user) for user in others], [table.SPY_CATCH_REWARD] * 2)
        self.assertEqual(self.coins(spy), 0)
        self.assertIsNone(self.game.advance_spy(round_id))  # settled once

    def test_a_tie_lets_the_spy_go_with_the_prize(self) -> None:
        round_id = self.start()
        spy = self.to_vote(round_id).spy
        players = self.game.spy_players(self.game.repo.get_round(round_id))
        others = [user for user in players if user != spy]
        self.game.vote_spy(round_id, others[0], players.index(spy))
        self.game.vote_spy(round_id, spy, players.index(others[0]))
        self.clock.advance(table.SPY_VOTE_SECONDS)
        self.assertEqual(self.game.advance_spy(round_id).kind, "escaped")
        self.assertEqual(self.coins(spy), table.SPY_ESCAPE_REWARD)


class MinesTest(GameCase):
    def field(self) -> tuple[str, list[int]]:
        status, found = self.game.start_mines(CHAT)
        self.assertEqual(status, "started")
        return found["id"], json.loads(found["text"])["mines"]

    def safe_cells(self, mines: list[int]) -> list[int]:
        return [cell for cell in range(table.MINES_SIDE ** 2) if cell not in mines]

    def test_safe_cells_fill_the_pot_and_taking_it_pays(self) -> None:
        round_id, mines = self.field()
        first, second = self.safe_cells(mines)[:2]
        self.assertEqual(self.game.open_cell(round_id, 2, first).value, table.cell_value(0))
        self.assertEqual(self.game.open_cell(round_id, 2, first).status, "open")
        self.assertEqual(self.game.open_cell(round_id, 3, second).value, table.cell_value(1))
        self.assertEqual(self.game.cash_mines(round_id, 2), ("ok", table.cell_value(0)))
        self.assertEqual(self.game.cash_mines(round_id, 2), ("empty", 0))
        self.assertEqual(self.coins(2), table.cell_value(0))

    def test_a_mine_burns_every_pot_not_taken(self) -> None:
        round_id, mines = self.field()
        cells = self.safe_cells(mines)
        self.game.open_cell(round_id, 2, cells[0])
        self.game.open_cell(round_id, 3, cells[1])
        self.game.cash_mines(round_id, 3)
        move = self.game.open_cell(round_id, 4, mines[0])
        self.assertEqual(move.status, "boom")
        self.assertEqual((move.result.stepper, move.result.burned), (4, {2: table.cell_value(0)}))
        self.assertEqual((self.coins(2), self.coins(3)), (0, table.cell_value(1)))
        self.assertEqual(self.game.badges_of(4), [("mines", "Жертва мины")])
        self.assertEqual(self.game.open_cell(round_id, 2, cells[2]).status, "closed")

    def test_a_clean_field_and_the_clock_pay_every_pot(self) -> None:
        round_id, mines = self.field()
        cells = self.safe_cells(mines)
        for cell in cells[:-1]:
            self.assertEqual(self.game.open_cell(round_id, 2, cell).status, "safe")
        move = self.game.open_cell(round_id, 3, cells[-1])
        self.assertEqual(move.status, "cleared")
        total = sum(table.cell_value(index) for index in range(len(cells)))
        self.assertEqual(self.coins(2) + self.coins(3), total)
        self.clock.advance(table.MINES_COOLDOWN_SECONDS)
        round_id, mines = self.field()
        self.game.open_cell(round_id, 5, self.safe_cells(mines)[0])
        self.clock.advance(table.MINES_SECONDS)
        self.assertEqual(self.game.finish_mines(round_id).paid, {5: table.cell_value(0)})


class SafeTest(GameCase):
    def open_safe(self) -> tuple[str, str]:
        status, found = self.game.start_safe(CHAT)
        self.assertEqual(status, "started")
        return found["id"], json.loads(found["text"])["code"]

    def test_tries_cost_coins_and_get_hints(self) -> None:
        round_id, code = self.open_safe()
        wrong = code[1] + code[0] + code[2:]
        self.assertEqual(self.game.guess_safe(round_id, 2, wrong).status, "poor")
        self.fund(2, 100)
        self.assertEqual(self.game.guess_safe(round_id, 2, "1123").status, "invalid")
        attempt = self.game.guess_safe(round_id, 2, wrong)
        self.assertEqual((attempt.status, attempt.exact, attempt.near), ("miss", 2, 2))
        self.assertEqual(self.coins(2), 100 - table.SAFE_GUESS_PRICE)
        self.assertEqual(self.game.guess_safe(round_id, 2, wrong).status, "wait")

    def test_the_cracker_takes_the_tries_and_the_seed(self) -> None:
        round_id, code = self.open_safe()
        self.fund(2, 100)
        self.fund(3, 100)
        self.game.guess_safe(round_id, 2, code[::-1])
        attempt = self.game.guess_safe(round_id, 3, code)
        self.assertEqual(attempt.status, "cracked")
        self.assertEqual((attempt.result.pot, attempt.result.seed), (2 * table.SAFE_GUESS_PRICE, table.SAFE_SEED))
        self.assertEqual(self.coins(3), 100 + table.SAFE_GUESS_PRICE + table.SAFE_SEED)

    def test_an_unopened_safe_leaves_its_coins_to_the_next(self) -> None:
        round_id, code = self.open_safe()
        self.fund(2, 100)
        self.game.guess_safe(round_id, 2, code[::-1])
        self.clock.advance(table.SAFE_SECONDS)
        self.assertEqual(self.game.guess_safe(round_id, 2, code).status, "closed")
        self.assertEqual(self.game.finish_safe(round_id).pot, table.SAFE_GUESS_PRICE)
        self.clock.advance(table.SAFE_COOLDOWN_SECONDS)
        _, found = self.game.start_safe(CHAT)
        self.assertEqual(json.loads(found["text"])["pot"], table.SAFE_GUESS_PRICE)


class PieceTest(GameCase):
    def test_the_earlier_the_right_letter_the_more_it_pays(self) -> None:
        status, found = self.game.start_piece(CHAT)
        self.assertEqual(status, "started")
        round_id, answer = found["id"], self.game.piece_state(found)["answer"]
        wrong = (answer + 1) % games.PIECE_OPTIONS
        self.assertEqual(self.game.guess_piece(round_id, 2, answer), "ok")
        self.assertEqual(self.game.guess_piece(round_id, 2, wrong), "already")
        self.assertEqual(self.game.guess_piece(round_id, 3, wrong), "ok")
        for stage in range(1, len(games.PIECE_ZOOMS)):
            self.clock.advance(games.PIECE_STAGE_SECONDS)
            self.assertEqual(self.game.advance_piece(round_id).stage, stage)
        self.assertEqual(self.game.guess_piece(round_id, 4, answer), "ok")
        self.clock.advance(games.PIECE_STAGE_SECONDS)
        step = self.game.advance_piece(round_id)
        self.assertEqual(step.kind, "done")
        self.assertEqual(step.paid, {2: games.PIECE_REWARDS[0], 4: games.PIECE_REWARDS[-1]})
        self.assertEqual(step.wrong, 1)
        self.assertEqual(self.game.start_piece(CHAT)[0], "cooldown")


class AuctionTest(GameCase):
    def test_sealed_bids_and_the_second_price(self) -> None:
        _, found = self.game.open_auction(CHAT, self.game.now() + 3600)
        round_id = found["id"]
        for user in (2, 3, 4):
            self.fund(user, 2000)
        self.assertEqual(self.game.raise_bid(round_id, 2, 2), ("ok", 1000))
        self.assertEqual(self.game.raise_bid(round_id, 2, 0), ("ok", 1050))
        self.assertEqual(self.game.raise_bid(round_id, 3, 1), ("ok", 200))
        self.assertEqual(self.game.raise_bid(round_id, 4, 1), ("ok", 200))
        self.assertEqual(self.game.withdraw_bid(round_id, 4), ("ok", 200))
        self.assertEqual(self.game.my_bid(round_id, 2), 1050)
        self.assertEqual(self.coins(2), 950)
        self.clock.advance(3600)
        self.assertEqual(self.game.raise_bid(round_id, 3, 0), ("closed", 0))
        [result] = self.game.settle_due_auctions()
        self.assertEqual((result.winner, result.price, result.bidders), (2, 200, 2))
        self.assertEqual((self.coins(2), self.coins(3), self.coins(4)), (1800, 2000, 2000))
        self.assertEqual(self.game.chests_of(2)[result.lot], 1)
        self.assertEqual(self.game.settle_due_auctions(), [])

    def test_a_poor_bid_takes_nothing(self) -> None:
        _, found = self.game.open_auction(CHAT, self.game.now() + 3600)
        self.assertEqual(self.game.raise_bid(found["id"], 2, 0), ("poor", auction.RAISES[0]))
        self.clock.advance(3600)
        [result] = self.game.settle_due_auctions()
        self.assertIsNone(result.winner)


class TeamWeekTest(GameCase):
    def setUp(self) -> None:
        super().setUp()
        for user in range(2, 8):
            self.game.repo.touch_member(CHAT, user, self.game.now())

    def test_the_draft_needs_enough_players_and_happens_once(self) -> None:
        self.assertEqual(self.game.draft_teams(-200), ("few", None))
        status, week = self.game.draft_teams(CHAT)
        self.assertEqual(status, "drafted")
        self.assertEqual(sorted(week.teams), [2, 3, 4, 5, 6, 7])
        self.assertEqual(sorted(week.teams.values()).count("red"), 3)
        self.assertEqual(self.game.draft_teams(CHAT)[0], "already")

    def test_the_colour_that_earned_more_wins_once(self) -> None:
        _, week = self.game.draft_teams(CHAT)
        reds = [user for user, colour in week.teams.items() if colour == "red"]
        blues = [user for user, colour in week.teams.items() if colour == "blue"]
        self.game.repo.add_coins(reds[0], 500, "vote", self.game.now() + 1)
        self.game.repo.add_coins(blues[0], 900, "gift", self.game.now() + 1, earn=False)  # gifts don't count
        self.clock.advance(60)
        self.assertEqual(self.game.team_week(CHAT).scores["red"], 500)
        result = self.game.finish_teams(CHAT)
        self.assertEqual((result.winner, result.bonus), ("red", teams.BONUS))
        self.assertEqual(self.coins(reds[1]), teams.BONUS)
        self.assertEqual(self.coins(blues[1]), 0)
        self.assertEqual(self.game.badges_of(reds[1]), [("team", "Победа в командной неделе")])
        self.assertIsNone(self.game.finish_teams(CHAT))

    def test_a_tie_pays_nobody(self) -> None:
        self.game.draft_teams(CHAT)
        result = self.game.finish_teams(CHAT)
        self.assertIsNone(result.winner)
        self.assertEqual(sum(self.coins(user) for user in range(2, 8)), 0)

    def test_a_sunday_the_bot_missed_is_settled_on_monday(self) -> None:
        _, week = self.game.draft_teams(CHAT)
        red = next(user for user, colour in week.teams.items() if colour == "red")
        self.game.repo.add_coins(red, 500, "vote", self.game.now() + 1)
        self.clock.advance(7 * 86400)  # next Monday: no result came out
        self.game.repo.add_coins(red, 900, "vote", self.game.now())  # this week's, not last week's
        result = self.game.finish_teams(CHAT, week.week)
        self.assertEqual((result.winner, result.week.scores["red"]), ("red", 500))
        self.assertIsNone(self.game.finish_teams(CHAT, week.week))

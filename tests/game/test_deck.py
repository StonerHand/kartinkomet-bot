"""The chat's one deck: nothing repeats until the warehouse has gone round, and a new cycle
keeps the latest shown out of its first draws."""

from bot.rules import deck
from tests.helpers import GameCase, make_game

CHAT = -100


class OneDeckTest(GameCase):
    def test_pic_drops_and_duels_share_one_deck(self) -> None:
        seen = []
        for _ in range(3):
            seen.append(self.game.draw_pic(CHAT)[0].id)
            battle = self.game.start_duel(CHAT).battle
            seen.extend(pic.id for pic in battle.pics)
            self.game.cancel_battle(battle.id)
        self.assertEqual(len(seen), 9)
        self.assertEqual(len(set(seen)), 9)  # 12 pics: no repeat across /pic and the arena

    def test_a_new_cycle_holds_back_the_end_of_the_last_one(self) -> None:
        game, clock, temp = make_game(pics=20)
        self.addCleanup(temp.cleanup)
        first = []
        for _ in range(20):
            clock.advance(1)
            first.append(game.draw_pic(CHAT)[0].id)
        self.assertEqual(len(set(first)), 20)
        tail = set(first[-int(20 * deck.CYCLE_MEMORY):])
        for _ in range(20 - len(tail)):
            clock.advance(1)
            self.assertNotIn(game.draw_pic(CHAT)[0].id, tail)


class DuplicateTest(GameCase):
    def test_the_twin_with_less_history_leaves(self) -> None:
        older, newer = self.game.repo.random_alive(2)
        self.game.repo.db.execute("UPDATE pics SET games = 5 WHERE id = ?", (newer.id,))  # fought more
        self.game.repo.db.commit()
        self.assertEqual(self.game.retire_duplicate(older.id, newer.id), older.id)
        self.assertEqual(self.game.repo.get_pic(older.id).status, "deleted")
        self.assertIsNone(self.game.retire_duplicate(older.id, newer.id))  # already gone


class WhoseTurnsTest(GameCase):
    def test_a_small_uploader_s_pics_take_turns(self) -> None:
        for index in range(3):
            self.game.repo.add_pic(f"own{index}", f"own-u{index}", 7, None, self.game.now())
        shown = []
        for _ in range(3):
            shown.append(self.game.repo.random_alive_of(7, unseen_in="whose:-100"))
            self.game.repo.mark_shown("whose:-100", [shown[-1].id], self.game.now())
        self.assertEqual(len({pic.id for pic in shown}), 3)
        self.assertIsNotNone(self.game.repo.random_alive_of(7, unseen_in="whose:-100"))  # all seen: any again

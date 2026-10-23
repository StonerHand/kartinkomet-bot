"""Challenges between players: pic duels and casino duels on dice, rematches, head-to-head scores."""

from dataclasses import dataclass, field

from bot.core import arena, deck, shop
from bot.db.repo import Battle
from bot.services.types import Granted


@dataclass(frozen=True)
class ChallengeAnswer:
    status: str  # gone | not_for_you | own | broke | declined | cancelled | busy | shortage | accepted
    challenge: dict | None = None
    battle: Battle | None = None  # pic duels only; a duel on dice is rolled by the caller


@dataclass(frozen=True)
class DiceDuel:
    challenge: dict
    values: tuple[int, int]  # challenger's throw, opponent's throw
    winner: int | None  # None on a draw: both stakes went back
    pot: int
    score: tuple[int, int]  # head-to-head after this duel: challenger's wins, opponent's wins
    granted: list[Granted] = field(default_factory=list)


DICE_DUEL_GAMES = ("dice", "darts", "bowling")  # 1..6 each: comparable throws


class ChallengesMixin:
    def create_challenge(
        self, chat_id: int, challenger: int, opponent: int | None, stake: int, game: str = ""
    ) -> tuple[str, dict | None]:
        """('ok' | 'small' | 'self' | 'pending' | 'broke', challenge). game: '' = a pic duel,
        else one of DICE_DUEL_GAMES."""
        if game and game not in DICE_DUEL_GAMES:
            return "gone", None
        if stake < shop.CHALLENGE_MIN:
            return "small", None
        if opponent == challenger:
            return "self", None
        pending = self.repo.pending_challenge_of(challenger)
        if pending and self.now() >= pending["expires_at"]:
            self.expire_challenge(pending)
            pending = None
        if pending:
            return "pending", pending
        if not self.repo.spend(challenger, stake, "challenge_stake", self.now()):
            return "broke", None
        challenge_id = self.repo.create_challenge(
            chat_id, challenger, opponent, stake, self.now(), self.now() + shop.CHALLENGE_SECONDS, game
        )
        self.repo.incr_counter(challenger, "challenges_sent")
        return "ok", self.repo.get_challenge(challenge_id)

    def answer_challenge(self, challenge_id: str, user_id: int, accept: bool, title: str = "") -> ChallengeAnswer:
        challenge = self.repo.get_challenge(challenge_id)
        if challenge is None or challenge["status"] != "pending":
            return ChallengeAnswer("gone", challenge)
        if self.now() >= challenge["expires_at"]:
            self.expire_challenge(challenge)
            return ChallengeAnswer("gone", challenge)
        challenger, target = challenge["from_user"], challenge["to_user"]
        if not accept:
            if user_id == challenger:
                status = "cancelled"
            elif target is None or user_id == target:
                status = "declined"
            else:
                return ChallengeAnswer("not_for_you", challenge)
            if self.repo.close_challenge(challenge_id, status):
                self.repo.add_coins(challenger, challenge["stake"], "challenge_refund", self.now(), earn=False)
            return ChallengeAnswer(status, challenge)
        if user_id == challenger:
            return ChallengeAnswer("own", challenge)
        if target is not None and user_id != target:
            return ChallengeAnswer("not_for_you", challenge)
        if challenge["game"]:  # a duel on dice: no arena, the caller throws
            if not self.repo.spend(user_id, challenge["stake"], "challenge_stake", self.now()):
                return ChallengeAnswer("broke", challenge)
            if not self.repo.accept_challenge(challenge_id, user_id):
                self.repo.add_coins(user_id, challenge["stake"], "challenge_refund", self.now(), earn=False)
                return ChallengeAnswer("gone", challenge)
            return ChallengeAnswer("accepted", self.repo.get_challenge(challenge_id))
        if self.repo.active_challenge_battle(challenge["chat_id"]):
            return ChallengeAnswer("busy", challenge)
        fighters = self._challenge_fighters(challenge["chat_id"], challenger, user_id)
        if fighters is None:
            return ChallengeAnswer("shortage", challenge)
        if not self.repo.spend(user_id, challenge["stake"], "challenge_stake", self.now()):
            return ChallengeAnswer("broke", challenge)
        if not self.repo.accept_challenge(challenge_id, user_id):
            self.repo.add_coins(user_id, challenge["stake"], "challenge_refund", self.now(), earn=False)
            return ChallengeAnswer("gone", challenge)
        battle_id = self.repo.create_battle(
            "duel", challenge["chat_id"], fighters, self.now(), arena.DUEL_SECONDS, title=title, mode="challenge"
        )
        self.repo.set_challenge_battle(challenge_id, battle_id)
        return ChallengeAnswer("accepted", self.repo.get_challenge(challenge_id), self.repo.get_battle(battle_id))

    def _challenge_fighters(self, chat_id: int, first: int, second: int) -> list[str] | None:
        """Each player fights with a random pic of their own; no pics — a mercenary from the deck."""
        chosen: list[str] = []
        for user_id in (first, second):
            own = self.repo.random_alive_of(user_id)
            if own is not None and own.id not in chosen:
                chosen.append(own.id)
                continue
            drawn = deck.draw_many(self.repo, f"arena:{chat_id}", self.now(), 1, exclude=chosen)
            if not drawn:
                return None
            chosen.append(drawn[0][0].id)
        return chosen

    def expire_challenge(self, challenge: dict) -> bool:
        if self.repo.close_challenge(challenge["id"], "expired"):
            self.repo.add_coins(challenge["from_user"], challenge["stake"], "challenge_refund", self.now(), earn=False)
            return True
        return False

    def _settle_challenge(self, battle: Battle, winner: int | None, counted: bool) -> tuple[dict | None, int | None]:
        """Pay the pot of a finished challenge. Returns (challenge, winning player or None)."""
        challenge = self.repo.challenge_for_battle(battle.id)
        if challenge is None:
            return None, None
        players = (challenge["from_user"], challenge["to_user"])
        stake = challenge["stake"]
        if not counted or winner is None:
            for user_id in players:
                self.repo.add_coins(user_id, stake, "challenge_refund", self.now(), earn=False)
            return challenge, None
        champion = players[winner]
        self.repo.set_challenge_winner(challenge["id"], champion)
        self.repo.add_coins(champion, stake * 2, "challenge_win", self.now(), earn=False)
        self.repo.incr_counter(champion, "challenge_wins")
        self.progress(champion, "challenge_win")
        return challenge, champion

    def settle_dice_duel(self, challenge_id: str, values: tuple[int, int]) -> DiceDuel | None:
        """Pay an accepted duel on dice: the higher throw takes both stakes, a draw returns them.
        Only the first call settles (the winner column is the lock)."""
        challenge = self.repo.get_challenge(challenge_id)
        if (
            challenge is None
            or challenge["status"] != "accepted"
            or not challenge["game"]
            or challenge["winner"] is not None
        ):
            return None
        players = (challenge["from_user"], challenge["to_user"])
        stake, pot = challenge["stake"], challenge["stake"] * 2
        winner = None if values[0] == values[1] else players[0 if values[0] > values[1] else 1]
        if winner is None:
            self.repo.set_challenge_winner(challenge_id, 0)  # 0: settled as a draw
            for user_id in players:
                self.repo.add_coins(user_id, stake, "challenge_refund", self.now(), earn=False)
        else:
            self.repo.set_challenge_winner(challenge_id, winner)
            self.repo.add_coins(winner, pot, "challenge_win", self.now(), earn=False)
            self.repo.incr_counter(winner, "challenge_wins")
            self.progress(winner, "challenge_win")
        score = self.repo.head_to_head(*players)
        return DiceDuel(self.repo.get_challenge(challenge_id), values, winner, pot, score, self.check_achievements(list(players)))

    def rematch(self, challenge_id: str, user_id: int) -> tuple[str, dict | None]:
        """A new challenge between the same two, same stake and game, sent by whoever pressed.
        ('ok' | 'gone' | 'not_for_you' | statuses of create_challenge, the new challenge)."""
        old = self.repo.get_challenge(challenge_id)
        if old is None or old["status"] != "accepted" or old["to_user"] is None:
            return "gone", None
        players = (old["from_user"], old["to_user"])
        if user_id not in players:
            return "not_for_you", None
        other = players[1] if user_id == players[0] else players[0]
        return self.create_challenge(old["chat_id"], user_id, other, old["stake"], old["game"])

    def head_to_head(self, first: int, second: int) -> tuple[int, int]:
        return self.repo.head_to_head(first, second)

    def cancel_dice_duel(self, challenge: dict) -> None:
        """No throws happened (Telegram refused the dice, or a restart came between): both stakes back."""
        self.repo.set_challenge_winner(challenge["id"], 0)
        for user_id in (challenge["from_user"], challenge["to_user"]):
            self.repo.add_coins(user_id, challenge["stake"], "challenge_refund", self.now(), earn=False)

    def refund_unthrown_dice_duels(self) -> int:
        duels = self.repo.unsettled_dice_duels()
        for challenge in duels:
            self.cancel_dice_duel(challenge)
        return len(duels)

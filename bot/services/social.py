"""People: gifts, robbery, marriage, player challenges."""

from dataclasses import dataclass, field

from bot.core import arena, days, deck, shop
from bot.db.repo import Battle
from bot.services.types import Granted


@dataclass(frozen=True)
class RobResult:
    status: str  # self | spouse | poor_robber | poor_victim | cooldown | jailed | protected | success | fail
    amount: int = 0
    wait: int = 0  # seconds until allowed again
    granted: list[Granted] = field(default_factory=list)


@dataclass(frozen=True)
class Divorce:
    status: str  # single | ok
    spouse: int | None = None
    mine: int = 0
    theirs: int = 0
    granted: list[Granted] = field(default_factory=list)


@dataclass(frozen=True)
class ChallengeAnswer:
    status: str  # gone | not_for_you | own | broke | declined | cancelled | busy | shortage | accepted
    challenge: dict | None = None
    battle: Battle | None = None


class SocialMixin:
    # ── gifts ──────────────────────────────────────────────────────────

    def give(self, giver: int, receiver: int, amount: int) -> tuple[str, list[Granted]]:
        """'ok' | 'self' | 'small' | 'broke'."""
        if giver == receiver:
            return "self", []
        if amount <= 0:
            return "small", []
        if not self.repo.spend(giver, amount, "give", self.now()):
            return "broke", []
        self.repo.add_coins(receiver, amount, "gift", self.now(), earn=False)
        self.repo.incr_counter(giver, "given", amount)
        self.progress(giver, "give")
        return "ok", self.check_achievements([giver])

    # ── robbery ────────────────────────────────────────────────────────

    def rob(self, robber: int, victim: int) -> RobResult:
        now = self.now()
        if robber == victim:
            return RobResult("self")
        spouse = self.repo.spouse_of(robber)
        if spouse and spouse[0] == victim:
            return RobResult("spouse")
        jail = self.repo.counter(robber, "jail_until")
        if jail > now:
            return RobResult("jailed", wait=jail - now)
        ready = self.repo.counter(robber, "rob_ready_at")
        if ready > now:
            return RobResult("cooldown", wait=ready - now)
        protected = self.repo.counter(victim, "robbed_until")
        if protected > now:
            return RobResult("protected", wait=protected - now)
        robber_coins = self.repo.player(robber)[0]
        victim_coins = self.repo.player(victim)[0]
        if robber_coins < shop.ROB_MIN_BALANCE:
            return RobResult("poor_robber")
        if victim_coins < shop.ROB_MIN_BALANCE:
            return RobResult("poor_victim")

        self.repo.set_counter(robber, "rob_ready_at", now + shop.ROB_COOLDOWN)
        chance = days.THIEVES_DAY_CHANCE if self.day_is("thieves_day") else shop.ROB_CHANCE
        events: dict[int, list[str]] = {}
        if self.rng.random() < chance:
            share = self.rng.uniform(*shop.ROB_SHARE)
            amount = min(shop.ROB_CAP, int(victim_coins * share))
            self.repo.add_coins(victim, -amount, "robbed", now, earn=False)
            self.repo.add_coins(robber, amount, "rob", now, earn=False)
            self.repo.set_counter(victim, "robbed_until", now + shop.VICTIM_PROTECTION)
            self.repo.incr_counter(robber, "robberies")
            self.repo.incr_counter(victim, "times_robbed")
            self.progress(robber, "rob_success")
            return RobResult("success", amount, granted=self.check_achievements([robber, victim]))
        fine = shop.rob_fine(robber_coins)
        self.repo.add_coins(robber, -fine, "rob_fine", now, earn=False)
        self.repo.add_coins(victim, fine, "rob_fine", now, earn=False)
        self.repo.set_counter(robber, "jail_until", now + shop.JAIL_SECONDS)
        events[robber] = ["caught"]
        return RobResult("fail", fine, wait=shop.JAIL_SECONDS, granted=self.check_achievements([robber], events))

    # ── marriage ───────────────────────────────────────────────────────

    def wedding_price(self) -> int:
        return 0 if self.day_is("wedding_day") else shop.WEDDING_PRICE

    def propose(self, chat_id: int, suitor: int, beloved: int) -> tuple[str, str | None]:
        """('ok' | 'self' | 'married' | 'taken' | 'broke', proposal id)."""
        if suitor == beloved:
            return "self", None
        if self.repo.spouse_of(suitor):
            return "married", None
        if self.repo.spouse_of(beloved):
            return "taken", None
        if self.repo.player(suitor)[0] < self.wedding_price():
            return "broke", None
        return "ok", self.repo.create_proposal(chat_id, suitor, beloved, self.now())

    def answer_proposal(self, proposal_id: str, user_id: int, yes: bool) -> tuple[str, dict | None, list[Granted]]:
        """('married' | 'declined' | 'withdrawn' | 'not_for_you' | 'gone' | 'expired' | 'broke' | 'taken', …)."""
        proposal = self.repo.get_proposal(proposal_id)
        if proposal is None or proposal["status"] != "pending":
            return "gone", proposal, []
        if user_id not in (proposal["from_user"], proposal["to_user"]):
            return "not_for_you", proposal, []
        if self.now() - proposal["created_at"] > shop.PROPOSAL_SECONDS:
            self.repo.close_proposal(proposal_id, "expired")
            return "expired", proposal, []
        if user_id == proposal["from_user"]:
            if yes:
                return "not_for_you", proposal, []
            self.repo.close_proposal(proposal_id, "declined")
            return "withdrawn", proposal, []
        if not yes:
            self.repo.close_proposal(proposal_id, "declined")
            return "declined", proposal, []
        first, second = proposal["from_user"], proposal["to_user"]
        if self.repo.spouse_of(first) or self.repo.spouse_of(second):
            self.repo.close_proposal(proposal_id, "declined")
            return "taken", proposal, []
        price = self.wedding_price()
        if not self.repo.spend(first, price, "wedding", self.now()):
            return "broke", proposal, []
        if not self.repo.spend(second, price, "wedding", self.now()):
            self.repo.add_coins(first, price, "wedding_refund", self.now(), earn=False)
            return "broke", proposal, []
        if not self.repo.close_proposal(proposal_id, "accepted") or not self.repo.marry(first, second, self.now()):
            for user in (first, second):
                self.repo.add_coins(user, price, "wedding_refund", self.now(), earn=False)
            return "gone", proposal, []
        events = {first: ["married"], second: ["married"]}
        return "married", proposal, self.check_achievements([first, second], events)

    def divorce(self, user_id: int) -> Divorce:
        spouse = self.repo.spouse_of(user_id)
        if spouse is None:
            return Divorce("single")
        other = spouse[0]
        mine, theirs = self.repo.player(user_id)[0], self.repo.player(other)[0]
        new_mine, new_theirs = shop.divorce_split(mine, theirs)
        self.repo.divorce(user_id)
        now = self.now()
        if new_mine != mine:
            self.repo.add_coins(user_id, new_mine - mine, "divorce", now, earn=False)
        if new_theirs != theirs:
            self.repo.add_coins(other, new_theirs - theirs, "divorce", now, earn=False)
        granted = self.check_achievements([user_id, other], {user_id: ["divorced"]})
        return Divorce("ok", other, new_mine, new_theirs, granted)

    # ── challenges ─────────────────────────────────────────────────────

    def create_challenge(self, chat_id: int, challenger: int, opponent: int | None, stake: int) -> tuple[str, dict | None]:
        """('ok' | 'small' | 'self' | 'pending' | 'broke', challenge)."""
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
            chat_id, challenger, opponent, stake, self.now(), self.now() + shop.CHALLENGE_SECONDS
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
        self.repo.add_coins(champion, stake * 2, "challenge_win", self.now(), earn=False)
        self.repo.incr_counter(champion, "challenge_wins")
        self.progress(champion, "challenge_win")
        return challenge, champion
